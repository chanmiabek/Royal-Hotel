from datetime import date, timedelta

from django.test import TestCase
from django.conf import settings
from django.urls import reverse

from .models import Booking, Hotel, Room


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
        self.assertEqual(response.json(), {"status": "ok"})

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
        response = self.client.get(reverse("payment_page", args=[booking.id]))
        self.assertEqual(response.status_code, 200)

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
