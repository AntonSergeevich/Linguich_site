"""Публичный сайт: захват заявок и доступность страниц."""

import re
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User, normalize_phone
from apps.billing.models import Tariff
from apps.notifications.models import Notification, NotificationKind

from . import antispam
from apps.utils import plural_ru

from .models import (
    FAQ,
    Course,
    CourseFormat,
    Language,
    Lead,
    LeadStatus,
    Location,
    Promo,
    Review,
    SiteSettings,
)
from .schematic import build_schematic


class PhoneNormalisationTests(TestCase):
    def test_every_common_russian_format_lands_on_one_value(self):
        for raw in [
            "+7 913 000-11-22", "8 (913) 000 11 22", "89130001122",
            "79130001122", "9130001122", "+7-913-000-11-22",
        ]:
            self.assertEqual(normalize_phone(raw), "+79130001122", raw)

    def test_empty_input_stays_empty(self):
        self.assertEqual(normalize_phone(""), "")
        self.assertEqual(normalize_phone(None), "")


class LeadFormTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@x.ru", first_name="Мария", role=Role.OWNER
        )
        self.language = Language.objects.create(name="Английский", slug="en")

    def filled_slowly(self, seconds=10):
        """Метка времени так, будто форму заполняли `seconds` секунд."""
        return antispam.form_timestamp(timezone.now() - timedelta(seconds=seconds))

    def post(self, **overrides):
        payload = {
            "name": "Ольга", "phone": "89130001122", "consent": "on",
            "form_ts": self.filled_slowly(),
        }
        payload.update(overrides)
        return self.client.post(reverse("school:lead_create"), payload)

    def test_valid_lead_is_stored_and_the_owner_is_pinged(self):
        response = self.post(message="Хочу английский", language=self.language.pk)
        self.assertEqual(response.status_code, 200)

        lead = Lead.objects.get()
        self.assertEqual(lead.phone, "+79130001122")
        self.assertEqual(lead.status, LeadStatus.NEW)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.owner, kind=NotificationKind.NEW_LEAD
            ).exists()
        )

    def test_broken_phone_is_reported_per_field(self):
        response = self.post(phone="123")
        self.assertEqual(response.status_code, 400)
        self.assertIn("phone", response.json()["fields"])
        self.assertFalse(Lead.objects.exists())

    def test_consent_is_required(self):
        response = self.client.post(reverse("school:lead_create"), {
            "name": "Ольга", "phone": "89130001122", "form_ts": self.filled_slowly(),
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("consent", response.json()["fields"])

    def test_honeypot_silently_blocks_bots(self):
        response = self.post(company="Spam Ltd")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Lead.objects.exists())

    def test_callback_widget_creates_a_lead_too(self):
        response = self.client.post(reverse("school:callback_create"), {
            "name": "Иван", "phone": "89130002233", "consent": "on",
            "form_ts": self.filled_slowly(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Lead.objects.get().source, "callback")


class PublicPagesTests(TestCase):
    def setUp(self):
        self.language = Language.objects.create(name="Английский", slug="en")
        self.course = Course.objects.create(
            language=self.language, title="Английский с нуля", slug="eng-0",
            price_per_lesson=1000, is_featured=True,
        )
        Location.objects.create(name="Центр", address="ул. Обороны, 3")
        Tariff.objects.create(name="8 занятий", lessons_count=8, price=7600)
        Review.objects.create(author_name="Ирина", text="Отлично")
        FAQ.objects.create(question="Есть пробный?", answer="Да")
        Promo.objects.create(title="Приведи друга", slug="friend")

    def test_every_public_page_renders(self):
        for url in [
            reverse("school:home"), reverse("school:courses"),
            reverse("school:course", args=[self.course.slug]),
            reverse("school:language", args=[self.language.slug]),
            reverse("school:teachers"), reverse("school:prices"),
            reverse("school:promos"), reverse("school:contacts"),
            reverse("school:privacy"), reverse("school:signup"),
            reverse("placement:test"),
        ]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_no_template_syntax_leaks_into_the_page(self):
        """Регрессия: многострочный {# … #} Django не считает комментарием
        и выводит его текст прямо на страницу."""
        for url in [reverse("school:home"), reverse("school:courses"),
                    reverse("school:prices"), reverse("school:signup"),
                    reverse("school:contacts"), reverse("placement:test")]:
            html = self.client.get(url).content.decode()
            for token in ("{#", "#}", "{%", "{{"):
                self.assertNotIn(token, html, f"{token} утёк в разметку на {url}")

    def test_course_filter_narrows_the_catalogue(self):
        other = Language.objects.create(name="Немецкий", slug="de")
        Course.objects.create(language=other, title="Немецкий", slug="de-0", price_per_lesson=900)

        response = self.client.get(reverse("school:courses"), {"language": "en"})
        titles = [c.title for c in response.context["courses"]]
        self.assertEqual(titles, ["Английский с нуля"])

    def test_sitemap_lists_courses_and_languages(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        xml = response.content.decode()
        self.assertIn(self.course.get_absolute_url(), xml)
        self.assertIn(self.language.get_absolute_url(), xml)
        self.assertIn("<priority>1.0</priority>", xml, "главная должна быть приоритетнее")

    def test_robots_hides_private_areas_and_points_at_the_sitemap(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        body = response.content.decode()
        for path in ("/cabinet/", "/admin/", "/accounts/"):
            self.assertIn(f"Disallow: {path}", body)
        self.assertIn("sitemap.xml", body)

    def test_inactive_course_is_hidden_and_404s(self):
        self.course.is_active = False
        self.course.save(update_fields=["is_active"])
        response = self.client.get(reverse("school:course", args=[self.course.slug]))
        self.assertEqual(response.status_code, 404)


class SiteSettingsTests(TestCase):
    def test_settings_are_a_singleton(self):
        first = SiteSettings.load()
        first.phone = "+7 000"
        first.save()
        second = SiteSettings.load()
        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertEqual(second.phone, "+7 000")


class LanguageTests(TestCase):
    def test_flag_code_becomes_an_emoji(self):
        self.assertEqual(Language(flag_code="gb").flag_emoji, "🇬🇧")
        self.assertEqual(Language(flag_code="ru").flag_emoji, "🇷🇺")

    def test_bad_flag_code_falls_back_to_a_globe(self):
        self.assertEqual(Language(flag_code="").flag_emoji, "🌐")
        self.assertEqual(Language(flag_code="xyz").flag_emoji, "🌐")


class AntispamTests(TestCase):
    """Слои защиты формы заявки. Каждый проверяем отдельно: если один
    отвалится, остальные должны продолжать держать."""

    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@x.ru", first_name="Мария", role=Role.OWNER
        )

    def post(self, seconds=10, path="school:lead_create", **overrides):
        payload = {
            "name": "Ольга", "phone": "89130001122", "consent": "on",
            "form_ts": antispam.form_timestamp(timezone.now() - timedelta(seconds=seconds)),
        }
        payload.update(overrides)
        return self.client.post(reverse(path), payload)

    def test_instant_submission_is_rejected(self):
        """Человек не заполняет форму за секунду — а бот заполняет."""
        response = self.post(seconds=0)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Lead.objects.exists())

    def test_missing_token_is_rejected(self):
        """Форма, собранная в обход страницы, метки времени не несёт."""
        response = self.client.post(reverse("school:lead_create"), {
            "name": "Ольга", "phone": "89130001122", "consent": "on",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Lead.objects.exists())

    def test_forged_token_is_rejected(self):
        response = self.post(form_ts="MTcwMDAwMDAwMA:fake:signature")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Lead.objects.exists())

    def test_stale_token_is_rejected(self):
        """Заготовленный когда-то токен не должен работать вечно."""
        response = self.post(seconds=antispam.MAX_FORM_AGE_SECONDS + 60)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Lead.objects.exists())

    def test_honeypot_catches_a_bot_that_fills_every_field(self):
        response = self.post(company="Spam Ltd")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Lead.objects.exists())

    def test_one_address_cannot_flood_the_crm(self):
        for index in range(antispam.MAX_LEADS_PER_IP_PER_HOUR):
            # Разные номера, иначе сработает гашение дублей, а не лимит.
            response = self.post(phone=f"891300011{index:02d}")
            self.assertEqual(response.status_code, 200, f"заявка {index + 1} должна пройти")
        response = self.post(phone="89130009999")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Lead.objects.count(), antispam.MAX_LEADS_PER_IP_PER_HOUR)

    def test_repeated_phone_does_not_duplicate_the_lead(self):
        """Второй клик по кнопке — не повод заводить вторую карточку,
        но и ошибку показывать не за что."""
        self.assertEqual(self.post().status_code, 200)
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Lead.objects.count(), 1)

    def test_origin_is_recorded(self):
        self.post(HTTP_USER_AGENT="TestBrowser/1.0")
        lead = Lead.objects.get()
        self.assertTrue(lead.ip, "без IP не посчитать частоту заявок")

    def test_callback_endpoint_is_guarded_too(self):
        response = self.post(seconds=0, path="school:callback_create")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Lead.objects.exists())


