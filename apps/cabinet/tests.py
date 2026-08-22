"""Кабинеты: разграничение доступа и сквозные сценарии обучения."""

import json
import re
from datetime import time, timedelta
from decimal import Decimal

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, StudentProfile, TeacherProfile, User
from apps.billing.models import Package, Payment, StudentAccount, Tariff
from apps.learning.models import Assignment, Submission, SubmissionStatus
from apps.notifications.models import Notification, NotificationKind
from apps.scheduling.models import (
    Enrollment,
    TeacherAvailability,
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


class AccountProvisioningViewTests(CabinetFixture):
    """Кто кому может выдать доступ. Ошибка здесь — это либо чужой человек
    в кабинете, либо владелица, запершая сама себя."""

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            email="admin@x.ru", password="pass12345", first_name="Ольга", role=Role.ADMIN
        )

    def create_student(self, **overrides):
        payload = {"first_name": "Пётр", "last_name": "Иванов", "phone": "89130006677"}
        payload.update(overrides)
        return self.client.post(reverse("cabinet:crm_student_create"), payload)

    def test_admin_can_issue_a_student_account(self):
        self.client.force_login(self.admin)
        response = self.create_student()
        self.assertEqual(response.status_code, 200)
        creds = response.json()["credentials"]
        self.assertEqual(creds["login"], "ivanov")
        self.assertTrue(creds["password"])
        self.assertIn(creds["password"], creds["message"])

        student = User.objects.get(username="ivanov")
        self.assertEqual(student.role, Role.STUDENT)
        self.assertTrue(student.must_change_password)
        self.assertTrue(student.check_password(creds["password"]))

    def test_teacher_cannot_issue_accounts(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.create_student().status_code, 403)
        self.assertFalse(User.objects.filter(username="ivanov").exists())

    def test_duplicate_phone_is_refused(self):
        self.client.force_login(self.owner)
        self.create_student()
        response = self.create_student(last_name="Петров")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="petrov").exists())

    def test_student_without_contacts_can_still_be_created(self):
        """У школьника может не быть ни почты, ни своего телефона."""
        self.client.force_login(self.owner)
        response = self.create_student(phone="", email="")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.get(username="ivanov").username)

    # --- сотрудники ------------------------------------------------------

    def create_staff(self, **overrides):
        payload = {"role": Role.TEACHER, "first_name": "Анна", "last_name": "Белова",
                   "pay_rate": "700"}
        payload.update(overrides)
        return self.client.post(reverse("cabinet:crm_staff_create"), payload)

    def test_owner_can_hire_a_teacher(self):
        self.client.force_login(self.owner)
        response = self.create_staff()
        self.assertEqual(response.status_code, 200)
        member = User.objects.get(username="belova")
        self.assertEqual(member.role, Role.TEACHER)
        self.assertEqual(member.teacher_profile.pay_rate, Decimal("700"))

    def test_owner_can_hire_an_administrator(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.create_staff(role=Role.ADMIN).status_code, 200)
        self.assertEqual(User.objects.get(username="belova").role, Role.ADMIN)

    def test_admin_cannot_hire_anyone(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.create_staff().status_code, 403)
        self.assertFalse(User.objects.filter(username="belova").exists())

    def test_nobody_can_be_hired_as_an_owner(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.create_staff(role=Role.OWNER).status_code, 400)
        self.assertEqual(User.objects.filter(role=Role.OWNER).count(), 1)

    def test_owner_cannot_lock_herself_out(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("cabinet:crm_staff_update", args=[self.owner.pk]),
            data=json.dumps({"is_active": "0"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)

    def test_teacher_with_lessons_is_disabled_rather_than_deleted(self):
        """Удалить преподавателя с историей — значит порвать журнал,
        расписание и расчёт зарплаты задним числом."""
        self.client.force_login(self.owner)
        response = self.client.post(reverse("cabinet:crm_staff_delete", args=[self.teacher.pk]))
        self.assertEqual(response.status_code, 200)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_active)
        self.assertTrue(User.objects.filter(pk=self.teacher.pk).exists())

    def test_fresh_hire_without_history_is_deleted_completely(self):
        self.client.force_login(self.owner)
        self.create_staff()
        member = User.objects.get(username="belova")
        response = self.client.post(reverse("cabinet:crm_staff_delete", args=[member.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(pk=member.pk).exists())

    def test_admin_can_reset_a_student_password_but_not_a_teachers(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(
                reverse("cabinet:crm_credentials_reset", args=[self.student.pk])
            ).status_code, 200
        )
        self.assertEqual(
            self.client.post(
                reverse("cabinet:crm_credentials_reset", args=[self.teacher.pk])
            ).status_code, 400
        )

    def test_reset_returns_a_password_that_actually_works(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("cabinet:crm_credentials_reset", args=[self.student.pk])
        )
        password = response.json()["credentials"]["password"]
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(password))
        self.assertTrue(self.student.must_change_password)


class TemplateLeakTests(CabinetFixture):
    """Django считает комментарием только ОДНОСТРОЧНЫЙ {# … #}. Многострочный
    он печатает на страницу как обычный текст.

    Публичные страницы такой тест уже стерегли, а кабинет — нет, и комментарий
    про перетаскивание уехал прямо в колонку заявок на глазах у владелицы.
    Поэтому проверяем каждую страницу кабинета для каждой роли.
    """

    OWNER_PAGES = ["cabinet:crm_home", "cabinet:crm_leads", "cabinet:crm_students",
                   "cabinet:crm_payments", "cabinet:crm_groups", "cabinet:crm_staff",
                   "cabinet:teacher_home", "cabinet:teacher_schedule",
                   "cabinet:teacher_students", "cabinet:teacher_review",
                   "cabinet:teacher_programs", "cabinet:teacher_availability",
                   "cabinet:notifications", "accounts:profile"]
    STUDENT_PAGES = ["cabinet:home", "cabinet:schedule", "cabinet:homework",
                     "cabinet:program", "cabinet:book", "cabinet:payments",
                     "cabinet:notifications", "accounts:profile"]

    def assertNoLeaks(self, user, names):
        self.client.force_login(user)
        for name in names:
            with self.subTest(page=name):
                html = self.client.get(reverse(name)).content.decode()
                for token in ("{#", "#}", "{%", "{{"):
                    if token not in html:
                        continue
                    # Печатаем только окрестность находки: вываливать всю
                    # страницу в отчёт бесполезно, её невозможно читать.
                    at = html.index(token)
                    self.fail(
                        f"{token} утёк в разметку на {name}: "
                        f"…{html[max(0, at - 60):at + 90]}…"
                    )

    def test_owner_pages_are_clean(self):
        Lead.objects.create(name="Пётр", phone="+79130001122")
        self.assertNoLeaks(self.owner, self.OWNER_PAGES)

    def test_student_pages_are_clean(self):
        self.assertNoLeaks(self.student, self.STUDENT_PAGES)


class LeadDeletionTests(CabinetFixture):
    """Спам нужно убирать совсем: статус «Отказ» оставляет его в воронке
    и портит счётчики."""

    def setUp(self):
        super().setUp()
        self.spam = Lead.objects.create(name="Casino Bonus", phone="+79130000001")
        self.client.force_login(self.owner)

    def test_manager_deletes_a_spam_lead(self):
        response = self.client.post(reverse("cabinet:crm_lead_delete", args=[self.spam.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lead.objects.filter(pk=self.spam.pk).exists())

    def test_converted_lead_is_kept_as_history(self):
        """Из карточки ученика видно, откуда он пришёл, — этот след не рвём."""
        self.spam.converted_user = self.student
        self.spam.save(update_fields=["converted_user"])
        response = self.client.post(reverse("cabinet:crm_lead_delete", args=[self.spam.pk]))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Lead.objects.filter(pk=self.spam.pk).exists())

    def test_teacher_cannot_delete_leads(self):
        self.client.force_login(self.teacher)
        self.assertEqual(
            self.client.post(reverse("cabinet:crm_lead_delete", args=[self.spam.pk])).status_code, 403
        )
        self.assertTrue(Lead.objects.filter(pk=self.spam.pk).exists())

    def purge(self, status):
        return self.client.post(
            reverse("cabinet:crm_leads_purge"),
            data=json.dumps({"status": status}), content_type="application/json",
        )

    def test_purging_a_column_clears_it(self):
        for index in range(4):
            Lead.objects.create(name=f"Спам {index}", phone=f"+7913000111{index}")
        response = self.purge(LeadStatus.NEW)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Lead.objects.filter(status=LeadStatus.NEW).exists())

    def test_purge_spares_leads_that_became_students(self):
        kept = Lead.objects.create(name="Настоящий", phone="+79130002222",
                                   converted_user=self.student)
        self.purge(LeadStatus.NEW)
        self.assertTrue(Lead.objects.filter(pk=kept.pk).exists())
        self.assertFalse(Lead.objects.filter(pk=self.spam.pk).exists())

    def test_unknown_column_is_refused(self):
        response = self.purge("что_попало")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Lead.objects.filter(pk=self.spam.pk).exists())

    def test_empty_column_reports_instead_of_pretending(self):
        self.assertEqual(self.purge(LeadStatus.WON).status_code, 400)


class StaffEditingTests(CabinetFixture):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def edit(self, member, **fields):
        return self.client.post(reverse("cabinet:crm_staff_update", args=[member.pk]), fields)

    def test_owner_renames_a_teacher_and_changes_the_rate(self):
        response = self.edit(self.teacher, first_name="Анна", last_name="Белова",
                             pay_rate="850", headline="Английский · IELTS")
        self.assertEqual(response.status_code, 200)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.last_name, "Белова")
        self.assertEqual(self.teacher.teacher_profile.pay_rate, Decimal("850"))
        self.assertEqual(self.teacher.teacher_profile.headline, "Английский · IELTS")

    def test_promoting_an_admin_to_teacher_gives_them_a_teaching_profile(self):
        """Без профиля ставка сохранится в никуда, и в расчёте зарплаты
        человека не будет."""
        admin = User.objects.create_user(email="a@x.ru", first_name="Ольга", role=Role.ADMIN)
        response = self.edit(admin, first_name="Ольга", role=Role.TEACHER, pay_rate="700")
        self.assertEqual(response.status_code, 200)
        admin.refresh_from_db()
        self.assertEqual(admin.role, Role.TEACHER)
        self.assertEqual(admin.teacher_profile.pay_rate, Decimal("700"))

    def test_owner_role_cannot_be_taken_away(self):
        self.edit(self.owner, first_name="Мария", role=Role.ADMIN)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.role, Role.OWNER)

    def test_admin_cannot_edit_staff(self):
        admin = User.objects.create_user(
            email="a@x.ru", password="pass12345", first_name="Ольга", role=Role.ADMIN
        )
        self.client.force_login(admin)
        self.assertEqual(self.edit(self.teacher, first_name="Взлом").status_code, 403)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.first_name, "Анна")

    def test_edit_button_carries_current_values(self):
        self.teacher.teacher_profile.headline = "Английский"
        self.teacher.teacher_profile.save()
        html = self.client.get(reverse("cabinet:crm_staff")).content.decode()
        self.assertIn('data-modal-open="#staff-edit-modal"', html)
        self.assertIn(reverse("cabinet:crm_staff_update", args=[self.teacher.pk]), html)
        self.assertIn('data-setheadline="Английский"', html)
        # У владелицы кнопки правки нет: роль и доступ она себе не меняет.
        self.assertNotIn(reverse("cabinet:crm_staff_update", args=[self.owner.pk]), html)


