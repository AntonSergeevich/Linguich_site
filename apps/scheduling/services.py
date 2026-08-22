"""Booking, attendance and lesson-generation rules.

Everything that changes a schedule goes through here so the invariants —
no double-booking, no silent double-charging — live in exactly one place.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.billing.models import LessonCharge, PackageStatus, StudentAccount
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify

from .models import (
    DeliveryMode,
    Enrollment,
    Lesson,
    LessonParticipant,
    LessonStatus,
    ParticipantStatus,
    RecurringSlot,
    TeacherAvailability,
    TimeOff,
)


def _aware(naive):
    return timezone.make_aware(naive, timezone.get_current_timezone())


def available_slots(teacher, start_date, days=14, mode=None, min_lead_hours=4):
    """Free bookable slots for a teacher, derived from their weekly windows
    minus real lessons and time off."""
    windows = teacher.availability.filter(is_active=True)
    if mode:
        windows = windows.filter(mode=mode)
    windows = list(windows.select_related("location"))
    if not windows:
        return []

    horizon_start = _aware(datetime.combine(start_date, datetime.min.time()))
    horizon_end = horizon_start + timedelta(days=days)

    busy = [
        (lesson.starts_at, lesson.ends_at)
        for lesson in Lesson.objects.filter(
            teacher=teacher,
            status=LessonStatus.SCHEDULED,
            starts_at__gte=horizon_start - timedelta(hours=6),
            starts_at__lt=horizon_end,
        )
    ]
    busy += [
        (off.starts_at, off.ends_at)
        for off in TimeOff.objects.filter(teacher=teacher, ends_at__gte=horizon_start, starts_at__lt=horizon_end)
    ]

    earliest = timezone.now() + timedelta(hours=min_lead_hours)
    slots = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        for window in windows:
            if window.weekday != day.weekday():
                continue
            for naive_start in window.slot_starts_for(day):
                start = _aware(naive_start)
                end = start + timedelta(minutes=window.slot_minutes)
                if start < earliest:
                    continue
                if any(start < b_end and end > b_start for b_start, b_end in busy):
                    continue
                slots.append({
                    "start": start,
                    "end": end,
                    "duration": window.slot_minutes,
                    "mode": window.mode,
                    "location": window.location,
                    "window_id": window.pk,
                })
    slots.sort(key=lambda s: s["start"])
    return slots


@transaction.atomic
def book_slot(student, teacher, start, duration=60, mode=DeliveryMode.ONLINE, location=None,
              course=None, is_trial=False, topic=""):
    """Create a one-off individual lesson and put the student in it."""
    end = start + timedelta(minutes=duration)
    # Окно-префильтр: ни один урок не длиннее суток, поэтому кандидатов на
    # пересечение достаточно искать в этом диапазоне, а само пересечение
    # проверяем по фактическому времени окончания.
    window_start = start - timedelta(days=1)

    clash = Lesson.objects.select_for_update().filter(
        teacher=teacher,
        status=LessonStatus.SCHEDULED,
        starts_at__lt=end,
        starts_at__gt=window_start,
    )
    if any(lesson.ends_at > start for lesson in clash):
        raise ValidationError("Это время только что заняли. Выберите, пожалуйста, другое.")
    if TimeOff.objects.filter(teacher=teacher, starts_at__lt=end, ends_at__gt=start).exists():
        raise ValidationError("Преподаватель недоступен в это время.")

    own = LessonParticipant.objects.filter(
        student=student,
        lesson__starts_at__lt=end,
        lesson__starts_at__gt=window_start,
        lesson__status=LessonStatus.SCHEDULED,
    ).exclude(status=ParticipantStatus.CANCELLED).select_related("lesson")
    if any(p.lesson.ends_at > start for p in own):
        raise ValidationError("У вас уже есть занятие в это время.")

    lesson = Lesson.objects.create(
        teacher=teacher,
        course=course,
        topic=topic,
        starts_at=start,
        duration_minutes=duration,
        mode=mode,
        location=location,
        capacity=1,
        is_trial=is_trial,
    )
    participant = LessonParticipant.objects.create(lesson=lesson, student=student)

    local = timezone.localtime(start)
    notify(
        student,
        NotificationKind.LESSON_BOOKED,
        "Урок забронирован",
        f"{local:%d.%m в %H:%M} — {teacher.short_name}. Ждём вас!",
        url="/cabinet/schedule/",
        lesson=lesson,
        dedupe_key=f"booked:{participant.pk}",
    )
    notify(
        teacher,
        NotificationKind.LESSON_BOOKED,
        "Новая запись на урок",
        f"{student.full_name} записался на {local:%d.%m в %H:%M}.",
        url="/cabinet/schedule/",
        lesson=lesson,
        dedupe_key=f"booked-teacher:{participant.pk}",
    )
    schedule_reminders_for(lesson)
    return lesson


@transaction.atomic
def join_lesson(student, lesson):
    """Add a student to an existing open lesson (group class, speaking club)."""
    if lesson.status != LessonStatus.SCHEDULED:
        raise ValidationError("Урок больше не активен.")
    if lesson.is_past:
        raise ValidationError("Этот урок уже прошёл.")

    participant = LessonParticipant.objects.filter(lesson=lesson, student=student).first()
    if participant and participant.status != ParticipantStatus.CANCELLED:
        return participant
    if lesson.seats_left <= 0:
        raise ValidationError("Свободных мест не осталось.")

    if participant:
        participant.status = ParticipantStatus.BOOKED
        participant.cancelled_at = None
        participant.is_chargeable = True
        participant.save(update_fields=["status", "cancelled_at", "is_chargeable"])
    else:
        participant = LessonParticipant.objects.create(lesson=lesson, student=student)

    schedule_reminders_for(lesson)
    return participant


@transaction.atomic
def cancel_participation(participant, by_user, reason=""):
    """Student (or staff) drops out of a lesson.

    Cancelling inside the free window keeps the lesson unpaid; later than that
    the lesson is still consumed — same as the school's offline policy.
    """
    lesson = participant.lesson
    if participant.status == ParticipantStatus.CANCELLED:
        return participant
    if lesson.is_past:
        raise ValidationError("Прошедший урок отменить нельзя.")

    free = lesson.can_be_cancelled_free_by(by_user) or by_user.is_teacher
    participant.status = ParticipantStatus.CANCELLED if free else ParticipantStatus.EXCUSED
    participant.is_chargeable = not free
    participant.cancelled_at = timezone.now()
    participant.save(update_fields=["status", "is_chargeable", "cancelled_at"])

    if not free:
        charge_participant(participant, note="Поздняя отмена")

    # A one-to-one slot with nobody left in it should free the teacher's calendar.
    if lesson.capacity == 1 and not lesson.active_participants.exists():
        lesson.status = LessonStatus.CANCELLED
        lesson.cancelled_reason = reason or "Отменён учеником"
        lesson.save(update_fields=["status", "cancelled_reason"])

    local = timezone.localtime(lesson.starts_at)
    notify(
        lesson.teacher,
        NotificationKind.LESSON_CANCELLED,
        "Отмена занятия",
        f"{participant.student.full_name} отменил урок {local:%d.%m в %H:%M}."
        + ("" if free else " Отмена поздняя — урок списан."),
        url="/cabinet/schedule/",
        lesson=lesson,
        dedupe_key=f"cancel:{participant.pk}",
    )
    return participant


@transaction.atomic
def cancel_lesson(lesson, by_user, reason=""):
    """School-side cancellation: nobody is charged."""
    lesson.status = LessonStatus.CANCELLED
    lesson.cancelled_reason = reason
    lesson.save(update_fields=["status", "cancelled_reason"])
    local = timezone.localtime(lesson.starts_at)
    for participant in lesson.active_participants.select_related("student"):
        participant.is_chargeable = False
        participant.save(update_fields=["is_chargeable"])
        notify(
            participant.student,
            NotificationKind.LESSON_CANCELLED,
            "Урок отменён",
            f"Занятие {local:%d.%m в %H:%M} отменено. {reason}".strip(),
            url="/cabinet/schedule/",
            lesson=lesson,
            dedupe_key=f"lesson-cancel:{lesson.pk}:{participant.student_id}",
        )
    lesson.notifications.filter(status="pending").update(status="skipped")
    return lesson


def uncharge_participant(participant):
    """Возвращает списанное занятие на абонемент. Идемпотентна."""
    charge = getattr(participant, "charge", None)
    if charge is None:
        return None
    package = charge.package
    charge.delete()
    # Кэш обратной связи OneToOne остаётся в объекте — без сброса повторное
    # списание решит, что урок уже оплачен, и молча ничего не сделает.
    try:
        del participant.charge
    except AttributeError:
        pass
    if package:
        package.refresh_status()
    return package


@transaction.atomic
def charge_participant(participant, note=""):
    """Consume one lesson from the student's package. Idempotent."""
    if hasattr(participant, "charge"):
        return participant.charge
    if not participant.is_chargeable:
        return None

    student = participant.student
    account = StudentAccount(student)
    package = account.active_package
    amount = Decimal("0")
    if package and package.tariff:
        amount = package.tariff.price_per_lesson
    elif package and package.lessons_total:
        amount = (Decimal(str(package.price)) / package.lessons_total).quantize(Decimal("0.01"))
    elif participant.lesson.course:
        amount = Decimal(str(participant.lesson.course.price_per_lesson))

    charge = LessonCharge.objects.create(
        participant=participant,
        student=student,
        package=package,
        amount=amount or 0,
        note=note,
    )
    if package:
        package.refresh_status()
        if package.lessons_left in (0, 1, 2):
            notify(
                student,
                NotificationKind.PACKAGE_LOW,
                "Абонемент заканчивается",
                f"Осталось занятий: {package.lessons_left}. Продлите абонемент, чтобы не прерывать курс.",
                url="/cabinet/payments/",
                dedupe_key=f"low:{package.pk}:{package.lessons_left}",
            )
    return charge


