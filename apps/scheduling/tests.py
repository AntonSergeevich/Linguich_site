"""Инварианты расписания: без двойных броней и без двойных списаний."""

from datetime import time, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role, StudentProfile, TeacherProfile, User
from apps.billing.models import LessonCharge, Package, StudentAccount, Tariff
from apps.notifications.models import Notification, NotificationKind
from apps.school.models import Course, Language

from . import services
from .models import (
    DeliveryMode,
    Enrollment,
    Group,
    Lesson,
    LessonParticipant,
    LessonStatus,
    ParticipantStatus,
    RecurringSlot,
    TeacherAvailability,
    TimeOff,
)


class SchedulingTestCase(TestCase):
    def setUp(self):
        self.language = Language.objects.create(name="Английский", slug="en")
        self.course = Course.objects.create(
            language=self.language, title="Английский", slug="eng", price_per_lesson=1000
        )
        self.teacher = User.objects.create_user(
            email="t@x.ru", first_name="Анна", last_name="С", role=Role.TEACHER
        )
        TeacherProfile.objects.create(user=self.teacher)
        self.student = User.objects.create_user(
            email="s@x.ru", first_name="Егор", last_name="Т", role=Role.STUDENT
        )
        StudentProfile.objects.create(user=self.student)

    def slot(self, days=2, hour=17):
        base = timezone.localtime(timezone.now()) + timedelta(days=days)
        return base.replace(hour=hour, minute=0, second=0, microsecond=0)


class BookingTests(SchedulingTestCase):
    def test_slots_come_from_availability_and_drop_once_taken(self):
        weekday = self.slot().weekday()
        TeacherAvailability.objects.create(
            teacher=self.teacher, weekday=weekday, start_time=time(16, 0),
            end_time=time(20, 0), slot_minutes=60,
        )
        free = services.available_slots(self.teacher, timezone.localdate(), days=7)
        self.assertTrue(free)

        chosen = free[0]["start"]
        services.book_slot(self.student, self.teacher, chosen)

        after = [s["start"] for s in services.available_slots(self.teacher, timezone.localdate(), days=7)]
        self.assertNotIn(chosen, after)

    def test_second_booking_on_same_slot_is_rejected(self):
        start = self.slot()
        services.book_slot(self.student, self.teacher, start)
        other = User.objects.create_user(email="s2@x.ru", first_name="Полина", role=Role.STUDENT)
        with self.assertRaises(ValidationError):
            services.book_slot(other, self.teacher, start)

    def test_adjacent_slots_do_not_collide(self):
        """Урок 17:00–18:00 не должен блокировать 18:00–19:00."""
        start = self.slot(hour=17)
        services.book_slot(self.student, self.teacher, start, duration=60)
        services.book_slot(self.student, self.teacher, start + timedelta(hours=1), duration=60)
        self.assertEqual(Lesson.objects.filter(teacher=self.teacher).count(), 2)

    def test_earlier_lesson_same_day_does_not_block_evening(self):
        """Регрессия: грубый 12-часовой фильтр раньше считал занятым весь день."""
        morning = self.slot(hour=9)
        services.book_slot(self.student, self.teacher, morning)
        services.book_slot(self.student, self.teacher, self.slot(hour=19))
        self.assertEqual(self.student.lesson_participations.count(), 2)

    def test_time_off_blocks_booking(self):
        start = self.slot()
        TimeOff.objects.create(
            teacher=self.teacher, starts_at=start - timedelta(hours=1),
            ends_at=start + timedelta(hours=2), reason="отпуск",
        )
        with self.assertRaises(ValidationError):
            services.book_slot(self.student, self.teacher, start)

    def test_booking_queues_reminders_for_the_future_only(self):
        services.book_slot(self.student, self.teacher, self.slot(days=3))
        reminders = Notification.objects.filter(
            recipient=self.student, kind=NotificationKind.LESSON_REMINDER
        )
        self.assertTrue(reminders.exists())
        self.assertTrue(all(n.scheduled_for > timezone.now() for n in reminders))


