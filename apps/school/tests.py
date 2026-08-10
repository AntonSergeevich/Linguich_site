"""Публичный сайт: захват заявок и доступность страниц."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User, normalize_phone
from apps.billing.models import Tariff
from apps.notifications.models import Notification, NotificationKind

from . import antispam
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