class FormPropertyShadowingTests(SimpleTestCase):
    """Поля формы становятся её свойствами по атрибуту name.

    Из-за этого <select name="method"> подменял form.method самим элементом
    («options.method.toUpperCase is not a function» при внесении платежа),
    а кнопки name="action" превращали form.action в список узлов — запрос
    улетал не по тому адресу и работа тихо не сохранялась.

    Автоматической проверки JS в проекте нет, поэтому стережём исходник:
    адрес и метод формы читаются только через getAttribute.
    """

    def code(self):
        """Исходник без комментариев: пояснения к правилу сами упоминают
        form.action и form.method, и проверка ловила бы их."""
        source = (settings.BASE_DIR / "static" / "js" / "app.js").read_text(encoding="utf-8")
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        return re.sub(r"//[^\n]*", "", source)

    def test_form_action_and_method_are_read_as_attributes(self):
        found = re.findall(r"\bform\.(action|method)\b", self.code())
        if found:
            self.fail(
                f"form.{found[0]} читается как свойство — его подменит поле формы "
                f"с таким же name. Нужен getAttribute или setAttribute."
            )

    def test_the_safe_form_is_actually_used(self):
        code = self.code()
        self.assertIn('form.getAttribute("action")', code)
        self.assertIn('form.getAttribute("method")', code)


