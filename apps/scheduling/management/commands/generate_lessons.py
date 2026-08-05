from django.core.management.base import BaseCommand

from apps.scheduling.services import generate_lessons


class Command(BaseCommand):
    help = "Материализует занятия групп из недельных слотов. Идемпотентно, можно гонять каждую ночь."

    def add_arguments(self, parser):
        parser.add_argument("--weeks", type=int, default=4)

    def handle(self, *args, **options):
        created = generate_lessons(weeks=options["weeks"])
        self.stdout.write(self.style.SUCCESS(f"создано занятий: {created}"))
