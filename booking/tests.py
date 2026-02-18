from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from .models import Booking, Room


class PublicPagesTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(
            title="Deluxe Suite",
            category="DLX",
            description="Large suite with city view",
            price="120.00",
            size=450,
            beds="1 King Bed",
            capacity=2,
            available=True,
        )

    def test_home_page_loads(self):
        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)

    def test_register_page_loads(self):
        response = self.client.get(reverse("register"))
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
        response = self.client.get(reverse("payment_page", args=[booking.id]))
        self.assertEqual(response.status_code, 200)
