import json
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Role, User
from apps.billing.models import Package, Payment, PaymentStatus, StudentAccount, Tariff
from apps.learning.models import Submission, SubmissionStatus
from apps.notifications.models import Notification
from apps.scheduling import services as sched
from apps.scheduling.models import (
    DeliveryMode,
    Lesson,
    LessonParticipant,
    LessonStatus,
    ParticipantStatus,
)
from apps.utils import json_error, json_ok, role_required

from .common import as_datetime_range, cabinet_context, week_bounds

WEEKDAY_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
# Срез первых двух букв дал бы «по» и «во» — короткие формы задаём явно.
WEEKDAY_SHORT_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTH_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def student_lessons(user):
    return (
        Lesson.objects.filter(participants__student=user)
        .exclude(participants__status=ParticipantStatus.CANCELLED)
        .select_related("teacher", "group", "course", "location")
        .distinct()
    )


@role_required(Role.STUDENT)
def dashboard(request):
    user = request.user
    now = timezone.now()
    upcoming = student_lessons(user).filter(starts_at__gte=now, status=LessonStatus.SCHEDULED).order_by("starts_at")
    account = StudentAccount(user)

    homework = (
        user.submissions.filter(status__in=[SubmissionStatus.ASSIGNED, SubmissionStatus.REDO])
        .select_related("assignment", "assignment__teacher")
        .order_by("assignment__due_at")[:4]
    )
    recent_marks = (
        user.submissions.filter(status=SubmissionStatus.REVIEWED, score__isnull=False)
        .select_related("assignment")
        .order_by("-reviewed_at")[:5]
    )
    attended = user.lesson_participations.filter(status=ParticipantStatus.ATTENDED).count()

    return render(request, "cabinet/student/dashboard.html", cabinet_context(
        request,
        next_lesson=upcoming.first(),
        upcoming=upcoming[:5],
        homework=homework,
        account=account,
        recent_marks=recent_marks,
        attended=attended,
        profile=getattr(user, "student_profile", None),
    ))


@role_required(Role.STUDENT)
def schedule(request):
    offset = int(request.GET.get("week", 0) or 0)
    monday, sunday = week_bounds(offset)
    start, end = as_datetime_range(monday, sunday)

    lessons = student_lessons(request.user).filter(starts_at__gte=start, starts_at__lt=end).order_by("starts_at")
    by_day = []
    for index in range(7):
        day = monday + timedelta(days=index)
        by_day.append({
            "date": day,
            "label": WEEKDAY_RU[index],
            "short": WEEKDAY_SHORT_RU[index],
            "is_today": day == timezone.localdate(),
            "lessons": [l for l in lessons if timezone.localtime(l.starts_at).date() == day],
        })

    history = student_lessons(request.user).filter(starts_at__lt=timezone.now()).order_by("-starts_at")[:10]
    return render(request, "cabinet/student/schedule.html", cabinet_context(
        request,
        days=by_day,
        week_offset=offset,
        monday=monday,
        sunday=sunday - timedelta(days=1),
        history=history,
    ))


@role_required(Role.STUDENT)
def homework(request):
    submissions = (
        request.user.submissions.select_related("assignment", "assignment__teacher", "assignment__unit")
        .prefetch_related("assignment__materials")
    )
    tab = request.GET.get("tab", "open")
    if tab == "done":
        submissions = submissions.filter(status=SubmissionStatus.REVIEWED)
    elif tab == "sent":
        submissions = submissions.filter(status=SubmissionStatus.SUBMITTED)
    else:
        submissions = submissions.filter(status__in=[SubmissionStatus.ASSIGNED, SubmissionStatus.REDO])

    return render(request, "cabinet/student/homework.html", cabinet_context(
        request,
        submissions=submissions.order_by("assignment__due_at", "-updated_at"),
        tab=tab,
        counts={
            "open": request.user.submissions.filter(
                status__in=[SubmissionStatus.ASSIGNED, SubmissionStatus.REDO]).count(),
            "sent": request.user.submissions.filter(status=SubmissionStatus.SUBMITTED).count(),
            "done": request.user.submissions.filter(status=SubmissionStatus.REVIEWED).count(),
        },
    ))


