# -*- coding: utf-8 -*-
"""Наполняет каталог школы: языки, курсы, тарифы, офисы, FAQ, отзывы, акции.

В отличие от ``seed_demo`` здесь нет ни одного выдуманного человека —
ни преподавателей, ни учеников, ни платежей. Поэтому команду можно и нужно
запускать на боевом сервере: без неё сайт открывается с пустым каталогом
(«0 языков в школе»), а заявку не к чему привязать.

Все записи создаются через ``get_or_create``, так что повторный запуск
ничего не сломает и не перезапишет отредактированные тексты.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.billing.models import Tariff
from apps.school.models import FAQ, Course, CourseFormat, Language, Location, Promo, Review

# Знак и цвет линии — то, чем язык живёт на схеме маршрутов в первом экране.
# Заводим здесь же: язык без цвета и буквы попадёт на схему безымянным.
LANGUAGES = [
    ("Английский", "english", "gb", "Самый востребованный — от нуля до С1 и экзаменов.", "A", "#008CD2"),
    ("Немецкий", "german", "de", "Учёба и работа в Германии, Австрии, Швейцарии.", "Ä", "#F2B134"),
    ("Китайский", "chinese", "cn", "Иероглифы без страха и живая разговорная практика.", "文", "#E2543C"),
    ("Французский", "french", "fr", "Язык, который приятно слышать в собственном исполнении.", "Ç", "#7C5CD6"),
    ("Корейский", "korean", "kr", "От хангыля до сериалов без субтитров.", "한", "#2FB98A"),
    ("Турецкий", "turkish", "tr", "Быстрый старт для поездок и переезда.", "Ş", "#E8657F"),
    ("Чешский", "czech", "cz", "Подготовка к учёбе в чешских вузах.", "Č", "#4E7FA8"),
]

COURSES = [
    ("english", "Английский с нуля", CourseFormat.GROUP, "A0", "A2", 1050, True,
     "Спокойный старт для тех, кто «учил в школе и всё забыл»."),
    ("english", "Разговорный английский", CourseFormat.CLUB, "A2", "B2", 900, True,
     "90 минут только речи: дискуссии, ролевые игры, живые темы."),
    ("english", "Английский индивидуально", CourseFormat.INDIVIDUAL, "A0", "C1", 1800, True,
     "Программа под вашу цель и график. Онлайн или в классе."),
    ("english", "Подготовка к IELTS", CourseFormat.EXAM, "B1", "C1", 2000, False,
     "Стратегии по всем четырём секциям и пробные экзамены."),
    ("english", "Английский для детей 7–10", CourseFormat.KIDS, "A0", "A2", 950, True,
     "Игры, песни и театр — дети говорят раньше, чем начинают бояться."),
    ("german", "Немецкий А1–А2", CourseFormat.GROUP, "A0", "A2", 1000, False,
     "Уверенная база за один учебный год."),
    ("chinese", "Китайский для начинающих", CourseFormat.GROUP, "A0", "A1", 1100, True,
     "Тоны, пиньинь и первые 300 иероглифов."),
    ("french", "Французский разговорный", CourseFormat.PAIR, "A1", "B1", 1200, False,
     "Мини-группы по 2–3 человека."),
]

TARIFFS = [
    ("Пробный урок", 1, 0, 14),
    ("Абонемент 8 занятий", 8, 7600, 90),
    ("Абонемент 16 занятий", 16, 14400, 120),
    ("Индивидуально 10 занятий", 10, 17000, 90),
]

OFFICES = [
    ("Центр на Обороны", "ул. Обороны, 3", "Красноярск", False),
    ("Емельяново", "ул. Московская, 178", "Емельяново", False),
    ("Онлайн", "Занятия по видеосвязи", "", True),
]

FAQS = [
    ("Как понять свой уровень?",
     "Пройдите бесплатный тест на сайте — 5 минут, и вы получите уровень по шкале CEFR "
     "с разбором по навыкам. Точный уровень подтвердим на пробном уроке."),
    ("Можно заниматься онлайн?",
     "Да. Онлайн-занятия идут в личном кабинете: ссылка на урок, материалы и домашние "
     "задания — всё в одном месте."),
    ("Что если я пропущу урок?",
     "Отменить без списания можно не позже чем за 12 часов до начала. Кнопка отмены — "
     "в расписании личного кабинета."),
    ("Есть ли пробное занятие?",
     "Да, первое занятие бесплатное. На нём преподаватель определяет уровень и предлагает программу."),
    ("Как оплачивать?",
     "Абонементами на 8 или 16 занятий. Баланс и история платежей видны в кабинете."),
]

PROMOS = [
    ("friend", "Приведи друга", "−20%", "Скидка 20% на следующий абонемент вам обоим",
     "Друг приходит на пробный урок и покупает абонемент — скидку получаете и вы, и он."),
    ("early", "Ранняя запись на осенний поток", "−15%", "Фиксируем цену до 31 августа", ""),
]


class Command(BaseCommand):
    help = "Наполняет каталог школы. Безопасно для боевого сервера: людей не создаёт."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-samples", action="store_true",
            help="Добавить примеры отзывов и акций. Без флага создаются только "
                 "языки, курсы, тарифы, офисы и вопросы-ответы.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        created = {"языков": 0, "курсов": 0, "тарифов": 0, "офисов": 0, "вопросов": 0}

        languages = {}
        for index, (name, slug, flag, pitch, glyph, color) in enumerate(LANGUAGES):
            languages[slug], new = Language.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "flag_code": flag, "short_pitch": pitch,
                          "glyph": glyph, "line_color": color, "sort_order": index * 10},
            )
            created["языков"] += new

        for index, (lang, title, fmt, low, high, price, featured, summary) in enumerate(COURSES):
            _, new = Course.objects.get_or_create(
                slug=f"{lang}-{fmt}-{index}",
                defaults={
                    "language": languages[lang], "title": title, "format": fmt,
                    "level_from": low, "level_to": high,
                    "price_per_lesson": Decimal(price), "is_featured": featured,
                    "summary": summary, "sort_order": index * 10,
                    "outcomes": "Свободно говорите на бытовые темы\n"
                                "Понимаете речь на слух\n"
                                "Пишете письма и сообщения без страха",
                },
            )
            created["курсов"] += new

        for name, lessons, price, days in TARIFFS:
            _, new = Tariff.objects.get_or_create(
                name=name,
                defaults={"lessons_count": lessons, "price": Decimal(price), "validity_days": days},
            )
            created["тарифов"] += new

        for name, address, city, online in OFFICES:
            _, new = Location.objects.get_or_create(
                name=name, defaults={"address": address, "city": city, "is_online": online},
            )
            created["офисов"] += new

        for question, answer in FAQS:
            _, new = FAQ.objects.get_or_create(question=question, defaults={"answer": answer})
            created["вопросов"] += new

        if options["with_samples"]:
            self._samples()

        summary = ", ".join(f"{name}: {count}" for name, count in created.items())
        self.stdout.write(self.style.SUCCESS(f"Создано — {summary}."))
        self.stdout.write(
            "Что уже было, не тронуто. Тексты и цены дальше правятся в админке: "
            "/admin/school/ и /admin/billing/tariff/."
        )

    def _samples(self):
        """Отзывы и акции — заглушки под замену, поэтому за флагом."""
        for author, role, text in [
            ("Екатерина М.", "мама ученицы, 9 лет",
             "Дочка бежит на занятия — это лучший отзыв, который я могу дать."),
            ("Артём К.", "B2, готовился к собеседованию",
             "Занимался индивидуально три месяца. Прошёл интервью — говорил спокойно."),
            ("Ирина С.", "разговорный клуб",
             "Наконец перестала бояться говорить. В клубе не страшно ошибаться."),
        ]:
            Review.objects.get_or_create(
                author_name=author, defaults={"author_role": role, "text": text}
            )

        for slug, title, badge, subtitle, description in PROMOS:
            Promo.objects.get_or_create(
                slug=slug,
                defaults={"title": title, "badge": badge, "subtitle": subtitle,
                          "description": description},
            )
        self.stdout.write("Добавлены примеры отзывов и акций — замените их своими.")
