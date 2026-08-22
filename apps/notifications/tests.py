"""Очередь уведомлений: дедупликация, расписание, каналы."""

import json
from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Role, User

from .models import Channel, Notification, NotificationKind, Status
from .services import channels_for, flush, notify, notify_many


class ChannelSelectionTests(TestCase):
    def test_inapp_is_always_on(self):
        user = User.objects.create_user(email="e@x.ru", first_name="Егор")
        self.assertIn(Channel.INAPP, channels_for(user))

    def test_telegram_only_when_linked_and_enabled(self):
        user = User.objects.create_user(email="e@x.ru", first_name="Егор")
        self.assertNotIn(Channel.TELEGRAM, channels_for(user))

        user.telegram_chat_id = "123"
        self.assertIn(Channel.TELEGRAM, channels_for(user))

        user.notify_telegram = False
        self.assertNotIn(Channel.TELEGRAM, channels_for(user))

    def test_email_respects_the_opt_out(self):
        user = User.objects.create_user(email="e@x.ru", first_name="Егор")
        self.assertIn(Channel.EMAIL, channels_for(user))
        user.notify_email = False
        self.assertNotIn(Channel.EMAIL, channels_for(user))


class QueueTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="egor@mail.ru", first_name="Егор", role=Role.STUDENT
        )

    def test_notify_fans_out_across_enabled_channels(self):
        created = notify(self.user, NotificationKind.CUSTOM, "Тема", "Текст")
        channels = {n.channel for n in created}
        self.assertEqual(channels, {Channel.INAPP, Channel.EMAIL})

    def test_dedupe_key_makes_the_call_idempotent(self):
        notify(self.user, NotificationKind.LESSON_REMINDER, "Урок", "Завтра", dedupe_key="x")
        again = notify(self.user, NotificationKind.LESSON_REMINDER, "Урок", "Завтра", dedupe_key="x")
        self.assertEqual(again, [])
        self.assertEqual(Notification.objects.count(), 2)  # inapp + email, по одному

    def test_notifying_nobody_is_a_no_op(self):
        self.assertEqual(notify(None, NotificationKind.CUSTOM, "x", "y"), [])

    def test_future_messages_are_not_sent_early(self):
        notify(
            self.user, NotificationKind.LESSON_REMINDER, "Урок", "Завтра",
            scheduled_for=timezone.now() + timedelta(hours=5),
        )
        sent, failed, _skipped = flush()
        self.assertEqual((sent, failed), (0, 0))
        self.assertEqual(Notification.objects.filter(status=Status.PENDING).count(), 2)

    def test_due_email_is_actually_delivered(self):
        notify(self.user, NotificationKind.CUSTOM, "Напоминание", "Урок в 18:00", url="/cabinet/")
        sent, failed, _ = flush()
        self.assertEqual(failed, 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Урок в 18:00", mail.outbox[0].body)
        self.assertIn("/cabinet/", mail.outbox[0].body, "ссылка должна быть абсолютной")
        self.assertEqual(sent, 2)  # inapp считается доставленным сразу

    def test_email_is_skipped_when_the_user_has_none(self):
        user = User.objects.create_user(phone="+79130001122", first_name="Без почты")
        notify(user, NotificationKind.CUSTOM, "Тема", "Текст", channels=[Channel.EMAIL])
        flush()
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Notification.objects.get(recipient=user).status, Status.SKIPPED)

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_telegram_without_a_token_is_skipped_not_failed(self):
        self.user.telegram_chat_id = "999"
        self.user.save(update_fields=["telegram_chat_id"])
        notify(self.user, NotificationKind.CUSTOM, "Тема", "Текст", channels=[Channel.TELEGRAM])
        _sent, failed, skipped = flush()
        self.assertEqual(failed, 0)
        self.assertEqual(skipped, 1)

    def test_one_broken_message_does_not_stop_the_queue(self):
        notify(self.user, NotificationKind.CUSTOM, "Первое", "Текст", channels=[Channel.INAPP])
        Notification.objects.create(
            recipient=self.user, kind=NotificationKind.CUSTOM,
            channel="carrier-pigeon", subject="Битое", body="?",
        )
        notify(self.user, NotificationKind.CUSTOM, "Третье", "Текст", channels=[Channel.INAPP])

        sent, failed, _ = flush()
        self.assertEqual(sent, 2)
        self.assertEqual(failed, 1)

    def test_unread_counter_ignores_skipped_messages(self):
        from apps.cabinet.common import unread_count

        notify(self.user, NotificationKind.CUSTOM, "Тема", "Текст", channels=[Channel.INAPP])
        self.assertEqual(unread_count(self.user), 1)

        Notification.objects.update(read_at=timezone.now())
        self.assertEqual(unread_count(self.user), 0)


