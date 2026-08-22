"""Схема маршрутов для первого экрана главной.

Язык — линия, уровень CEFR — станция, цель ученика — конечная. Всё, что рисуется
на схеме, приходит отсюда и только из базы: если у школы нет открытого набора,
на линии не появится отметка, а не подставится красивая выдумка.
"""

from django.db.models import F, Q
from django.utils import timezone

from apps.accounts.models import CEFR
from apps.scheduling.models import Group
from apps.utils import plural_ru

from .models import Course, CourseFormat, Language

# Лестница уровней на схеме. C2 школа не заявляет, поэтому ступень появляется
# только если какой-то курс до неё действительно доходит.
BASE_LEVELS = ["A0", "A1", "A2", "B1", "B2", "C1"]
ALL_LEVELS = [value for value, _label in CEFR.choices]

MAX_MARKS_PER_LINE = 2


def _index(level):
    """Порядковый номер уровня или None, если уровень не заполнен."""
    try:
        return ALL_LEVELS.index(level)
    except ValueError:
        return None


def _span(courses):
    """Границы линии: от самого низкого уровня курсов языка до самого высокого."""
    starts = [i for i in (_index(c.level_from) for c in courses) if i is not None]
    ends = [i for i in (_index(c.level_to) for c in courses) if i is not None]
    if not starts and not ends:
        return None
    low = min(starts) if starts else min(ends)
    high = max(ends) if ends else max(starts)
    return low, max(low, high)


def _exam_branch(courses, span):
    """Подготовка к экзамену — настоящая ветка линии, а не украшение."""
    exams = [c for c in courses if c.format == CourseFormat.EXAM]
    if not exams:
        return None
    branch = _span(exams)
    if not branch:
        return None
    low, high = branch
    if high <= low or low < span[0]:
        return None
    return {"from_index": low, "to_index": min(high, span[1]), "name": "Экзамен"}


def _marks(groups, span):
    """Отметки живых наборов: расписание и число свободных мест."""
    marks = []
    for group in groups:
        if len(marks) >= MAX_MARKS_PER_LINE:
            break
        index = _index(group.level)
        if index is None:
            index = _index(group.course.level_from)
        if index is None:
            index = span[0]
        index = min(max(index, span[0]), span[1])
        seats = group.seats_left
        if not seats:
            continue
        schedule = group.schedule_summary or "расписание уточняется"
        marks.append({
            "index": index,
            "schedule": schedule,
            "seats": seats,
            "seats_word": plural_ru(seats, "место", "места", "мест"),
            "url": group.course.get_absolute_url(),
            "course": group.course.title,
        })
    return marks


def build_schematic(today=None):
    """Данные схемы: лестница уровней и линия на каждый язык школы."""
    today = today or timezone.localdate()

    languages = list(Language.objects.filter(is_active=True))
    courses_by_language = {}
    for course in Course.objects.filter(is_active=True).only(
        "language_id", "format", "level_from", "level_to", "title", "slug"
    ):
        courses_by_language.setdefault(course.language_id, []).append(course)

    groups_by_language = {}
    # Набор открыт, если группа ещё не стартовала или дата старта пока не назначена.
    # Уже идущую группу школа не обещает: на схеме про неё не будет отметки.
    upcoming = (
        Group.objects.filter(is_active=True, course__is_active=True)
        .filter(Q(starts_on__gte=today) | Q(starts_on__isnull=True))
        .select_related("course", "course__language")
        .order_by(F("starts_on").asc(nulls_last=True))
    )
    for group in upcoming:
        groups_by_language.setdefault(group.course.language_id, []).append(group)

    lines = []
    top = len(BASE_LEVELS) - 1
    for position, language in enumerate(languages):
        courses = courses_by_language.get(language.id, [])
        if not courses:
            continue
        span = _span(courses)
        if not span:
            continue
        low, high = span
        top = max(top, high)
        label = ALL_LEVELS[low] if low == high else f"{ALL_LEVELS[low]} → {ALL_LEVELS[high]}"
        lines.append({
            "id": language.slug,
            "name": language.name,
            "url": language.get_absolute_url(),
            "color": language.color(position),
            "glyph": language.glyph_display,
            "from_index": low,
            "to_index": high,
            "levels_label": label,
            "branch": _exam_branch(courses, span),
            "marks": _marks(groups_by_language.get(language.id, []), span),
        })

    levels = ALL_LEVELS[: top + 1]
    return {"levels": levels, "lines": lines}
