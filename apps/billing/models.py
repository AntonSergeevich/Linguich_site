from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

ZERO = Decimal("0.00")


class Tariff(models.Model):
    """A sellable package: «8 уроков английского индивидуально — 12 000 ₽»."""

    name = models.CharField(_("Название"), max_length=140)
    course = models.ForeignKey(
        "school.Course", on_delete=models.SET_NULL, null=True, blank=True, related_name="tariffs"
    )
    lessons_count = models.PositiveSmallIntegerField(_("Уроков в абонементе"), default=8)
    price = models.DecimalField(_("Цена, ₽"), max_digits=10, decimal_places=2)
    validity_days = models.PositiveSmallIntegerField(
        _("Срок действия, дней"), default=90, help_text=_("0 — бессрочно.")
    )
    description = models.CharField(max_length=220, blank=True)
    is_public = models.BooleanField(_("Показывать на сайте"), default=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        verbose_name = _("Тариф")
        verbose_name_plural = _("Тарифы")
        ordering = ["sort_order", "price"]

    def __str__(self):
        return f"{self.name} — {self.price:.0f} ₽"

    @property
    def price_per_lesson(self):
        if not self.lessons_count:
            return ZERO
        # Приводим к Decimal явно: у только что созданного объекта в поле
        # может лежать int/float, пока он не перечитан из базы.
        return (Decimal(str(self.price)) / self.lessons_count).quantize(Decimal("0.01"))


class PackageStatus(models.TextChoices):
    ACTIVE = "active", _("Активен")
    EXHAUSTED = "exhausted", _("Уроки закончились")
    EXPIRED = "expired", _("Истёк срок")
    CANCELLED = "cancelled", _("Аннулирован")


class Package(models.Model):
    """A package issued to a student. Issuing it creates the receivable;
    payments settle it, lessons consume it."""

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="packages")
    tariff = models.ForeignKey(Tariff, on_delete=models.SET_NULL, null=True, blank=True)
    group = models.ForeignKey(
        "scheduling.Group", on_delete=models.SET_NULL, null=True, blank=True, related_name="packages"
    )
    lessons_total = models.PositiveSmallIntegerField(_("Уроков"), default=8)
    price = models.DecimalField(_("Стоимость, ₽"), max_digits=10, decimal_places=2)
    issued_on = models.DateField(_("Выдан"), default=timezone.localdate)
    expires_on = models.DateField(_("Действует до"), null=True, blank=True)
    status = models.CharField(max_length=12, choices=PackageStatus.choices, default=PackageStatus.ACTIVE)
    comment = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="packages_issued"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Абонемент")
        verbose_name_plural = _("Абонементы")
        ordering = ["-issued_on", "-id"]

    def __str__(self):
        return f"{self.student} · {self.lessons_total} ур. от {self.issued_on:%d.%m.%Y}"

    def save(self, *args, **kwargs):
        if not self.expires_on and self.tariff and self.tariff.validity_days:
            self.expires_on = self.issued_on + timezone.timedelta(days=self.tariff.validity_days)
        super().save(*args, **kwargs)

    @property
    def lessons_used(self):
        return self.charges.count()

    @property
    def lessons_left(self):
        return max(0, self.lessons_total - self.lessons_used)

    @property
    def is_expired(self):
        return bool(self.expires_on and self.expires_on < timezone.localdate())

    @property
    def is_usable(self):
        return self.status == PackageStatus.ACTIVE and self.lessons_left > 0 and not self.is_expired

    def refresh_status(self):
        if self.status == PackageStatus.CANCELLED:
            return
        if self.lessons_left == 0:
            new_status = PackageStatus.EXHAUSTED
        elif self.is_expired:
            new_status = PackageStatus.EXPIRED
        else:
            new_status = PackageStatus.ACTIVE
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=["status"])


class PaymentMethod(models.TextChoices):
    CASH = "cash", _("Наличные")
    CARD = "card", _("Карта / перевод")
    BANK = "bank", _("Счёт (юрлицо)")
    ONLINE = "online", _("Онлайн-оплата")
    OTHER = "other", _("Другое")


class PaymentStatus(models.TextChoices):
    PENDING = "pending", _("Ожидает")
    PAID = "paid", _("Оплачено")
    REFUNDED = "refunded", _("Возврат")


class Payment(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments")
    package = models.ForeignKey(
        Package, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments"
    )
    amount = models.DecimalField(_("Сумма, ₽"), max_digits=10, decimal_places=2)
    method = models.CharField(_("Способ"), max_length=8, choices=PaymentMethod.choices, default=PaymentMethod.CARD)
    status = models.CharField(max_length=8, choices=PaymentStatus.choices, default=PaymentStatus.PAID)
    paid_on = models.DateField(_("Дата"), default=timezone.localdate, db_index=True)
    comment = models.CharField(max_length=200, blank=True)
    # Filled in by the payment-provider webhook once online payments are switched on.
    provider = models.CharField(max_length=32, blank=True)
    provider_payment_id = models.CharField(max_length=120, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments_recorded"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Платёж")
        verbose_name_plural = _("Платежи")
        ordering = ["-paid_on", "-id"]
        indexes = [models.Index(fields=["-paid_on", "status"])]

    def __str__(self):
        return f"{self.student} · {self.amount:.0f} ₽ · {self.paid_on:%d.%m.%Y}"


class LessonCharge(models.Model):
    """A consumed lesson. One row per attended lesson per student."""

    participant = models.OneToOneField(
        "scheduling.LessonParticipant", on_delete=models.CASCADE, related_name="charge"
    )
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_charges")
    package = models.ForeignKey(
        Package, on_delete=models.SET_NULL, null=True, blank=True, related_name="charges"
    )
    amount = models.DecimalField(_("Стоимость урока, ₽"), max_digits=9, decimal_places=2, default=ZERO)
    charged_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=160, blank=True)

    class Meta:
        verbose_name = _("Списание урока")
        verbose_name_plural = _("Списания уроков")
        ordering = ["-charged_at"]

    def __str__(self):
        return f"{self.student} · {self.amount:.0f} ₽"


class StudentAccount:
    """Read-only money/lesson view for one student.

    Two independent ledgers, because a language school genuinely has two:
    how much money is owed, and how many paid lessons are left.
    """

    def __init__(self, student):
        self.student = student

    @property
    def packages(self):
        return self.student.packages.exclude(status=PackageStatus.CANCELLED)

    @property
    def billed(self):
        return self.packages.aggregate(s=Sum("price"))["s"] or ZERO

    @property
    def paid(self):
        return (
            self.student.payments.filter(status=PaymentStatus.PAID).aggregate(s=Sum("amount"))["s"] or ZERO
        )

    @property
    def balance(self):
        """Positive = student owes money. Negative = prepaid credit."""
        return self.billed - self.paid

    @property
    def lessons_purchased(self):
        return self.packages.aggregate(s=Sum("lessons_total"))["s"] or 0

    @property
    def lessons_used(self):
        return self.student.lesson_charges.count()

    @property
    def lessons_left(self):
        return self.lessons_purchased - self.lessons_used

    @property
    def active_package(self):
        for package in self.packages.filter(status=PackageStatus.ACTIVE).order_by("issued_on"):
            if package.is_usable:
                return package
        return None

    @property
    def needs_attention(self):
        return self.balance > 0 or self.lessons_left <= 1
