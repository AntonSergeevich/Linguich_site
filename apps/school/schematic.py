"""Схема маршрутов для первого экрана главной.

Язык — линия, уровень CEFR — станция, цель ученика — конечная. Всё, что рисуется
на схеме, приходит отсюда и только из базы: если у школы нет открытого набора,
на линии не появится отметка, а не подставится красивая выдумка.
"""

from django.db.models import F, Q
from django.utils import formats, timezone

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
    adult = [c for c in courses if c.format != CourseFormat.KIDS] or courses
    starts = [i for i in (_index(c.level_from) for c in adult) if i is not None]
    ends = [i for i in (_index(c.level_to) for c in adult) if i is not None]
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


def _marks(groups, span, index_by_age=None):
    """Отметки живых наборов: расписание и число свободных мест."""
    marks = []
    for group in groups:
        if len(marks) >= MAX_MARKS_PER_LINE:
            break
        if index_by_age is not None:
            index = index_by_age.get(group.course.age_from)
        else:
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
        # Дата старта — половина ответа: «осталось два места» двигает сильнее,
        # когда видно, к какому числу. Нет даты — не выдумываем.
        starts = formats.date_format(group.starts_on, "j E") if group.starts_on else ""
        marks.append({
            "index": index,
            "starts": starts,
            "schedule": schedule,
            "seats": seats,
            "seats_word": plural_ru(seats, "место", "места", "мест"),
            "url": group.course.get_absolute_url(),
            "course": group.course.title,
        })
    return marks


def _kids_view(languages, courses_by_language, groups_by_language):
    """Детская схема: та же карта, но шкала — возраст, а не CEFR.

    Родитель приходит с «моему девять», а не с «у него A2», и мерить его
    ребёнка уровнями — значит заставлять переводить. Шкала строится из
    настоящих возрастов детских курсов: выдуманных ступеней тут нет.
    """
    kids_by_language = {}
    ages = set()
    for language_id, courses in courses_by_language.items():
        found = [
            course for course in courses
            if course.format == CourseFormat.KIDS and course.age_from and course.age_to
        ]
        if not found:
            continue
        kids_by_language[language_id] = found
        for course in found:
            ages.add(course.age_from)
            ages.add(course.age_to)

    if not kids_by_language:
        return None

    ladder = sorted(ages)
    index_of = {age: position for position, age in enumerate(ladder)}

    lines = []
    for position, language in enumerate(languages):
        courses = kids_by_language.get(language.id)
        if not courses:
            continue
        low = min(index_of[course.age_from] for course in courses)
        high = max(index_of[course.age_to] for course in courses)
        kids_ids = {course.id for course in courses}
        marks = _marks(
            [g for g in groups_by_language.get(language.id, []) if g.course_id in kids_ids],
            (low, high),
            index_by_age=index_of,
        )
        lines.append({
            "id": language.slug,
            "name": language.name,
            "url": language.get_absolute_url(),
            "color": language.color(position),
            "glyph": language.glyph_display,
            "from_index": low,
            "to_index": high,
            "levels_label": f"{ladder[low]}–{ladder[high]} лет",
            "branch": None,
            "marks": marks,
        })

    if not lines:
        return None
    return {
        "levels": [str(age) for age in ladder],
        "level_labels": [f"{age} {plural_ru(age, 'год', 'года', 'лет')}" for age in ladder],
        "axis_label": "Возраст",
        "lines": lines,
    }


def build_schematic(today=None):
    """Данные схемы: лестница уровней и линия на каждый язык школы."""
    today = today or timezone.localdate()

    languages = list(Language.objects.filter(is_active=True))
    courses_by_language = {}
    for course in Course.objects.filter(is_active=True).only(
        "language_id", "format", "level_from", "level_to", "age_from", "age_to", "title", "slug"
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
        if span:
            low, high = span
            label = ALL_LEVELS[low] if low == high else f"{ALL_LEVELS[low]} → {ALL_LEVELS[high]}"
        else:
            # Уровни у курсов не заполнены. Выкинуть язык со схемы нельзя:
            # вместе с ним пропадёт и открытый набор. Ставим одну станцию
            # и говорим прямо, что диапазон ещё не задан.
            low = high = 0
            label = "уровень уточняется"
        top = max(top, high)
        lines.append({
            "id": language.slug,
            "name": language.name,
            "url": language.get_absolute_url(),
            "color": language.color(position),
            "glyph": language.glyph_display,
            "from_index": low,
            "to_index": high,
            "levels_label": label,
            "branch": _exam_branch(courses, (low, high)),
            "marks": _marks(groups_by_language.get(language.id, []), (low, high)),
        })

    levels = ALL_LEVELS[: top + 1]
    return {
        "levels": levels,
        "level_labels": levels,
        "axis_label": "Уровень",
        "lines": lines,
        "kids": _kids_view(languages, courses_by_language, groups_by_language),
    }
