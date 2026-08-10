"""Очередь уведомлений: дедупликация, расписание, каналы."""

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
