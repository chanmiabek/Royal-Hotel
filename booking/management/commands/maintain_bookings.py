import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from booking.models import Booking, BookingCommission, EmailOutbox, HotelPayout, Payment
from booking.views import _expire_stale_pending_bookings, _mpesa_query_stk_status

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


logger = logging.getLogger(__name__)
PAYMENT_REMINDER_AFTER = timedelta(hours=10)


class Command(BaseCommand):
    help = "Expire abandoned bookings and reconcile pending provider payments."

    def add_arguments(self, parser):
        parser.add_argument('--skip-reconciliation', action='store_true')

    def handle(self, *args, **options):
        reminders = self._queue_payment_reminders()
        expired = _expire_stale_pending_bookings()
        settlements = self._create_settlements()
        payouts = self._release_payouts()
        completed = Booking.objects.filter(
            status='CONFIRMED', check_out__lte=timezone.localdate(),
        ).update(status='COMPLETED', updated_at=timezone.now())
        reconciled = 0
        if not options['skip_reconciliation']:
            cutoff = timezone.now() - timedelta(
                minutes=getattr(settings, 'PAYMENT_RECONCILE_MINUTES', 10),
            )
            for payment in Payment.objects.filter(status='PENDING', created_at__lte=cutoff).iterator():
                if self._reconcile(payment):
                    reconciled += 1
        self.stdout.write(self.style.SUCCESS(
            f'Queued {reminders} reminders; expired {expired}; settlements {settlements}; payouts {payouts}; completed {completed}; reconciled {reconciled} payments.'
        ))

    def _create_settlements(self):
        created = 0
        for payment in Payment.objects.filter(status='SUCCEEDED').select_related('booking__room__hotel'):
            booking = payment.booking
            hotel = booking.room.hotel if booking.room_id else None
            if not hotel or hasattr(booking, 'commission'):
                continue
            rate = hotel.commission_rate
            commission_amount = (payment.amount * rate).quantize(payment.amount.as_tuple().exponent)
            hotel_amount = payment.amount - commission_amount
            BookingCommission.objects.create(
                booking=booking, hotel=hotel, gross_amount=payment.amount,
                commission_rate=rate, commission_amount=commission_amount,
                hotel_amount=hotel_amount,
            )
            HotelPayout.objects.create(
                hotel=hotel, booking=booking, method=hotel.payout_method,
                account_reference=hotel.payout_account_reference,
                amount=hotel_amount, currency=payment.currency,
                scheduled_for=payment.updated_at + timedelta(hours=getattr(settings, 'PAYOUT_HOLD_HOURS', 6)),
            )
            created += 1
        return created

    def _release_payouts(self):
        if not getattr(settings, 'PAYSTACK_TRANSFER_ENABLED', False) or requests is None:
            return 0
        released = 0
        for payout in HotelPayout.objects.filter(status='PENDING', scheduled_for__lte=timezone.now()).select_related('hotel'):
            hotel = payout.hotel
            try:
                recipient = payout.account_reference or self._create_recipient(hotel)
                if not recipient:
                    continue
                response = requests.post(
                    f"{settings.PAYSTACK_BASE_URL}/transfer",
                    headers={'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}', 'Content-Type': 'application/json'},
                    json={'source': 'balance', 'amount': int(payout.amount * 100), 'recipient': recipient,
                          'reference': f'royal-payout-{payout.id}', 'reason': f'Royal Hotel booking #{payout.booking_id}',
                          'currency': payout.currency}, timeout=20,
                )
                data = response.json()
                if response.ok and data.get('status'):
                    payout.status = 'PROCESSING'
                    payout.reference = data.get('data', {}).get('transfer_code') or f'royal-payout-{payout.id}'
                    payout.account_reference = recipient
                    payout.save(update_fields=['status', 'reference', 'account_reference', 'updated_at'])
                    payout.booking.commission.status = 'RELEASED'
                    payout.booking.commission.save(update_fields=['status', 'updated_at'])
                    released += 1
            except Exception:
                logger.exception('Payout release failed for payout %s', payout.pk)
        return released

    def _create_recipient(self, hotel):
        method = hotel.payout_method
        if method == 'BANK' and hotel.bank_account_number and hotel.bank_branch:
            payload = {'type': 'kepss', 'name': hotel.bank_account_name or hotel.name,
                       'account_number': hotel.bank_account_number, 'bank_code': hotel.bank_branch,
                       'currency': 'KES'}
        elif method == 'MOBILE_MONEY' and hotel.mobile_money_number:
            payload = {'type': 'mobile_money', 'name': hotel.name,
                       'account_number': hotel.mobile_money_number,
                       'bank_code': settings.PAYSTACK_MOBILE_MONEY_CODE, 'currency': 'KES'}
        else:
            return ''
        response = requests.post(
            f"{settings.PAYSTACK_BASE_URL}/transferrecipient",
            headers={'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}', 'Content-Type': 'application/json'},
            json=payload, timeout=20,
        )
        data = response.json()
        return data.get('data', {}).get('recipient_code', '') if response.ok and data.get('status') else ''

    def _queue_payment_reminders(self):
        now = timezone.now()
        reminder_cutoff = now - PAYMENT_REMINDER_AFTER
        expiry_cutoff = now - timedelta(hours=12)
        queued = 0
        for booking in Booking.objects.filter(
            status='PENDING',
            email__isnull=False,
            created_at__lte=reminder_cutoff,
            created_at__gt=expiry_cutoff,
        ).iterator():
            subject = f'Payment reminder for Royal Hotel Booking #{booking.id}'
            if EmailOutbox.objects.filter(subject=subject).exists():
                continue
            EmailOutbox.objects.create(
                subject=subject,
                body=(
                    f'Hello {booking.first_name},\n\n'
                    f'Please complete payment for booking #{booking.id} within 2 hours '
                    'to keep your room reservation. Unpaid bookings expire after 12 hours.\n\n'
                    'Thank you for choosing Royal Hotel.'
                ),
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', ''),
                recipients=[booking.email],
            )
            queued += 1
        return queued

    def _reconcile(self, payment):
        if requests is None or not payment.reference:
            return False
        if payment.provider == 'PAYSTACK':
            return self._reconcile_paystack(payment)
        if payment.provider == 'PAYPAL':
            return self._reconcile_paypal(payment)
        if payment.provider == 'MPESA':
            result, error = _mpesa_query_stk_status(payment)
            if error or not result:
                return False
            code = str(result.get('ResultCode', ''))
            if code and code != '0':
                payment.status = 'CANCELLED' if code == '1032' else 'FAILED'
                payment.raw_response = {**(payment.raw_response or {}), 'reconciliation': result}
                payment.save(update_fields=['status', 'raw_response', 'updated_at'])
                return True
        return False

    def _reconcile_paystack(self, payment):
        secret = getattr(settings, 'PAYSTACK_SECRET_KEY', '')
        if not secret:
            return False
        try:
            response = requests.get(
                f"{settings.PAYSTACK_BASE_URL}/transaction/verify/{payment.reference}",
                headers={'Authorization': f'Bearer {secret}'}, timeout=20,
            )
            payload = response.json()
        except Exception:
            logger.exception('Paystack reconciliation failed for payment %s', payment.pk)
            return False
        data = payload.get('data') or {}
        valid = (
            response.ok and payload.get('status') is True and data.get('status') == 'success'
            and int(data.get('amount') or 0) == int(payment.amount * 100)
            and str(data.get('currency') or '').upper() == payment.currency.upper()
            and str((data.get('metadata') or {}).get('booking_id')) == str(payment.booking_id)
        )
        if not valid:
            return False
        return self._mark_succeeded(payment, payload, str(data.get('id') or payment.reference))

    def _reconcile_paypal(self, payment):
        client_id = getattr(settings, 'PAYPAL_CLIENT_ID', '')
        secret = getattr(settings, 'PAYPAL_CLIENT_SECRET', '')
        if not client_id or not secret:
            return False
        try:
            token_response = requests.post(
                f"{settings.PAYPAL_BASE_URL}/v1/oauth2/token",
                data={'grant_type': 'client_credentials'}, auth=(client_id, secret), timeout=15,
            )
            token_response.raise_for_status()
            token = token_response.json()['access_token']
            response = requests.get(
                f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders/{payment.reference}",
                headers={'Authorization': f'Bearer {token}'}, timeout=15,
            )
            payload = response.json()
        except Exception:
            logger.exception('PayPal reconciliation failed for payment %s', payment.pk)
            return False
        if not response.ok or payload.get('status') != 'COMPLETED':
            return False
        unit = (payload.get('purchase_units') or [{}])[0]
        amount = unit.get('amount') or {}
        valid = (
            str(amount.get('value')) == str(payment.amount)
            and str(amount.get('currency_code') or '').upper() == payment.currency.upper()
        )
        return self._mark_succeeded(payment, payload, payment.reference) if valid else False

    def _mark_succeeded(self, payment, payload, receipt):
        with transaction.atomic():
            locked = Payment.objects.select_for_update().select_related('booking').get(pk=payment.pk)
            if locked.status == 'SUCCEEDED':
                return False
            locked.status = 'SUCCEEDED'
            locked.provider_receipt = receipt
            locked.raw_response = payload
            locked.save(update_fields=['status', 'provider_receipt', 'raw_response', 'updated_at'])
            if locked.booking.status == 'PENDING':
                locked.booking.status = 'CONFIRMED'
                locked.booking.save(update_fields=['status', 'updated_at'])
        return True
