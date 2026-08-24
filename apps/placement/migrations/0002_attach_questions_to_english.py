from django.db import migrations


def attach_to_english(apps, schema_editor):
    """Старый банк — английский, хотя язык у вопросов не был проставлен.

    Движок подставлял вопросы без языка как «общие», поэтому тест по
    китайскому спрашивал по-английски. Пока язык не проставлен, эту ошибку
    не исправить: она выглядит как задуманное поведение.
    """
    Question = apps.get_model("placement", "Question")
    Language = apps.get_model("school", "Language")
    english = Language.objects.filter(slug="english").first()
    if english is None:
        return
    Question.objects.filter(language__isnull=True).update(language=english)


def detach(apps, schema_editor):
    Question = apps.get_model("placement", "Question")
    Language = apps.get_model("school", "Language")
    english = Language.objects.filter(slug="english").first()
    if english is not None:
        Question.objects.filter(language=english).update(language=None)


class Migration(migrations.Migration):
    dependencies = [
        ("placement", "0001_initial"),
        ("school", "0005_merge_20260822_2144"),
    ]

    operations = [migrations.RunPython(attach_to_english, detach)]
