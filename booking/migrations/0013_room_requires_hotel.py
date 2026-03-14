from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0012_userprofile_mobile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="room",
            name="hotel",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rooms",
                to="booking.hotel",
            ),
        ),
    ]
