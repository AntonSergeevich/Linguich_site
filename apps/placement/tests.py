"""Адаптивный тест уровня: лестница вверх/вниз и честный итоговый уровень."""

import json

from django.test import TestCase
from django.urls import reverse

from apps.school.models import Language, Lead, LeadSource

from . import engine
from .models import LEVEL_LADDER, Question, Skill, TestSession


def make_bank(per_level=6, language=None, levels=None):
    """Банк, где верный ответ всегда индекс 0 — так тест управляет исходом."""
    for level in levels or LEVEL_LADDER:
        for index in range(per_level):
            Question.objects.create(
                language=language,
                level=level,
                skill=[Skill.GRAMMAR, Skill.VOCABULARY, Skill.READING, Skill.USAGE][index % 4],
                prompt=f"{language.slug if language else 'общий'} {level} вопрос {index}",
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
        self.language = Language.objects.create(name="Английский", slug="english")
        make_bank(language=self.language)

    def begin(self, language=None):
        return self.client.post(
            reverse("placement:start"),
            data=json.dumps({"language": (language or self.language).pk}),
            content_type="application/json",
        )

    def test_full_run_over_http_returns_a_level_and_skill_breakdown(self):
        start = self.begin()
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
        start = self.begin().json()
        other = self.client_class()
        question = Question.objects.get(pk=start["question"]["id"])
        response = other.post(
            reverse("placement:answer"),
            data=json.dumps({"session": start["session"], "question": question.pk, "chosen": 0}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_result_capture_creates_a_lead_with_the_level(self):
        start = self.begin().json()
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
        start = self.begin().json()
        response = self.client.post(reverse("placement:lead"), {
            "session": start["session"], "name": "", "phone": "",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("fields", response.json())


class LanguageBankTests(TestCase):
    """Школа учит семи языкам, а тест спрашивал по-английски всех.

    Причина была не в вопросах, а в том, что язык сессии никогда не
    выставлялся: движок брал «общие» вопросы, а общими оказались
    английские — единственные, что существовали.
    """

    def setUp(self):
        self.english = Language.objects.create(name="Английский", slug="english", sort_order=1)
        self.german = Language.objects.create(name="Немецкий", slug="german", sort_order=2)
        self.korean = Language.objects.create(name="Корейский", slug="korean", sort_order=3)
        make_bank(language=self.english)
        make_bank(language=self.german, levels=["A1", "A2"])

    def begin(self, language):
        return self.client.post(
            reverse("placement:start"),
            data=json.dumps({"language": language.pk if language else None}),
            content_type="application/json",
        )

    def test_the_test_cannot_start_without_a_language(self):
        response = self.begin(None)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(TestSession.objects.exists())

    def test_a_german_test_never_asks_an_english_question(self):
        payload = self.begin(self.german).json()
        session = TestSession.objects.get(pk=payload["session"])
        for _ in range(engine.MAX_QUESTIONS):
            question = engine.next_question(session)
            if question is None:
                break
            self.assertEqual(question.language_id, self.german.pk, question.prompt)
            engine.register_answer(session, question, question.correct_index, 3)

    def test_a_language_without_a_bank_is_not_offered(self):
        """Предложить тест и упереться в «вопросов нет» хуже, чем честно
        позвать на пробный урок."""
        offered = [language.pk for language in engine.languages_with_bank()]
        self.assertIn(self.english.pk, offered)
        self.assertNotIn(self.korean.pk, offered)

        response = self.client.get(reverse("placement:test"))
        self.assertContains(response, "Немецкий")
        self.assertContains(response, "корейский")  # в строке «тест ещё готовим»

    def test_starting_a_language_without_questions_is_refused_politely(self):
        response = self.begin(self.korean)
        self.assertEqual(response.status_code, 503)
        self.assertIn("бесплатном уроке", response.json()["error"])

    def test_the_ceiling_of_a_partial_bank_is_reported(self):
        """Показать «ваш уровень A2» тому, кто читает B2, и промолчать о том,
        что выше не спрашивали, — это соврать."""
        self.assertEqual(engine.bank_ceiling(self.german), "A2")
        self.assertEqual(engine.bank_ceiling(self.english), "C1")

    def test_the_result_carries_the_ceiling_to_the_screen(self):
        payload = self.begin(self.german).json()
        question = payload["question"]
        data = {}
        for _ in range(engine.MAX_QUESTIONS + 5):
            obj = Question.objects.get(pk=question["id"])
            data = self.client.post(
                reverse("placement:answer"),
                data=json.dumps({
                    "session": payload["session"], "question": obj.pk,
                    "chosen": obj.correct_index, "seconds": 2,
                }),
                content_type="application/json",
            ).json()
            if data["finished"]:
                break
            question = data["question"]
        self.assertEqual(data["result"]["ceiling"], "A2")
        self.assertEqual(data["result"]["language"], "Немецкий")


class ShippedBanksTests(TestCase):
    """Стартовые банки грузятся и не разъезжаются с каталогом языков."""

    def test_every_bank_matches_a_language_and_has_valid_keys(self):
        from .banks import BANKS

        for slug, bank in BANKS.items():
            with self.subTest(language=slug):
                self.assertTrue(bank, "пустой банк никому не нужен")
                for level, _skill, prompt, _hint, options, correct, _why in bank:
                    self.assertIn(level, LEVEL_LADDER, prompt)
                    self.assertGreaterEqual(len(options), 2, prompt)
                    self.assertTrue(
                        0 <= correct < len(options),
                        f"верный вариант вне списка: {prompt}",
                    )
                    self.assertEqual(len(options), len(set(options)), f"дубли вариантов: {prompt}")

    def test_the_loader_attaches_questions_to_their_language(self):
        from django.core.management import call_command

        Language.objects.create(name="Немецкий", slug="german")
        Language.objects.create(name="Английский", slug="english")
        call_command("load_placement_questions", verbosity=0)

        german = Question.objects.filter(language__slug="german")
        self.assertTrue(german.exists())
        self.assertFalse(
            Question.objects.filter(language__isnull=True).exists(),
            "вопрос без языка снова станет «общим» и попадёт в чужой тест",
        )


class QuizInterfaceTests(TestCase):
    """Мелочи интерфейса, которые ломают доверие к тесту целиком."""

    def setUp(self):
        self.language = Language.objects.create(name="Английский", slug="english")
        make_bank(language=self.language)

    def test_the_page_sets_the_csrf_cookie(self):
        """Регрессия: на странице теста нет ни одной формы, поэтому Django не
        ставил cookie. Кто заходил на тест напрямую, получал 403 на «Начать»."""
        response = self.client.get(reverse("placement:test"))
        self.assertIn("csrftoken", response.cookies)

    def test_hover_on_answers_is_limited_to_a_real_pointer(self):
        """Регрессия с телефона: на тач-экране браузер оставляет «залипший»
        ховер на месте последнего касания. Вопрос перерисовывается целиком,
        и подсветка садилась на кнопку с тем же номером в новом вопросе —
        человек читал её как подсказку правильного ответа."""
        from django.conf import settings

        css = (settings.BASE_DIR / "static" / "css" / "site.css").read_text(encoding="utf-8")

        guarded = []
        cursor = 0
        while True:
            opened = css.find("@media (hover: hover)", cursor)
            if opened == -1:
                break
            # Границы блока считаем по скобкам: искать закрывающую по тексту
            # нельзя, внутри вложены собственные правила.
            depth, index = 0, css.index("{", opened)
            while index < len(css):
                if css[index] == "{":
                    depth += 1
                elif css[index] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                index += 1
            guarded.append((opened, index))
            cursor = index

        cursor = 0
        while True:
            hit = css.find(".quiz-option:hover", cursor)
            if hit == -1:
                break
            inside = any(start < hit < end for start, end in guarded)
            self.assertTrue(
                inside,
                "правило :hover для ответа должно жить внутри @media (hover: hover), "
                f"иначе на телефоне подсветка переезжает на следующий вопрос (позиция {hit})",
            )
            cursor = hit + 1
