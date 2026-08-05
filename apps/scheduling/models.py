from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import CEFR

WEEKDAYS = [
    (0, _("Понедельник")),
    (1, _("Вторник")),
    (2, _("Среда")),
    (3, _("Четверг")),
    (4, _("Пятница")),
    (5, _("Суббота")),
    (6, _("Воскресенье")),
]
WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


class DeliveryMode(models.TextChoices):
    OFFLINE = "offline", _("В классе")
    ONLINE = "online", _("Онлайн")


class Group(models.Model):
    """A learning group. A group with capacity 1 is simply an individual track,
    which keeps every downstream query (schedule, billing, homework) uniform."""

    name = models.CharField(_("Название"), max_length=120)
    course = models.ForeignKey("school.Course", on_delete=models.PROTECT, related_name="groups")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="teaching_groups",
        limit_choices_to={"role__in": ["teacher", "owner"]},
    )
    location = models.ForeignKey("school.Location", on_delete=models.SET_NULL, null=True, blank=True)
    mode = models.CharField(_("Формат"), max_length=8, choices=DeliveryMode.choices, default=DeliveryMode.OFFLINE)
    level = models.CharField(_("Уровень"), max_length=2, choices=CEFR.choices, blank=True)
    capacity = models.PositiveSmallIntegerField(_("Мест"), default=8)
    meeting_url = models.URLField(_("Ссылка на онлайн-класс"), blank=True)
    starts_on = models.DateField(_("Старт"), null=True, blank=True)
    ends_on = models.DateField(_("Окончание"), null=True, blank=True)
    program = models.ForeignKey(
        "learning.Program", on_delete=models.SET_NULL, null=True, blank=True, related_name="groups",
        verbose_name=_("Учебная программа"),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Группа")
        verbose_name_plural = _("Группы")
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_individual(self):
        return self.capacity == 1

    @property
    def active_enrollments(self):
        return self.enrollments.filter(is_active=True)

    @property
    def seats_taken(self):
        return self.active_enrollments.count()

    @property
    def seats_left(self):
        return max(0, self.capacity - self.seats_taken)

    @property
    def schedule_summary(self):
        parts = [
            f"{WEEKDAYS_SHORT[s.weekday]} {s.start_time.strftime('%H:%M')}"
            for s in self.slots.all()
        ]
        return ", ".join(parts)


class RecurringSlot(models.Model):
    """Weekly pattern a group runs on; lessons are materialised from it."""

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="slots")
    weekday = models.PositiveSmallIntegerField(_("День недели"), choices=WEEKDAYS)
    start_time = models.TimeField(_("Начало"))
    duration_minutes = models.PositiveSmallIntegerField(_("Длительность, мин"), default=60)

    class Meta:
        verbose_name = _("Слот расписания")
        verbose_name_plural = _("Слоты расписания")
        ordering = ["weekday", "start_time"]
        unique_together = [("group", "weekday", "start_time")]

    def __str__(self):
        return f"{self.group} · {WEEKDAYS_SHORT[self.weekday]} {self.start_time:%H:%M}"


class Enrollment(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments",
        limit_choices_to={"role": "student"},
    )
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="enrollments")
    started_on = models.DateField(default=timezone.localdate)
    ended_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = _("Зачисление")
        verbose_name_plural = _("Зачисления")
        unique_together = [("student", "group")]
        ordering = ["-started_on"]

    def __str__(self):
        return f"{self.student} → {self.group}"


class TeacherAvailability(models.Model):
    """Weekly windows in which a teacher accepts one-off bookings."""

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="availability",
        limit_choices_to={"role__in": ["teacher", "owner"]},
    )
    weekday = models.PositiveSmallIntegerField(_("День недели"), choices=WEEKDAYS)
    start_time = models.TimeField(_("С"))
    end_time = models.TimeField(_("До"))
    slot_minutes = models.PositiveSmallIntegerField(_("Шаг слота, мин"), default=60)
    mode = models.CharField(max_length=8, choices=DeliveryMode.choices, default=DeliveryMode.ONLINE)
    location = models.ForeignKey("school.Location", on_delete=models.SET_NULL, null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("Окно записи")
        verbose_name_plural = _("Окна записи")
        ordering = ["weekday", "start_time"]

    def __str__(self):
        return f"{self.teacher} · {WEEKDAYS_SHORT[self.weekday]} {self.start_time:%H:%M}–{self.end_time:%H:%M}"

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError(_("Время окончания должно быть позже начала."))

    def slot_starts_for(self, day):
        """Yield naive start times for a concrete date."""
        if self.valid_from and day < self.valid_from:
            return
        if self.valid_until and day > self.valid_until:
            return
        cursor = datetime.combine(day, self.start_time)
        end = datetime.combine(day, self.end_time)
        step = timedelta(minutes=self.slot_minutes)
        while cursor + step <= end:
            yield cursor
            cursor += step


class TimeOff(models.Model):
    """A holiday or a one-off block that removes a teacher from the grid."""

    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="time_off")
    starts_at = models.DateTimeField(_("С"))
    ends_at = models.DateTimeField(_("До"))
    reason = models.CharField(max_length=140, blank=True)

    class Meta:
        verbose_name = _("Недоступность")
        verbose_name_plural = _("Недоступность")
        ordering = ["-starts_at"]

    def __str__(self):
        return f"{self.teacher}: {self.starts_at:%d.%m %H:%M} – {self.ends_at:%d.%m %H:%M}"


class LessonStatus(models.TextChoices):
    SCHEDULED = "scheduled", _("Запланирован")
    COMPLETED = "completed", _("Проведён")
    CANCELLED = "cancelled", _("Отменён")


