import json
from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Role, User
from apps.billing.models import StudentAccount
from apps.learning.models import (
    Assignment,
    Material,
    MaterialKind,
    Module,
    Program,
    Submission,
    SubmissionStatus,
    Unit,
)
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify, notify_many
from apps.scheduling import services as sched
from apps.scheduling.models import (
    WEEKDAYS,
    DeliveryMode,
    Enrollment,
    Group,
    Lesson,
    LessonParticipant,
    LessonStatus,
    ParticipantStatus,
    TeacherAvailability,
)
from apps.utils import json_error, json_ok, teacher_required

from .common import as_datetime_range, cabinet_context, week_bounds
from .student import MONTH_RU, WEEKDAY_RU, WEEKDAY_SHORT_RU


@teacher_required
def dashboard(request):
    user = request.user
    now = timezone.now()
    today_start, today_end = as_datetime_range(timezone.localdate(), timezone.localdate() + timedelta(days=1))

    today = user.lessons_taught.filter(
        starts_at__gte=today_start, starts_at__lt=today_end
    ).exclude(status=LessonStatus.CANCELLED).select_related("group", "course", "location").order_by("starts_at")

    # Уроки в отсрочке: закончились, но ещё не списались. Только на них
    # и нужно смотреть — остальное закроется само.
    unmarked = [
        lesson for lesson in user.lessons_taught.filter(
            status=LessonStatus.SCHEDULED, starts_at__lt=now
        ).select_related("group").order_by("starts_at")[:8]
        if lesson.is_awaiting_autocomplete
    ]

    to_review = (
        Submission.objects.filter(assignment__teacher=user, status=SubmissionStatus.SUBMITTED)
        .select_related("student", "assignment").order_by("submitted_at")[:8]
    )

    week_start, week_end = week_bounds(0)
    ws, we = as_datetime_range(week_start, week_end)
    lessons_this_week = user.lessons_taught.filter(starts_at__gte=ws, starts_at__lt=we).exclude(
        status=LessonStatus.CANCELLED
    ).count()

    student_ids = set(
        LessonParticipant.objects.filter(lesson__teacher=user).values_list("student_id", flat=True)
    )

    return render(request, "cabinet/teacher/dashboard.html", cabinet_context(
        request,
        today=today,
        next_lesson=user.lessons_taught.filter(starts_at__gte=now, status=LessonStatus.SCHEDULED)
                        .select_related("group", "course").order_by("starts_at").first(),
        unmarked=unmarked,
        to_review=to_review,
        lessons_this_week=lessons_this_week,
        student_count=len(student_ids),
        groups=Group.objects.filter(teacher=user, is_active=True).annotate(
            students=Count("enrollments", filter=Q(enrollments__is_active=True))
        ),
    ))


@teacher_required
def schedule(request):
    offset = int(request.GET.get("week", 0) or 0)
    monday, sunday = week_bounds(offset)
    start, end = as_datetime_range(monday, sunday)

    lessons = (
        request.user.lessons_taught.filter(starts_at__gte=start, starts_at__lt=end)
        .select_related("group", "course", "location")
        .prefetch_related("participants")
        .order_by("starts_at")
    )
    for lesson in lessons:
        # Шаблон не умеет вызывать методы с аргументами, а право на правку
        # зависит от того, кто смотрит: считаем здесь.
        lesson.can_correct = lesson.is_correctable_by(request.user)

    days = []
    for index in range(7):
        day = monday + timedelta(days=index)
        days.append({
            "date": day,
            "label": WEEKDAY_RU[index],
            "short": WEEKDAY_SHORT_RU[index],
            "is_today": day == timezone.localdate(),
            "lessons": [l for l in lessons if timezone.localtime(l.starts_at).date() == day],
        })

    return render(request, "cabinet/teacher/schedule.html", cabinet_context(
        request,
        days=days,
        week_offset=offset,
        monday=monday,
        sunday=sunday - timedelta(days=1),
        # Уроки, которые отметились сами и человек этого ещё не подтвердил.
        # Ради этой плашки автоотметка и остаётся заметной: занятия уже
        # списаны, и увидеть ошибку надо сегодня, а не в конце месяца.
        autocompleted=request.user.lessons_taught.filter(
            status=LessonStatus.COMPLETED, completed_by__isnull=True,
            completed_at__gte=timezone.now() - timedelta(days=correction_days()),
        ).select_related("group").order_by("-starts_at"),
        autocomplete_minutes=getattr(settings, "LESSON_AUTOCOMPLETE_MINUTES", 45),
        correction_days=correction_days(),
    ))


