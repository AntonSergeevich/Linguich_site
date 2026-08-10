"""Вход по email или телефону, регистрация, привязка Telegram."""

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Role, StudentProfile, User


class UserModelTests(TestCase):
    def test_phone_is_normalised_on_save(self):
        user = User.objects.create_user(phone="8 913 000-11-22", first_name="Егор")
        user.refresh_from_db()
        self.assertEqual(user.phone, "+79130001122")

    def test_email_is_lowercased(self):
        user = User.objects.create_user(email="  Egor@MAIL.RU ", first_name="Егор")
        user.refresh_from_db()
        self.assertEqual(user.email, "egor@mail.ru")

    def test_account_needs_at_least_one_identifier(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(first_name="Никто")

    def test_owner_counts_as_a_teacher_everywhere(self):
        owner = User.objects.create_user(email="o@x.ru", first_name="Мария", role=Role.OWNER)
        self.assertTrue(owner.is_owner)
        self.assertTrue(owner.is_teacher, "владелица тоже ведёт уроки")
        self.assertFalse(owner.is_student)

    def test_display_helpers(self):
        user = User(first_name="Егор", last_name="Тимофеев")
        self.assertEqual(user.full_name, "Егор Тимофеев")
        self.assertEqual(user.short_name, "Егор Т.")
        self.assertEqual(user.initials, "ЕТ")

    def test_initials_survive_a_missing_surname(self):
        self.assertEqual(User(first_name="Егор").initials, "Е")


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="egor@mail.ru", phone="+79130001122",
            password="verysecret123", first_name="Егор", role=Role.STUDENT,
        )
        StudentProfile.objects.create(user=self.user)

    def login(self, username, password="verysecret123"):
        return self.client.post(
            reverse("accounts:login"), {"username": username, "password": password}
        )

    def test_login_works_with_email(self):
        self.assertEqual(self.login("egor@mail.ru").status_code, 302)

    def test_login_works_with_any_phone_format(self):
        for variant in ["+79130001122", "89130001122", "8 913 000 11 22"]:
            self.client.logout()
            self.assertEqual(self.login(variant).status_code, 302, variant)

    def test_wrong_password_is_refused(self):
        response = self.login("egor@mail.ru", "неверный")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())

    def test_inactive_account_cannot_log_in(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.login("egor@mail.ru").status_code, 200)

    def test_next_parameter_only_accepts_internal_paths(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "egor@mail.ru", "password": "verysecret123",
            "next": "https://evil.example.com/steal",
        })
        self.assertEqual(response.url, reverse("cabinet:home"))

    def test_internal_next_is_honoured(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": "egor@mail.ru", "password": "verysecret123",
            "next": "/cabinet/homework/",
        })
        self.assertEqual(response.url, "/cabinet/homework/")


class RegistrationTests(TestCase):
    def payload(self, **overrides):
        data = {
            "first_name": "Полина", "last_name": "Крылова",
            "email": "polina@mail.ru", "phone": "89130003344",
            "password1": "verysecret123", "password2": "verysecret123",
            "consent": "on",
        }
        data.update(overrides)
        return data

    def test_registration_creates_a_student_with_a_profile(self):
        response = self.client.post(reverse("accounts:register"), self.payload())
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(email="polina@mail.ru")
        self.assertEqual(user.role, Role.STUDENT)
        self.assertTrue(hasattr(user, "student_profile"))
        self.assertEqual(user.phone, "+79130003344")

    def test_duplicate_email_is_refused(self):
        User.objects.create_user(email="polina@mail.ru", first_name="Другая")
        response = self.client.post(reverse("accounts:register"), self.payload())
        self.assertIn("email", response.context["form"].errors)

    def test_duplicate_phone_is_refused(self):
        User.objects.create_user(phone="+79130003344", first_name="Другая")
        response = self.client.post(reverse("accounts:register"), self.payload())
        self.assertIn("phone", response.context["form"].errors)

    def test_mismatched_passwords_are_refused(self):
        response = self.client.post(
            reverse("accounts:register"), self.payload(password2="другое123")
        )
        self.assertIn("password2", response.context["form"].errors)

    def test_weak_password_is_refused(self):
        response = self.client.post(
            reverse("accounts:register"), self.payload(password1="123", password2="123")
        )
        self.assertIn("password1", response.context["form"].errors)


