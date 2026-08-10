"""Кабинеты: разграничение доступа и сквозные сценарии обучения."""

import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, StudentProfile, TeacherProfile, User
from apps.billing.models import Package, Payment, StudentAccount, Tariff
from apps.learning.models import Assignment, Submission, SubmissionStatus
from apps.notifications.models import Notification, NotificationKind
from apps.scheduling.models import (
    Enrollment,
    Group,
    Lesson,
    LessonParticipant,
    ParticipantStatus,
)
from apps.school.models import Course, Language, Lead, LeadStatus


class CabinetFixture(TestCase):
    def setUp(self):
        self.language = Language.objects.create(name="Английский", slug="en")
        self.course = Course.objects.create(
            language=self.language, title="Английский", slug="eng", price_per_lesson=1000
        )
        self.owner = User.objects.create_user(
            email="owner@x.ru", password="pass12345", first_name="Мария", role=Role.OWNER
        )
        TeacherProfile.objects.create(user=self.owner, pay_rate=Decimal("700"))
        self.teacher = User.objects.create_user(
            email="teacher@x.ru", password="pass12345", first_name="Анна", role=Role.TEACHER
        )
        TeacherProfile.objects.create(user=self.teacher, pay_rate=Decimal("600"))
        self.student = User.objects.create_user(
            email="student@x.ru", password="pass12345", first_name="Егор", role=Role.STUDENT
        )
        StudentProfile.objects.create(user=self.student)

        self.group = Group.objects.create(
            name="A1 вечер", course=self.course, teacher=self.teacher, capacity=6
        )
        Enrollment.objects.create(student=self.student, group=self.group)
        self.lesson = Lesson.objects.create(
            group=self.group, course=self.course, teacher=self.teacher,
            starts_at=timezone.now() + timedelta(days=1), capacity=6,
        )
        self.participant = LessonParticipant.objects.create(
            lesson=self.lesson, student=self.student
        )


