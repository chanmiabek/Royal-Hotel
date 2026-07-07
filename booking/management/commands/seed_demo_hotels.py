from __future__ import annotations

from dataclasses import dataclass
from itertools import cycle
from pathlib import Path
import re

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction

from booking.models import Hotel, Room, UserProfile


@dataclass(frozen=True)
class _RoomTemplate:
    category: str
    title: str
    price: int
    size_sqft: int
    beds: str
    capacity: int
    amenities: str
    description: str


def _list_source_images(subdir: str) -> list[Path]:
    media_base = Path(getattr(settings, "MEDIA_ROOT", "")) / subdir
    static_base = Path(settings.BASE_DIR) / "static" / "img" / subdir
    fallback_static_base = Path(settings.BASE_DIR) / "static" / "img" / "room"

    base = media_base if media_base.exists() and media_base.is_dir() else static_base
    if subdir == "hotel" and (not base.exists() or not base.is_dir()):
        base = fallback_static_base
    if not base.exists() or not base.is_dir():
        return []

    images: list[str] = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.jfif", "*.webp"):
        images.extend([p.name for p in base.glob(ext)])
    return [base / name for name in sorted(dict.fromkeys(images))]


def _store_demo_images(subdir: str) -> list[str]:
    stored_names: list[str] = []
    for source_path in _list_source_images(subdir):
        storage_name = f"{subdir}/{source_path.name}"
        if not default_storage.exists(storage_name):
            with source_path.open("rb") as source_file:
                storage_name = default_storage.save(storage_name, File(source_file))
        stored_names.append(storage_name)
    return stored_names


def _demo_hotels() -> list[dict]:
    return [
        {
            "name": "Royal Gardens Hotel",
            "star_rating": 5,
            "city": "Nairobi",
            "country": "Kenya",
            "address": "Kenyatta Avenue",
            "phone": "+254 700 000 001",
            "email": "reservations@royalgardens.example",
            "description": "A modern city hotel with elegant rooms, fast WiFi, and premium service.",
        },
        {
            "name": "Sunset View Resort",
            "star_rating": 4,
            "city": "Mombasa",
            "country": "Kenya",
            "address": "Nyali Beach Road",
            "phone": "+254 700 000 002",
            "email": "hello@sunsetview.example",
            "description": "Beach-inspired comfort with spacious rooms, ocean vibes, and calm evenings.",
        },
        {
            "name": "Skyline Suites",
            "star_rating": 4,
            "city": "Nairobi",
            "country": "Kenya",
            "address": "Upper Hill",
            "phone": "+254 700 000 003",
            "email": "stay@skylinesuites.example",
            "description": "Business-friendly suites with quiet workspaces and quick access to the city.",
        },
        {
            "name": "Coastal Breeze Inn",
            "star_rating": 3,
            "city": "Kilifi",
            "country": "Kenya",
            "address": "Bofa Road",
            "phone": "+254 700 000 004",
            "email": "bookings@coastalbreeze.example",
            "description": "Relaxed rooms, fresh air, and a warm welcome — perfect for a weekend getaway.",
        },
        {
            "name": "Highland Retreat Lodge",
            "star_rating": 5,
            "city": "Nyeri",
            "country": "Kenya",
            "address": "Aberdare Foothills",
            "phone": "+254 700 000 005",
            "email": "frontdesk@highlandretreat.example",
            "description": "A serene retreat with cozy rooms, scenic views, and a premium lodge experience.",
        },
        {
            "name": "Savannah Grand Hotel",
            "star_rating": 4,
            "city": "Nakuru",
            "country": "Kenya",
            "address": "Kenyatta Avenue",
            "phone": "+254 700 000 006",
            "email": "reservations@savannahgrand.example",
            "description": "Comfort meets convenience with stylish rooms and thoughtful amenities.",
        },
    ]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    return slug.strip("-") or "hotel"


def _ensure_owner_account(hotel: Hotel, password: str, reset_password: bool = False) -> tuple[User, bool]:
    slug = _slugify(hotel.name)
    email = f"{slug}.owner@example.com"

    user = User.objects.filter(username__iexact=email).first() or User.objects.filter(email__iexact=email).first()
    created = False
    if user is None:
        user = User(username=email, email=email)
        user.set_password(password)
        parts = [part for part in (hotel.name or "").split() if part]
        if parts:
            user.first_name = parts[0]
            if len(parts) > 1:
                user.last_name = " ".join(parts[1:])[:150]
        user.save()
        created = True
    elif reset_password:
        user.set_password(password)
        user.save(update_fields=["password"])

    profile, _ = UserProfile.objects.get_or_create(user=user)
    if profile.user_type != "OWNER":
        profile.user_type = "OWNER"
        profile.save(update_fields=["user_type"])

    if hotel.owner_id is None:
        hotel.owner = user
        hotel.save(update_fields=["owner"])
    return user, created


