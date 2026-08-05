# -*- coding: utf-8 -*-
"""Банк вопросов для адаптивного теста.

Каждый уровень — своя связка навыков, чтобы результат опирался не только
на грамматику. Команда идемпотентна: вопросы матчатся по тексту.
"""

from django.core.management.base import BaseCommand

from apps.placement.models import Question, Skill

G, V, R, U = Skill.GRAMMAR, Skill.VOCABULARY, Skill.READING, Skill.USAGE

QUESTIONS = [
    # ---------------- A1 ----------------
    ("A1", G, "She ____ a doctor.", "", ["am", "is", "are", "be"], 1, "3-е лицо ед. ч. — is."),
    ("A1", G, "I ____ like coffee.", "", ["doesn't", "am not", "don't", "not"], 2, "С I — don't."),
    ("A1", G, "There ____ two windows in the room.", "", ["is", "are", "be", "was"], 1, "Множественное число — are."),
    ("A1", V, "The opposite of «cheap» is ____.", "", ["expensive", "quiet", "heavy", "early"], 0, ""),
    ("A1", V, "You keep money in a ____.", "", ["bakery", "library", "wallet", "kitchen"], 2, ""),
    ("A1", U, "— How are you? — ____", "", ["I'm 20.", "Fine, thanks.", "Yes, please.", "It's Monday."], 1, ""),
    ("A1", U, "In a shop you say: «____ much is it?»", "", ["What", "How", "Which", "Where"], 1, ""),
    ("A1", G, "My brother ____ football every Sunday.", "", ["play", "plays", "playing", "is play"], 1, ""),
    ("A1", V, "Monday, Tuesday, ____, Thursday.", "", ["Sunday", "Friday", "Wednesday", "Saturday"], 2, ""),
    ("A1", R, "«The café opens at 8 a.m. and closes at 6 p.m.» Can you have dinner there at 8 p.m.?",
     "", ["Yes, always", "No, it is closed", "Only at weekends", "The text does not say"], 1, ""),

    # ---------------- A2 ----------------
    ("A2", G, "I ____ to London last summer.", "", ["go", "have gone", "went", "was going"], 2,
     "Past Simple: есть маркер last summer."),
    ("A2", G, "She is ____ than her sister.", "", ["tall", "taller", "tallest", "more tall"], 1, ""),
    ("A2", G, "We ____ watch TV yesterday evening.", "", ["didn't", "don't", "weren't", "haven't"], 0, ""),
    ("A2", G, "If it rains, we ____ at home.", "", ["stayed", "will stay", "would stay", "stay"], 1,
     "Первый тип условных: will + инфинитив."),
    ("A2", V, "I'm looking ____ my keys — I can't find them.", "", ["at", "for", "after", "up"], 1, ""),
    ("A2", V, "A person who cooks in a restaurant is a ____.", "", ["waiter", "chef", "clerk", "driver"], 1, ""),
    ("A2", U, "— Would you like some tea? — ____", "", ["Yes, I would like.", "Yes, please.", "Yes, I like.", "No, thanks you."], 1, ""),
    ("A2", G, "There isn't ____ milk in the fridge.", "", ["some", "many", "any", "a"], 2, ""),
    ("A2", R, "«Trains to Moscow leave every hour except on Sundays.» How often do trains run on Sunday?",
     "", ["Every hour", "They don't run", "Twice a day", "Every two hours"], 1, ""),
    ("A2", V, "It was a ____ film — I laughed all the time.", "", ["boring", "funny", "scary", "serious"], 1, ""),

    # ---------------- B1 ----------------
    ("B1", G, "I ____ here since 2019.", "", ["work", "worked", "have worked", "am working"], 2,
     "since + Present Perfect."),
    ("B1", G, "She said she ____ tired.", "", ["is", "was", "will be", "has been"], 1, "Согласование времён."),
    ("B1", G, "The house ____ in 1890.", "", ["built", "was built", "has built", "is building"], 1,
     "Пассивный залог в прошедшем."),
    ("B1", G, "If I ____ more time, I would travel more.", "", ["have", "had", "will have", "would have"], 1,
     "Второй тип условных."),
    ("B1", V, "I can't ____ to buy a new laptop this year.", "", ["afford", "allow", "manage", "spend"], 0, ""),
    ("B1", V, "The meeting was put ____ until next week.", "", ["out", "off", "on", "up"], 1,
     "put off = отложить."),
    ("B1", U, "Your colleague made a mistake. The most polite reply is:",
     "", ["You're wrong.", "That's a stupid idea.", "I see your point, but maybe we could try another way.",
          "Do it again."], 2, ""),
    ("B1", G, "He's used to ____ early.", "", ["get up", "getting up", "got up", "gets up"], 1,
     "be used to + -ing."),
    ("B1", R, "«Although the price has risen, sales remain strong.» What does the sentence say?",
     "", ["Sales fell because of the price", "Sales are good despite the higher price",
          "The price did not change", "Sales stopped"], 1, ""),
    ("B1", V, "She has a good ____ of humour.", "", ["feeling", "sense", "mind", "way"], 1, ""),

    # ---------------- B2 ----------------
    ("B2", G, "By the time we arrived, the film ____.", "", ["started", "has started", "had started", "was starting"], 2,
     "Past Perfect для более раннего действия."),
    ("B2", G, "I'd rather you ____ smoke here.", "", ["don't", "didn't", "won't", "not"], 1,
     "would rather + past subjunctive."),
    ("B2", G, "Not only ____ late, but he also forgot the documents.",
     "", ["he was", "was he", "he is", "is he"], 1, "Инверсия после not only."),
    ("B2", G, "The report needs ____ before Friday.", "", ["finish", "to finishing", "finishing", "finished"], 2,
     "need + -ing = пассивное значение."),
    ("B2", V, "The new policy will come into ____ next month.", "", ["effect", "action", "power", "work"], 0, ""),
    ("B2", V, "His argument doesn't really hold ____.", "", ["water", "air", "ground", "weight"], 0, ""),
    ("B2", U, "In a job interview, «I'm a bit of a perfectionist» is usually meant as:",
     "", ["a complaint", "a joke", "a soft way to name a weakness", "a criticism of the company"], 2, ""),
    ("B2", G, "Had I known about the delay, I ____ earlier.",
     "", ["would leave", "will leave", "would have left", "had left"], 2, "Третий тип условных с инверсией."),
    ("B2", R, "«The findings, while preliminary, suggest a causal link.» The author is:",
     "", ["certain of the link", "cautiously suggesting a link", "denying any link", "quoting someone else"], 1, ""),
    ("B2", V, "She was ____ over for promotion again.", "", ["passed", "put", "taken", "gone"], 0, ""),

    # ---------------- C1 ----------------
    ("C1", G, "Rarely ____ such a compelling argument.",
     "", ["I have heard", "have I heard", "I heard", "did I heard"], 1, "Инверсия после rarely."),
    ("C1", G, "It's high time we ____ this problem seriously.",
     "", ["take", "took", "have taken", "will take"], 1, "It's high time + past."),
    ("C1", G, "He denied ____ anything about the incident.",
     "", ["to know", "knowing", "know", "known"], 1, "deny + -ing."),
    ("C1", V, "The government was accused of ____ the issue.",
     "", ["glossing over", "glancing at", "leaning on", "brushing up"], 0, "gloss over = замалчивать."),
    ("C1", V, "Her success was a ____ conclusion from the start.",
     "", ["foregone", "forlorn", "forward", "forgotten"], 0, "foregone conclusion = предрешённый исход."),
    ("C1", U, "«With all due respect, I must disagree» in a meeting signals:",
     "", ["full agreement", "polite but firm opposition", "confusion", "an apology"], 1, ""),
    ("C1", G, "____ for your support, the project would have failed.",
     "", ["If not", "Were it not", "Had not it", "Unless"], 1, ""),
    ("C1", R, "«The policy is, at best, a stopgap.» The writer thinks the policy is:",
     "", ["excellent", "a temporary fix", "dangerous", "too expensive"], 1, ""),
    ("C1", V, "The two accounts of the event are hard to ____.",
     "", ["reconcile", "reconsider", "recollect", "recommend"], 0, ""),
    ("C1", G, "Little ____ that the decision would change everything.",
     "", ["she knew", "did she know", "she did know", "knew she"], 1, ""),
]


class Command(BaseCommand):
    help = "Загружает банк вопросов теста уровня английского."

    def handle(self, *args, **options):
        created = updated = 0
        for level, skill, prompt, hint, options_list, correct, explanation in QUESTIONS:
            obj, was_created = Question.objects.update_or_create(
                prompt=prompt,
                defaults={
                    "level": level,
                    "skill": skill,
                    "hint": hint,
                    "options": options_list,
                    "correct_index": correct,
                    "explanation": explanation,
                    "is_active": True,
                },
            )
            created += was_created
            updated += not was_created
        self.stdout.write(self.style.SUCCESS(f"вопросов добавлено {created}, обновлено {updated}"))
