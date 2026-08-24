from django.db import migrations


def set_link(apps, schema_editor):
    """Адрес разработчика на уже существующей строке настроек.

    Значения по умолчанию срабатывают только при создании записи, а она
    создана давно: без этого шага поле осталось бы пустым, и подпись в
    подвале была бы просто текстом без ссылки.
    """
    SiteSettings = apps.get_model("school", "SiteSettings")
    SiteSettings.objects.filter(developer_url="").update(
        developer_url="https://s-poryadok.ru/"
    )


class Migration(migrations.Migration):
    dependencies = [("school", "0007_developer_credit")]

    operations = [migrations.RunPython(set_link, migrations.RunPython.noop)]
