from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0002_payment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="room",
            name="image",
            field=models.ImageField(blank=True, null=True, upload_to="room/"),
        ),
    ]
