"""Адаптивный тест уровня: лестница вверх/вниз и честный итоговый уровень."""

import json

from django.test import TestCase
from django.urls import reverse

from apps.school.models import Lead, LeadSource

from . import engine
from .models import LEVEL_LADDER, Question, Skill, TestSession


def make_bank(per_level=6):
    """Банк, где верный ответ всегда индекс 0 — так тест управляет исходом."""
    for level in LEVEL_LADDER:
        for index in range(per_level):
            Question.objects.create(
                level=level,
                skill=[Skill.GRAMMAR, Skill.VOCABULARY, Skill.READING, Skill.USAGE][index % 4],
                prompt=f"{level} вопрос {index}",
                options=["верно", "мимо", "мимо2", "мимо3"],
                correct_index=0,
                explanation="потому что",
            )


class EngineTests(TestCase):
    def setUp(self):
        make_bank()

    def play(self, answer_correctly, limit=40):
        """Прогоняет тест до конца. Возвращает (сессия, список уровней вопросов)."""
        session = TestSession.objects.create(current_level="A2")
        seen = []
        for _ in range(limit):
            question = engine.next_question(session)
            if question is None:
                break
            seen.append(question.level)
            chosen = question.correct_index if answer_correctly(question) else 3
            _correct, keep_going = engine.register_answer(session, question, chosen)
            if not keep_going:
                break
        session.result_level = engine.final_level(session)
        return session, seen

    def test_strong_learner_climbs_to_the_top(self):
        session, seen = self.play(lambda q: True)
        self.assertIn("C1", seen, "отличник должен дойти до верхней ступени")
        self.assertIn(session.result_level, ("C1", "C2"))

    def test_weak_learner_falls_to_the_floor_quickly(self):
        session, seen = self.play(lambda q: False)
        self.assertEqual(session.result_level, "A0")
        self.assertLess(
            session.total_count, engine.MAX_QUESTIONS,
            "новичку нельзя выдавать все 20 вопросов — он их просто не прочитает",
        )

    def test_learner_settles_on_the_level_they_half_pass(self):
        # Всё верно до B1 включительно, дальше мимо.
        def answer(question):
            return LEVEL_LADDER.index(question.level) <= LEVEL_LADDER.index("B1")

        session, _seen = self.play(answer)
        self.assertIn(session.result_level, ("B1", "B2"))

    def test_test_never_exceeds_the_cap(self):
        make_bank(per_level=30)
        session, _ = self.play(lambda q: q.level in ("A2", "B1"))
        self.assertLessEqual(session.total_count, engine.MAX_QUESTIONS)

    def test_questions_never_repeat(self):
        session, _ = self.play(lambda q: True)
        ids = list(session.answers.values_list("question_id", flat=True))
        self.assertEqual(len(ids), len(set(ids)))


class TestApiTests(TestCase):
    def setUp(self):
        make_bank()

    def test_full_run_over_http_returns_a_level_and_skill_breakdown(self):
        start = self.client.post(
            reverse("placement:start"), data="{}", content_type="application/json"
        )
        self.assertEqual(start.status_code, 200)
        payload = start.json()
        session_id = payload["session"]
        question = payload["question"]

        for _ in range(engine.MAX_QUESTIONS + 5):
            obj = Question.objects.get(pk=question["id"])
            response = self.client.post(
                reverse("placement:answer"),
                data=json.dumps({
                    "session": session_id, "question": obj.pk,
                    "chosen": obj.correct_index, "seconds": 3,
                }),
                content_type="application/json",
            )
            data = response.json()
            if data["finished"]:
                break
            question = data["question"]

        self.assertTrue(data["finished"])
        self.assertTrue(data["result"]["level"])
        self.assertTrue(data["result"]["skills"])
        self.assertTrue(all(0 <= row["percent"] <= 100 for row in data["result"]["skills"]))

    def test_someone_elses_session_cannot_be_answered(self):
        start = self.client.post(
            reverse("placement:start"), data="{}", content_type="application/json"
        ).json()
        other = self.client_class()
        question = Question.objects.get(pk=start["question"]["id"])
        response = other.post(
            reverse("placement:answer"),
            data=json.dumps({"session": start["session"], "question": question.pk, "chosen": 0}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_result_capture_creates_a_lead_with_the_level(self):
        start = self.client.post(
            reverse("placement:start"), data="{}", content_type="application/json"
        ).json()
        session = TestSession.objects.get(pk=start["session"])
        session.result_level = "B1"
        session.save(update_fields=["result_level"])

        response = self.client.post(reverse("placement:lead"), {
            "session": session.pk, "name": "Иван", "phone": "89130001111",
        })
        self.assertEqual(response.status_code, 200)
        lead = Lead.objects.get(name="Иван")
        self.assertEqual(lead.source, LeadSource.PLACEMENT_TEST)
        self.assertEqual(lead.placement_level, "B1")
        self.assertEqual(lead.phone, "+79130001111")

    def test_lead_capture_requires_contacts(self):
        start = self.client.post(
            reverse("placement:start"), data="{}", content_type="application/json"
        ).json()
        response = self.client.post(reverse("placement:lead"), {
            "session": start["session"], "name": "", "phone": "",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("fields", response.json())