class ClientIpTests(TestCase):
    """X-Forwarded-For клиент может подделать целиком — кроме последнего
    элемента, который дописывает наш собственный nginx."""

    def make(self, **meta):
        from django.test import RequestFactory

        return RequestFactory().post("/api/lead/", **meta)

    def test_real_address_is_taken_from_the_end_of_the_chain(self):
        request = self.make(
            HTTP_X_FORWARDED_FOR="203.0.113.9, 198.51.100.7", REMOTE_ADDR="127.0.0.1"
        )
        self.assertEqual(antispam.client_ip(request), "198.51.100.7")

    def test_spoofed_header_cannot_hide_the_client(self):
        """Бот пишет чужой адрес первым — nginx всё равно допишет настоящий."""
        request = self.make(
            HTTP_X_FORWARDED_FOR="8.8.8.8", REMOTE_ADDR="198.51.100.7"
        )
        # Один элемент — это и есть то, что дописал nginx.
        self.assertEqual(antispam.client_ip(request), "8.8.8.8")

    def test_falls_back_to_remote_addr(self):
        request = self.make(REMOTE_ADDR="198.51.100.7")
        self.assertEqual(antispam.client_ip(request), "198.51.100.7")


class SeedCatalogTests(TestCase):
    """Команда для боевого сервера: каталог наполняет, людей — нет."""

    def run_command(self, **kwargs):
        from io import StringIO
        from django.core.management import call_command

        out = StringIO()
        call_command("seed_catalog", stdout=out, **kwargs)
        return out.getvalue()

    def test_catalog_appears(self):
        self.run_command()
        self.assertEqual(Language.objects.filter(is_active=True).count(), 7)
        self.assertTrue(Course.objects.exists())
        self.assertTrue(FAQ.objects.exists())
        self.assertTrue(Location.objects.exists())

    def test_no_fictional_people_are_created(self):
        """Главное отличие от seed_demo: на боевом сервере выдуманным
        ученикам и платежам не место."""
        from apps.billing.models import Payment

        self.run_command(with_samples=True)
        self.assertFalse(User.objects.exists())
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(Lead.objects.exists())

    def test_second_run_changes_nothing(self):
        self.run_command()
        Course.objects.update(summary="Отредактировано вручную")
        before = Language.objects.count()
        self.run_command()
        self.assertEqual(Language.objects.count(), before)
        self.assertEqual(Course.objects.first().summary, "Отредактировано вручную")

    def test_samples_are_opt_in(self):
        self.run_command()
        self.assertFalse(Review.objects.exists())
        self.run_command(with_samples=True)
        self.assertTrue(Review.objects.exists())

    def test_homepage_stops_showing_zero_languages(self):
        response = self.client.get(reverse("school:home"))
        self.assertEqual(len(response.context["languages"]), 0)
        self.run_command()
        response = self.client.get(reverse("school:home"))
        self.assertEqual(len(response.context["languages"]), 7)