class CancellationTests(SchedulingTestCase):
    def book(self, days=3):
        lesson = services.book_slot(self.student, self.teacher, self.slot(days=days))
        return lesson, lesson.participants.get(student=self.student)

    def test_early_cancellation_is_free(self):
        lesson, participant = self.book(days=3)
        services.cancel_participation(participant, self.student)
        participant.refresh_from_db()
        self.assertEqual(participant.status, ParticipantStatus.CANCELLED)
        self.assertFalse(LessonCharge.objects.filter(participant=participant).exists())
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, LessonStatus.CANCELLED)

    def test_late_cancellation_consumes_a_lesson(self):
        lesson = Lesson.objects.create(
            teacher=self.teacher, starts_at=timezone.now() + timedelta(hours=2),
            duration_minutes=60, capacity=1, course=self.course,
        )
        participant = LessonParticipant.objects.create(lesson=lesson, student=self.student)
        services.cancel_participation(participant, self.student)
        participant.refresh_from_db()
        self.assertEqual(participant.status, ParticipantStatus.EXCUSED)
        self.assertTrue(LessonCharge.objects.filter(participant=participant).exists())

    def test_school_side_cancellation_charges_nobody(self):
        lesson, participant = self.book()
        services.cancel_lesson(lesson, self.teacher, "заболел преподаватель")
        participant.refresh_from_db()
        self.assertFalse(participant.is_chargeable)
        self.assertFalse(LessonCharge.objects.filter(participant=participant).exists())
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.student, kind=NotificationKind.LESSON_CANCELLED
            ).exists()
        )

    def test_past_lesson_cannot_be_cancelled(self):
        lesson = Lesson.objects.create(
            teacher=self.teacher, starts_at=timezone.now() - timedelta(days=1), capacity=1
        )
        participant = LessonParticipant.objects.create(lesson=lesson, student=self.student)
        with self.assertRaises(ValidationError):
            services.cancel_participation(participant, self.student)


class AttendanceTests(SchedulingTestCase):
    def setUp(self):
        super().setUp()
        self.tariff = Tariff.objects.create(name="8 занятий", lessons_count=8, price=8000)
        self.package = Package.objects.create(
            student=self.student, tariff=self.tariff, lessons_total=8, price=8000
        )
        self.lesson = Lesson.objects.create(
            teacher=self.teacher, course=self.course,
            starts_at=timezone.now() - timedelta(hours=2), capacity=5,
        )
        self.participant = LessonParticipant.objects.create(
            lesson=self.lesson, student=self.student
        )

    def test_attendance_consumes_exactly_one_lesson(self):
        services.save_attendance(
            self.lesson, {str(self.participant.pk): ParticipantStatus.ATTENDED}, self.teacher
        )
        account = StudentAccount(self.student)
        self.assertEqual(account.lessons_used, 1)
        self.assertEqual(account.lessons_left, 7)

    def test_saving_attendance_twice_does_not_double_charge(self):
        marks = {str(self.participant.pk): ParticipantStatus.ATTENDED}
        services.save_attendance(self.lesson, marks, self.teacher)
        services.save_attendance(self.lesson, marks, self.teacher)
        self.assertEqual(StudentAccount(self.student).lessons_used, 1)

    def test_no_show_is_charged_but_documented_absence_is_not(self):
        services.save_attendance(
            self.lesson, {str(self.participant.pk): ParticipantStatus.ABSENT}, self.teacher
        )
        self.assertEqual(StudentAccount(self.student).lessons_used, 1)

        second = Lesson.objects.create(
            teacher=self.teacher, starts_at=timezone.now() - timedelta(hours=1), capacity=5
        )
        participant = LessonParticipant.objects.create(lesson=second, student=self.student)
        services.save_attendance(
            second, {str(participant.pk): ParticipantStatus.EXCUSED}, self.teacher
        )
        self.assertEqual(StudentAccount(self.student).lessons_used, 1)

    def test_charge_price_comes_from_the_package(self):
        services.save_attendance(
            self.lesson, {str(self.participant.pk): ParticipantStatus.ATTENDED}, self.teacher
        )
        charge = LessonCharge.objects.get(participant=self.participant)
        self.assertEqual(charge.amount, self.tariff.price_per_lesson)

    def test_low_balance_warning_is_sent(self):
        Package.objects.all().delete()
        Package.objects.create(student=self.student, tariff=self.tariff, lessons_total=1, price=1000)
        services.save_attendance(
            self.lesson, {str(self.participant.pk): ParticipantStatus.ATTENDED}, self.teacher
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.student, kind=NotificationKind.PACKAGE_LOW
            ).exists()
        )


