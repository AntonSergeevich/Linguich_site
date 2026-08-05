from django.core.management.base import BaseCommand

from apps.notifications.services import flush


class Command(BaseCommand):
    help = "Отправляет уведомления из очереди. Запускать по cron раз в минуту."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **options):
        sent, failed, skipped = flush(limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(f"отправлено {sent}, ошибок {failed}, пропущено {skipped}")
        )