CHARGEABLE = {ParticipantStatus.ATTENDED, ParticipantStatus.ABSENT}


@transaction.atomic
def save_attendance(lesson, marks, by_user):
    """``marks`` maps participant id -> ParticipantStatus. Charges follow attendance."""
    for participant in lesson.participants.select_related("student"):
        new_status = marks.get(str(participant.pk)) or marks.get(participant.pk)
        if not new_status or new_status not in ParticipantStatus.values:
            continue
        if participant.status == new_status:
            continue
        participant.status = new_status
        # "Был" and "не пришёл" both consume the lesson; a documented early
        # cancellation does not.
        participant.is_chargeable = new_status in CHARGEABLE
        participant.save(update_fields=["status", "is_chargeable"])
        if participant.is_chargeable:
            charge_participant(participant)
        else:
            uncharge_participant(participant)

    return complete_lesson(lesson, by_user)


@transaction.atomic
def complete_lesson(lesson, by_user=None, now=None):
    """Урок проведён. Все, кого не отметили иначе, считаются пришедшими.

    ``by_user`` пустой — урок отметился сам по времени; кабинет покажет это
    отдельной плашкой, чтобы преподаватель мог поправить.
    """
    for participant in lesson.participants.select_related("student"):
        if participant.status == ParticipantStatus.CANCELLED:
            continue
        if participant.status == ParticipantStatus.BOOKED:
            participant.status = ParticipantStatus.ATTENDED
            participant.is_chargeable = True
            participant.save(update_fields=["status", "is_chargeable"])
        if participant.is_chargeable:
            charge_participant(participant)

    lesson.status = LessonStatus.COMPLETED
    lesson.completed_at = now or timezone.now()
    lesson.completed_by = by_user
    lesson.save(update_fields=["status", "completed_at", "completed_by"])
    return lesson


