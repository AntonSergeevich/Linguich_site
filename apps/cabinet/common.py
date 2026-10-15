"""Shared cabinet plumbing: navigation and the small counters it badges."""

from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.accounts.models import Role
from apps.learning.models import Submission, SubmissionStatus
from apps.notifications.models import Notification, Status
from apps.scheduling.models import LessonStatus
from apps.school.models import Lead, LeadStatus


def unread_count(user):
    return (
        Notification.objects.filter(recipient=user, channel="inapp", read_at__isnull=True)
        .exclude(status=Status.SKIPPED)
        .count()
    )


def _account_group(user):
    return ("Аккаунт", [
        ("cabinet:notifications", "Уведомления", "i-bell", unread_count(user)),
        ("accounts:profile", "Профиль", "i-user", 0),
    ])


def student_nav(user):
    open_homework = user.submissions.filter(
        status__in=[SubmissionStatus.ASSIGNED, SubmissionStatus.REDO]
    ).count()
    return [
        (None, [
            ("cabinet:home", "Обзор", "i-home", 0),
            ("cabinet:schedule", "Расписание", "i-calendar", 0),
            ("cabinet:homework", "Домашние задания", "i-book", open_homework),
            ("cabinet:program", "Моя программа", "i-globe", 0),
            ("cabinet:book", "Записаться на урок", "i-plus", 0),
        ]),
        ("Аккаунт", [
            ("cabinet:payments", "Оплаты и абонемент", "i-card", 0),
            ("cabinet:notifications", "Уведомления", "i-bell", unread_count(user)),
            ("accounts:profile", "Профиль", "i-user", 0),
        ]),
    ]


def _teaching_items(user):
    pending = Submission.objects.filter(
        assignment__teacher=user, status=SubmissionStatus.SUBMITTED
    ).count()
    # Считаем не «непроведённые» — их теперь закрывает автоотметка, — а те,
    # что отметились сами и никто на них не взглянул: только там и может
    # прятаться ошибка.
    unconfirmed = user.lessons_taught.filter(
        status=LessonStatus.COMPLETED, completed_by__isnull=True
    ).count()
    return [
        ("cabinet:teacher_schedule", "Расписание и журнал", "i-calendar", unconfirmed),
        ("cabinet:teacher_students", "Мои ученики", "i-users", 0),
        ("cabinet:teacher_review", "Проверка работ", "i-check", pending),
        ("cabinet:teacher_programs", "Программы и материалы", "i-book", 0),
        ("cabinet:teacher_availability", "Окна для записи", "i-clock", 0),
    ]


def teacher_nav(user):
    return [
        (None, [("cabinet:teacher_home", "Обзор", "i-home", 0)] + _teaching_items(user)),
        _account_group(user),
    ]


def _school_items(include_staff):
    """Разделы CRM. Состав сотрудников — только владелице."""
    new_leads = Lead.objects.filter(status=LeadStatus.NEW).count()
    items = [
        ("cabinet:crm_home", "Сводка", "i-chart", 0),
        ("cabinet:crm_leads", "Заявки", "i-inbox", new_leads),
        ("cabinet:crm_schedule", "Расписание школы", "i-calendar", 0),
        ("cabinet:crm_students", "Ученики", "i-users", 0),
        ("cabinet:crm_payments", "Платежи и долги", "i-card", 0),
        ("cabinet:crm_groups", "Группы", "i-users", 0),
    ]
    if include_staff:
        items.append(("cabinet:crm_staff", "Сотрудники", "i-user", 0))
    return items


def admin_nav(user):
    """Администратор ведёт школу, но не преподаёт и не видит зарплат."""
    return [("Школа", _school_items(include_staff=False)), _account_group(user)]


def owner_nav(user):
    """The owner runs the school *and* teaches, so she gets both toolsets —
    business first, her own lessons second."""
    return [
        ("Школа", _school_items(include_staff=True)),
        ("Моё преподавание", _teaching_items(user)),
        _account_group(user),
    ]


# Нижняя панель на телефоне: четыре раздела, ради которых в кабинет
# заходят каждый день, — без бургера и второго касания. Остальное — под
# пятой кнопкой «Меню», которая открывает то же боковое меню.
TABS = {
    "student": [
        ("cabinet:home", "Главная"),
        ("cabinet:schedule", "Расписание"),
        ("cabinet:homework", "Задания"),
        ("cabinet:payments", "Оплата"),
    ],
    "teacher": [
        ("cabinet:teacher_home", "Обзор"),
        ("cabinet:teacher_schedule", "Журнал"),
        ("cabinet:teacher_review", "Проверка"),
        ("cabinet:teacher_students", "Ученики"),
    ],
    "school": [
        ("cabinet:crm_home", "Сводка"),
        ("cabinet:crm_leads", "Заявки"),
        ("cabinet:crm_schedule", "Расписание"),
        ("cabinet:crm_payments", "Оплаты"),
    ],
}


def tabs_for(user, nav_groups, path):
    """Вкладки нижней панели и сумма счётчиков всего, что в неё не попало.

    Счётчики берём из уже собранного меню — второй раз в базу не ходим.
    Активной считается вкладка с самым длинным адресом-префиксом текущей
    страницы: карточка ученика подсвечивает «Ученики», а не «Главную»."""
    from django.urls import reverse

    if user.is_manager:
        picks = TABS["school"]
    elif user.is_teacher:
        picks = TABS["teacher"]
    else:
        picks = TABS["student"]

    items = {url_name: (icon, count) for _, group in nav_groups for url_name, _, icon, count in group}
    tabs = []
    for url_name, label in picks:
        icon, count = items.get(url_name, ("i-home", 0))
        tabs.append({"url_name": url_name, "href": reverse(url_name), "label": label,
                     "icon": icon, "count": count, "active": False})

    matches = [tab for tab in tabs if path == tab["href"] or (path.startswith(tab["href"]) and tab["href"].count("/") > 2)]
    if matches:
        max(matches, key=lambda tab: len(tab["href"]))["active"] = True

    in_tabs = {tab["url_name"] for tab in tabs}
    rest = sum(count for url_name, (_, count) in items.items() if url_name not in in_tabs)
    return tabs, rest


def nav_for(user):
    if user.is_owner:
        return owner_nav(user)
    if user.role == Role.ADMIN:
        return admin_nav(user)
    if user.is_teacher:
        return teacher_nav(user)
    return student_nav(user)


def cabinet_context(request, **extra):
    nav_groups = nav_for(request.user)
    tabs, tabs_rest = tabs_for(request.user, nav_groups, request.path)
    context = {"nav_groups": nav_groups, "unread": unread_count(request.user),
               "tabs": tabs, "tabs_rest": tabs_rest}
    context.update(extra)
    return context


def week_bounds(offset=0):
    """Monday..Sunday of the week ``offset`` weeks from now, in local dates."""
    today = timezone.localdate() + timedelta(weeks=offset)
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=7)


def as_datetime_range(start_date, end_date):
    """Local dates -> aware datetimes covering [start, end)."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(start_date, time.min), tz)
    end = timezone.make_aware(datetime.combine(end_date, time.min), tz)
    return start, end
