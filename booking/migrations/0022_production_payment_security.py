import uuid

from django.db import migrations, models
import django.db.models.expressions


def _check_constraint(condition, name):
    try:
        return models.CheckConstraint(condition=condition, name=name)
    except TypeError:
        return models.CheckConstraint(check=condition, name=name)


def populate_booking_tokens(apps, schema_editor):
    Booking = apps.get_model('booking', 'Booking')
    for booking in Booking.objects.filter(public_token__isnull=True).iterator():
        booking.public_token = uuid.uuid4()
        booking.save(update_fields=['public_token'])


class Migration(migrations.Migration):
    dependencies = [('booking', '0021_hotel_latitude_hotel_longitude_and_more')]

    operations = [
        migrations.AddField(
            model_name='booking', name='public_token',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(populate_booking_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='booking', name='public_token',
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True),
        ),
        migrations.AlterField(
            model_name='payment', name='provider',
            field=models.CharField(choices=[('PAYPAL', 'PayPal'), ('MPESA', 'M-Pesa'), ('PAYSTACK', 'Paystack')], max_length=20),
        ),
        migrations.AddConstraint(
            model_name='booking',
            constraint=_check_constraint(models.Q(('check_out__gt', django.db.models.expressions.F('check_in'))), 'booking_checkout_after_checkin'),
        ),
        migrations.AddConstraint(
            model_name='booking',
            constraint=_check_constraint(models.Q(('guests__gte', 1)), 'booking_guests_positive'),
        ),
        migrations.AddConstraint(
            model_name='booking',
            constraint=_check_constraint(models.Q(('total_price__isnull', True), ('total_price__gte', 0), _connector='OR'), 'booking_total_nonnegative'),
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.UniqueConstraint(condition=models.Q(('reference__isnull', False), models.Q(('reference', ''), _negated=True)), fields=('provider', 'reference'), name='unique_payment_provider_reference'),
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=_check_constraint(models.Q(('amount__gt', 0)), 'payment_amount_positive'),
        ),
    ]