class GroupScheduleTests(SchedulingTestCase):
    def test_lessons_are_generated_from_weekly_slots_and_are_idempotent(self):
        group = Group.objects.create(
            name="A1 вечер", course=self.course, teacher=self.teacher, capacity=6,
            starts_on=timezone.localdate() - timedelta(days=1),
        )
        RecurringSlot.objects.create(group=group, weekday=1, start_time=time(18, 0))
        RecurringSlot.objects.create(group=group, weekday=3, start_time=time(18, 0))
        Enrollment.objects.create(student=self.student, group=group)

        first = services.generate_lessons(weeks=2)
        self.assertGreaterEqual(first, 2)
        again = services.generate_lessons(weeks=2)
        self.assertEqual(again, 0, "повторный запуск не должен плодить дубли")

        lesson = group.lessons.first()
        self.assertTrue(lesson.participants.filter(student=self.student).exists())

    def test_joining_a_group_adds_the_student_to_future_lessons_only(self):
        group = Group.objects.create(name="B1", course=self.course, teacher=self.teacher, capacity=6)
        past = Lesson.objects.create(
            group=group, teacher=self.teacher, starts_at=timezone.now() - timedelta(days=2), capacity=6
        )
        future = Lesson.objects.create(
            group=group, teacher=self.teacher, starts_at=timezone.now() + timedelta(days=2), capacity=6
        )
        enrollment = Enrollment.objects.create(student=self.student, group=group)
        services.sync_group_roster(enrollment)

        self.assertTrue(future.participants.filter(student=self.student).exists())
        self.assertFalse(past.participants.filter(student=self.student).exists())


class OpenLessonTests(SchedulingTestCase):
    def test_capacity_is_enforced(self):
        lesson = Lesson.objects.create(
            teacher=self.teacher, starts_at=timezone.now() + timedelta(days=1),
            capacity=1, is_bookable=True,
        )
        services.join_lesson(self.student, lesson)
        other = User.objects.create_user(email="s3@x.ru", first_name="Кирилл", role=Role.STUDENT)
        with self.assertRaises(ValidationError):
            services.join_lesson(other, lesson)

    def test_rejoining_after_cancelling_reuses_the_row(self):
        lesson = Lesson.objects.create(
            teacher=self.teacher, starts_at=timezone.now() + timedelta(days=3),
            capacity=4, is_bookable=True,
        )
        participant = services.join_lesson(self.student, lesson)
        services.cancel_participation(participant, self.student)
        again = services.join_lesson(self.student, lesson)
        self.assertEqual(participant.pk, again.pk)
        self.assertEqual(lesson.participants.filter(student=self.student).count(), 1)