@role_required(Role.STUDENT)
def homework_detail(request, pk):
    submission = get_object_or_404(
        Submission.objects.select_related("assignment", "assignment__teacher", "assignment__unit"),
        pk=pk, student=request.user,
    )
    return render(request, "cabinet/student/homework_detail.html", cabinet_context(
        request, submission=submission, assignment=submission.assignment,
    ))


@role_required(Role.STUDENT)
@require_POST
def homework_submit(request, pk):
    submission = get_object_or_404(Submission, pk=pk, student=request.user)
    if submission.status == SubmissionStatus.REVIEWED:
        return json_error("Работа уже проверена.")

    text = (request.POST.get("answer_text") or "").strip()
    upload = request.FILES.get("answer_file")
    if not text and not upload and submission.assignment.requires_submission:
        return json_error("Напишите ответ или прикрепите файл.", fields={"answer_text": "Пустой ответ"})

    submission.answer_text = text
    if upload:
        submission.answer_file = upload
    submission.mark_submitted()

    from apps.notifications.models import NotificationKind
    from apps.notifications.services import notify

    notify(
        submission.assignment.teacher,
        NotificationKind.HOMEWORK_SUBMITTED,
        "Ученик сдал работу",
        f"{request.user.full_name} сдал «{submission.assignment.title}».",
        url="/cabinet/t/review/",
        dedupe_key=f"submitted:{submission.pk}:{submission.submitted_at:%Y%m%d%H%M}",
    )
    return json_ok("Работа отправлена преподавателю.", redirect="/cabinet/homework/")


@role_required(Role.STUDENT)
def program(request):
    """The curriculum behind the student's groups, with progress marked."""
    enrollments = (
        request.user.enrollments.filter(is_active=True)
        .select_related("group", "group__program", "group__course", "group__teacher")
    )
    blocks = []
    done_unit_ids = set(
        student_lessons(request.user)
        .filter(status=LessonStatus.COMPLETED, unit__isnull=False)
        .values_list("unit_id", flat=True)
    )
    for enrollment in enrollments:
        program_obj = enrollment.group.program
        if not program_obj:
            continue
        modules = []
        for module in program_obj.modules.prefetch_related("units__materials"):
            units = list(module.units.all())
            modules.append({
                "module": module,
                "units": [{"unit": u, "done": u.pk in done_unit_ids} for u in units],
                "done": sum(1 for u in units if u.pk in done_unit_ids),
                "total": len(units),
            })
        total = sum(m["total"] for m in modules)
        done = sum(m["done"] for m in modules)
        blocks.append({
            "group": enrollment.group,
            "program": program_obj,
            "modules": modules,
            "percent": round(100 * done / total) if total else 0,
            "done": done,
            "total": total,
        })

    return render(request, "cabinet/student/program.html", cabinet_context(request, blocks=blocks))


@role_required(Role.STUDENT)
def payments(request):
    account = StudentAccount(request.user)
    return render(request, "cabinet/student/payments.html", cabinet_context(
        request,
        account=account,
        packages=request.user.packages.select_related("tariff").order_by("-issued_on"),
        payments=request.user.payments.filter(status=PaymentStatus.PAID).order_by("-paid_on"),
        charges=request.user.lesson_charges.select_related("participant__lesson").order_by("-charged_at")[:20],
        tariffs=Tariff.objects.filter(is_active=True, is_public=True),
    ))


