from datetime import date, timedelta

from django.test import TestCase
from django.test import override_settings
from django.conf import settings
from django.urls import reverse
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
import hashlib
import hmac
import json

from .models import Booking, EmailOutbox, Hotel, HotelDocument, HotelApplication, Payment, Room


class PublicPagesTests(TestCase):
    def setUp(self):
        self.hotel = Hotel.objects.create(
            name="Royal Test Hotel",
            city="Nairobi",
            country="Kenya",
            is_active=True,
            is_approved=True,
        )
        self.room = Room.objects.create(
            title="Deluxe Suite",
            category="DLX",
            description="Large suite with city view",
            price="120.00",
            size=450,
            beds="1 King Bed",
            capacity=2,
            available=True,
            hotel=self.hotel,
        )

    def test_home_page_loads(self):
        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)

    def test_register_page_loads(self):
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 200)

    def test_health_check_returns_ok(self):
        response = self.client.get(reverse("health_check"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "database": "ok", "cache": "ok"})

    def test_liveness_does_not_depend_on_database_query(self):
        response = self.client.get(reverse("liveness_check"))
        self.assertEqual(response.status_code, 200)

    def test_booking_page_loads_and_prefills_room(self):
        response = self.client.get(reverse("booking"), {"room": self.room.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "selected")

    def test_payment_page_loads(self):
        booking = Booking.objects.create(
            room=self.room,
            first_name="Jane",
            last_name="Doe",
            mobile="+1234567890",
            email="jane@example.com",
            check_in=date.today(),
            check_out=date.today() + timedelta(days=2),
            guests=2,
            total_price="240.00",
        )
        response = self.client.get(
            reverse("payment_page", args=[booking.id]),
            {"access_key": str(booking.public_token)},
        )
        self.assertEqual(response.status_code, 200)

    def test_payment_page_rejects_guessed_booking_id(self):
        booking = Booking.objects.create(
            room=self.room, first_name="Private", last_name="Guest",
            mobile="+254700000000", email="private@example.com",
            check_in=date.today(), check_out=date.today() + timedelta(days=1),
            guests=1, total_price="120.00",
        )
        response = self.client.get(reverse("payment_page", args=[booking.id]))
        self.assertEqual(response.status_code, 404)

    def test_mpesa_callback_rejects_wrong_amount(self):
        booking = Booking.objects.create(
            room=self.room, first_name="M", last_name="Pesa",
            mobile="254700000000", email="mpesa@example.com",
            check_in=date.today(), check_out=date.today() + timedelta(days=1),
            guests=1, total_price="120.00",
        )
        payment = Payment.objects.create(
            booking=booking, provider="MPESA", status="PENDING",
            amount="120.00", currency="KES", reference="checkout-test",
        )
        payload = {
            "Body": {"stkCallback": {
                "CheckoutRequestID": "checkout-test", "ResultCode": 0,
                "CallbackMetadata": {"Item": [
                    {"Name": "Amount", "Value": 1},
                    {"Name": "MpesaReceiptNumber", "Value": "TEST123"},
                ]},
            }}
        }
        response = self.client.post(
            reverse("mpesa_callback"), data=payload, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db(); booking.refresh_from_db()
        self.assertEqual(payment.status, "FAILED")
        self.assertEqual(booking.status, "PENDING")

    @override_settings(PAYSTACK_WEBHOOK_SECRET='webhook-secret')
    def test_paystack_webhook_requires_valid_signature_and_confirms_matching_payment(self):
        booking = Booking.objects.create(
            room=self.room, first_name='Pay', last_name='Stack', mobile='254700000000',
            email='paystack@example.com', check_in=date.today(),
            check_out=date.today() + timedelta(days=1), guests=1, total_price='120.00',
        )
        payment = Payment.objects.create(
            booking=booking, provider='PAYSTACK', amount='120.00', currency='KES', reference='RH-test',
        )
        payload = json.dumps({'event': 'charge.success', 'data': {
            'id': 987, 'reference': 'RH-test', 'status': 'success', 'amount': 12000,
            'currency': 'KES', 'metadata': {'booking_id': booking.id},
        }}).encode()
        signature = hmac.new(b'webhook-secret', payload, hashlib.sha512).hexdigest()
        response = self.client.post(
            reverse('paystack_webhook'), data=payload, content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db(); booking.refresh_from_db()
        self.assertEqual(payment.status, 'SUCCEEDED')
        self.assertEqual(payment.provider_receipt, '987')
        self.assertEqual(booking.status, 'CONFIRMED')

    def test_jwt_me_requires_bearer_token(self):
        response = self.client.get(reverse("jwt_me"))
        self.assertEqual(response.status_code, 401)


class SettingsDefaultsTests(TestCase):
    def test_mpesa_callback_default_is_absolute_https_url(self):
        self.assertEqual(
            settings.MPESA_CALLBACK_URL,
            "https://royal-hotel-mwb5.onrender.com/payments/mpesa/callback/",
        )

    def test_email_defaults_do_not_enable_smtp_without_credentials(self):
        self.assertEqual(settings.EMAIL_HOST, "smtp.gmail.com")
        self.assertEqual(settings.EMAIL_PORT, 587)
        self.assertEqual(settings.EMAIL_HOST_USER, "")
        self.assertEqual(settings.EMAIL_HOST_PASSWORD, "")


class ProductionSecurityTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff', password='safe-password', is_staff=True)

    def test_staff_without_platform_permission_cannot_open_custom_admin(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertRedirects(response, reverse('index'))

    def test_explicit_platform_permission_allows_admin_access(self):
        permission = Permission.objects.get(codename='access_platform_admin')
        self.staff.user_permissions.add(permission)
        self.client.force_login(self.staff)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)

    @override_settings(EMAIL_QUEUE_ENABLED=True)
    def test_production_email_is_queued(self):
        from booking.views import send_mail
        send_mail('Subject', 'Body', 'from@example.com', ['to@example.com'])
        self.assertTrue(EmailOutbox.objects.filter(subject='Subject', status='PENDING').exists())

    def test_partner_document_rejects_disguised_executable(self):
        application = HotelApplication.objects.create(
            hotel_name='Secure Hotel', contact_name='Owner', contact_email='owner@example.com',
            contact_phone='254700000000', agreed_to_terms=True,
        )
        document = HotelDocument(
            application=application, document_type='LICENSE',
            file=SimpleUploadedFile('license.pdf', b'MZ-not-a-pdf', content_type='application/pdf'),
        )
        with self.assertRaises(Exception):
            document.full_clean()