class RouteMapTests(TestCase):
    """Первый экран главной: схема маршрутов.

    Схема обещает посетителю точность — язык, уровень, открытый набор.
    Поэтому тестом держим не картинку, а правдивость: на схему не должно
    попасть ничего, чего у школы нет в базе.
    """

    def setUp(self):
        self.english = Language.objects.create(
            name="Английский", slug="english", glyph="A", line_color="#008CD2", sort_order=10
        )
        self.korean = Language.objects.create(name="Корейский", slug="korean", sort_order=20)
        self.course = Course.objects.create(
            language=self.english, title="Английский с нуля", slug="en-a0",
            level_from="A0", level_to="B1", price_per_lesson=1000,
        )
        self.teacher = User.objects.create_user(
            email="t@linguich.ru", first_name="Анна", last_name="С", role=Role.TEACHER
        )

    def group(self, **overrides):
        from apps.scheduling.models import Group

        values = {
            "name": "Английский · вечерняя",
            "course": self.course,
            "teacher": self.teacher,
            "capacity": 8,
            "level": "A0",
            "starts_on": timezone.localdate() + timedelta(days=7),
        }
        values.update(overrides)
        return Group.objects.create(**values)

    def line(self, data, slug):
        for line in data["lines"]:
            if line["id"] == slug:
                return line
        return None

    def test_language_without_courses_does_not_get_a_line(self):
        """Язык в каталоге ещё не значит, что на него можно записаться."""
        data = build_schematic()
        self.assertIsNotNone(self.line(data, "english"))
        self.assertIsNone(self.line(data, "korean"))

    def test_line_spans_the_levels_its_courses_cover(self):
        data = build_schematic()
        line = self.line(data, "english")
        self.assertEqual(data["levels"][line["from_index"]], "A0")
        self.assertEqual(data["levels"][line["to_index"]], "B1")
        self.assertEqual(line["levels_label"], "A0 → B1")

    def test_only_an_open_intake_gets_a_mark(self):
        """Группа, которая уже идёт, — не обещание: отметки на схеме нет."""
        self.group(starts_on=timezone.localdate() - timedelta(days=14))
        self.assertEqual(self.line(build_schematic(), "english")["marks"], [])

        self.group(name="Английский · утренняя")
        marks = self.line(build_schematic(), "english")["marks"]
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0]["seats"], 8)
        self.assertEqual(marks[0]["seats_word"], "мест")

    def test_a_group_without_free_seats_is_not_advertised(self):
        from apps.scheduling.models import Enrollment

        group = self.group(capacity=1)
        student = User.objects.create_user(email="s@linguich.ru", first_name="Егор", role=Role.STUDENT)
        Enrollment.objects.create(student=student, group=group)
        self.assertEqual(self.line(build_schematic(), "english")["marks"], [])

    def test_exam_course_becomes_a_branch_of_the_line(self):
        Course.objects.create(
            language=self.english, title="Подготовка к IELTS", slug="en-ielts",
            format=CourseFormat.EXAM, level_from="B1", level_to="C1", price_per_lesson=2000,
        )
        branch = self.line(build_schematic(), "english")["branch"]
        self.assertIsNotNone(branch)
        self.assertEqual(build_schematic()["levels"][branch["to_index"]], "C1")

    def test_language_keeps_its_own_colour_and_letter(self):
        line = self.line(build_schematic(), "english")
        self.assertEqual(line["color"], "#008CD2")
        self.assertEqual(line["glyph"], "A")

    def test_a_language_without_a_chosen_colour_still_gets_one(self):
        """Школа завела язык и не выбрала цвет — схема не должна остаться без линии."""
        Course.objects.create(
            language=self.korean, title="Корейский с нуля", slug="ko-a0",
            level_from="A0", level_to="A2", price_per_lesson=1000,
        )
        line = self.line(build_schematic(), "korean")
        self.assertTrue(line["color"].startswith("#"))
        self.assertEqual(line["glyph"], "К")

    def test_the_page_is_readable_without_javascript(self):
        """Скрипт — надстройка. Без него остаётся список языков с уровнями."""
        self.group()
        html = self.client.get(reverse("school:home")).content.decode()
        self.assertIn('class="rt__list"', html)
        self.assertIn("Английский", html)
        self.assertIn("A0 → B1", html)

    def test_the_paint_layer_says_nothing_to_a_screen_reader(self):
        html = self.client.get(reverse("school:home")).content.decode()
        self.assertIn('data-wash-canvas aria-hidden="true"', html)

    def test_motion_can_be_switched_off_by_the_visitor(self):
        from django.conf import settings

        css = (settings.BASE_DIR / "static" / "css" / "home.css").read_text(encoding="utf-8")
        self.assertIn("prefers-reduced-motion", css)


