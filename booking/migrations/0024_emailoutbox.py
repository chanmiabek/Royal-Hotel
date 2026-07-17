import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('booking', '0023_production_operations')]

    operations = [
        migrations.CreateModel(
            name='EmailOutbox',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject', models.CharField(max_length=255)),
                ('body', models.TextField()),
                ('from_email', models.EmailField(blank=True, max_length=254)),
                ('recipients', models.JSONField(default=list)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('SENT', 'Sent'), ('FAILED', 'Failed')], db_index=True, default='PENDING', max_length=10)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('last_error', models.TextField(blank=True)),
                ('available_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['created_at']},
        ),
    ]
