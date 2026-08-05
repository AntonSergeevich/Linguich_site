from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Channel(models.TextChoices):
    EMAIL = "email", _("Email")
    TELEGRAM = "telegram", _("Telegram")
    INAPP = "inapp", _("В кабинете")


class NotificationKind(models.TextChoices):
    LESSON_REMINDER = "lesson_reminder", _("Напоминание об уроке")
    LESSON_CANCELLED = "lesson_cancelled", _("Урок отменён")
    LESSON_BOOKED = "lesson_booked", _("Запись на урок")
    HOMEWORK_ASSIGNED = "homework_assigned", _("Новое домашнее задание")
    HOMEWORK_REVIEWED = "homework_reviewed", _("Домашка проверена")
    HOMEWORK_SUBMITTED = "homework_submitted", _("Ученик сдал домашку")
    PACKAGE_LOW = "package_low", _("Заканчивается абонемент")
    PAYMENT_DUE = "payment_due", _("Напоминание об оплате")
    PAYMENT_RECEIVED = "payment_received", _("Платёж получен")
    NEW_LEAD = "new_lead", _("Новая заявка")
    CUSTOM = "custom", _("Произвольное")


class Status(models.TextChoices):
    PENDING = "pending", _("В очереди")
    SENT = "sent", _("Отправлено")
    FAILED = "failed", _("Ошибка")
    SKIPPED = "skipped", _("Пропущено")


class Notification(models.Model):
    """A queued message. Nothing is sent inline during a request — a cron-driven
    worker drains the queue, so a dead SMTP server can never break a booking."""

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=24, choices=NotificationKind.choices, default=NotificationKind.CUSTOM)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.INAPP)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    url = models.CharField(max_length=300, blank=True)
    lesson = models.ForeignKey(
        "scheduling.Lesson", on_delete=models.CASCADE, null=True, blank=True, related_name="notifications"
    )
    scheduled_for = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    dedupe_key = models.CharField(max_length=140, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Уведомление")
        verbose_name_plural = _("Уведомления")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "scheduled_for"])]

    def __str__(self):
        return f"{self.get_kind_display()} → {self.recipient}"

    @property
    def is_unread(self):
        return self.read_at is None

    def mark_sent(self):
        self.status = Status.SENT
        self.sent_at = timezone.now()
        self.save(update_fields=["status", "sent_at"])

    def mark_failed(self, error):
        self.status = Status.FAILED
        self.error = str(error)[:300]
        self.save(update_fields=["status", "error"])
