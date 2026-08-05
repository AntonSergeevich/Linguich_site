"""Queueing and delivery of notifications.

Requests only ever *enqueue*. Delivery happens in ``send_notifications``, run by
cron every minute. That keeps booking and homework flows fast and immune to a
flaky SMTP or Telegram endpoint.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Channel, Notification, NotificationKind, Status

logger = logging.getLogger(__name__)


def channels_for(user):
    """Which channels this user actually wants, best first."""
    channels = [Channel.INAPP]
    if user.notify_telegram and user.telegram_chat_id:
        channels.append(Channel.TELEGRAM)
    if user.notify_email and user.email:
        channels.append(Channel.EMAIL)
    return channels


def notify(user, kind, subject, body, url="", lesson=None, scheduled_for=None, dedupe_key=None, channels=None):
    """Queue one message across every channel the user has enabled.

    ``dedupe_key`` makes the call idempotent — safe to run the reminder
    scheduler as often as you like.
    """
    if user is None:
        return []
    scheduled_for = scheduled_for or timezone.now()
    created = []
    for channel in channels or channels_for(user):
        key = f"{dedupe_key}:{channel}" if dedupe_key else None
        try:
            # Собственный savepoint обязателен: если поймать IntegrityError без
            # него, внешняя транзакция (бронирование, выдача домашки) останется
            # помеченной как сломанная и упадёт на следующем же запросе.
            with transaction.atomic():
                note = Notification.objects.create(
                    recipient=user,
                    kind=kind,
                    channel=channel,
                    subject=subject,
                    body=body,
                    url=url,
                    lesson=lesson,
                    scheduled_for=scheduled_for,
                    dedupe_key=key,
                )
        except IntegrityError:
            continue  # уже в очереди
        created.append(note)
    return created


def notify_many(users, **kwargs):
    out = []
    for user in users:
        out.extend(notify(user, **kwargs))
    return out


# --- delivery --------------------------------------------------------------

def _deliver_email(note):
    recipient = note.recipient
    if not recipient.email:
        note.status = Status.SKIPPED
        note.save(update_fields=["status"])
        return False
    body = note.body
    if note.url:
        body = f"{body}\n\n{settings.SITE_URL}{note.url}"
    send_mail(
        subject=note.subject or "Лингвич",
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient.email],
        fail_silently=False,
    )
    return True


def _deliver_telegram(note):
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = note.recipient.telegram_chat_id
    if not token or not chat_id:
        note.status = Status.SKIPPED
        note.save(update_fields=["status"])
        return False

    import json
    import urllib.request

    text = f"*{note.subject}*\n\n{note.body}" if note.subject else note.body
    if note.url:
        text += f"\n\n{settings.SITE_URL}{note.url}"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status == 200


DELIVERY = {
    Channel.EMAIL: _deliver_email,
    Channel.TELEGRAM: _deliver_telegram,
    Channel.INAPP: lambda note: True,  # nothing to push; it is read in the cabinet
}


def flush(limit=200):
    """Send everything that is due. Returns (sent, failed, skipped)."""
    due = Notification.objects.filter(
        status=Status.PENDING, scheduled_for__lte=timezone.now()
    ).select_related("recipient")[:limit]

    sent = failed = skipped = 0
    for note in due:
        handler = DELIVERY.get(note.channel)
        if handler is None:
            note.mark_failed("unknown channel")
            failed += 1
            continue
        try:
            if handler(note):
                note.mark_sent()
                sent += 1
            else:
                skipped += 1
        except Exception as exc:  # network/SMTP failures must not stop the queue
            logger.warning("notification %s failed: %s", note.pk, exc)
            note.mark_failed(exc)
            failed += 1
    return sent, failed, skipped