class DedupeKeyTests(TestCase):
    """Регрессия: ключ дедупликации не включал получателя, и одно событие
    на нескольких адресатов доходило только до первого."""

    def setUp(self):
        self.first = User.objects.create_user(
            email="one@x.ru", first_name="Мария", role=Role.OWNER
        )
        self.second = User.objects.create_user(
            email="two@x.ru", first_name="Ольга", role=Role.ADMIN
        )

    def test_one_event_reaches_every_recipient(self):
        notify_many(
            [self.first, self.second],
            kind=NotificationKind.NEW_LEAD, subject="Новая заявка",
            body="Пётр", dedupe_key="lead:1",
        )
        for user in (self.first, self.second):
            with self.subTest(user=user.email):
                self.assertTrue(
                    Notification.objects.filter(recipient=user, channel=Channel.INAPP).exists()
                )

    def test_repeating_the_same_event_still_does_not_duplicate(self):
        for _ in range(3):
            notify_many(
                [self.first, self.second],
                kind=NotificationKind.NEW_LEAD, subject="Новая заявка",
                body="Пётр", dedupe_key="lead:1",
            )
        self.assertEqual(
            Notification.objects.filter(recipient=self.first, channel=Channel.INAPP).count(), 1
        )


class ParentDeliveryTests(TestCase):
    """Про деньги пишем родителю, про учёбу — ученику.

    Кабинет у них один: заводить второй аккаунт значило бы удвоить логины
    ради тех же самых экранов. Разное только одно — кому уходит письмо.
    """

    def setUp(self):
        from apps.accounts.models import StudentProfile

        self.student = User.objects.create_user(
            email="kid@x.ru", first_name="Артём", role=Role.STUDENT, notify_email=True
        )
        self.profile = StudentProfile.objects.create(
            user=self.student, parent_name="Ирина", parent_email="mama@x.ru",
            parent_telegram_chat_id="777",
        )
        self.student.telegram_chat_id = "111"
        self.student.notify_telegram = True
        self.student.save()

    def emails_for(self, kind):
        mail.outbox = []
        notify(self.student, kind, "Тема", "Текст", channels=[Channel.EMAIL])
        flush()
        return mail.outbox[0].to if mail.outbox else []

    def test_money_reaches_the_parent(self):
        self.assertEqual(
            sorted(self.emails_for(NotificationKind.PACKAGE_LOW)), ["kid@x.ru", "mama@x.ru"]
        )

    def test_studies_stay_with_the_student(self):
        self.assertEqual(self.emails_for(NotificationKind.HOMEWORK_ASSIGNED), ["kid@x.ru"])

    def test_the_parent_can_be_switched_off(self):
        self.profile.notify_parent = False
        self.profile.save(update_fields=["notify_parent"])
        self.assertEqual(self.emails_for(NotificationKind.PACKAGE_LOW), ["kid@x.ru"])

    def test_a_student_without_a_parent_is_unaffected(self):
        self.profile.parent_email = ""
        self.profile.save(update_fields=["parent_email"])
        self.assertEqual(self.emails_for(NotificationKind.PAYMENT_DUE), ["kid@x.ru"])

    def test_a_teacher_has_no_parent_and_does_not_crash(self):
        """У преподавателя нет student_profile — обращение к нему не должно
        ронять рассылку про платежи."""
        teacher = User.objects.create_user(
            email="t@x.ru", first_name="Анна", role=Role.TEACHER, notify_email=True
        )
        mail.outbox = []
        notify(teacher, NotificationKind.PAYMENT_RECEIVED, "Тема", "Текст", channels=[Channel.EMAIL])
        flush()
        self.assertEqual(mail.outbox[0].to, ["t@x.ru"])

    def test_both_telegram_chats_get_the_money_notice(self):
        """Забыть родителя в Telegram — ровно та ошибка, ради которой поле
        и заводили: смс уходит ребёнку, а платит не он."""
        import urllib.request
        from unittest import mock

        from . import services

        note = Notification.objects.create(
            recipient=self.student, kind=NotificationKind.PACKAGE_LOW,
            channel=Channel.TELEGRAM, subject="Тема", body="Текст",
            scheduled_for=timezone.now(),
        )
        sent = []

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=None):
            sent.append(json.loads(request.data)["chat_id"])
            return Response()

        with override_settings(TELEGRAM_BOT_TOKEN="token"):
            with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
                self.assertTrue(services._deliver_telegram(note))
        self.assertEqual(sorted(sent), ["111", "777"])

    def test_one_unreachable_chat_does_not_block_the_other(self):
        """У родителя бот может быть не запущен — ученику написать всё равно
        нужно, а не уронить всю доставку."""
        import urllib.request
        from unittest import mock

        from . import services

        note = Notification.objects.create(
            recipient=self.student, kind=NotificationKind.PACKAGE_LOW,
            channel=Channel.TELEGRAM, subject="Тема", body="Текст",
            scheduled_for=timezone.now(),
        )

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=None):
            if json.loads(request.data)["chat_id"] == "777":
                raise OSError("chat not found")
            return Response()

        with override_settings(TELEGRAM_BOT_TOKEN="token"):
            with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
                self.assertTrue(services._deliver_telegram(note))
