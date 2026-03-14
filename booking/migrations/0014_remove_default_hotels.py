from django.db import migrations


def remove_default_hotels(apps, schema_editor):
    Hotel = apps.get_model("booking", "Hotel")

    Hotel.objects.filter(
        name__in=["Royal Hotel", "Default Hotel"],
        owner__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0013_room_requires_hotel"),
    ]

    operations = [
        migrations.RunPython(remove_default_hotels, migrations.RunPython.noop),
    ]