def _room_templates(hotel_name: str, city: str, price_offset: int) -> list[_RoomTemplate]:
    return [
        _RoomTemplate(
            category="STD",
            title=f"Standard Room - {hotel_name}",
            price=4500 + price_offset,
            size_sqft=260,
            beds="1 Queen",
            capacity=2,
            amenities="WiFi, TV, Shower, Desk",
            description=f"Simple, clean and comfortable. Ideal for short stays in {city}.",
        ),
        _RoomTemplate(
            category="PRE",
            title=f"Premium Room - {hotel_name}",
            price=6500 + price_offset,
            size_sqft=320,
            beds="1 King",
            capacity=2,
            amenities="WiFi, TV, Shower, Balcony, Mini Bar",
            description=f"Extra space, better views, and added comfort for your stay in {city}.",
        ),
        _RoomTemplate(
            category="SLV",
            title=f"Silver Room - {hotel_name}",
            price=5500 + price_offset,
            size_sqft=300,
            beds="2 Single(s)",
            capacity=2,
            amenities="WiFi, TV, Shower, Coffee Maker",
            description=f"A balanced option with great value and comfort in {city}.",
        ),
        _RoomTemplate(
            category="DLX",
            title=f"Deluxe Room - {hotel_name}",
            price=8500 + price_offset,
            size_sqft=380,
            beds="1 King",
            capacity=3,
            amenities="WiFi, TV, Bathtub, Balcony, Mini Bar",
            description=f"Designed for comfort with premium finishes and relaxing space in {city}.",
        ),
        _RoomTemplate(
            category="EXE",
            title=f"Executive Room - {hotel_name}",
            price=12000 + price_offset,
            size_sqft=450,
            beds="1 King",
            capacity=3,
            amenities="WiFi, TV, Bathtub, Lounge Area, Room Service",
            description=f"Perfect for business travelers — extra room, extra comfort, and privacy in {city}.",
        ),
        _RoomTemplate(
            category="APT",
            title=f"Apartment Suite - {hotel_name}",
            price=16000 + price_offset,
            size_sqft=620,
            beds="2 Queen",
            capacity=4,
            amenities="WiFi, TV, Kitchen, Lounge Area, Balcony, Room Service",
            description=f"Spacious suite for families and longer stays in {city}.",
        ),
    ]


class Command(BaseCommand):
    help = "Create 6 demo hotels and 6 rooms per hotel using images from the media folder."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demo hotels/rooms by name before creating them.",
        )
        parser.add_argument(
            "--owner-password",
            default="Owner12345!",
            help="Password for created demo owner accounts (default: Owner12345!).",
        )
        parser.add_argument(
            "--reset-owner-password",
            action="store_true",
            help="Reset password for existing demo owner accounts.",
        )
        parser.add_argument(
            "--refresh-images",
            action="store_true",
            help="Update existing demo hotels and rooms with the stored demo images.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        hotel_images = _store_demo_images("hotel")
        room_images = _store_demo_images("room")

        if options.get("reset"):
            demo_names = [h["name"] for h in _demo_hotels()]
            Room.objects.filter(hotel__name__in=demo_names).delete()
            Hotel.objects.filter(name__in=demo_names).delete()

        room_image_pool = cycle(room_images) if room_images else None
        hotel_image_pool = cycle(hotel_images) if hotel_images else None

        created_hotels = 0
        created_rooms = 0
        created_owners = 0
        owner_password = options.get("owner_password") or "Owner12345!"
        reset_owner_password = bool(options.get("reset_owner_password"))
        refresh_images = bool(options.get("refresh_images"))
        owner_accounts: list[tuple[str, bool]] = []

        for idx, hotel_data in enumerate(_demo_hotels(), start=1):
            defaults = dict(hotel_data)
            if hotel_image_pool:
                defaults["image"] = next(hotel_image_pool)

            hotel, hotel_created = Hotel.objects.get_or_create(
                name=hotel_data["name"],
                defaults=defaults,
            )
            if hotel_created:
                created_hotels += 1
            elif refresh_images and hotel_image_pool:
                hotel.image = next(hotel_image_pool)
                hotel.save(update_fields=["image"])

            owner, owner_created = _ensure_owner_account(
                hotel,
                password=owner_password,
                reset_password=reset_owner_password,
            )
            if owner_created:
                created_owners += 1
            owner_accounts.append((owner.username, owner_created))

            templates = _room_templates(
                hotel_name=hotel.name,
                city=hotel.city or "your destination",
                price_offset=idx * 250,
            )

            for tpl in templates:
                room_defaults = {
                    "category": tpl.category,
                    "description": tpl.description,
                    "amenities": tpl.amenities,
                    "price": tpl.price,
                    "size": tpl.size_sqft,
                    "beds": tpl.beds,
                    "available": True,
                    "capacity": tpl.capacity,
                    "is_approved": True,
                    "owner": owner,
                }
                if room_image_pool:
                    room_defaults["image"] = next(room_image_pool)

                room, room_created = Room.objects.get_or_create(
                    hotel=hotel,
                    title=tpl.title,
                    defaults=room_defaults,
                )
                if room_created:
                    created_rooms += 1
                else:
                    update_fields = []
                    if refresh_images and room_image_pool:
                        room.image = next(room_image_pool)
                        update_fields.append("image")
                    if room.owner_id is None and owner is not None:
                        room.owner = owner
                        update_fields.append("owner")
                    if update_fields:
                        room.save(update_fields=update_fields)

        self.stdout.write(
            self.style.SUCCESS(
                "Demo data ready. "
                f"Hotels created: {created_hotels}. Rooms created: {created_rooms}. Owners created: {created_owners}."
            )
        )

        unique_accounts = list(dict.fromkeys(owner_accounts))
        self.stdout.write("Demo owners (login with email + password):")
        for email, created in unique_accounts:
            suffix = " (created)" if created else ""
            self.stdout.write(f" - {email}{suffix}")
        self.stdout.write(f"Password: {owner_password}")
