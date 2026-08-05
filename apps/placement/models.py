from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# Ladder the adaptive engine walks up and down.
LEVEL_LADDER = ["A1", "A2", "B1", "B2", "C1"]

LEVEL_COPY = {
    "A0": ("Beginner", "Вы в самом начале — и это лучшая точка старта: прогресс будет заметен уже через месяц."),
    "A1": ("Elementary", "Вы понимаете простые фразы и можете рассказать о себе. Дальше — уверенный быт и путешествия."),
    "A2": ("Pre-Intermediate", "Базы хватает на бытовые ситуации. Следующий шаг — свободнее говорить и перестать переводить в голове."),
    "B1": ("Intermediate", "Вы уже общаетесь. Теперь важно убрать ошибки, расширить лексику и научиться говорить длинными мыслями."),
    "B2": ("Upper-Intermediate", "Сильный уровень: работа, собеседования, переговоры. Дальше — нюансы, идиомы и академический язык."),
    "C1": ("Advanced", "Вы свободно владеете языком. Полируем стиль, беглость и профессиональную лексику."),
    "C2": ("Proficiency", "Уровень, близкий к носителю. Работаем точечно — над стилистикой и специализированной лексикой."),
}


class Skill(models.TextChoices):
    GRAMMAR = "grammar", _("Грамматика")
    VOCABULARY = "vocabulary", _("Лексика")
    READING = "reading", _("Чтение")
    USAGE = "usage", _("Речевые ситуации")


class Question(models.Model):
    language = models.ForeignKey(
        "school.Language", on_delete=models.CASCADE, related_name="test_questions", null=True, blank=True
    )
    level = models.CharField(_("Уровень"), max_length=2, db_index=True)
    skill = models.CharField(_("Навык"), max_length=12, choices=Skill.choices, default=Skill.GRAMMAR)
    prompt = models.CharField(_("Вопрос"), max_length=300)
    hint = models.CharField(_("Пояснение к заданию"), max_length=200, blank=True)
    options = models.JSONField(_("Варианты"), default=list)
    correct_index = models.PositiveSmallIntegerField(_("Номер верного варианта"), default=0)
    explanation = models.CharField(_("Почему так"), max_length=300, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("Вопрос теста")
        verbose_name_plural = _("Вопросы теста")
        ordering = ["level", "id"]

    def __str__(self):
        return f"[{self.level}] {self.prompt[:60]}"

    @property
    def correct_option(self):
        try:
            return self.options[self.correct_index]
        except (IndexError, TypeError):
            return ""


class TestSession(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="placement_sessions"
    )
    session_key = models.CharField(max_length=64, db_index=True, blank=True)
    language = models.ForeignKey("school.Language", on_delete=models.SET_NULL, null=True, blank=True)
    current_level = models.CharField(max_length=2, default="A2")
    visited_levels = models.JSONField(default=list, blank=True)
    result_level = models.CharField(max_length=2, blank=True)
    correct_count = models.PositiveSmallIntegerField(default=0)
    total_count = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    lead = models.ForeignKey("school.Lead", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = _("Прохождение теста")
        verbose_name_plural = _("Прохождения теста")
        ordering = ["-started_at"]

    def __str__(self):
        who = self.user or "аноним"
        return f"{who} → {self.result_level or '...'}"

    @property
    def is_finished(self):
        return self.finished_at is not None

    @property
    def accuracy(self):
        if not self.total_count:
            return 0
        return round(100 * self.correct_count / self.total_count)

    @property
    def duration_minutes(self):
        end = self.finished_at or timezone.now()
        return max(1, round((end - self.started_at).total_seconds() / 60))

    @property
    def level_title(self):
        return LEVEL_COPY.get(self.result_level, ("", ""))[0]

    @property
    def level_message(self):
        return LEVEL_COPY.get(self.result_level, ("", ""))[1]

    def skill_breakdown(self):
        """Per-skill accuracy — the part students actually screenshot and share."""
        rows = []
        for value, label in Skill.choices:
            answers = self.answers.filter(question__skill=value)
            total = answers.count()
            if not total:
                continue
            correct = answers.filter(is_correct=True).count()
            rows.append({
                "skill": label,
                "total": total,
                "correct": correct,
                "percent": round(100 * correct / total),
            })
        return rows


class TestAnswer(models.Model):
    session = models.ForeignKey(TestSession, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    chosen_index = models.SmallIntegerField(default=-1)
    is_correct = models.BooleanField(default=False)
    seconds_spent = models.PositiveSmallIntegerField(default=0)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Ответ в тесте")
        verbose_name_plural = _("Ответы в тесте")
        unique_together = [("session", "question")]
        ordering = ["answered_at"]

    def __str__(self):
        return f"{self.session_id} · {'✓' if self.is_correct else '✗'}"