def correction_days():
    return getattr(settings, "LESSON_CORRECTION_DAYS", 7)


def _own_lesson(request, pk):
    """Урок преподавателя — или любой, если смотрит владелица."""
    lesson = get_object_or_404(Lesson, pk=pk)
    if lesson.teacher_id != request.user.pk and not request.user.is_owner:
        return None
    return lesson


@teacher_required
@require_POST
def lesson_complete(request, pk):
    """«Провести сейчас» — не дожидаясь, пока сработает отсрочка."""
    lesson = _own_lesson(request, pk)
    if lesson is None:
        return json_error("Это не ваш урок.", status=403)
    if lesson.status == LessonStatus.COMPLETED:
        sched.confirm_completion(lesson, request.user)
        return json_ok("Отметка подтверждена.")
    sched.complete_lesson(lesson, request.user)
    return json_ok("Урок проведён, занятия списаны.")


@teacher_required
@require_POST
def lesson_reopen(request, pk):
    """«Урок не состоялся»: снимаем списания, ученикам возвращаем занятия."""
    lesson = _own_lesson(request, pk)
    if lesson is None:
        return json_error("Это не ваш урок.", status=403)
    if not lesson.is_correctable_by(request.user):
        return json_error(
            f"Журнал за этот урок закрыт — прошло больше {correction_days()} дней. "
            "Поправить может владелица.", status=403,
        )
    data = json.loads(request.body or "{}")
    sched.reopen_lesson(lesson, request.user, data.get("reason", ""))
    return json_ok("Урок помечен несостоявшимся, занятия возвращены.")


@teacher_required
@require_POST
def lessons_confirm(request):
    """«Всё верно» одним нажатием на все автоотметки разом."""
    confirmed = 0
    for lesson in request.user.lessons_taught.filter(
        status=LessonStatus.COMPLETED, completed_by__isnull=True
    ):
        sched.confirm_completion(lesson, request.user)
        confirmed += 1
    return json_ok(f"Подтверждено уроков: {confirmed}.")


@teacher_required
def lesson_detail(request, pk):
    """The lesson journal: attendance, topic, notes and homework in one screen."""
    lesson = get_object_or_404(
        Lesson.objects.select_related("group", "course", "teacher", "unit"), pk=pk
    )
    if lesson.teacher_id != request.user.pk and not request.user.is_owner:
        return redirect("cabinet:teacher_schedule")

    participants = lesson.participants.select_related("student").order_by("student__first_name")
    program_units = []
    if lesson.group and lesson.group.program:
        program_units = Unit.objects.filter(module__program=lesson.group.program).select_related("module")

    return render(request, "cabinet/teacher/lesson.html", cabinet_context(
        request,
        lesson=lesson,
        participants=participants,
        statuses=ParticipantStatus.choices,
        program_units=program_units,
        assignments=lesson.assignments.prefetch_related("submissions"),
        can_correct=lesson.is_correctable_by(request.user),
        teacher_programs=Program.objects.filter(is_active=True).filter(
            Q(author=request.user) | Q(is_shared=True)
        ),
    ))