class RussianDatesTests(CabinetFixture):
    """Регрессия: у браузера с английской локалью Django печатал дни недели
    как «MON». Сайт русский — язык не должен зависеть от настроек гостя."""

    def test_schedule_headers_stay_russian(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("cabinet:crm_schedule"), headers={"accept-language": "en-US,en;q=0.9"}
        )
        html = response.content.decode()
        self.assertNotIn(">Mon<", html)
        for short in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"):
            self.assertIn(short, html)


class SchoolScheduleTests(CabinetFixture):
    """Общая картина занятости: кто когда занят и куда можно записать."""

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            email="admin@x.ru", password="pass12345", first_name="Ольга", role=Role.ADMIN
        )
        # Окно ставим на среду и смотрим следующую неделю. «Завтра» здесь
        # не годится: в воскресенье завтра — понедельник уже другой недели,
        # текущая неделя его не показывает, и тест падал по воскресеньям.
        # Следующая неделя целиком в будущем, какой бы день ни был сегодня.
        TeacherAvailability.objects.create(
            teacher=self.teacher, weekday=2,
            start_time=time(15, 0), end_time=time(19, 0), slot_minutes=60,
        )

    def test_admin_sees_the_school_schedule(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("cabinet:crm_schedule"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["rows"])

    def test_teacher_cannot_open_it(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("cabinet:crm_schedule")).status_code, 403)

    def test_free_windows_are_offered(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("cabinet:crm_schedule"), {"week": "1"})
        free = sum(len(day["free"]) for row in response.context["rows"] for day in row["days"])
        self.assertGreater(free, 0, "свободные окна не рассчитались")

    def test_free_windows_can_be_hidden(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("cabinet:crm_schedule"), {"week": "1", "free": "0"})
        free = sum(len(day["free"]) for row in response.context["rows"] for day in row["days"])
        self.assertEqual(free, 0)

    def test_student_options_carry_lessons_left_and_payment(self):
        """То, что спрашивают по телефону, должно быть видно в момент записи."""
        self.client.force_login(self.owner)
        response = self.client.get(reverse("cabinet:crm_schedule"))
        row = next(r for r in response.context["student_rows"] if r["student"] == self.student)
        self.assertIn("lessons_left", row)
        self.assertIn("last_payment", row)
        self.assertContains(response, "осталось")

    def book(self, **overrides):
        # Заведомо свободное время: в фикстуре у этого преподавателя уже
        # стоит занятие на завтра, и запись в тот же час законно отклоняется.
        when = (timezone.localtime(timezone.now()) + timedelta(days=3)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        payload = {
            "student": self.student.pk,
            "teacher": self.teacher.pk,
            "starts_at": when.strftime("%Y-%m-%dT%H:%M"),
            "duration": 60,
        }
        payload.update(overrides)
        return self.client.post(reverse("cabinet:crm_schedule_book"), payload)

    def test_admin_books_a_student(self):
        self.client.force_login(self.admin)
        response = self.book()
        self.assertEqual(response.status_code, 200)
        lesson = Lesson.objects.order_by("-id").first()
        self.assertEqual(lesson.teacher, self.teacher)
        self.assertTrue(lesson.participants.filter(student=self.student).exists())

    def test_double_booking_the_same_time_is_refused(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.book().status_code, 200)
        response = self.book()
        self.assertEqual(response.status_code, 400)

    def test_broken_datetime_is_reported(self):
        self.client.force_login(self.owner)
        response = self.book(starts_at="когда-нибудь")
        self.assertEqual(response.status_code, 400)

    def test_booking_warns_when_the_package_is_spent(self):
        """Записать даём — человек на линии. Но про оплату надо сказать."""
        self.client.force_login(self.owner)
        response = self.book()
        self.assertIn("не осталось оплаченных", response.json()["message"])

    def test_teacher_cannot_book_through_the_crm(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.book().status_code, 403)


class GroupDetailTests(CabinetFixture):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def test_group_page_lists_members_with_their_balance(self):
        response = self.client.get(reverse("cabinet:crm_group", args=[self.group.pk]))
        self.assertEqual(response.status_code, 200)
        names = [row["student"] for row in response.context["roster"]]
        self.assertIn(self.student, names)
        self.assertIn("lessons_left", response.context["roster"][0])

    def test_groups_list_links_to_the_page(self):
        response = self.client.get(reverse("cabinet:crm_groups"))
        self.assertContains(response, reverse("cabinet:crm_group", args=[self.group.pk]))

    def test_enrolling_adds_the_student_to_future_lessons(self):
        newcomer = User.objects.create_user(
            email="new@x.ru", first_name="Ника", role=Role.STUDENT
        )
        response = self.client.post(
            reverse("cabinet:crm_group_enroll", args=[self.group.pk]), {"student": newcomer.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.lesson.participants.filter(student=newcomer).exists())

    def test_removing_a_student_keeps_past_lessons(self):
        """В прошедших занятиях стоят отметки и списания — переписывать их
        задним числом значит испортить журнал и деньги."""
        past = Lesson.objects.create(
            group=self.group, course=self.course, teacher=self.teacher,
            starts_at=timezone.now() - timedelta(days=3), capacity=6,
        )
        LessonParticipant.objects.create(lesson=past, student=self.student)
        enrollment = self.group.enrollments.get(student=self.student)

        response = self.client.post(reverse("cabinet:crm_group_unenroll", args=[enrollment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(past.participants.filter(student=self.student).exists())
        self.assertFalse(self.lesson.participants.filter(student=self.student).exists())
        enrollment.refresh_from_db()
        self.assertFalse(enrollment.is_active)

    def test_full_group_refuses_new_students(self):
        self.group.capacity = 1
        self.group.save(update_fields=["capacity"])
        other = User.objects.create_user(email="o@x.ru", first_name="Олег", role=Role.STUDENT)
        response = self.client.post(
            reverse("cabinet:crm_group_enroll", args=[self.group.pk]), {"student": other.pk}
        )
        self.assertEqual(response.status_code, 400)

    def test_weekly_slot_can_be_added_and_removed(self):
        response = self.client.post(
            reverse("cabinet:crm_group_slot_create", args=[self.group.pk]),
            {"weekday": 2, "start_time": "18:00", "duration_minutes": 90},
        )
        self.assertEqual(response.status_code, 200)
        slot = self.group.slots.get(weekday=2)
        self.assertEqual(slot.duration_minutes, 90)

        self.assertEqual(
            self.client.post(reverse("cabinet:crm_group_slot_delete", args=[slot.pk])).status_code, 200
        )
        self.assertFalse(self.group.slots.filter(pk=slot.pk).exists())

    def test_duplicate_slot_is_refused(self):
        self.client.post(reverse("cabinet:crm_group_slot_create", args=[self.group.pk]),
                         {"weekday": 3, "start_time": "18:00"})
        response = self.client.post(reverse("cabinet:crm_group_slot_create", args=[self.group.pk]),
                                    {"weekday": 3, "start_time": "18:00"})
        self.assertEqual(response.status_code, 400)


class LessonMarkingTests(CabinetFixture):
    """Отметка урока должна быть в самой строке расписания.

    Регрессия из жизни: действие пряталось за серой кнопкой «Журнал», и
    владелица, глядя на плашку «нужно отметить», не нашла, куда нажать.
    """

    def setUp(self):
        super().setUp()
        self.tariff = Tariff.objects.create(name="8 занятий", lessons_count=8, price=8000)
        Package.objects.create(
            student=self.student, tariff=self.tariff, lessons_total=8, price=8000
        )
        self.lesson.starts_at = timezone.now() - timedelta(hours=3)
        self.lesson.save(update_fields=["starts_at"])
        self.client.force_login(self.teacher)

    def complete(self):
        from apps.scheduling import services as sched

        sched.autocomplete_lessons()
        self.lesson.refresh_from_db()

    def test_the_schedule_row_carries_the_action_itself(self):
        self.complete()
        response = self.client.get(reverse("cabinet:teacher_schedule"))
        self.assertContains(response, reverse("cabinet:teacher_lesson_reopen", args=[self.lesson.pk]))
        self.assertContains(response, reverse("cabinet:teacher_lessons_confirm"))

    def test_a_lesson_in_the_grace_window_can_be_held_or_dropped_from_the_row(self):
        self.lesson.starts_at = timezone.now() - timedelta(minutes=70)
        self.lesson.save(update_fields=["starts_at"])
        response = self.client.get(reverse("cabinet:teacher_schedule"))
        self.assertContains(response, reverse("cabinet:teacher_lesson_complete", args=[self.lesson.pk]))
        self.assertContains(response, "Не состоялся")

    def test_marking_a_lesson_as_not_held_returns_the_lesson(self):
        self.complete()
        self.assertEqual(StudentAccount(self.student).lessons_used, 1)

        response = self.client.post(
            reverse("cabinet:teacher_lesson_reopen", args=[self.lesson.pk]),
            data=json.dumps({"reason": "заболела"}), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StudentAccount(self.student).lessons_used, 0)

    def test_confirming_clears_the_banner(self):
        self.complete()
        self.assertContains(
            self.client.get(reverse("cabinet:teacher_schedule")), "автоматически"
        )
        self.client.post(reverse("cabinet:teacher_lessons_confirm"))
        self.assertNotContains(
            self.client.get(reverse("cabinet:teacher_schedule")), "Отмечено проведёнными автоматически"
        )

    def test_a_foreign_lesson_cannot_be_touched(self):
        other = User.objects.create_user(
            email="other@x.ru", password="pass12345", first_name="Пётр", role=Role.TEACHER
        )
        TeacherProfile.objects.create(user=other)
        self.client.force_login(other)
        for name in ("teacher_lesson_complete", "teacher_lesson_reopen"):
            with self.subTest(view=name):
                response = self.client.post(
                    reverse(f"cabinet:{name}", args=[self.lesson.pk]),
                    data="{}", content_type="application/json",
                )
                self.assertEqual(response.status_code, 403)

    def test_a_closed_month_cannot_be_rewritten_by_the_teacher(self):
        """После закрытия журнала правит только владелица — иначе выручку
        прошлого месяца можно переписать задним числом."""
        self.lesson.starts_at = timezone.now() - timedelta(days=40)
        self.lesson.save(update_fields=["starts_at"])
        self.complete()

        response = self.client.post(
            reverse("cabinet:teacher_lesson_reopen", args=[self.lesson.pk]),
            data="{}", content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(StudentAccount(self.student).lessons_used, 1)

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("cabinet:teacher_lesson_reopen", args=[self.lesson.pk]),
            data="{}", content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StudentAccount(self.student).lessons_used, 0)

    def test_the_attendance_sheet_preselects_everyone_as_present(self):
        response = self.client.get(reverse("cabinet:teacher_lesson", args=[self.lesson.pk]))
        html = response.content.decode()
        row = html.split(f'name="status-{self.participant.pk}"')
        self.assertIn('value="attended"', row[1][:60])
        self.assertIn("checked", row[1][:120], "по умолчанию должен стоять «был»")