class LessonQuerySet(models.QuerySet):
    def upcoming(self):
        return self.filter(starts_at__gte=timezone.now(), status=LessonStatus.SCHEDULED)

    def past(self):
        return self.filter(starts_at__lt=timezone.now())

    def for_student(self, user):
        return self.filter(participants__student=user).exclude(
            participants__status=ParticipantStatus.CANCELLED
        ).distinct()

    def for_teacher(self, user):
        return self.filter(teacher=user)

    def in_range(self, start, end):
        return self.filter(starts_at__gte=start, starts_at__lt=end)


class Lesson(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="lessons", null=True, blank=True)
    course = models.ForeignKey("school.Course", on_delete=models.SET_NULL, null=True, blank=True)
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="lessons_taught",
        limit_choices_to={"role__in": ["teacher", "owner"]},
    )
    topic = models.CharField(_("Тема"), max_length=180, blank=True)
    unit = models.ForeignKey(
        "learning.Unit", on_delete=models.SET_NULL, null=True, blank=True, related_name="lessons",
        verbose_name=_("Юнит программы"),
    )
    starts_at = models.DateTimeField(_("Начало"), db_index=True)
    duration_minutes = models.PositiveSmallIntegerField(_("Длительность, мин"), default=60)
    mode = models.CharField(_("Формат"), max_length=8, choices=DeliveryMode.choices, default=DeliveryMode.OFFLINE)
    location = models.ForeignKey("school.Location", on_delete=models.SET_NULL, null=True, blank=True)
    meeting_url = models.URLField(_("Ссылка на онлайн-класс"), blank=True)
    capacity = models.PositiveSmallIntegerField(_("Мест"), default=1)
    is_trial = models.BooleanField(_("Пробный урок"), default=False)
    is_bookable = models.BooleanField(_("Доступен для самозаписи"), default=False)
    status = models.CharField(max_length=12, choices=LessonStatus.choices, default=LessonStatus.SCHEDULED)
    teacher_note = models.TextField(_("Заметка преподавателя"), blank=True)
    cancelled_reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = LessonQuerySet.as_manager()

    class Meta:
        verbose_name = _("Урок")
        verbose_name_plural = _("Уроки")
        ordering = ["starts_at"]
        indexes = [
            models.Index(fields=["teacher", "starts_at"]),
            models.Index(fields=["status", "starts_at"]),
        ]

    def __str__(self):
        return f"{self.title} · {timezone.localtime(self.starts_at):%d.%m %H:%M}"

    @property
    def title(self):
        return self.topic or (self.group.name if self.group else "Индивидуальный урок")

    @property
    def ends_at(self):
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    @property
    def is_past(self):
        return self.ends_at < timezone.now()

    @property
    def is_live_now(self):
        return self.starts_at <= timezone.now() <= self.ends_at

    @property
    def starts_in(self):
        return self.starts_at - timezone.now()

    @property
    def active_participants(self):
        return self.participants.exclude(status=ParticipantStatus.CANCELLED)

    @property
    def seats_left(self):
        return max(0, self.capacity - self.active_participants.count())

    @property
    def join_url(self):
        if self.meeting_url:
            return self.meeting_url
        if self.group and self.group.meeting_url:
            return self.group.meeting_url
        profile = getattr(self.teacher, "teacher_profile", None)
        return profile.default_meeting_url if profile else ""

    def overlaps_teacher_schedule(self):
        """True if the teacher already has something at this time."""
        clash = Lesson.objects.filter(teacher=self.teacher, status=LessonStatus.SCHEDULED).exclude(pk=self.pk)
        for lesson in clash.filter(
            starts_at__lt=self.ends_at, starts_at__gte=self.starts_at - timedelta(hours=12)
        ):
            if lesson.ends_at > self.starts_at:
                return True
        return TimeOff.objects.filter(
            teacher=self.teacher, starts_at__lt=self.ends_at, ends_at__gt=self.starts_at
        ).exists()

    def can_be_cancelled_free_by(self, user):
        hours = getattr(settings, "FREE_CANCELLATION_HOURS", 12)
        return self.starts_at - timezone.now() > timedelta(hours=hours)


class ParticipantStatus(models.TextChoices):
    BOOKED = "booked", _("Записан")
    ATTENDED = "attended", _("Был")
    ABSENT = "absent", _("Не пришёл")
    EXCUSED = "excused", _("Отменил заранее")
    CANCELLED = "cancelled", _("Запись отменена")


class LessonParticipant(models.Model):
    """One student's relationship to one lesson: booking + attendance in one row."""

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="participants")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_participations",
        limit_choices_to={"role": "student"},
    )
    status = models.CharField(max_length=12, choices=ParticipantStatus.choices, default=ParticipantStatus.BOOKED)
    booked_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    is_chargeable = models.BooleanField(
        _("Списывать урок"), default=True,
        help_text=_("Снимается, если ученик отменил заранее или урок отменила школа."),
    )
    teacher_comment = models.TextField(_("Комментарий по уроку"), blank=True)
    performance = models.PositiveSmallIntegerField(
        _("Оценка активности"), null=True, blank=True, help_text=_("1–5, видна ученику.")
    )

    class Meta:
        verbose_name = _("Участник урока")
        verbose_name_plural = _("Участники уроков")
        unique_together = [("lesson", "student")]
        ordering = ["student__last_name"]

    def __str__(self):
        return f"{self.student} @ {self.lesson}"

    @property
    def is_active(self):
        return self.status != ParticipantStatus.CANCELLED