@transaction.atomic
def confirm_completion(lesson, by_user):
    """«Всё верно»: человек посмотрел на автоотметку и согласился.

    Ничего не пересчитывает — только снимает с урока признак «отметился сам»,
    чтобы плашка не висела вечно.
    """
    if lesson.status != LessonStatus.COMPLETED or lesson.completed_by_id:
        return lesson
    lesson.completed_by = by_user
    lesson.save(update_fields=["completed_by"])
    return lesson


@transaction.atomic
def reopen_lesson(lesson, by_user, reason=""):
    """Урок не состоялся: снимаем списания и возвращаем занятия на абонемент.

    Отдельная операция, а не «отменить»: отмена уведомляет учеников, а здесь
    исправляют уже случившуюся автоотметку — беспокоить людей незачем.
    """
    for participant in lesson.participants.all():
        participant.is_chargeable = False
        if participant.status in CHARGEABLE:
            participant.status = ParticipantStatus.EXCUSED
        participant.save(update_fields=["status", "is_chargeable"])
        uncharge_participant(participant)

    lesson.status = LessonStatus.CANCELLED
    lesson.cancelled_reason = reason or "Урок не состоялся"
    lesson.completed_at = None
    lesson.completed_by = by_user
    lesson.save(update_fields=["status", "cancelled_reason", "completed_at", "completed_by"])
    return lesson


