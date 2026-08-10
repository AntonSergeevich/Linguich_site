import re
import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.timezone import now as tz_now
from django.utils.translation import gettext_lazy as _


def normalize_phone(value):
    """Reduce any Russian phone format to a canonical +7XXXXXXXXXX string."""
    if not value:
        return ""
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if not digits:
        return ""
    return "+" + digits


class Role(models.TextChoices):
    STUDENT = "student", _("Ученик")
    TEACHER = "teacher", _("Преподаватель")
    # Администратор ведёт заявки, учеников и платежи, но не видит зарплат
    # и не может заводить сотрудников — это остаётся за владелицей.
    ADMIN = "admin", _("Администратор")
    OWNER = "owner", _("Владелец")


class CEFR(models.TextChoices):
    A0 = "A0", "A0 · Beginner"
    A1 = "A1", "A1 · Elementary"
    A2 = "A2", "A2 · Pre-Intermediate"
    B1 = "B1", "B1 · Intermediate"
    B2 = "B2", "B2 · Upper-Intermediate"
    C1 = "C1", "C1 · Advanced"
    C2 = "C2", "C2 · Proficiency"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, phone, password, **extra):
        if not email and not phone and not extra.get("username"):
            raise ValueError("Нужен email, телефон или логин")
        email = self.normalize_email(email) if email else None
        phone = normalize_phone(phone) or None
        user = self.model(email=email, phone=phone, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email=None, phone=None, password=None, **extra):
        extra.setdefault("role", Role.STUDENT)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, phone, password, **extra)

    def create_superuser(self, email=None, phone=None, password=None, **extra):
        extra.setdefault("role", Role.OWNER)
        extra["is_staff"] = True
        extra["is_superuser"] = True
        extra.setdefault("is_active", True)
        return self._create(email, phone, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """A single account model for students, teachers and the owner.

    Login works with either email or phone — students routinely remember one
    but not the other, and forcing a username on them costs conversions.
    """

    email = models.EmailField(_("Email"), unique=True, null=True, blank=True)
    phone = models.CharField(_("Телефон"), max_length=20, unique=True, null=True, blank=True)
    # Логин выдаёт школа, когда заводит ученика: у школьника может не быть
    # ни почты, ни своего телефона, а войти в кабинет ему всё равно нужно.
    username = models.CharField(
        _("Логин"), max_length=32, unique=True, null=True, blank=True, db_index=True
    )
    first_name = models.CharField(_("Имя"), max_length=80)
    last_name = models.CharField(_("Фамилия"), max_length=80, blank=True)
    role = models.CharField(_("Роль"), max_length=16, choices=Role.choices, default=Role.STUDENT, db_index=True)
    avatar = models.ImageField(_("Фото"), upload_to="avatars/", blank=True, null=True)
    timezone = models.CharField(_("Часовой пояс"), max_length=64, default="Asia/Krasnoyarsk")

    telegram_chat_id = models.CharField(max_length=32, blank=True, db_index=True)
    telegram_link_code = models.CharField(max_length=16, blank=True, db_index=True)
    notify_email = models.BooleanField(_("Уведомления на email"), default=True)
    notify_telegram = models.BooleanField(_("Уведомления в Telegram"), default=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    # Пароль, выданный школой, знает не только владелец аккаунта — значит,
    # он временный и должен быть заменён при первом входе.
    must_change_password = models.BooleanField(_("Сменить пароль при входе"), default=False)
    date_joined = models.DateTimeField(default=tz_now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name"]

    class Meta:
        verbose_name = _("Пользователь")
        verbose_name_plural = _("Пользователи")
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return self.full_name or self.email or self.phone or f"user #{self.pk}"

    def clean(self):
        super().clean()
        if not self.email and not self.phone and not self.username:
            raise ValidationError(_("Укажите email, телефон или логин."))

    def save(self, *args, **kwargs):
        self.phone = normalize_phone(self.phone) or None
        self.email = (self.email or "").strip().lower() or None
        # Логин нечувствителен к регистру: ученик, которому его продиктовали,
        # наберёт как получится, а уникальность должна остаться настоящей.
        self.username = (self.username or "").strip().lower() or None
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def short_name(self):
        if self.last_name:
            return f"{self.first_name} {self.last_name[0]}."
        return self.first_name

    @property
    def initials(self):
        parts = [p for p in (self.first_name, self.last_name) if p]
        return "".join(p[0].upper() for p in parts[:2]) or "?"

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.first_name

    # -- role helpers -------------------------------------------------------
    @property
    def is_student(self):
        return self.role == Role.STUDENT

    @property
    def is_teacher(self):
        """The owner teaches too, so she counts as a teacher everywhere."""
        return self.role in {Role.TEACHER, Role.OWNER}

    @property
    def is_owner(self):
        return self.role == Role.OWNER

    @property
    def is_manager(self):
        """Кто работает с учениками и заявками: администратор и владелица.

        Отдельно от `is_owner`, потому что деньги сотрудников и заведение
        новых сотрудников остаются только у владелицы.
        """
        return self.role in {Role.ADMIN, Role.OWNER}

    def ensure_telegram_code(self):
        if not self.telegram_link_code:
            self.telegram_link_code = secrets.token_urlsafe(6)[:10]
            self.save(update_fields=["telegram_link_code"])
        return self.telegram_link_code

    @property
    def telegram_link_url(self):
        bot = getattr(settings, "TELEGRAM_BOT_USERNAME", "")
        return f"https://t.me/{bot}?start={self.ensure_telegram_code()}"


class TeacherProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="teacher_profile")
    headline = models.CharField(_("Специализация"), max_length=140, blank=True)
    bio = models.TextField(_("О себе"), blank=True)
    languages = models.ManyToManyField("school.Language", blank=True, related_name="teachers")
    experience_since = models.PositiveIntegerField(_("В профессии с"), null=True, blank=True)
    education = models.CharField(_("Образование"), max_length=200, blank=True)
    is_native = models.BooleanField(_("Носитель языка"), default=False)
    show_on_site = models.BooleanField(_("Показывать на сайте"), default=True)
    accepts_new_students = models.BooleanField(_("Набирает учеников"), default=True)
    calendar_color = models.CharField(max_length=7, default="#0B6E7F")
    pay_rate = models.DecimalField(
        _("Ставка за урок, ₽"), max_digits=9, decimal_places=2, default=0,
        help_text=_("Используется для расчёта зарплаты в отчётах владельца."),
    )
    default_meeting_url = models.URLField(_("Постоянная ссылка на онлайн-класс"), blank=True)
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        verbose_name = _("Профиль преподавателя")
        verbose_name_plural = _("Профили преподавателей")
        ordering = ["sort_order", "user__last_name"]

    def __str__(self):
        return f"{self.user} — преподаватель"

    @property
    def years_of_experience(self):
        if not self.experience_since:
            return None
        return max(0, timezone.now().year - self.experience_since)


class StudentStatus(models.TextChoices):
    LEAD = "lead", _("Лид")
    TRIAL = "trial", _("Пробный урок")
    ACTIVE = "active", _("Учится")
    PAUSED = "paused", _("Пауза")
    CHURNED = "churned", _("Ушёл")


class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="student_profile")
    status = models.CharField(max_length=16, choices=StudentStatus.choices, default=StudentStatus.LEAD, db_index=True)
    level = models.CharField(_("Уровень"), max_length=2, choices=CEFR.choices, blank=True)
    birth_date = models.DateField(_("Дата рождения"), null=True, blank=True)
    goal = models.TextField(_("Цель обучения"), blank=True)
    parent_name = models.CharField(_("Родитель / контактное лицо"), max_length=120, blank=True)
    parent_phone = models.CharField(_("Телефон родителя"), max_length=20, blank=True)
    source = models.CharField(_("Откуда узнал"), max_length=120, blank=True)
    internal_notes = models.TextField(_("Заметки администратора"), blank=True)
    started_at = models.DateField(_("Начало обучения"), null=True, blank=True)

    class Meta:
        verbose_name = _("Профиль ученика")
        verbose_name_plural = _("Профили учеников")

    def __str__(self):
        return f"{self.user} — ученик"

    @property
    def age(self):
        if not self.birth_date:
            return None
        today = timezone.localdate()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )

    @property
    def is_minor(self):
        age = self.age
        return age is not None and age < 18