@teacher_required
@require_POST
def lesson_save(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    if lesson.teacher_id != request.user.pk and not request.user.is_owner:
        return json_error("Это не ваш урок.", status=403)

    lesson.topic = (request.POST.get("topic") or "").strip()
    lesson.teacher_note = (request.POST.get("teacher_note") or "").strip()
    lesson.meeting_url = (request.POST.get("meeting_url") or "").strip()
    unit_id = request.POST.get("unit")
    lesson.unit_id = int(unit_id) if unit_id else None
    lesson.save(update_fields=["topic", "teacher_note", "meeting_url", "unit"])

    marks = {}
    comments = {}
    for key, value in request.POST.items():
        if key.startswith("status-"):
            marks[key[7:]] = value
        elif key.startswith("comment-"):
            comments[key[8:]] = value

    if marks:
        sched.save_attendance(lesson, marks, request.user)
    for participant_id, comment in comments.items():
        LessonParticipant.objects.filter(pk=participant_id, lesson=lesson).update(
            teacher_comment=comment.strip()
        )

    return json_ok("Журнал сохранён.")


@teacher_required
@require_POST
def lesson_cancel(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    if lesson.teacher_id != request.user.pk and not request.user.is_owner:
        return json_error("Это не ваш урок.", status=403)
    data = json.loads(request.body or "{}")
    sched.cancel_lesson(lesson, request.user, data.get("reason", "Отменён школой"))
    return json_ok("Урок отменён, ученики предупреждены.")


@teacher_required
def students(request):
    """Everyone this teacher actually teaches, with money and progress in view."""
    student_ids = LessonParticipant.objects.filter(
        lesson__teacher=request.user
    ).values_list("student_id", flat=True)
    enrolled_ids = Enrollment.objects.filter(
        group__teacher=request.user, is_active=True
    ).values_list("student_id", flat=True)

    queryset = (
        User.objects.filter(pk__in=set(student_ids) | set(enrolled_ids))
        .select_related("student_profile").order_by("first_name")
    )
    search = request.GET.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(phone__icontains=search)
        )

    rows = []
    for student in queryset:
        account = StudentAccount(student)
        rows.append({
            "student": student,
            "account": account,
            "open_homework": student.submissions.filter(
                assignment__teacher=request.user,
                status__in=[SubmissionStatus.ASSIGNED, SubmissionStatus.REDO],
            ).count(),
            "next": Lesson.objects.filter(
                teacher=request.user, participants__student=student, starts_at__gte=timezone.now(),
                status=LessonStatus.SCHEDULED,
            ).order_by("starts_at").first(),
        })

    return render(request, "cabinet/teacher/students.html", cabinet_context(
        request, rows=rows, search=search,
    ))


@teacher_required
def student_detail(request, pk):
    student = get_object_or_404(User.objects.select_related("student_profile"), pk=pk, role=Role.STUDENT)
    lessons = Lesson.objects.filter(participants__student=student).select_related("teacher", "group")
    if not request.user.is_owner:
        lessons = lessons.filter(teacher=request.user)

    return render(request, "cabinet/teacher/student_detail.html", cabinet_context(
        request,
        student=student,
        account=StudentAccount(student),
        upcoming=lessons.filter(starts_at__gte=timezone.now(), status=LessonStatus.SCHEDULED).order_by("starts_at")[:5],
        history=lessons.filter(starts_at__lt=timezone.now()).order_by("-starts_at")[:15],
        submissions=student.submissions.select_related("assignment").order_by("-updated_at")[:15],
        enrollments=student.enrollments.select_related("group", "group__course"),
        placement=student.placement_sessions.filter(finished_at__isnull=False).first(),
    ))


@teacher_required
def review_queue(request):
    queryset = Submission.objects.filter(assignment__teacher=request.user).select_related(
        "student", "assignment"
    )
    tab = request.GET.get("tab", "pending")
    if tab == "pending":
        queryset = queryset.filter(status=SubmissionStatus.SUBMITTED).order_by("submitted_at")
    elif tab == "open":
        queryset = queryset.filter(
            status__in=[SubmissionStatus.ASSIGNED, SubmissionStatus.REDO]
        ).order_by("assignment__due_at")
    else:
        queryset = queryset.filter(status=SubmissionStatus.REVIEWED).order_by("-reviewed_at")

    return render(request, "cabinet/teacher/review.html", cabinet_context(
        request,
        submissions=queryset[:80],
        tab=tab,
        counts={
            "pending": Submission.objects.filter(
                assignment__teacher=request.user, status=SubmissionStatus.SUBMITTED).count(),
            "open": Submission.objects.filter(
                assignment__teacher=request.user,
                status__in=[SubmissionStatus.ASSIGNED, SubmissionStatus.REDO]).count(),
            "done": Submission.objects.filter(
                assignment__teacher=request.user, status=SubmissionStatus.REVIEWED).count(),
        },
    ))


@teacher_required
def submission_detail(request, pk):
    submission = get_object_or_404(
        Submission.objects.select_related("student", "assignment"), pk=pk, assignment__teacher=request.user
    )
    return render(request, "cabinet/teacher/submission.html", cabinet_context(
        request, submission=submission,
    ))


@teacher_required
@require_POST
def submission_review(request, pk):
    submission = get_object_or_404(Submission, pk=pk, assignment__teacher=request.user)
    action = request.POST.get("action", "review")
    feedback = (request.POST.get("teacher_feedback") or "").strip()
    score_raw = request.POST.get("score")

    submission.teacher_feedback = feedback
    submission.score = int(score_raw) if score_raw else None
    submission.status = SubmissionStatus.REDO if action == "redo" else SubmissionStatus.REVIEWED
    submission.reviewed_at = timezone.now()
    submission.save(update_fields=["teacher_feedback", "score", "status", "reviewed_at"])

    notify(
        submission.student,
        NotificationKind.HOMEWORK_REVIEWED,
        "Домашка проверена" if action != "redo" else "Домашку нужно доработать",
        f"«{submission.assignment.title}»"
        + (f" — {submission.score}/{submission.assignment.max_score}." if submission.score is not None else ".")
        + (f" {feedback}" if feedback else ""),
        url=f"/cabinet/homework/{submission.pk}/",
        dedupe_key=f"reviewed:{submission.pk}:{submission.reviewed_at:%Y%m%d%H%M}",
    )
    return json_ok("Проверено.", redirect="/cabinet/t/review/")


@teacher_required
@require_POST
def assignment_create(request):
    """Issue homework to a whole group, to one lesson's roster, or to picked students."""
    title = (request.POST.get("title") or "").strip()
    if not title:
        return json_error("Укажите название задания.", fields={"title": "Обязательное поле"})

    due_raw = request.POST.get("due_at")
    assignment = Assignment.objects.create(
        title=title,
        description=(request.POST.get("description") or "").strip(),
        teacher=request.user,
        lesson_id=request.POST.get("lesson") or None,
        group_id=request.POST.get("group") or None,
        unit_id=request.POST.get("unit") or None,
        due_at=timezone.make_aware(datetime.fromisoformat(due_raw)) if due_raw else None,
        max_score=int(request.POST.get("max_score") or 10),
        requires_submission=request.POST.get("requires_submission") != "0",
    )

    link = (request.POST.get("material_url") or "").strip()
    if link:
        Material.objects.create(
            assignment=assignment, title=request.POST.get("material_title") or "Материал",
            kind=MaterialKind.LINK, url=link, uploaded_by=request.user,
        )
    for upload in request.FILES.getlist("material_files"):
        Material.objects.create(
            assignment=assignment, title=upload.name, kind=MaterialKind.FILE,
            file=upload, uploaded_by=request.user,
        )

    student_ids = request.POST.getlist("students")
    if student_ids:
        recipients = list(User.objects.filter(pk__in=student_ids, role=Role.STUDENT))
    elif assignment.lesson_id:
        recipients = [p.student for p in assignment.lesson.active_participants.select_related("student")]
    elif assignment.group_id:
        recipients = [e.student for e in assignment.group.active_enrollments.select_related("student")]
    else:
        recipients = []

    if not recipients:
        assignment.delete()
        return json_error("Некому выдать задание — выберите группу, урок или учеников.")

    assignment.assign_to(recipients)
    due_text = f" Срок: {timezone.localtime(assignment.due_at):%d.%m %H:%M}." if assignment.due_at else ""
    notify_many(
        recipients,
        kind=NotificationKind.HOMEWORK_ASSIGNED,
        subject="Новое домашнее задание",
        body=f"«{assignment.title}» от {request.user.short_name}.{due_text}",
        url="/cabinet/homework/",
        dedupe_key=f"hw:{assignment.pk}",
    )
    return json_ok(f"Задание выдано ({len(recipients)} чел.).")


# --- Programs ------------------------------------------------------------

@teacher_required
def programs(request):
    queryset = Program.objects.filter(is_active=True).filter(
        Q(author=request.user) | Q(is_shared=True)
    ).select_related("language", "author").annotate(modules_count=Count("modules"))
    return render(request, "cabinet/teacher/programs.html", cabinet_context(
        request, programs=queryset,
    ))


@teacher_required
def program_detail(request, pk):
    program = get_object_or_404(
        Program.objects.select_related("language", "author").prefetch_related(
            Prefetch("modules", queryset=Module.objects.prefetch_related("units__materials"))
        ),
        pk=pk,
    )
    return render(request, "cabinet/teacher/program_detail.html", cabinet_context(
        request, program=program, can_edit=program.author_id == request.user.pk or request.user.is_owner,
    ))


@teacher_required
@require_POST
def program_create(request):
    title = (request.POST.get("title") or "").strip()
    language_id = request.POST.get("language")
    if not title or not language_id:
        return json_error("Укажите название и язык программы.")
    program = Program.objects.create(
        title=title, language_id=language_id, level=request.POST.get("level", ""),
        description=request.POST.get("description", ""), author=request.user,
    )
    return json_ok("Программа создана.", redirect=f"/cabinet/t/programs/{program.pk}/")


@teacher_required
@require_POST
def module_create(request, pk):
    program = get_object_or_404(Program, pk=pk)
    title = (request.POST.get("title") or "").strip()
    if not title:
        return json_error("Название модуля обязательно.")
    order = program.modules.count() + 1
    Module.objects.create(program=program, title=title, order=order,
                          summary=request.POST.get("summary", ""))
    return json_ok("Модуль добавлен.", redirect=f"/cabinet/t/programs/{program.pk}/")


@teacher_required
@require_POST
def unit_create(request, pk):
    module = get_object_or_404(Module, pk=pk)
    title = (request.POST.get("title") or "").strip()
    if not title:
        return json_error("Название темы обязательно.")
    unit = Unit.objects.create(
        module=module,
        title=title,
        order=module.units.count() + 1,
        objectives=request.POST.get("objectives", ""),
        content=request.POST.get("content", ""),
        vocabulary=request.POST.get("vocabulary", ""),
    )
    link = (request.POST.get("material_url") or "").strip()
    if link:
        Material.objects.create(unit=unit, title=request.POST.get("material_title") or "Материал",
                                kind=MaterialKind.LINK, url=link, uploaded_by=request.user)
    for upload in request.FILES.getlist("material_files"):
        Material.objects.create(unit=unit, title=upload.name, kind=MaterialKind.FILE,
                                file=upload, uploaded_by=request.user)
    return json_ok("Тема добавлена.", redirect=f"/cabinet/t/programs/{module.program_id}/")


# --- Availability --------------------------------------------------------

@teacher_required
def availability(request):
    return render(request, "cabinet/teacher/availability.html", cabinet_context(
        request,
        windows=request.user.availability.select_related("location").order_by("weekday", "start_time"),
        weekdays=WEEKDAYS,
        time_off=request.user.time_off.filter(ends_at__gte=timezone.now()).order_by("starts_at"),
        modes=DeliveryMode.choices,
    ))


@teacher_required
@require_POST
def availability_create(request):
    try:
        window = TeacherAvailability(
            teacher=request.user,
            weekday=int(request.POST["weekday"]),
            start_time=request.POST["start_time"],
            end_time=request.POST["end_time"],
            slot_minutes=int(request.POST.get("slot_minutes") or 60),
            mode=request.POST.get("mode") or DeliveryMode.ONLINE,
        )
        window.full_clean(exclude=["location"])
        window.save()
    except (KeyError, ValueError):
        return json_error("Заполните день и время.")
    except ValidationError as exc:
        return json_error(exc.messages[0])
    return json_ok("Окно добавлено.", redirect="/cabinet/t/availability/")


@teacher_required
@require_POST
def availability_delete(request, pk):
    request.user.availability.filter(pk=pk).delete()
    return json_ok("Окно удалено.")


@teacher_required
@require_POST
def time_off_create(request):
    from apps.scheduling.models import TimeOff

    starts = request.POST.get("starts_at")
    ends = request.POST.get("ends_at")
    if not starts or not ends:
        return json_error("Укажите период.")
    TimeOff.objects.create(
        teacher=request.user,
        starts_at=timezone.make_aware(datetime.fromisoformat(starts)),
        ends_at=timezone.make_aware(datetime.fromisoformat(ends)),
        reason=request.POST.get("reason", ""),
    )
    return json_ok("Период отмечен как недоступный.", redirect="/cabinet/t/availability/")
