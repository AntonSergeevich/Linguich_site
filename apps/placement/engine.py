"""Adaptive routing for the placement test.

The old test was ten fixed general-knowledge questions — it measured trivia, not
English. This one walks a CEFR ladder: four questions per level, then step up,
step down, or stop. A confident learner reaches C1 in ~12 questions; a beginner
is never made to grind through twenty items they cannot read.
"""

import random

from django.db.models import Q

from .models import LEVEL_LADDER, Question, TestAnswer

BLOCK_SIZE = 4          # questions per level before re-routing
MAX_QUESTIONS = 20
PASS_THRESHOLD = 0.75   # ≥3 из 4 — уровень взят, идём выше
FAIL_THRESHOLD = 0.25   # ≤1 из 4 — уровень не взят, идём ниже


def _stats(session, level):
    answers = session.answers.filter(question__level=level)
    total = answers.count()
    correct = answers.filter(is_correct=True).count()
    return total, correct


def next_question(session):
    """Pick the next question, or return None when the test is over."""
    if session.total_count >= MAX_QUESTIONS:
        return None

    level = session.current_level
    asked_ids = set(session.answers.values_list("question_id", flat=True))

    queryset = Question.objects.filter(level=level, is_active=True).exclude(pk__in=asked_ids)
    if session.language_id:
        # Вопросы без языка — общие, они годятся для любого теста.
        queryset = queryset.filter(Q(language=session.language) | Q(language__isnull=True))
    pool = list(queryset)
    if not pool:
        # Ран out of items at this level — try to move on rather than repeat.
        moved = _advance(session, force=True)
        return next_question(session) if moved else None

    # Разные навыки внутри блока: не даём подряд четыре одинаковых задания.
    recent_skills = list(
        session.answers.order_by("-answered_at").values_list("question__skill", flat=True)[:2]
    )
    fresh = [q for q in pool if q.skill not in recent_skills]
    return random.choice(fresh or pool)


def _advance(session, force=False):
    """Move up or down the ladder. Returns False when the test should end."""
    level = session.current_level
    total, correct = _stats(session, level)
    if not force and total < BLOCK_SIZE:
        return True  # block not finished, stay here

    ratio = correct / total if total else 0
    index = LEVEL_LADDER.index(level) if level in LEVEL_LADDER else 1
    visited = list(session.visited_levels or [])

    if ratio >= PASS_THRESHOLD:
        target = index + 1
    elif ratio <= FAIL_THRESHOLD:
        target = index - 1
    else:
        return False  # settled at this level

    if target < 0 or target >= len(LEVEL_LADDER):
        return False
    next_level = LEVEL_LADDER[target]
    if next_level in visited:
        return False  # already measured there — stop instead of oscillating

    visited.append(level)
    session.current_level = next_level
    session.visited_levels = visited
    session.save(update_fields=["current_level", "visited_levels"])
    return True


def register_answer(session, question, chosen_index, seconds=0):
    is_correct = chosen_index == question.correct_index
    TestAnswer.objects.get_or_create(
        session=session,
        question=question,
        defaults={"chosen_index": chosen_index, "is_correct": is_correct, "seconds_spent": min(seconds, 65535)},
    )
    session.total_count = session.answers.count()
    session.correct_count = session.answers.filter(is_correct=True).count()
    session.save(update_fields=["total_count", "correct_count"])

    total, _correct = _stats(session, session.current_level)
    keep_going = True
    if total >= BLOCK_SIZE:
        keep_going = _advance(session)
    return is_correct, keep_going


def final_level(session):
    """Highest level the learner actually cleared, with A0 as the floor."""
    best = None
    for level in LEVEL_LADDER:
        total, correct = _stats(session, level)
        if total and correct / total >= 0.5:
            best = level
    if best is None:
        return "A0"
    # Идеальный результат на потолке лестницы честно тянет на C2.
    if best == LEVEL_LADDER[-1]:
        total, correct = _stats(session, best)
        if total and correct == total:
            return "C2"
    return best
