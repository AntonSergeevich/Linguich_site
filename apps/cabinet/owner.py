import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Role, StudentProfile, StudentStatus, User, normalize_phone
from apps.billing.models import (
    LessonCharge,
    Package,
    PackageStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    StudentAccount,
    Tariff,
)
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify
from apps.scheduling import services as sched
from apps.scheduling.models import (
    Enrollment,
    Group,
    Lesson,
    LessonParticipant,
    LessonStatus,
    ParticipantStatus,
    RecurringSlot,
)
from apps.school.models import Course, Lead, LeadStatus, Location
from apps.utils import json_error, json_ok, manager_required, owner_required

from .common import as_datetime_range, cabinet_context

ZERO = Decimal("0.00")
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _month_start(offset=0):
    today = timezone.localdate().replace(day=1)
    year, month = today.year, today.month - offset
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


@manager_required
def crm_home(request):
    """The one screen that answers «как идут дела»."""
    today = timezone.localdate()
    month_start = _month_start()
    prev_start = _month_start(1)

    paid = Payment.objects.filter(status=PaymentStatus.PAID)
    revenue_month = paid.filter(paid_on__gte=month_start).aggregate(s=Sum("amount"))["s"] or ZERO
    revenue_prev = paid.filter(paid_on__gte=prev_start, paid_on__lt=month_start).aggregate(
        s=Sum("amount")
    )["s"] or ZERO
    delta = None
    if revenue_prev:
        delta = round(100 * (revenue_month - revenue_prev) / revenue_prev)

    # 12-месячный график выручки
    series = (
        paid.filter(paid_on__gte=_month_start(11))
        .annotate(month=TruncMonth("paid_on"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("month")
    )
    buckets = {row["month"].strftime("%Y-%m"): row["total"] for row in series}
    chart = []
    for index in range(11, -1, -1):
        point = _month_start(index)
        value = buckets.get(point.strftime("%Y-%m"), ZERO)
        chart.append({"label": MONTHS_SHORT[point.month - 1], "value": value})
    peak = max((row["value"] for row in chart), default=ZERO) or Decimal("1")
    for row in chart:
        row["percent"] = round(100 * row["value"] / peak)

    debtors = _debtors()
    total_debt = sum(row["balance"] for row in debtors)

    week_start, week_end = as_datetime_range(today, today + timedelta(days=7))
    return render(request, "cabinet/owner/dashboard.html", cabinet_context(
        request,
        revenue_month=revenue_month,
        revenue_prev=revenue_prev,
        revenue_delta=delta,
        chart=chart,
        active_students=User.objects.filter(
            role=Role.STUDENT, is_active=True, student_profile__status=StudentStatus.ACTIVE
        ).count(),
        new_leads=Lead.objects.filter(status=LeadStatus.NEW).count(),
        leads_month=Lead.objects.filter(created_at__date__gte=month_start).count(),
        lessons_week=Lesson.objects.filter(
            starts_at__gte=week_start, starts_at__lt=week_end
        ).exclude(status=LessonStatus.CANCELLED).count(),
        debtors=debtors[:8],
        debtor_count=len(debtors),
        total_debt=total_debt,
        recent_payments=paid.select_related("student").order_by("-paid_on", "-id")[:8],
        recent_leads=Lead.objects.order_by("-created_at")[:6],
        funnel=[
            (label, Lead.objects.filter(status=value).count())
            for value, label in LeadStatus.choices
        ],
    ))


def _debtors():
    """Students whose issued packages exceed what they have paid."""
    rows = []
    students = (
        User.objects.filter(role=Role.STUDENT)
        .annotate(
            billed=Coalesce(
                Sum("packages__price", filter=~Q(packages__status=PackageStatus.CANCELLED)),
                Value(ZERO), output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            settled=Coalesce(
                Sum("payments__amount", filter=Q(payments__status=PaymentStatus.PAID)),
                Value(ZERO), output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
        )
        .select_related("student_profile")
    )
    for student in students:
        balance = student.billed - student.settled
        if balance > 0:
            rows.append({"student": student, "balance": balance,
                         "billed": student.billed, "paid": student.settled})
    rows.sort(key=lambda row: row["balance"], reverse=True)
    return rows


# --- Leads ---------------------------------------------------------------

@manager_required
def leads(request):
    queryset = Lead.objects.select_related("language", "course", "assigned_to")
    status = request.GET.get("status", "")
    search = request.GET.get("q", "").strip()
    if status:
        queryset = queryset.filter(status=status)
    if search:
        queryset = queryset.filter(Q(name__icontains=search) | Q(phone__icontains=search))

    columns = []
    for value, label in LeadStatus.choices:
        columns.append({
            "value": value,
            "label": label,
            "items": Lead.objects.filter(status=value).order_by("-created_at")[:25],
            "count": Lead.objects.filter(status=value).count(),
        })

    return render(request, "cabinet/owner/leads.html", cabinet_context(
        request,
        leads=queryset[:100],
        columns=columns,
        statuses=LeadStatus.choices,
        active_status=status,
        search=search,
        view=request.GET.get("view", "board"),
        managers=User.objects.filter(role__in=[Role.OWNER, Role.TEACHER], is_active=True),
    ))


@manager_required
@require_POST
def lead_update(request, pk):
    lead = get_object_or_404(Lead, pk=pk)
    data = json.loads(request.body or "{}") if request.content_type == "application/json" else request.POST

    if "status" in data:
        # Молча игнорировать неизвестный статус нельзя: доска покажет
        # карточку в новой колонке, а в базе останется старая — расхождение
        # заметят только через день.
        if data["status"] not in dict(LeadStatus.choices):
            return json_error("Неизвестный статус заявки.")
        lead.status = data["status"]
    if "admin_notes" in data:
        lead.admin_notes = data["admin_notes"]
    if data.get("assigned_to"):
        manager = User.objects.filter(
            pk=data["assigned_to"], is_active=True,
            role__in=[Role.OWNER, Role.ADMIN, Role.TEACHER],
        ).first()
        if manager is None:
            return json_error("Такого сотрудника нет.")
        lead.assigned_to = manager
    lead.save()
    return json_ok("Заявка обновлена.")


@manager_required
@require_POST
def lead_convert(request, pk):
    """Turn a lead into a real student account in one click."""
    lead = get_object_or_404(Lead, pk=pk)
    if lead.converted_user_id:
        return json_error("Заявка уже превращена в ученика.")

    phone = normalize_phone(lead.phone)
    existing = User.objects.filter(Q(phone=phone) | Q(email__iexact=lead.email or "\0")).first()
    if existing:
        user = existing
    else:
        parts = lead.name.split()
        user = User.objects.create_user(
            email=lead.email or None,
            phone=phone,
            first_name=parts[0] if parts else lead.name,
            last_name=" ".join(parts[1:]),
            role=Role.STUDENT,
        )
    StudentProfile.objects.get_or_create(
        user=user,
        defaults={"status": StudentStatus.TRIAL, "level": lead.placement_level or "",
                  "source": lead.get_source_display()},
    )
    lead.converted_user = user
    lead.status = LeadStatus.WON
    lead.save(update_fields=["converted_user", "status"])
    return json_ok("Ученик создан.", redirect=f"/cabinet/crm/students/{user.pk}/")


# --- Students ------------------------------------------------------------

@manager_required
def students(request):
    queryset = (
        User.objects.filter(role=Role.STUDENT)
        .select_related("student_profile")
        .prefetch_related("enrollments__group__teacher")
    )
    status = request.GET.get("status", "")
    search = request.GET.get("q", "").strip()
    teacher_id = request.GET.get("teacher", "")
    debt_only = request.GET.get("debt") == "1"

    if status:
        queryset = queryset.filter(student_profile__status=status)
    if search:
        queryset = queryset.filter(
            Q(first_name__icontains=search) | Q(last_name__icontains=search)
            | Q(phone__icontains=search) | Q(email__icontains=search)
        )
    if teacher_id:
        queryset = queryset.filter(
            Q(enrollments__group__teacher_id=teacher_id) | Q(lesson_participations__lesson__teacher_id=teacher_id)
        ).distinct()

    rows = []
    for student in queryset.order_by("first_name")[:300]:
        account = StudentAccount(student)
        if debt_only and account.balance <= 0:
            continue
        enrollment = student.enrollments.filter(is_active=True).first()
        rows.append({
            "student": student,
            "account": account,
            "group": enrollment.group if enrollment else None,
            "teacher": enrollment.group.teacher if enrollment else None,
            "next": Lesson.objects.filter(
                participants__student=student, starts_at__gte=timezone.now(), status=LessonStatus.SCHEDULED
            ).order_by("starts_at").first(),
        })

    return render(request, "cabinet/owner/students.html", cabinet_context(
        request,
        rows=rows,
        statuses=StudentStatus.choices,
        active_status=status,
        search=search,
        teacher_id=teacher_id,
        debt_only=debt_only,
        teachers=User.objects.filter(role__in=[Role.TEACHER, Role.OWNER], is_active=True),
    ))


@manager_required
def student_card(request, pk):
    student = get_object_or_404(User.objects.select_related("student_profile"), pk=pk, role=Role.STUDENT)
    account = StudentAccount(student)
    lessons = Lesson.objects.filter(participants__student=student).select_related("teacher", "group")

    return render(request, "cabinet/owner/student_card.html", cabinet_context(
        request,
        student=student,
        profile=getattr(student, "student_profile", None),
        account=account,
        packages=student.packages.select_related("tariff").order_by("-issued_on"),
        payments=student.payments.order_by("-paid_on")[:20],
        charges=student.lesson_charges.select_related("participant__lesson").order_by("-charged_at")[:20],
        enrollments=student.enrollments.select_related("group", "group__teacher", "group__course"),
        upcoming=lessons.filter(starts_at__gte=timezone.now(), status=LessonStatus.SCHEDULED).order_by("starts_at")[:5],
        history=lessons.filter(starts_at__lt=timezone.now()).order_by("-starts_at")[:10],
        tariffs=Tariff.objects.filter(is_active=True),
        groups=Group.objects.filter(is_active=True).select_related("course", "teacher"),
        methods=PaymentMethod.choices,
        statuses=StudentStatus.choices,
        attendance={
            "attended": student.lesson_participations.filter(status=ParticipantStatus.ATTENDED).count(),
            "absent": student.lesson_participations.filter(status=ParticipantStatus.ABSENT).count(),
        },
    ))


@manager_required
@require_POST
def student_update(request, pk):
    student = get_object_or_404(User, pk=pk, role=Role.STUDENT)
    profile, _created = StudentProfile.objects.get_or_create(user=student)
    if request.POST.get("status") in dict(StudentStatus.choices):
        profile.status = request.POST["status"]
    profile.internal_notes = request.POST.get("internal_notes", profile.internal_notes)
    profile.level = request.POST.get("level", profile.level)
    profile.save()
    return json_ok("Карточка обновлена.")


@manager_required
@require_POST
def enrollment_create(request, pk):
    student = get_object_or_404(User, pk=pk, role=Role.STUDENT)
    group = get_object_or_404(Group, pk=request.POST.get("group"))
    if group.seats_left <= 0:
        return json_error("В группе нет свободных мест.")
    enrollment, created = Enrollment.objects.get_or_create(student=student, group=group)
    if not created and enrollment.is_active:
        return json_error("Ученик уже в этой группе.")
    enrollment.is_active = True
    enrollment.ended_on = None
    enrollment.save()
    sched.sync_group_roster(enrollment)
    return json_ok(f"Ученик добавлен в «{group.name}».")


# --- Payments ------------------------------------------------------------

@manager_required
def payments(request):
    queryset = Payment.objects.select_related("student", "package", "created_by")
    period = request.GET.get("period", "month")
    search = request.GET.get("q", "").strip()

    if period == "month":
        queryset = queryset.filter(paid_on__gte=_month_start())
    elif period == "prev":
        queryset = queryset.filter(paid_on__gte=_month_start(1), paid_on__lt=_month_start())
    elif period == "year":
        queryset = queryset.filter(paid_on__year=timezone.localdate().year)
    if search:
        queryset = queryset.filter(
            Q(student__first_name__icontains=search) | Q(student__last_name__icontains=search)
        )

    totals = queryset.filter(status=PaymentStatus.PAID).aggregate(total=Sum("amount"), count=Count("id"))
    by_method = (
        queryset.filter(status=PaymentStatus.PAID)
        .values("method").annotate(total=Sum("amount")).order_by("-total")
    )
    method_labels = dict(PaymentMethod.choices)
    for row in by_method:
        row["label"] = method_labels.get(row["method"], row["method"])

    debtors = _debtors()
    return render(request, "cabinet/owner/payments.html", cabinet_context(
        request,
        payments=queryset.order_by("-paid_on", "-id")[:200],
        total=totals["total"] or ZERO,
        count=totals["count"] or 0,
        by_method=by_method,
        period=period,
        search=search,
        debtors=debtors,
        total_debt=sum(row["balance"] for row in debtors),
        students=User.objects.filter(role=Role.STUDENT, is_active=True).order_by("first_name"),
        methods=PaymentMethod.choices,
        tariffs=Tariff.objects.filter(is_active=True),
    ))


@manager_required
@require_POST
def payment_create(request):
    student = get_object_or_404(User, pk=request.POST.get("student"), role=Role.STUDENT)
    try:
        amount = Decimal(request.POST.get("amount", "0").replace(",", "."))
    except Exception:
        return json_error("Некорректная сумма.", fields={"amount": "Введите число"})
    if amount <= 0:
        return json_error("Сумма должна быть больше нуля.", fields={"amount": "Больше нуля"})

    paid_on = request.POST.get("paid_on")
    payment = Payment.objects.create(
        student=student,
        amount=amount,
        method=request.POST.get("method") or PaymentMethod.CARD,
        paid_on=date.fromisoformat(paid_on) if paid_on else timezone.localdate(),
        comment=request.POST.get("comment", ""),
        created_by=request.user,
    )

    # Оплата вместе с выдачей абонемента — самый частый сценарий у стойки.
    tariff_id = request.POST.get("tariff")
    if tariff_id:
        tariff = get_object_or_404(Tariff, pk=tariff_id)
        package = Package.objects.create(
            student=student, tariff=tariff, lessons_total=tariff.lessons_count,
            price=tariff.price, created_by=request.user,
        )
        payment.package = package
        payment.save(update_fields=["package"])

    notify(
        student,
        NotificationKind.PAYMENT_RECEIVED,
        "Платёж получен",
        f"Спасибо! Зачислили {amount:.0f} ₽."
        + (f" Абонемент на {package.lessons_total} занятий активен." if tariff_id else ""),
        url="/cabinet/payments/",
        dedupe_key=f"payment:{payment.pk}",
    )
    return json_ok("Платёж записан.")


@manager_required
@require_POST
def package_create(request):
    student = get_object_or_404(User, pk=request.POST.get("student"), role=Role.STUDENT)
    tariff_id = request.POST.get("tariff")
    if tariff_id:
        tariff = get_object_or_404(Tariff, pk=tariff_id)
        lessons, price = tariff.lessons_count, tariff.price
    else:
        tariff = None
        lessons = int(request.POST.get("lessons_total") or 0)
        try:
            price = Decimal(request.POST.get("price", "0").replace(",", "."))
        except Exception:
            return json_error("Некорректная стоимость.")
        if not lessons:
            return json_error("Укажите количество занятий.")

    Package.objects.create(
        student=student, tariff=tariff, lessons_total=lessons, price=price,
        comment=request.POST.get("comment", ""), created_by=request.user,
    )
    return json_ok("Абонемент выдан. Долг обновлён.")


@manager_required
@require_POST
def debt_remind(request):
    """Nudge every debtor at once — the task the owner does by hand today."""
    sent = 0
    for row in _debtors():
        notify(
            row["student"],
            NotificationKind.PAYMENT_DUE,
            "Напоминание об оплате",
            f"По вашему счёту числится задолженность {row['balance']:.0f} ₽. "
            "Оплатить можно в школе или переводом — реквизиты пришлём по запросу.",
            url="/cabinet/payments/",
            dedupe_key=f"debt:{row['student'].pk}:{timezone.localdate():%Y-%m-%d}",
        )
        sent += 1
    return json_ok(f"Напоминания отправлены: {sent}.")


# --- Groups --------------------------------------------------------------

@manager_required
def groups(request):
    queryset = (
        Group.objects.select_related("course", "course__language", "teacher", "location", "program")
        .prefetch_related("slots")
        .annotate(students=Count("enrollments", filter=Q(enrollments__is_active=True)))
        .order_by("-is_active", "name")
    )
    return render(request, "cabinet/owner/groups.html", cabinet_context(
        request,
        groups=queryset,
        courses=Course.objects.filter(is_active=True).select_related("language"),
        teachers=User.objects.filter(role__in=[Role.TEACHER, Role.OWNER], is_active=True),
        locations=Location.objects.filter(is_active=True),
    ))


@manager_required
@require_POST
def group_create(request):
    name = (request.POST.get("name") or "").strip()
    if not name:
        return json_error("Укажите название группы.", fields={"name": "Обязательное поле"})
    group = Group.objects.create(
        name=name,
        course_id=request.POST["course"],
        teacher_id=request.POST["teacher"],
        location_id=request.POST.get("location") or None,
        capacity=int(request.POST.get("capacity") or 8),
        level=request.POST.get("level", ""),
        mode=request.POST.get("mode", "offline"),
        meeting_url=request.POST.get("meeting_url", ""),
        starts_on=request.POST.get("starts_on") or None,
    )
    for weekday, start_time in zip(request.POST.getlist("weekday"), request.POST.getlist("start_time")):
        if weekday and start_time:
            RecurringSlot.objects.create(
                group=group, weekday=int(weekday), start_time=start_time,
                duration_minutes=int(request.POST.get("duration") or 60),
            )
    created = sched.generate_lessons(weeks=6)
    return json_ok(f"Группа создана, уроков в расписании: {created}.")


@manager_required
@require_POST
def generate_schedule(request):
    weeks = int(json.loads(request.body or "{}").get("weeks", 4))
    created = sched.generate_lessons(weeks=weeks)
    return json_ok(f"Создано занятий: {created}.")


# --- Staff ---------------------------------------------------------------

@owner_required
def staff(request):
    month_start = _month_start()
    teachers = (
        User.objects.filter(role__in=[Role.TEACHER, Role.OWNER])
        .select_related("teacher_profile").order_by("first_name")
    )
    rows = []
    for teacher in teachers:
        held = teacher.lessons_taught.filter(
            status=LessonStatus.COMPLETED, starts_at__date__gte=month_start
        ).count()
        rate = getattr(getattr(teacher, "teacher_profile", None), "pay_rate", ZERO) or ZERO
        rows.append({
            "teacher": teacher,
            "lessons_month": held,
            "payroll": rate * held,
            "students": LessonParticipant.objects.filter(lesson__teacher=teacher)
                        .values("student").distinct().count(),
            "upcoming": teacher.lessons_taught.filter(
                starts_at__gte=timezone.now(), status=LessonStatus.SCHEDULED
            ).count(),
        })
    return render(request, "cabinet/owner/staff.html", cabinet_context(
        request, rows=rows, payroll_total=sum(row["payroll"] for row in rows), month_start=month_start,
    ))