class AutoCompletionTests(SchedulingTestCase):
    """Урок проводится сам, преподаватель правит только исключения.

    Здесь сторожим три вещи, на которых держатся деньги школы: отсрочку,
    возврат списанного и то, что повторный запуск ничего не удваивает.
    """

    def setUp(self):
        super().setUp()
        self.tariff = Tariff.objects.create(name="8 занятий", lessons_count=8, price=8000)
        Package.objects.create(
            student=self.student, tariff=self.tariff, lessons_total=8, price=8000
        )

    def lesson(self, ended_minutes_ago):
        started = timezone.now() - timedelta(minutes=ended_minutes_ago + 60)
        lesson = Lesson.objects.create(
            teacher=self.teacher, course=self.course, starts_at=started,
            duration_minutes=60, capacity=5,
        )
        LessonParticipant.objects.create(lesson=lesson, student=self.student)
        return lesson

    def test_lesson_completes_itself_once_the_grace_window_passes(self):
        lesson = self.lesson(ended_minutes_ago=60)
        self.assertEqual(services.autocomplete_lessons(), 1)
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, LessonStatus.COMPLETED)
        self.assertIsNone(lesson.completed_by, "автоотметка не должна выглядеть как ручная")
        self.assertEqual(StudentAccount(self.student).lessons_used, 1)

    def test_the_grace_window_holds_the_lesson_back(self):
        """Отсрочка — единственное окно, чтобы сказать «урок не состоялся»
        до списания. Без неё автоотметка бьёт в спину."""
        lesson = self.lesson(ended_minutes_ago=10)
        self.assertEqual(services.autocomplete_lessons(), 0)
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, LessonStatus.SCHEDULED)
        self.assertTrue(lesson.is_awaiting_autocomplete)
        self.assertEqual(StudentAccount(self.student).lessons_used, 0)

    def test_running_twice_does_not_charge_twice(self):
        self.lesson(ended_minutes_ago=60)
        services.autocomplete_lessons()
        self.assertEqual(services.autocomplete_lessons(), 0)
        self.assertEqual(StudentAccount(self.student).lessons_used, 1)

    def test_a_cancelled_booking_is_never_charged_by_the_robot(self):
        lesson = self.lesson(ended_minutes_ago=60)
        lesson.participants.update(status=ParticipantStatus.CANCELLED)
        services.autocomplete_lessons()
        self.assertEqual(StudentAccount(self.student).lessons_used, 0)

    def test_reopening_returns_the_lesson_to_the_package(self):
        """«Урок не состоялся» после автоотметки: занятие должно вернуться,
        иначе ученик заплатил за то, чего не было."""
        lesson = self.lesson(ended_minutes_ago=60)
        services.autocomplete_lessons()
        self.assertEqual(StudentAccount(self.student).lessons_used, 1)

        services.reopen_lesson(lesson, self.teacher, "преподаватель заболел")
        self.assertEqual(StudentAccount(self.student).lessons_used, 0)
        self.assertEqual(StudentAccount(self.student).lessons_left, 8)
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, LessonStatus.CANCELLED)

    def test_marking_an_absence_after_the_robot_keeps_the_charge(self):
        """«Не пришёл» — тоже списание: место держали. Меняется только
        отметка, деньги остаются."""
        lesson = self.lesson(ended_minutes_ago=60)
        services.autocomplete_lessons()
        participant = lesson.participants.get()
        services.save_attendance(
            lesson, {str(participant.pk): ParticipantStatus.ABSENT}, self.teacher
        )
        self.assertEqual(StudentAccount(self.student).lessons_used, 1)
        participant.refresh_from_db()
        self.assertEqual(participant.status, ParticipantStatus.ABSENT)

    def test_correcting_to_an_early_cancellation_gives_the_lesson_back(self):
        lesson = self.lesson(ended_minutes_ago=60)
        services.autocomplete_lessons()
        participant = lesson.participants.get()
        services.save_attendance(
            lesson, {str(participant.pk): ParticipantStatus.EXCUSED}, self.teacher
        )
        self.assertEqual(StudentAccount(self.student).lessons_used, 0)

    def test_confirming_takes_the_auto_mark_off_the_banner(self):
        lesson = self.lesson(ended_minutes_ago=60)
        services.autocomplete_lessons()
        lesson.refresh_from_db()
        self.assertTrue(lesson.was_autocompleted)

        services.confirm_completion(lesson, self.teacher)
        lesson.refresh_from_db()
        self.assertFalse(lesson.was_autocompleted)
        self.assertEqual(lesson.completed_by, self.teacher)
        self.assertEqual(StudentAccount(self.student).lessons_used, 1, "подтверждение не должно списывать второй раз")

    def test_a_future_lesson_is_not_in_the_grace_window(self):
        """Регрессия: окно отсрочки открывалось у ещё не начавшихся уроков,
        и кабинет предлагал «провести» завтрашнее занятие."""
        lesson = Lesson.objects.create(
            teacher=self.teacher, course=self.course,
            starts_at=timezone.now() + timedelta(hours=3), duration_minutes=60, capacity=5,
        )
        self.assertFalse(lesson.is_awaiting_autocomplete)

    def test_old_lessons_are_closed_for_the_teacher_but_not_for_the_owner(self):
        lesson = self.lesson(ended_minutes_ago=60)
        lesson.starts_at = timezone.now() - timedelta(days=30)
        lesson.save(update_fields=["starts_at"])
        owner = User.objects.create_user(email="o@x.ru", first_name="Евгения", role=Role.OWNER)
        self.assertFalse(lesson.is_correctable_by(self.teacher))
        self.assertTrue(lesson.is_correctable_by(owner))