@role_required(Role.STUDENT)
def book(request):
    """Self-service booking: pick a teacher, pick a free slot."""
    teachers = (
        User.objects.filter(role__in=[Role.TEACHER, Role.OWNER], is_active=True,
                            teacher_profile__accepts_new_students=True)
        .select_related("teacher_profile").order_by("first_name")
    )
    account = StudentAccount(request.user)
    open_group_lessons = (
        Lesson.objects.upcoming()
        .filter(is_bookable=True)
        .exclude(participants__student=request.user)
        .select_related("teacher", "course", "group", "location")
        .order_by("starts_at")[:12]
    )
    return render(request, "cabinet/student/book.html", cabinet_context(
        request, teachers=teachers, account=account, open_lessons=open_group_lessons,
    ))


@login_required
def slots_api(request):
    """Free slots for a teacher, grouped by day. Consumed by booking.js."""
    teacher_id = request.GET.get("teacher")
    if not teacher_id:
        return json_error("Не выбран преподаватель.")
    teacher = get_object_or_404(User, pk=teacher_id, role__in=[Role.TEACHER, Role.OWNER])

    mode = request.GET.get("mode") or None
    slots = sched.available_slots(teacher, timezone.localdate(), days=14, mode=mode)

    days, current = [], None
    for slot in slots:
        local = timezone.localtime(slot["start"])
        key = local.date()
        if current is None or current["key"] != key:
            weekday = WEEKDAY_RU[key.weekday()].capitalize()
            current = {
                "key": key,
                # Месяц остаётся строчным — по-русски «7 августа», не «7 Августа».
                "label": f"{weekday}, {key.day} {MONTH_RU[key.month - 1]}",
                "slots": [],
            }
            days.append(current)
        current["slots"].append({"start": slot["start"].isoformat(), "time": local.strftime("%H:%M")})

    return json_ok(days=[{"label": d["label"], "slots": d["slots"]} for d in days])


@role_required(Role.STUDENT)
@require_POST
def book_api(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return json_error("Некорректный запрос.")

    teacher = get_object_or_404(User, pk=data.get("teacher"), role__in=[Role.TEACHER, Role.OWNER])
    if not data.get("start"):
        return json_error("Не выбрано время.")
    try:
        start = datetime.fromisoformat(data["start"])
    except ValueError:
        return json_error("Некорректное время.")
    if timezone.is_naive(start):
        start = timezone.make_aware(start)

    try:
        sched.book_slot(
            student=request.user,
            teacher=teacher,
            start=start,
            duration=int(data.get("duration") or 60),
            mode=data.get("mode") or DeliveryMode.ONLINE,
        )
    except ValidationError as exc:
        return json_error(exc.messages[0])

    return json_ok("Записали! Напоминание придёт заранее.", redirect="/cabinet/schedule/")


@login_required
@require_POST
def join_api(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    try:
        sched.join_lesson(request.user, lesson)
    except ValidationError as exc:
        return json_error(exc.messages[0])
    return json_ok("Вы записаны на занятие.")


@login_required
@require_POST
def cancel_api(request, pk):
    participant = get_object_or_404(
        LessonParticipant.objects.select_related("lesson"), lesson_id=pk, student=request.user
    )
    free = participant.lesson.can_be_cancelled_free_by(request.user)
    try:
        sched.cancel_participation(participant, request.user)
    except ValidationError as exc:
        return json_error(exc.messages[0])
    return json_ok(
        "Запись отменена." if free else "Отмена поздняя — урок списан с абонемента."
    )


@login_required
def notifications(request):
    items = Notification.objects.filter(recipient=request.user, channel="inapp").order_by("-created_at")[:60]
    Notification.objects.filter(recipient=request.user, channel="inapp", read_at__isnull=True).update(
        read_at=timezone.now()
    )
    return render(request, "cabinet/notifications.html", cabinet_context(request, items=items))


@login_required
def home_redirect(request):
    """Single /cabinet/ entry point that lands each role where it belongs."""
    if request.user.is_owner:
        return redirect("cabinet:crm_home")
    if request.user.is_teacher:
        return redirect("cabinet:teacher_home")
    return dashboard(request)
