from django.db import models
from django.utils import timezone
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import CEFR


class SiteSettings(models.Model):
    """Single-row model so the owner can edit contacts without a developer."""

    brand_name = models.CharField(max_length=60, default="Лингвич")
    tagline = models.CharField(max_length=140, default="Языковая школа в Красноярске")
    phone = models.CharField(max_length=32, default="+7 (391) 214-73-03")
    email = models.EmailField(default="linguich@ya.ru")
    telegram_url = models.URLField(blank=True)
    whatsapp_url = models.URLField(blank=True)
    vk_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    hero_title = models.CharField(max_length=160, default="Язык, на котором вы наконец заговорите")
    hero_subtitle = models.CharField(
        max_length=240,
        default="Английский, немецкий, китайский и ещё пять языков — в группах, индивидуально и онлайн.",
    )
    notify_leads_to = models.EmailField(
        blank=True, help_text=_("Куда присылать уведомления о новых заявках.")
    )

    # Блок «слово основателя» на главной. Для локальной школы личное обращение
    # владелицы конвертирует лучше любого рекламного текста, но появляется он
    # только когда есть и фото, и текст — иначе выглядит пустой заглушкой.
    founder_name = models.CharField(
        _("Основатель: имя"), max_length=120, blank=True, default="Глухова Евгения Алексеевна"
    )
    founder_role = models.CharField(
        _("Основатель: должность"), max_length=140, blank=True,
        default="основатель школы, преподаватель английского",
    )
    founder_photo = models.ImageField(_("Основатель: фото"), upload_to="site/", blank=True, null=True)
    founder_quote = models.TextField(
        _("Основатель: обращение"), blank=True,
        default="Я открыла «Лингвич» в 2011 году, потому что верю: язык учат разговором, "
                "а не зубрёжкой правил. Мы не гонимся за количеством — я лично знаю каждого "
                "преподавателя и вижу, как идут дела у каждой группы.",
    )

    # Полоса доверия под первым экраном. Человек выбирает языковую школу по
    # чужому опыту, а не по вёрстке, и оценка с площадки — самый сильный
    # довод, какой у школы есть. Числа редактируются в админке: подставлять
    # их в шаблон значит гарантированно забыть обновить.
    rating_value = models.DecimalField(
        _("Оценка на площадке"), max_digits=2, decimal_places=1, null=True, blank=True,
        help_text=_("Например 4.9. Пусто — блок с оценкой не показывается."),
    )
    rating_count = models.PositiveIntegerField(_("Отзывов на площадке"), default=0)
    rating_source = models.CharField(_("Площадка"), max_length=40, blank=True, default="2ГИС")
    rating_url = models.URLField(_("Ссылка на отзывы"), blank=True)
    students_total = models.CharField(
        _("Учеников всего"), max_length=20, blank=True, default="1 400+",
        help_text=_("Как показывать: «1 400+». Пишется словом, а не числом, — это витрина."),
    )
    since_year = models.PositiveSmallIntegerField(_("Работаем с"), default=2011)

    class Meta:
        verbose_name = _("Настройки сайта")
        verbose_name_plural = _("Настройки сайта")

    def __str__(self):
        return self.brand_name

    @property
    def years_open(self):
        return max(1, timezone.localdate().year - self.since_year)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def show_founder(self):
        return bool(self.founder_quote and self.founder_name)