class AccessControlTests(CabinetFixture):
    STUDENT_ONLY = ["cabinet:schedule", "cabinet:homework", "cabinet:program", "cabinet:payments"]
    TEACHER_ONLY = ["cabinet:teacher_home", "cabinet:teacher_students", "cabinet:teacher_review"]
    OWNER_ONLY = ["cabinet:crm_home", "cabinet:crm_leads", "cabinet:crm_students",
                  "cabinet:crm_payments", "cabinet:crm_groups", "cabinet:crm_staff"]

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(reverse("cabinet:home"), follow=True)
        self.assertTrue(response.redirect_chain[-1][0].startswith("/accounts/login/"))

    def test_student_cannot_reach_teacher_or_owner_areas(self):
        self.client.force_login(self.student)
        for name in self.TEACHER_ONLY + self.OWNER_ONLY:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_teacher_cannot_reach_the_crm(self):
        self.client.force_login(self.teacher)
        for name in self.OWNER_ONLY:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_teacher_cannot_open_student_only_pages(self):
        self.client.force_login(self.teacher)
        for name in self.STUDENT_ONLY:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_owner_gets_both_toolsets(self):
        self.client.force_login(self.owner)
        for name in self.OWNER_ONLY + self.TEACHER_ONLY:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_each_role_lands_on_its_own_home(self):
        for user, expected in [
            (self.owner, "/cabinet/crm/"),
            (self.teacher, "/cabinet/t/"),
        ]:
            self.client.force_login(user)
            response = self.client.get(reverse("cabinet:home"))
            self.assertRedirects(response, expected)

        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("cabinet:home")).status_code, 200)

    def test_a_student_cannot_open_another_students_homework(self):
        other = User.objects.create_user(email="o@x.ru", first_name="Аня", role=Role.STUDENT)
        assignment = Assignment.objects.create(title="ДЗ", teacher=self.teacher)
        submission = Submission.objects.create(assignment=assignment, student=other)

        self.client.force_login(self.student)
        response = self.client.get(
            reverse("cabinet:homework_detail", args=[submission.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_a_teacher_cannot_edit_a_lesson_they_do_not_own(self):
        foreign = Lesson.objects.create(
            teacher=self.owner, starts_at=timezone.now() + timedelta(days=1), capacity=1
        )
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("cabinet:teacher_lesson_save", args=[foreign.pk]), {"topic": "взлом"}
        )
        self.assertEqual(response.status_code, 403)
        foreign.refresh_from_db()
        self.assertEqual(foreign.topic, "")


class HomeworkFlowTests(CabinetFixture):
    def test_assignment_reaches_every_participant_and_comes_back_graded(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("cabinet:teacher_assignment_create"), {
            "title": "Эссе", "description": "8 предложений",
            "lesson": self.lesson.pk, "max_score": "10",
        })
        self.assertEqual(response.status_code, 200, response.content)

        submission = Submission.objects.get(student=self.student)
        self.assertEqual(submission.status, SubmissionStatus.ASSIGNED)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.student, kind=NotificationKind.HOMEWORK_ASSIGNED
            ).exists()
        )

        self.client.force_login(self.student)
        self.client.post(
            reverse("cabinet:homework_submit", args=[submission.pk]),
            {"answer_text": "My weekend was great."},
        )
        submission.refresh_from_db()
        self.assertEqual(submission.status, SubmissionStatus.SUBMITTED)
        self.assertIsNotNone(submission.submitted_at)

        self.client.force_login(self.teacher)
        self.client.post(reverse("cabinet:teacher_submission_save", args=[submission.pk]), {
            "score": "9", "teacher_feedback": "Отлично", "action": "review",
        })
        submission.refresh_from_db()
        self.assertEqual(submission.status, SubmissionStatus.REVIEWED)
        self.assertEqual(submission.score, 9)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.student, kind=NotificationKind.HOMEWORK_REVIEWED
            ).exists()
        )

    def test_returning_work_for_rework_reopens_it_for_the_student(self):
        assignment = Assignment.objects.create(title="ДЗ", teacher=self.teacher)
        submission = Submission.objects.create(
            assignment=assignment, student=self.student, status=SubmissionStatus.SUBMITTED
        )
        self.client.force_login(self.teacher)
        self.client.post(reverse("cabinet:teacher_submission_save", args=[submission.pk]), {
            "teacher_feedback": "Мало примеров", "action": "redo",
        })
        submission.refresh_from_db()
        self.assertEqual(submission.status, SubmissionStatus.REDO)
        self.assertTrue(submission.is_open)

    def test_assignment_without_recipients_is_rejected(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("cabinet:teacher_assignment_create"), {
            "title": "В никуда", "max_score": "10",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Assignment.objects.filter(title="В никуда").exists())

    def test_assignment_needs_a_title(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse("cabinet:teacher_assignment_create"), {
            "title": "", "lesson": self.lesson.pk,
        })
        self.assertEqual(response.status_code, 400)


class CrmTests(CabinetFixture):
    def setUp(self):
        super().setUp()
        self.tariff = Tariff.objects.create(
            name="8 занятий", lessons_count=8, price=Decimal("7600")
        )
        self.client.force_login(self.owner)

    def test_payment_with_a_tariff_issues_the_package_in_one_step(self):
        response = self.client.post(reverse("cabinet:crm_payment_create"), {
            "student": self.student.pk, "amount": "7600",
            "method": "cash", "tariff": self.tariff.pk,
        })
        self.assertEqual(response.status_code, 200, response.content)

        account = StudentAccount(self.student)
        self.assertEqual(account.paid, Decimal("7600"))
        self.assertEqual(account.balance, Decimal("0"))
        self.assertEqual(account.lessons_left, 8)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.student, kind=NotificationKind.PAYMENT_RECEIVED
            ).exists()
        )

    def test_a_bad_amount_is_rejected(self):
        for amount in ["", "0", "-100", "не число"]:
            response = self.client.post(reverse("cabinet:crm_payment_create"), {
                "student": self.student.pk, "amount": amount,
            })
            self.assertEqual(response.status_code, 400, amount)
        self.assertEqual(Payment.objects.count(), 0)

    def test_issuing_a_package_alone_creates_a_debt(self):
        self.client.post(reverse("cabinet:crm_package_create"), {
            "student": self.student.pk, "tariff": self.tariff.pk,
        })
        self.assertEqual(StudentAccount(self.student).balance, Decimal("7600"))

    def test_debt_reminders_reach_debtors_only(self):
        Package.objects.create(
            student=self.student, tariff=self.tariff, lessons_total=8, price=Decimal("7600")
        )
        paid_up = User.objects.create_user(email="p@x.ru", first_name="Ольга", role=Role.STUDENT)
        StudentProfile.objects.create(user=paid_up)

        self.client.post(
            reverse("cabinet:crm_debt_remind"), data="{}", content_type="application/json"
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.student, kind=NotificationKind.PAYMENT_DUE
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                recipient=paid_up, kind=NotificationKind.PAYMENT_DUE
            ).exists()
        )

    def test_lead_converts_into_a_student_once(self):
        lead = Lead.objects.create(name="Пётр Смирнов", phone="+79130009999")
        response = self.client.post(
            reverse("cabinet:crm_lead_convert", args=[lead.pk]),
            data="{}", content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        lead.refresh_from_db()
        self.assertEqual(lead.status, LeadStatus.WON)
        created = lead.converted_user
        self.assertEqual(created.first_name, "Пётр")
        self.assertEqual(created.last_name, "Смирнов")
        self.assertEqual(created.role, Role.STUDENT)
        self.assertTrue(hasattr(created, "student_profile"))

        repeat = self.client.post(
            reverse("cabinet:crm_lead_convert", args=[lead.pk]),
            data="{}", content_type="application/json",
        )
        self.assertEqual(repeat.status_code, 400)

    def test_enrolling_into_a_full_group_is_refused(self):
        full = Group.objects.create(
            name="Полная", course=self.course, teacher=self.teacher, capacity=1
        )
        Enrollment.objects.create(student=self.student, group=full)
        newcomer = User.objects.create_user(email="n@x.ru", first_name="Ника", role=Role.STUDENT)
        StudentProfile.objects.create(user=newcomer)

        response = self.client.post(
            reverse("cabinet:crm_enroll", args=[newcomer.pk]), {"group": full.pk}
        )
        self.assertEqual(response.status_code, 400)

    def test_payroll_counts_only_completed_lessons(self):
        Lesson.objects.create(
            teacher=self.teacher, starts_at=timezone.now() - timedelta(days=1),
            capacity=1, status="completed",
        )
        Lesson.objects.create(
            teacher=self.teacher, starts_at=timezone.now() + timedelta(days=1), capacity=1
        )
        response = self.client.get(reverse("cabinet:crm_staff"))
        rows = {row["teacher"].pk: row for row in response.context["rows"]}
        self.assertEqual(rows[self.teacher.pk]["lessons_month"], 1)
        self.assertEqual(rows[self.teacher.pk]["payroll"], Decimal("600"))


class StudentCabinetTests(CabinetFixture):
    def test_dashboard_shows_the_next_lesson_and_the_balance(self):
        Package.objects.create(student=self.student, lessons_total=8, price=Decimal("7600"))
        self.client.force_login(self.student)
        response = self.client.get(reverse("cabinet:home"))
        self.assertEqual(response.context["next_lesson"], self.lesson)
        self.assertEqual(response.context["account"].lessons_left, 8)

    def test_cancelled_bookings_disappear_from_the_schedule(self):
        self.client.force_login(self.student)
        self.client.post(
            reverse("cabinet:cancel_api", args=[self.lesson.pk]),
            data="{}", content_type="application/json",
        )
        response = self.client.get(reverse("cabinet:schedule"))
        visible = [l for day in response.context["days"] for l in day["lessons"]]
        self.assertNotIn(self.lesson, visible)

    def test_program_progress_counts_completed_units(self):
        from apps.learning.models import Module, Program, Unit

        program = Program.objects.create(title="A2→B1", language=self.language)
        module = Module.objects.create(program=program, title="Модуль 1")
        done = Unit.objects.create(module=module, title="Тема 1")
        Unit.objects.create(module=module, title="Тема 2")
        self.group.program = program
        self.group.save(update_fields=["program"])

        self.lesson.unit = done
        self.lesson.status = "completed"
        self.lesson.save(update_fields=["unit", "status"])

        self.client.force_login(self.student)
        response = self.client.get(reverse("cabinet:program"))
        block = response.context["blocks"][0]
        self.assertEqual(block["done"], 1)
        self.assertEqual(block["total"], 2)
        self.assertEqual(block["percent"], 50)


class ProfilePageTests(CabinetFixture):
    """Профиль живёт в accounts, а шаблон наследует кабинетный каркас.

    Регрессия: страница рендерилась без cabinet_context, боковое меню
    оказывалось пустым, и уйти с профиля можно было только кнопкой
    «назад» в браузере.
    """

    def test_sidebar_navigation_is_present_for_every_role(self):
        for user, expected in (
            (self.student, "Расписание"),
            (self.teacher, "Проверка работ"),
            (self.owner, "Заявки"),
        ):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(reverse("accounts:profile"))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["nav_groups"], "боковое меню пустое")
                self.assertContains(response, expected)
                self.assertContains(response, reverse("cabinet:home"))


