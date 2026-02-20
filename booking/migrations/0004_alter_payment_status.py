from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("booking", "0003_alter_room_image_upload_path"),
    ]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("SUCCEEDED", "Succeeded"),
                    ("FAILED", "Failed"),
                    ("CANCELLED", "Cancelled"),
                    ("REFUNDED", "Refunded"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),
    ]
