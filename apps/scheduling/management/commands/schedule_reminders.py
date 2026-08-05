from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.scheduling.models import Lesson, LessonStatus
from apps.scheduling.services import schedule_reminders_for


class Command(BaseCommand):
    help = "Ставит в очередь напоминания об уроках на ближайшие дни. Безопасно запускать часто."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=3)

    def handle(self, *args, **options):
        horizon = timezone.now() + timedelta(days=options["days"])
        lessons = Lesson.objects.filter(
            status=LessonStatus.SCHEDULED,
            starts_at__gte=timezone.now(),
            starts_at__lte=horizon,
        ).prefetch_related("participants__student")

        for lesson in lessons:
            schedule_reminders_for(lesson)
        self.stdout.write(self.style.SUCCESS(f"обработано уроков: {lessons.count()}"))