def autocomplete_lessons(now=None):
    """Отмечает проведёнными уроки, у которых вышла отсрочка. Идемпотентна."""
    now = now or timezone.now()
    minutes = getattr(settings, "LESSON_AUTOCOMPLETE_MINUTES", 45)
    # Урок не может закончиться раньше, чем начался, поэтому фильтр по началу
    # — надёжное «не больше чем нужно»: точную границу считаем по ends_at,
    # которое зависит от длительности каждого урока.
    candidates = Lesson.objects.filter(
        status=LessonStatus.SCHEDULED, starts_at__lt=now - timedelta(minutes=minutes)
    ).prefetch_related("participants")
    done = 0
    for lesson in candidates:
        if lesson.autocompletes_at > now:
            continue
        complete_lesson(lesson, by_user=None, now=now)
        done += 1
    return done


def schedule_reminders_for(lesson):
    """Queue the pre-lesson pings for everyone involved."""
    offsets = getattr(settings, "LESSON_REMINDER_OFFSETS", [1440, 60])
    local = timezone.localtime(lesson.starts_at)
    for minutes in offsets:
        fire_at = lesson.starts_at - timedelta(minutes=minutes)
        if fire_at <= timezone.now():
            continue
        when = "завтра" if minutes >= 720 else f"через {minutes} мин"
        for participant in lesson.active_participants.select_related("student"):
            notify(
                participant.student,
                NotificationKind.LESSON_REMINDER,
                f"Урок {when}",
                f"{lesson.title} — {local:%d.%m в %H:%M}, преподаватель {lesson.teacher.short_name}.",
                url="/cabinet/schedule/",
                lesson=lesson,
                scheduled_for=fire_at,
                dedupe_key=f"reminder:{lesson.pk}:{participant.student_id}:{minutes}",
            )


def generate_lessons(weeks=4, from_date=None):
    """Materialise group lessons from weekly slots. Safe to re-run."""
    start = from_date or timezone.localdate()
    end = start + timedelta(weeks=weeks)
    created = 0

    for slot in RecurringSlot.objects.select_related("group", "group__teacher", "group__location").filter(
        group__is_active=True
    ):
        group = slot.group
        day = start
        while day < end:
            if day.weekday() == slot.weekday:
                if group.starts_on and day < group.starts_on:
                    day += timedelta(days=1)
                    continue
                if group.ends_on and day > group.ends_on:
                    break
                starts_at = _aware(datetime.combine(day, slot.start_time))
                if not Lesson.objects.filter(group=group, starts_at=starts_at).exists():
                    lesson = Lesson.objects.create(
                        group=group,
                        course=group.course,
                        teacher=group.teacher,
                        starts_at=starts_at,
                        duration_minutes=slot.duration_minutes,
                        mode=group.mode,
                        location=group.location,
                        meeting_url=group.meeting_url,
                        capacity=group.capacity,
                    )
                    students = [e.student for e in group.active_enrollments.select_related("student")]
                    LessonParticipant.objects.bulk_create(
                        [LessonParticipant(lesson=lesson, student=s) for s in students]
                    )
                    created += 1
            day += timedelta(days=1)
    return created


def sync_group_roster(enrollment):
    """When a student joins a group mid-course, add them to future lessons."""
    future = enrollment.group.lessons.filter(
        starts_at__gte=timezone.now(), status=LessonStatus.SCHEDULED
    )
    LessonParticipant.objects.bulk_create(
        [LessonParticipant(lesson=lesson, student=enrollment.student) for lesson in future],
        ignore_conflicts=True,
    )