class Location(models.Model):
    name = models.CharField(_("Название"), max_length=80)
    address = models.CharField(_("Адрес"), max_length=200)
    city = models.CharField(_("Город"), max_length=80, default="Красноярск")
    map_embed_url = models.URLField(_("Карта (iframe src)"), blank=True)
    is_online = models.BooleanField(_("Онлайн-площадка"), default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("Филиал")
        verbose_name_plural = _("Филиалы")
        ordering = ["-is_online", "name"]

    def __str__(self):
        return self.name


class Language(models.Model):
    name = models.CharField(_("Язык"), max_length=60)
    slug = models.SlugField(unique=True)
    flag_code = models.CharField(_("Код флага"), max_length=4, default="gb", help_text="ISO 3166-1 alpha-2")
    short_pitch = models.CharField(_("Короткое описание"), max_length=180, blank=True)
    description = models.TextField(_("Описание"), blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        verbose_name = _("Язык")
        verbose_name_plural = _("Языки")
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("school:language", args=[self.slug])

    @property
    def flag_emoji(self):
        """Regional-indicator pair for the ISO code — no flag sprite needed."""
        code = (self.flag_code or "").strip().upper()
        if len(code) != 2 or not code.isalpha():
            return "🌐"
        return "".join(chr(0x1F1E6 + ord(char) - ord("A")) for char in code)


class CourseFormat(models.TextChoices):
    GROUP = "group", _("Группа")
    INDIVIDUAL = "individual", _("Индивидуально")
    PAIR = "pair", _("Пара / мини-группа")
    CLUB = "club", _("Разговорный клуб")
    KIDS = "kids", _("Дети")
    EXAM = "exam", _("Подготовка к экзамену")
    CORPORATE = "corporate", _("Корпоративный")


class Course(models.Model):
    language = models.ForeignKey(Language, on_delete=models.CASCADE, related_name="courses")
    title = models.CharField(_("Название"), max_length=140)
    slug = models.SlugField(unique=True)
    format = models.CharField(_("Формат"), max_length=16, choices=CourseFormat.choices, default=CourseFormat.GROUP)
    level_from = models.CharField(_("Уровень от"), max_length=2, choices=CEFR.choices, blank=True)
    level_to = models.CharField(_("Уровень до"), max_length=2, choices=CEFR.choices, blank=True)
    age_from = models.PositiveSmallIntegerField(_("Возраст от"), null=True, blank=True)
    age_to = models.PositiveSmallIntegerField(_("Возраст до"), null=True, blank=True)
    summary = models.CharField(_("Короткое описание"), max_length=220, blank=True)
    description = models.TextField(_("Описание"), blank=True)
    outcomes = models.TextField(
        _("Результаты"), blank=True, help_text=_("По одному пункту на строку.")
    )
    duration_minutes = models.PositiveSmallIntegerField(_("Длительность урока, мин"), default=60)
    lessons_per_week = models.PositiveSmallIntegerField(_("Занятий в неделю"), default=2)
    price_per_lesson = models.DecimalField(_("Цена за урок, ₽"), max_digits=9, decimal_places=2, default=0)
    is_online_available = models.BooleanField(_("Есть онлайн"), default=True)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(_("На главной"), default=False)
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        verbose_name = _("Курс")
        verbose_name_plural = _("Курсы")
        ordering = ["sort_order", "title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("school:course", args=[self.slug])

    @property
    def outcome_list(self):
        return [line.strip() for line in self.outcomes.splitlines() if line.strip()]

    @property
    def level_range(self):
        if self.level_from and self.level_to:
            return f"{self.level_from}–{self.level_to}"
        return self.level_from or self.level_to or "любой уровень"


class Promo(models.Model):
    title = models.CharField(_("Заголовок"), max_length=140)
    slug = models.SlugField(unique=True)
    subtitle = models.CharField(_("Подзаголовок"), max_length=200, blank=True)
    description = models.TextField(_("Условия"), blank=True)
    badge = models.CharField(_("Плашка"), max_length=40, blank=True, help_text="Например: −20%")
    starts_at = models.DateField(null=True, blank=True)
    ends_at = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("Акция")
        verbose_name_plural = _("Акции")
        ordering = ["-starts_at", "title"]

    def __str__(self):
        return self.title


class Review(models.Model):
    author_name = models.CharField(_("Имя"), max_length=120)
    author_role = models.CharField(_("Кто"), max_length=120, blank=True, help_text="Например: мама ученика, 8 лет")
    text = models.TextField(_("Отзыв"))
    rating = models.PositiveSmallIntegerField(_("Оценка"), default=5)
    language = models.ForeignKey(Language, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviews")
    photo = models.ImageField(upload_to="reviews/", blank=True, null=True)
    # Отзыв без источника ничем не отличается от текста, который школа
    # написала себе сама. Площадка и ссылка превращают его в доказательство.
    source = models.CharField(
        _("Откуда отзыв"), max_length=40, blank=True,
        help_text=_("Например «2ГИС» или «Яндекс Карты». Пусто — просто отзыв на сайте."),
    )
    source_url = models.URLField(_("Ссылка на отзыв"), blank=True)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Отзыв")
        verbose_name_plural = _("Отзывы")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.author_name} ({self.rating}/5)"


class FAQ(models.Model):
    question = models.CharField(max_length=220)
    answer = models.TextField()
    sort_order = models.PositiveIntegerField(default=100)
    is_published = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("Вопрос-ответ")
        verbose_name_plural = _("Вопросы и ответы")
        ordering = ["sort_order"]

    def __str__(self):
        return self.question


class LeadStatus(models.TextChoices):
    NEW = "new", _("Новая")
    IN_PROGRESS = "in_progress", _("В работе")
    SCHEDULED = "scheduled", _("Записан на пробный")
    WON = "won", _("Стал учеником")
    LOST = "lost", _("Отказ")


class LeadSource(models.TextChoices):
    TRIAL_FORM = "trial", _("Форма записи")
    CALLBACK = "callback", _("Обратный звонок")
    PLACEMENT_TEST = "placement", _("Тест уровня")
    COURSE_PAGE = "course", _("Страница курса")
    PHONE = "phone", _("Звонок")
    OFFLINE = "offline", _("Пришли в офис")
    OTHER = "other", _("Другое")


class Lead(models.Model):
    """Every inbound request lands here and shows up in the owner's CRM."""

    name = models.CharField(_("Имя"), max_length=120)
    phone = models.CharField(_("Телефон"), max_length=20)
    email = models.EmailField(_("Email"), blank=True)
    message = models.TextField(_("Сообщение"), blank=True)
    language = models.ForeignKey(Language, on_delete=models.SET_NULL, null=True, blank=True)
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True)
    preferred_format = models.CharField(max_length=16, choices=CourseFormat.choices, blank=True)
    source = models.CharField(max_length=16, choices=LeadSource.choices, default=LeadSource.TRIAL_FORM)
    status = models.CharField(max_length=16, choices=LeadStatus.choices, default=LeadStatus.NEW, db_index=True)
    placement_level = models.CharField(max_length=2, choices=CEFR.choices, blank=True)
    assigned_to = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_leads"
    )
    converted_user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="origin_leads"
    )
    admin_notes = models.TextField(_("Комментарий"), blank=True)
    # Нужны для защиты от ботов: по ним считается частота заявок с адреса
    # и видно, что за поток пришёл, если начнётся налив.
    ip = models.CharField(max_length=45, blank=True, db_index=True)
    user_agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Заявка")
        verbose_name_plural = _("Заявки")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            # Счётчик заявок с одного адреса за час — самый горячий запрос
            # антиспама, он выполняется на каждой отправке формы.
            models.Index(fields=["ip", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.name} · {self.phone}"

    @property
    def is_open(self):
        return self.status in {LeadStatus.NEW, LeadStatus.IN_PROGRESS, LeadStatus.SCHEDULED}
