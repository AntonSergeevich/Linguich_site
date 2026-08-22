from django.db import migrations
from django.db.models import F


def mark_history_as_confirmed(apps, schema_editor):
    """Уроки, отмеченные до появления автоотметки, ставил человек.

    Без этого вся история попадёт в плашку «отметилось само, проверьте» —
    преподаватель откроет журнал и увидит сотню занятий на подтверждение.
    """
    Lesson = apps.get_model("scheduling", "Lesson")
    Lesson.objects.filter(status="completed", completed_by__isnull=True).update(
        completed_by=F("teacher"), completed_at=F("starts_at")
    )


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0002_lesson_completed_at_lesson_completed_by")]

    operations = [
        migrations.RunPython(mark_history_as_confirmed, migrations.RunPython.noop),
    ]