class AdminRoleTests(CabinetFixture):
    """Администратор ведёт заявки и учеников, но не распоряжается
    сотрудниками и не видит их зарплат."""

    CRM_DAILY = ["cabinet:crm_home", "cabinet:crm_leads", "cabinet:crm_students",
                 "cabinet:crm_payments", "cabinet:crm_groups"]

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            email="admin@x.ru", password="pass12345", first_name="Ольга", role=Role.ADMIN
        )
        self.client.force_login(self.admin)

    def test_admin_can_run_the_daily_crm(self):
        for name in self.CRM_DAILY:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_admin_cannot_reach_staff_or_payroll(self):
        self.assertEqual(self.client.get(reverse("cabinet:crm_staff")).status_code, 403)

    def test_admin_cannot_reach_teaching_pages(self):
        for name in ["cabinet:teacher_home", "cabinet:teacher_review"]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_admin_lands_in_the_crm(self):
        response = self.client.get(reverse("cabinet:home"), follow=True)
        self.assertEqual(response.redirect_chain[-1][0], reverse("cabinet:crm_home"))

    def test_admin_sidebar_hides_staff(self):
        response = self.client.get(reverse("cabinet:crm_home"))
        links = [item[0] for _, items in response.context["nav_groups"] for item in items]
        self.assertIn("cabinet:crm_leads", links)
        self.assertNotIn("cabinet:crm_staff", links)

    def test_new_leads_reach_admins_too(self):
        from apps.school.views import _alert_staff_about

        lead = Lead.objects.create(name="Пётр", phone="+79130005566")
        _alert_staff_about(lead)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.admin, kind=NotificationKind.NEW_LEAD
            ).exists()
        )


