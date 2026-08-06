"""Публичный сайт: захват заявок и доступность страниц."""

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User, normalize_phone
from apps.billing.models import Tariff
from apps.notifications.models import Notification, NotificationKind

from .models import FAQ, Course, Language, Lead, LeadStatus, Location, Promo, Review, SiteSettings


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

    def post(self, **overrides):
        payload = {"name": "Ольга", "phone": "89130001122", "consent": "on"}
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
            "name": "Ольга", "phone": "89130001122",
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
