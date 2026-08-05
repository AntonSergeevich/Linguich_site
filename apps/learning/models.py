from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import CEFR


class Program(models.Model):
    """A reusable curriculum: the teacher builds it once, then hangs groups on it."""

    title = models.CharField(_("Название программы"), max_length=160)
    language = models.ForeignKey("school.Language", on_delete=models.CASCADE, related_name="programs")
    level = models.CharField(_("Уровень"), max_length=2, choices=CEFR.choices, blank=True)
    description = models.TextField(_("Описание"), blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="programs"
    )
    is_shared = models.BooleanField(
        _("Доступна другим преподавателям"), default=True,
        help_text=_("Общая библиотека школы — программу можно взять за основу."),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Программа")
        verbose_name_plural = _("Программы")
        ordering = ["language__name", "level", "title"]

    def __str__(self):
        return f"{self.title} ({self.level})" if self.level else self.title

    @property
    def unit_count(self):
        return Unit.objects.filter(module__program=self).count()


class Module(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(_("Название модуля"), max_length=160)
    summary = models.CharField(max_length=240, blank=True)
    order = models.PositiveSmallIntegerField(default=1)

    class Meta:
        verbose_name = _("Модуль")
        verbose_name_plural = _("Модули")
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.program} · {self.title}"


class Unit(models.Model):
    """One lesson's worth of curriculum: objectives, content and materials."""

    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="units")
    title = models.CharField(_("Тема"), max_length=180)
    order = models.PositiveSmallIntegerField(default=1)
    objectives = models.TextField(_("Цели урока"), blank=True, help_text=_("По одному пункту на строку."))
    content = models.TextField(_("Конспект / план"), blank=True)
    vocabulary = models.TextField(_("Лексика"), blank=True, help_text=_("word — перевод, по строке на слово."))
    estimated_minutes = models.PositiveSmallIntegerField(default=60)

    class Meta:
        verbose_name = _("Юнит")
        verbose_name_plural = _("Юниты")
        ordering = ["module__order", "order", "id"]

    def __str__(self):
        return self.title

    @property
    def objective_list(self):
        return [line.strip() for line in self.objectives.splitlines() if line.strip()]

    @property
    def vocabulary_pairs(self):
        pairs = []
        for line in self.vocabulary.splitlines():
            line = line.strip()
            if not line:
                continue
            for sep in ("—", "–", " - ", "="):
                if sep in line:
                    term, _sep, translation = line.partition(sep)
                    pairs.append((term.strip(), translation.strip()))
                    break
            else:
                pairs.append((line, ""))
        return pairs


class MaterialKind(models.TextChoices):
    FILE = "file", _("Файл")
    LINK = "link", _("Ссылка")
    VIDEO = "video", _("Видео")
    AUDIO = "audio", _("Аудио")
    TEXT = "text", _("Текст")


class Material(models.Model):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="materials", null=True, blank=True)
    assignment = models.ForeignKey(
        "learning.Assignment", on_delete=models.CASCADE, related_name="materials", null=True, blank=True
    )
    title = models.CharField(_("Название"), max_length=180)
    kind = models.CharField(max_length=8, choices=MaterialKind.choices, default=MaterialKind.LINK)
    url = models.URLField(blank=True)
    file = models.FileField(upload_to="materials/%Y/%m/", blank=True, null=True)
    body = models.TextField(_("Текст"), blank=True)
    order = models.PositiveSmallIntegerField(default=1)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Материал")
        verbose_name_plural = _("Материалы")
        ordering = ["order", "id"]

    def __str__(self):
        return self.title

    @property
    def href(self):
        if self.file:
            return self.file.url
        return self.url

    @property
    def icon(self):
        return {
            MaterialKind.FILE: "file",
            MaterialKind.LINK: "link",
            MaterialKind.VIDEO: "video",
            MaterialKind.AUDIO: "audio",
            MaterialKind.TEXT: "text",
        }.get(self.kind, "file")


class Assignment(models.Model):
    """Homework. Created once by a teacher and handed to a group or to picked students."""

    title = models.CharField(_("Название"), max_length=180)
    description = models.TextField(_("Задание"), blank=True)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assignments_created")
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name="assignments")
    lesson = models.ForeignKey(
        "scheduling.Lesson", on_delete=models.SET_NULL, null=True, blank=True, related_name="assignments",
        verbose_name=_("Выдано на уроке"),
    )
    group = models.ForeignKey(
        "scheduling.Group", on_delete=models.SET_NULL, null=True, blank=True, related_name="assignments"
    )
    due_at = models.DateTimeField(_("Срок сдачи"), null=True, blank=True)
    max_score = models.PositiveSmallIntegerField(_("Максимум баллов"), default=10)
    requires_submission = models.BooleanField(
        _("Нужно сдать работу"), default=True,
        help_text=_("Снимите, если задание «прочитать/послушать» без отправки ответа."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Задание")
        verbose_name_plural = _("Задания")
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_overdue(self):
        return bool(self.due_at and self.due_at < timezone.now())

    @property
    def pending_review_count(self):
        return self.submissions.filter(status=SubmissionStatus.SUBMITTED).count()

    def assign_to(self, students):
        """Hand this assignment to students, skipping anyone who already has it."""
        existing = set(self.submissions.values_list("student_id", flat=True))
        created = [
            Submission(assignment=self, student=student)
            for student in students
            if student.pk not in existing
        ]
        Submission.objects.bulk_create(created)
        return len(created)


class SubmissionStatus(models.TextChoices):
    ASSIGNED = "assigned", _("Назначено")
    SUBMITTED = "submitted", _("Сдано")
    REVIEWED = "reviewed", _("Проверено")
    REDO = "redo", _("На доработку")


class Submission(models.Model):
    """A student's copy of an assignment — created the moment it is handed out."""

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions")
    status = models.CharField(max_length=12, choices=SubmissionStatus.choices, default=SubmissionStatus.ASSIGNED)
    answer_text = models.TextField(_("Ответ"), blank=True)
    answer_file = models.FileField(upload_to="submissions/%Y/%m/", blank=True, null=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    teacher_feedback = models.TextField(_("Комментарий преподавателя"), blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Работа ученика")
        verbose_name_plural = _("Работы учеников")
        unique_together = [("assignment", "student")]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.student} — {self.assignment}"

    @property
    def is_open(self):
        return self.status in {SubmissionStatus.ASSIGNED, SubmissionStatus.REDO}

    @property
    def is_overdue(self):
        return self.is_open and self.assignment.is_overdue

    def mark_submitted(self):
        self.status = SubmissionStatus.SUBMITTED
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at", "updated_at"])
