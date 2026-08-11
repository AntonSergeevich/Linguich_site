"""Разбор настроек БД: ошибка здесь роняет сайт целиком и молча."""

import os
from unittest import mock

from django.test import SimpleTestCase

from config.settings import _email_security, _postgres_settings


class DatabaseSettingsTests(SimpleTestCase):
    def build(self, **env):
        with mock.patch.dict(os.environ, env, clear=False):
            for key in ("POSTGRES_DB", "DATABASE_URL"):
                if key not in env:
                    os.environ.pop(key, None)
            return _postgres_settings()

    def test_separate_variables_are_used_as_is(self):
        config = self.build(
            POSTGRES_DB="linguich", POSTGRES_USER="linguich",
            POSTGRES_PASSWORD="p@ss:w0rd!", POSTGRES_HOST="localhost",
        )
        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["NAME"], "linguich")
        # Пароль со спецсимволами не должен ничего экранировать.
        self.assertEqual(config["PASSWORD"], "p@ss:w0rd!")

    def test_database_url_password_is_percent_decoded(self):
        """Регрессия: urlparse отдаёт пароль закодированным, и Postgres
        отвечал бы «password authentication failed» без объяснений."""
        config = self.build(
            DATABASE_URL="postgres://ling%40user:p%40ss%3Aw0rd@db.host:6432/linguich"
        )
        self.assertEqual(config["USER"], "ling@user")
        self.assertEqual(config["PASSWORD"], "p@ss:w0rd")
        self.assertEqual(config["HOST"], "db.host")
        self.assertEqual(config["PORT"], 6432)
        self.assertEqual(config["NAME"], "linguich")

    def test_separate_variables_win_over_url(self):
        config = self.build(
            POSTGRES_DB="from_vars",
            DATABASE_URL="postgres://u:p@host:5432/from_url",
        )
        self.assertEqual(config["NAME"], "from_vars")

    def test_no_postgres_config_means_sqlite(self):
        self.assertIsNone(self.build())

    def test_non_postgres_url_is_ignored(self):
        self.assertIsNone(self.build(DATABASE_URL="mysql://u:p@host/db"))

    def test_connections_are_reused(self):
        config = self.build(POSTGRES_DB="linguich", POSTGRES_PASSWORD="x")
        self.assertEqual(config["CONN_MAX_AGE"], 60, "без этого каждый запрос открывает новое соединение")


class EmailSecurityTests(SimpleTestCase):
    """Режим шифрования SMTP. Ошибка тут молчаливая: письма не уходят."""

    def build(self, port, **env):
        with mock.patch.dict(os.environ, env, clear=False):
            for key in ("EMAIL_USE_SSL", "EMAIL_USE_TLS"):
                if key not in env:
                    os.environ.pop(key, None)
            return _email_security(port)

    def test_port_465_means_ssl(self):
        self.assertEqual(self.build(465), (True, False))

    def test_port_587_means_starttls(self):
        self.assertEqual(self.build(587), (False, True))

    def test_environment_wins_over_the_port(self):
        self.assertEqual(self.build(465, EMAIL_USE_SSL="False", EMAIL_USE_TLS="True"), (False, True))

    def test_both_enabled_is_resolved_instead_of_crashing(self):
        """Django отказывается стартовать при SSL и TLS одновременно —
        именно так выглядит .env, где порт поменяли, а строку забыли."""
        ssl, tls = self.build(465, EMAIL_USE_SSL="True", EMAIL_USE_TLS="True")
        self.assertFalse(ssl and tls)
        self.assertTrue(ssl)


class LanguageTests(SimpleTestCase):
    """Регрессия: с английской локалью браузера Django печатал дни недели
    как «MON», хотя сайт русский. LocaleMiddleware выбирает язык по
    заголовку, поэтому список доступных языков должен быть один."""

    def test_only_russian_is_offered(self):
        from django.conf import settings

        self.assertEqual([code for code, _ in settings.LANGUAGES], ["ru"])

    def test_english_cannot_be_negotiated(self):
        """Именно этим LocaleMiddleware и переключался на английский,
        печатая «MON» вместо «Пн»."""
        from django.utils import translation

        with self.assertRaises(LookupError):
            translation.get_supported_language_variant("en")


class SpacingUtilitiesTests(SimpleTestCase):
    """Классы отступов легко написать в шаблоне и забыть добавить в CSS.

    Так и вышло: mt-3 стоял в двадцати местах, а правила не существовало —
    бейдж акции прилипал к заголовку, и заметить это можно было только
    глазами на конкретной странице.
    """

    def used(self):
        import re

        from django.conf import settings

        names = set()
        roots = [settings.BASE_DIR / "templates", settings.BASE_DIR / "static" / "js"]
        for root in roots:
            for path in root.rglob("*"):
                if path.suffix not in {".html", ".js"}:
                    continue
                names |= set(re.findall(r"\bm[tb]-\d+\b", path.read_text(encoding="utf-8")))
        return names

    def defined(self):
        import re

        from django.conf import settings

        css = (settings.BASE_DIR / "static" / "css" / "base.css").read_text(encoding="utf-8")
        return set(re.findall(r"\.(m[tb]-\d+)\s*\{", css))

    def test_every_used_spacing_class_exists(self):
        missing = sorted(self.used() - self.defined())
        self.assertFalse(
            missing,
            f"в разметке есть классы отступов, которых нет в CSS: {', '.join(missing)}",
        )
