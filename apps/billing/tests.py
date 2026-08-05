"""Два независимых счётчика школы: сколько денег должны и сколько уроков осталось."""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role, StudentProfile, User

from .models import (
    LessonCharge,
    Package,
    PackageStatus,
    Payment,
    PaymentStatus,
    StudentAccount,
    Tariff,
)


class StudentAccountTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(
            email="s@x.ru", first_name="Егор", role=Role.STUDENT
        )
        StudentProfile.objects.create(user=self.student)
        self.tariff = Tariff.objects.create(
            name="8 занятий", lessons_count=8, price=Decimal("7600"), validity_days=90
        )

    def test_issuing_a_package_creates_a_debt(self):
        Package.objects.create(
            student=self.student, tariff=self.tariff, lessons_total=8, price=self.tariff.price
        )
        account = StudentAccount(self.student)
        self.assertEqual(account.billed, Decimal("7600"))
        self.assertEqual(account.paid, Decimal("0"))
        self.assertEqual(account.balance, Decimal("7600"))
        self.assertEqual(account.lessons_left, 8)

    def test_payment_settles_the_debt(self):
        package = Package.objects.create(
            student=self.student, tariff=self.tariff, lessons_total=8, price=self.tariff.price
        )
        Payment.objects.create(student=self.student, package=package, amount=Decimal("7600"))
        self.assertEqual(StudentAccount(self.student).balance, Decimal("0"))

    def test_prepayment_shows_as_credit(self):
        Payment.objects.create(student=self.student, amount=Decimal("3000"))
        self.assertEqual(StudentAccount(self.student).balance, Decimal("-3000"))

    def test_refunded_payments_do_not_count(self):
        Payment.objects.create(
            student=self.student, amount=Decimal("7600"), status=PaymentStatus.REFUNDED
        )
        self.assertEqual(StudentAccount(self.student).paid, Decimal("0"))

    def test_cancelled_package_is_excluded_from_both_ledgers(self):
        Package.objects.create(
            student=self.student, lessons_total=8, price=Decimal("7600"),
            status=PackageStatus.CANCELLED,
        )
        account = StudentAccount(self.student)
        self.assertEqual(account.billed, Decimal("0"))
        self.assertEqual(account.lessons_purchased, 0)

    def test_expiry_is_derived_from_the_tariff(self):
        package = Package.objects.create(
            student=self.student, tariff=self.tariff, lessons_total=8, price=self.tariff.price
        )
        self.assertIsNotNone(package.expires_on)
        self.assertEqual(
            (package.expires_on - package.issued_on).days, self.tariff.validity_days
        )

    def test_expired_package_is_not_usable(self):
        package = Package.objects.create(
            student=self.student, lessons_total=8, price=Decimal("7600"),
            expires_on=timezone.localdate() - timezone.timedelta(days=1),
        )
        self.assertTrue(package.is_expired)
        self.assertFalse(package.is_usable)
        self.assertIsNone(StudentAccount(self.student).active_package)

    def test_active_package_is_the_oldest_usable_one(self):
        old = Package.objects.create(
            student=self.student, lessons_total=4, price=Decimal("4000"),
            issued_on=timezone.localdate() - timezone.timedelta(days=30),
        )
        Package.objects.create(student=self.student, lessons_total=8, price=Decimal("7600"))
        self.assertEqual(StudentAccount(self.student).active_package, old)

    def test_refresh_status_marks_an_expired_package(self):
        package = Package.objects.create(
            student=self.student, lessons_total=8, price=Decimal("7600"),
            expires_on=timezone.localdate() - timezone.timedelta(days=1),
        )
        package.refresh_status()
        self.assertEqual(package.status, PackageStatus.EXPIRED)

    def test_refresh_status_never_revives_a_cancelled_package(self):
        package = Package.objects.create(
            student=self.student, lessons_total=8, price=Decimal("7600"),
            status=PackageStatus.CANCELLED,
        )
        package.refresh_status()
        self.assertEqual(package.status, PackageStatus.CANCELLED)

    def test_needs_attention_flags_debt_and_empty_balance(self):
        Package.objects.create(student=self.student, lessons_total=8, price=Decimal("7600"))
        self.assertTrue(StudentAccount(self.student).needs_attention, "есть долг")

        Payment.objects.create(student=self.student, amount=Decimal("7600"))
        self.assertFalse(StudentAccount(self.student).needs_attention)


class TariffTests(TestCase):
    def test_price_per_lesson_rounds_to_kopecks(self):
        tariff = Tariff.objects.create(name="3 занятия", lessons_count=3, price=Decimal("1000"))
        self.assertEqual(tariff.price_per_lesson, Decimal("333.33"))

    def test_price_per_lesson_survives_a_freshly_built_object(self):
        """Регрессия: до перечитывания из базы в price лежал int и падал quantize."""
        tariff = Tariff(name="8", lessons_count=8, price=8000)
        self.assertEqual(tariff.price_per_lesson, Decimal("1000.00"))

    def test_zero_lessons_does_not_divide_by_zero(self):
        tariff = Tariff(name="пустой", lessons_count=0, price=Decimal("1000"))
        self.assertEqual(tariff.price_per_lesson, Decimal("0.00"))
