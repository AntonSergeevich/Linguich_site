"""Разбор настроек БД: ошибка здесь роняет сайт целиком и молча."""

import os
from unittest import mock

from django.test import SimpleTestCase

from config.settings import _postgres_settings


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
