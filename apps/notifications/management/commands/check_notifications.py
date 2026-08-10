"""Диагностика доставки уведомлений.

Когда «уведомления не приходят», причин обычно три, и снаружи они выглядят
одинаково: очередь никто не разбирает (не поставлен cron), получателю нечего
слать (не привязан Telegram, нет email) или отправка падает (неверный токен,
почта отвергает логин). Команда разделяет эти случаи и говорит, что чинить.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.notifications.models import Channel, Notification, Status


class Command(BaseCommand):
    help = "Показывает состояние очереди уведомлений и проверяет каналы доставки."

    def add_arguments(self, parser):
        parser.add_argument(
            "--send-test", action="store_true",
            help="Отправить пробное сообщение владельцу прямо сейчас, минуя очередь.",
        )

    def handle(self, *args, **options):
        self._section("Настройки")
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        self._line("TELEGRAM_BOT_TOKEN", "задан" if token else "ПУСТО", ok=bool(token))
        self._line("TELEGRAM_BOT_USERNAME", getattr(settings, "TELEGRAM_BOT_USERNAME", "") or "ПУСТО")
        self._line("TELEGRAM_LINK_API_KEY",
                   "задан" if getattr(settings, "TELEGRAM_LINK_API_KEY", "") else "пусто")
        self._line("EMAIL_BACKEND", settings.EMAIL_BACKEND.rsplit(".", 2)[-2:][0])

        self._section("Получатели")
        staff = User.objects.filter(role__in=[Role.OWNER, Role.ADMIN], is_active=True)
        if not staff:
            self._line("сотрудники", "НИ ОДНОГО — заявки некому слать", ok=False)
        for user in staff:
            linked = bool(user.telegram_chat_id)
            self._line(
                str(user),
                ("Telegram привязан" if linked else "Telegram НЕ привязан")
                + (", уведомления в Telegram выключены" if not user.notify_telegram else ""),
                ok=linked and user.notify_telegram,
            )

        self._section("Очередь")
        pending = Notification.objects.filter(status=Status.PENDING)
        overdue = pending.filter(scheduled_for__lte=timezone.now() - timedelta(minutes=5))
        self._line("ждут отправки", str(pending.count()))
        self._line(
            "просрочены больше 5 минут", str(overdue.count()),
            ok=not overdue.exists(),
            hint="очередь никто не разбирает — проверьте cron: crontab -l",
        )
        for channel in (Channel.TELEGRAM, Channel.EMAIL, Channel.INAPP):
            counts = {
                status: Notification.objects.filter(channel=channel, status=status).count()
                for status, _ in Status.choices
            }
            self._line(f"канал {channel}", ", ".join(f"{k}: {v}" for k, v in counts.items()))

        last_failed = Notification.objects.filter(status=Status.FAILED).order_by("-id").first()
        if last_failed:
            self._section("Последняя ошибка")
            self._line(str(last_failed.pk), last_failed.error or "без текста", ok=False)

        if options["send_test"]:
            self._section("Пробная отправка")
            self._send_test(staff)

    # -- helpers ------------------------------------------------------------

    def _send_test(self, staff):
        from apps.notifications.services import _deliver_telegram

        target = staff.filter(telegram_chat_id__gt="").first()
        if target is None:
            self._line("некому", "ни у кого не привязан Telegram", ok=False)
            return
        note = Notification(
            recipient=target, channel=Channel.TELEGRAM,
            subject="Проверка связи",
            body="Если вы это видите — уведомления о заявках дойдут.",
        )
        try:
            # Объект намеренно не сохраняем: это разовая проверка канала,
            # в истории уведомлений ей не место.
            delivered = _deliver_telegram(note)
        except Exception as exc:
            self._line(str(target), f"ОШИБКА: {exc}", ok=False)
            return
        self._line(str(target), "доставлено" if delivered else "пропущено", ok=delivered)

    def _section(self, title):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    def _line(self, name, value, ok=None, hint=""):
        style = self.style.SUCCESS if ok else (self.style.ERROR if ok is False else str)
        self.stdout.write(f"  {name:.<36} {style(value)}")
        if hint and ok is False:
            self.stdout.write(f"       → {hint}")