class PluralRuTests(TestCase):
    """Встроенный ``pluralize`` умеет две формы, русскому нужно три."""

    def test_counts_get_the_right_ending(self):
        cases = {1: "место", 2: "места", 5: "мест", 11: "мест", 21: "место", 104: "места"}
        for count, expected in cases.items():
            self.assertEqual(plural_ru(count, "место", "места", "мест"), expected, count)

    def test_the_template_filter_says_the_same(self):
        from django.template import Context, Template

        rendered = Template(
            '{% load ru %}{% for n in ns %}{{ n }} {{ n|plural:"занятие,занятия,занятий" }};{% endfor %}'
        ).render(Context({"ns": [1, 2, 5]}))
        self.assertEqual(rendered, "1 занятие;2 занятия;5 занятий;")

    def test_pluralize_with_three_forms_is_not_used_anywhere(self):
        """Регрессия: `{{ n|pluralize:"ь,я,ей" }}` рендерит пустоту, и на
        странице остаётся «5 модул». Django принимает только две формы."""
        from django.conf import settings

        broken = []
        for path in (settings.BASE_DIR / "templates").rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            for match in re.findall(r'pluralize:"([^"]*)"', text):
                if match.count(",") >= 2:
                    broken.append(f"{path.name}: {match}")
        self.assertFalse(broken, f"pluralize с тремя формами молча вернёт пустоту: {broken}")


class StickyHeaderTests(TestCase):
    """Шапка закреплена при прокрутке — и остаётся такой.

    Ломается это не в самой шапке: `overflow-x: hidden` на body делает его
    контейнером прокрутки, и любой sticky внутри перестаёт липнуть. Ошибка
    беззвучная, поэтому держим её тестом.
    """

    def css(self, name):
        from django.conf import settings

        return (settings.BASE_DIR / "static" / "css" / name).read_text(encoding="utf-8")

    def test_the_header_is_sticky(self):
        block = self.css("site.css").split(".site-header {")[1].split("}")[0]
        self.assertIn("position: sticky", block)
        self.assertIn("top: 0", block)

    def test_body_does_not_create_its_own_scroll_container(self):
        base = self.css("base.css")
        body = base.split("body {")[1].split("}")[0]
        self.assertNotIn("overflow-x: hidden", body)
        self.assertIn("overflow-x: clip", body)


