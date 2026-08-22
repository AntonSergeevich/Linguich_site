from django.core.management.base import BaseCommand

from apps.scheduling.services import autocomplete_lessons


class Command(BaseCommand):
    help = (
        "Отмечает проведёнными уроки, у которых вышла отсрочка после конца. "
        "Безопасно запускать часто: уже отмеченные не трогает."
    )

    def handle(self, *args, **options):
        done = autocomplete_lessons()
        self.stdout.write(self.style.SUCCESS(f"отмечено проведёнными: {done}"))
