import booking.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('booking', '0022_production_payment_security')]

    operations = [
        migrations.AlterModelOptions(
            name='userprofile',
            options={'permissions': [('access_platform_admin', 'Can access the platform administration workspace')]},
        ),
        migrations.AddField(
            model_name='payment', name='provider_receipt',
            field=models.CharField(blank=True, db_index=True, max_length=120, null=True),
        ),
        migrations.AlterField(
            model_name='hotel', name='payout_method',
            field=models.CharField(blank=True, choices=[('BANK', 'Bank Transfer'), ('MOBILE_MONEY', 'Mobile Money'), ('PAYPAL', 'PayPal'), ('PAYSTACK', 'Paystack')], default='BANK', max_length=20),
        ),
        migrations.AlterField(
            model_name='hotelapplication', name='payout_method',
            field=models.CharField(choices=[('BANK', 'Bank Transfer'), ('MOBILE_MONEY', 'Mobile Money'), ('PAYPAL', 'PayPal'), ('PAYSTACK', 'Paystack')], default='BANK', max_length=20),
        ),
        migrations.AlterField(
            model_name='hotelpayout', name='method',
            field=models.CharField(choices=[('BANK', 'Bank Transfer'), ('MOBILE_MONEY', 'Mobile Money'), ('PAYPAL', 'PayPal'), ('PAYSTACK', 'Paystack')], default='BANK', max_length=20),
        ),
        migrations.AlterField(
            model_name='hoteldocument', name='file',
            field=models.FileField(upload_to='hotel_docs/', validators=[booking.models.validate_private_document]),
        ),
        migrations.AlterField(
            model_name='hotelagreement', name='document',
            field=models.FileField(blank=True, null=True, upload_to='hotel_agreements/', validators=[booking.models.validate_private_document]),
        ),
        migrations.AddConstraint(
            model_name='payment',
            constraint=models.UniqueConstraint(
                condition=models.Q(provider_receipt__isnull=False) & ~models.Q(provider_receipt=''),
                fields=('provider', 'provider_receipt'), name='unique_payment_provider_receipt',
            ),
        ),
    ]