@override_settings(TELEGRAM_WEBHOOK_SECRET="s3cret")
class TelegramLinkTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="e@x.ru", first_name="Егор")
        self.code = self.user.ensure_telegram_code()

    def send(self, text, secret="s3cret"):
        import json

        return self.client.post(
            reverse("accounts:telegram_webhook"),
            data=json.dumps({"message": {"chat": {"id": 4242}, "text": text}}),
            content_type="application/json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=secret,
        )

    def test_start_with_a_valid_code_links_the_chat(self):
        self.assertEqual(self.send(f"/start {self.code}").status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_chat_id, "4242")

    def test_unknown_code_links_nothing(self):
        self.send("/start bogus")
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_chat_id, "")

    def test_wrong_secret_is_rejected(self):
        response = self.send(f"/start {self.code}", secret="nope")
        self.assertEqual(response.status_code, 403)
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_chat_id, "")

    def test_link_code_is_stable(self):
        self.assertEqual(self.user.ensure_telegram_code(), self.code)


@override_settings(TELEGRAM_LINK_API_KEY="botkey")
class TelegramBotApiTests(TestCase):
    """Привязка чата из уже работающего бота школы, без вебхука."""

    def setUp(self):
        self.user = User.objects.create_user(email="e@x.ru", first_name="Егор")
        self.code = self.user.ensure_telegram_code()

    def call(self, payload, key="botkey"):
        import json

        return self.client.post(
            reverse("accounts:telegram_link"),
            data=json.dumps(payload), content_type="application/json",
            HTTP_X_API_KEY=key,
        )

    def test_bot_can_link_a_chat(self):
        response = self.call({"code": self.code, "chat_id": 777})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_chat_id, "777")

    def test_wrong_api_key_is_rejected(self):
        self.assertEqual(self.call({"code": self.code, "chat_id": 777}, key="nope").status_code, 403)
        self.user.refresh_from_db()
        self.assertEqual(self.user.telegram_chat_id, "")

    def test_unknown_code_is_reported(self):
        self.assertEqual(self.call({"code": "bogus", "chat_id": 777}).status_code, 404)

    def test_missing_fields_are_reported(self):
        self.assertEqual(self.call({"code": self.code}).status_code, 400)

    @override_settings(TELEGRAM_LINK_API_KEY="")
    def test_endpoint_is_closed_when_no_key_configured(self):
        self.assertEqual(self.call({"code": self.code, "chat_id": 777}, key="").status_code, 403)


class PhoneWidgetTests(TestCase):
    """Маска в app.js ищет поля по type="tel". Поле, отрендеренное обычным
    текстовым, тихо остаётся без форматирования — заметить это на глаз в
    большой форме почти невозможно, поэтому проверяем разметкой."""

    def assertMasked(self, html, field):
        self.assertIn('type="tel"', html, f"{field}: маска не привяжется")
        self.assertIn('inputmode="tel"', html, f"{field}: нет цифровой клавиатуры на телефоне")

    def test_registration_phone_is_a_tel_field(self):
        from .forms import RegistrationForm

        self.assertMasked(str(RegistrationForm()["phone"]), "регистрация")

    def test_profile_phone_is_a_tel_field(self):
        from .forms import ProfileForm

        self.assertMasked(str(ProfileForm()["phone"]), "профиль")

    def test_parent_phone_is_a_tel_field(self):
        from .forms import StudentDetailsForm

        self.assertMasked(str(StudentDetailsForm()["parent_phone"]), "телефон родителя")

    def test_public_forms_are_tel_fields(self):
        from apps.school.forms import CallbackForm, LeadForm

        self.assertMasked(str(LeadForm()["phone"]), "заявка")
        self.assertMasked(str(CallbackForm()["phone"]), "обратный звонок")

    def test_typed_number_survives_normalisation(self):
        """То, что отдаёт маска, сервер обязан принять без правок."""
        from .models import normalize_phone

        self.assertEqual(normalize_phone("+7 (913) 000-11-22"), "+79130001122")