class LeadBoardTests(CabinetFixture):
    """Доска заявок переносит карточки перетаскиванием, а сервер обязан
    либо сохранить статус, либо честно отказать — иначе экран и база
    разойдутся молча."""

    def setUp(self):
        super().setUp()
        self.lead = Lead.objects.create(name="Пётр", phone="+79130007788")
        self.client.force_login(self.owner)

    def move(self, status, **extra):
        payload = {"status": status}
        payload.update(extra)
        return self.client.post(
            reverse("cabinet:crm_lead_update", args=[self.lead.pk]),
            data=json.dumps(payload), content_type="application/json",
        )

    def test_moving_to_a_real_column_saves(self):
        response = self.move(LeadStatus.SCHEDULED)
        self.assertEqual(response.status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatus.SCHEDULED)

    def test_unknown_status_is_refused_instead_of_ignored(self):
        response = self.move("на_подумать")
        self.assertEqual(response.status_code, 400)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatus.NEW)

    def test_assigning_to_a_student_is_refused(self):
        response = self.move(LeadStatus.NEW, assigned_to=self.student.pk)
        self.assertEqual(response.status_code, 400)
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.assigned_to)

    def test_assigning_to_a_teacher_works(self):
        response = self.move(LeadStatus.NEW, assigned_to=self.teacher.pk)
        self.assertEqual(response.status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.assigned_to, self.teacher)

    def test_board_markup_carries_what_the_dragger_needs(self):
        response = self.client.get(reverse("cabinet:crm_leads"))
        html = response.content.decode()
        self.assertIn("data-lead-board", html)
        self.assertIn(f'data-lead="{self.lead.pk}"', html)
        self.assertIn('data-status="scheduled"', html)
        self.assertIn("data-drag-handle", html)
        # draggable запускает родной механизм браузера и глушит pointer-события.
        self.assertNotIn("draggable=", html)
