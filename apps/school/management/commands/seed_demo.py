# -*- coding: utf-8 -*-
"""Наполняет пустую базу демо-контентом: языки, курсы, преподаватели,
группы, ученики, платежи, домашки. Нужен, чтобы сайт и кабинеты можно было
показать заказчику до того, как заведены реальные данные.
"""

import random
from datetime import date, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import CEFR, Role, StudentProfile, StudentStatus, TeacherProfile, User
from apps.billing.models import Package, Payment, PaymentMethod, Tariff
from apps.learning.models import Assignment, Material, MaterialKind, Module, Program, Unit
from apps.scheduling.models import DeliveryMode, Enrollment, Group, RecurringSlot, TeacherAvailability
from apps.scheduling.services import generate_lessons
from apps.school.models import (
    FAQ,
    Course,
    CourseFormat,
    Language,
    Lead,
    LeadSource,
    LeadStatus,
    Location,
    Promo,
    Review,
    SiteSettings,
)

LANGUAGES = [
    ("Английский", "english", "gb", "Самый востребованный — от нуля до С1 и экзаменов."),
    ("Немецкий", "german", "de", "Учёба и работа в Германии, Австрии, Швейцарии."),
    ("Китайский", "chinese", "cn", "Иероглифы без страха и живая разговорная практика."),
    ("Французский", "french", "fr", "Язык, который приятно слышать в собственном исполнении."),
    ("Корейский", "korean", "kr", "От хангыля до сериалов без субтитров."),
    ("Турецкий", "turkish", "tr", "Быстрый старт для поездок и переезда."),
    ("Чешский", "czech", "cz", "Подготовка к учёбе в чешских вузах."),
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

TEACHERS = [
    ("Евгения", "Глухова", "owner@linguich.ru", "+79130000001", Role.OWNER,
     "Основатель школы · английский, методика", ["english"], 2011, False),
    ("Анна", "Соколова", "anna@linguich.ru", "+79130000002", Role.TEACHER,
     "Английский · подготовка к IELTS", ["english"], 2014, False),
    ("Дмитрий", "Верещагин", "dmitry@linguich.ru", "+79130000003", Role.TEACHER,
     "Немецкий · деловой язык", ["german"], 2016, False),
    ("Ли", "Вэй", "li@linguich.ru", "+79130000004", Role.TEACHER,
     "Китайский · носитель языка", ["chinese"], 2018, True),
]

STUDENTS = [
    ("Егор", "Тимофеев", "+79130001001", "B1"),
    ("Полина", "Крылова", "+79130001002", "A2"),
    ("Артём", "Носов", "+79130001003", "B2"),
    ("Софья", "Белова", "+79130001004", "A1"),
    ("Кирилл", "Данилов", "+79130001005", "B1"),
    ("Вероника", "Зайцева", "+79130001006", "A2"),
    ("Максим", "Орлов", "+79130001007", "C1"),
    ("Алиса", "Громова", "+79130001008", "A0"),
]


class Command(BaseCommand):
    help = "Заполняет базу демонстрационными данными."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="linguich2024",
                            help="Пароль для всех демо-аккаунтов.")

    @transaction.atomic
    def handle(self, *args, **options):
        password = options["password"]

        site = SiteSettings.load()
        site.notify_leads_to = "owner@linguich.ru"
        site.telegram_url = "https://t.me/linguich"
        site.vk_url = "https://vk.com/linguich"
        site.save()

        offices = [
            Location.objects.get_or_create(
                name="Центр на Обороны", defaults={"address": "ул. Обороны, 3", "city": "Красноярск"}
            )[0],
            Location.objects.get_or_create(
                name="Емельяново", defaults={"address": "ул. Московская, 178", "city": "Емельяново"}
            )[0],
            Location.objects.get_or_create(
                name="Онлайн", defaults={"address": "Занятия по видеосвязи", "is_online": True}
            )[0],
        ]

        languages = {}
        for index, (name, slug, flag, pitch) in enumerate(LANGUAGES):
            languages[slug] = Language.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "flag_code": flag, "short_pitch": pitch, "sort_order": index * 10},
            )[0]

        courses = {}
        for index, (lang, title, fmt, lv_from, lv_to, price, featured, summary) in enumerate(COURSES):
            slug = f"{lang}-{fmt}-{index}"
            courses[slug] = Course.objects.get_or_create(
                slug=slug,
                defaults={
                    "language": languages[lang], "title": title, "format": fmt,
                    "level_from": lv_from, "level_to": lv_to, "price_per_lesson": Decimal(price),
                    "is_featured": featured, "summary": summary, "sort_order": index * 10,
                    "outcomes": "Свободно говорите на бытовые темы\nПонимаете речь на слух\n"
                                "Пишете письма и сообщения без страха",
                },
            )[0]

        teachers = []
        for first, last, email, phone, role, headline, langs, since, native in TEACHERS:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={"first_name": first, "last_name": last, "phone": phone, "role": role,
                          "is_staff": role == Role.OWNER, "is_superuser": role == Role.OWNER},
            )
            if created:
                user.set_password(password)
                user.save()
            profile, _ = TeacherProfile.objects.get_or_create(
                user=user,
                defaults={"headline": headline, "experience_since": since, "is_native": native,
                          "pay_rate": Decimal("700"),
                          "bio": "Верю, что язык учат разговором, а не зубрёжкой правил. "
                                 "На занятиях много практики и мало теории ради теории."},
            )
            profile.languages.set([languages[code] for code in langs])
            teachers.append(user)

            for weekday in (0, 2, 4):
                TeacherAvailability.objects.get_or_create(
                    teacher=user, weekday=weekday, start_time=time(16, 0),
                    defaults={"end_time": time(20, 0), "slot_minutes": 60, "mode": DeliveryMode.ONLINE},
                )

        students = []
        for first, last, phone, level in STUDENTS:
            user, created = User.objects.get_or_create(
                phone=phone,
                defaults={"first_name": first, "last_name": last, "role": Role.STUDENT,
                          "email": f"{phone[1:]}@demo.linguich.ru"},
            )
            if created:
                user.set_password(password)
                user.save()
            StudentProfile.objects.get_or_create(
                user=user,
                defaults={"level": level, "status": StudentStatus.ACTIVE,
                          "goal": "Свободно говорить в поездках и на работе.",
                          "started_at": timezone.localdate() - timedelta(days=random.randint(30, 400))},
            )
            students.append(user)

        tariffs = []
        for name, lessons, price in [
            ("Пробный урок", 1, 0), ("Абонемент 8 занятий", 8, 7600),
            ("Абонемент 16 занятий", 16, 14400), ("Индивидуально 10 занятий", 10, 17000),
        ]:
            tariffs.append(Tariff.objects.get_or_create(
                name=name, defaults={"lessons_count": lessons, "price": Decimal(price),
                                     "validity_days": 90 if lessons > 1 else 14},
            )[0])

        program = Program.objects.get_or_create(
            title="General English A2 → B1",
            defaults={"language": languages["english"], "level": CEFR.B1, "author": teachers[0],
                      "description": "Годовая программа: от бытовых тем к свободному разговору."},
        )[0]
        if not program.modules.exists():
            for module_index, (module_title, units) in enumerate([
                ("Everyday life", ["Daily routine", "Food and eating out", "Shopping and money"]),
                ("Travel", ["At the airport", "Hotels and directions", "Telling a travel story"]),
                ("Work and study", ["Talking about your job", "Emails and messages", "Job interview basics"]),
            ], start=1):
                module = Module.objects.create(program=program, title=module_title, order=module_index)
                for unit_index, unit_title in enumerate(units, start=1):
                    unit = Unit.objects.create(
                        module=module, title=unit_title, order=unit_index,
                        objectives="Освоить активную лексику темы\nОтработать грамматику в речи\n"
                                   "Провести диалог без подготовки",
                        content="Разминка · лексика · грамматика в контексте · парная практика · вывод.",
                        vocabulary="commute — добираться до работы\nrun late — опаздывать\n"
                                   "grab a bite — перекусить",
                    )
                    Material.objects.create(
                        unit=unit, title="Рабочий лист", kind=MaterialKind.LINK,
                        url="https://example.com/worksheet", uploaded_by=teachers[0],
                    )

        groups = []
        for index, (course_key, teacher, name, level) in enumerate([
            (list(courses)[0], teachers[1], "Английский с нуля · вечерняя", "A1"),
            (list(courses)[1], teachers[0], "Speaking Club B1+", "B1"),
            (list(courses)[6], teachers[3], "Китайский с нуля · дневная", "A1"),
        ]):
            group, created = Group.objects.get_or_create(
                name=name,
                defaults={"course": courses[course_key], "teacher": teacher, "capacity": 8,
                          "level": level, "location": offices[0], "mode": DeliveryMode.OFFLINE,
                          "program": program if index == 0 else None,
                          "starts_on": timezone.localdate() - timedelta(days=14)},
            )
            if created:
                for weekday, hour in [(1, 18), (3, 18)] if index == 0 else [(2, 19)] if index == 1 else [(0, 17), (4, 17)]:
                    RecurringSlot.objects.create(group=group, weekday=weekday, start_time=time(hour, 0))
            groups.append(group)

        for position, student in enumerate(students):
            group = groups[position % len(groups)]
            enrollment, _ = Enrollment.objects.get_or_create(student=student, group=group)
            package = Package.objects.get_or_create(
                student=student, tariff=tariffs[1],
                defaults={"lessons_total": 8, "price": tariffs[1].price,
                          "issued_on": timezone.localdate() - timedelta(days=20)},
            )[0]
            # Часть учеников оставляем должниками — CRM должна это показывать.
            if position % 3 != 0:
                Payment.objects.get_or_create(
                    student=student, package=package,
                    defaults={"amount": package.price, "method": PaymentMethod.CARD,
                              "paid_on": timezone.localdate() - timedelta(days=19)},
                )

        created_lessons = generate_lessons(weeks=4)

        assignment = Assignment.objects.get_or_create(
            title="Расскажите про свой обычный день",
            defaults={"teacher": teachers[0], "group": groups[0],
                      "description": "Напишите 8–10 предложений в Present Simple. "
                                     "Используйте не меньше пяти слов из юнита.",
                      "due_at": timezone.now() + timedelta(days=3), "max_score": 10},
        )[0]
        assignment.assign_to([e.student for e in groups[0].active_enrollments])

        for name, phone, source, status in [
            ("Ольга", "+79130002001", LeadSource.TRIAL_FORM, LeadStatus.NEW),
            ("Иван", "+79130002002", LeadSource.PLACEMENT_TEST, LeadStatus.IN_PROGRESS),
            ("Наталья", "+79130002003", LeadSource.CALLBACK, LeadStatus.SCHEDULED),
            ("Сергей", "+79130002004", LeadSource.COURSE_PAGE, LeadStatus.WON),
        ]:
            Lead.objects.get_or_create(
                phone=phone,
                defaults={"name": name, "source": source, "status": status,
                          "language": languages["english"]},
            )

        for author, role, text in [
            ("Екатерина М.", "мама ученицы, 9 лет", "Дочка бежит на занятия — это лучший отзыв, который я могу дать. "
                                                    "За год от «не понимаю ничего» до диалогов с преподавателем."),
            ("Артём К.", "B2, готовился к собеседованию", "Занимался индивидуально три месяца. "
                                                          "Прошёл интервью в международную команду — говорил спокойно."),
            ("Ирина С.", "разговорный клуб", "Наконец перестала бояться говорить. В клубе не страшно ошибаться."),
        ]:
            Review.objects.get_or_create(author_name=author, defaults={"author_role": role, "text": text})

        for question, answer in [
            ("Как понять свой уровень?", "Пройдите бесплатный тест на сайте — 5 минут, и вы получите уровень "
                                         "по шкале CEFR с разбором по навыкам. Точный уровень подтвердим на пробном уроке."),
            ("Можно заниматься онлайн?", "Да. Онлайн-занятия идут в личном кабинете: ссылка на урок, материалы "
                                         "и домашние задания — всё в одном месте."),
            ("Что если я пропущу урок?", "Отменить без списания можно не позже чем за 12 часов до начала. "
                                         "Кнопка отмены — в расписании личного кабинета."),
            ("Есть ли пробное занятие?", "Да, первое занятие бесплатное. На нём преподаватель определяет уровень "
                                         "и предлагает программу."),
            ("Как оплачивать?", "Абонементами на 8 или 16 занятий. Баланс и история платежей видны в кабинете."),
        ]:
            FAQ.objects.get_or_create(question=question, defaults={"answer": answer})

        Promo.objects.get_or_create(
            slug="friend",
            defaults={"title": "Приведи друга", "badge": "−20%",
                      "subtitle": "Скидка 20% на следующий абонемент вам обоим",
                      "description": "Друг приходит на пробный урок и покупает абонемент — "
                                     "скидку получаете и вы, и он."},
        )
        Promo.objects.get_or_create(
            slug="early",
            defaults={"title": "Ранняя запись на осенний поток", "badge": "−15%",
                      "subtitle": "Фиксируем цену до 31 августа"},
        )

        self.stdout.write(self.style.SUCCESS(
            f"Готово. Преподавателей: {len(teachers)}, учеников: {len(students)}, "
            f"групп: {len(groups)}, занятий создано: {created_lessons}.\n"
            f"Вход владельца: owner@linguich.ru / {password}"
        ))
