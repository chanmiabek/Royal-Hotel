from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.core.validators import validate_email
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db.models import (
    Avg,
    Count,
    Exists,
    ExpressionWrapper,
    FloatField,
    Min,
    OuterRef,
    Q,
    Sum,
    Value,
)
from django.db import connection
from django.db.utils import ProgrammingError, OperationalError
from django.utils.translation import gettext as _
from django.utils.http import (
    url_has_allowed_host_and_scheme,
)
from decimal import Decimal, InvalidOperation
import json
import io
import base64
import secrets
from functools import wraps, lru_cache
from urllib.parse import urlencode
from django.contrib.auth.models import User
from datetime import datetime
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import (
    Room,
    Booking,
    ContactMessage,
    Payment,
    Review,
    UserProfile,
    PasswordResetCode,
    Hotel,
    HotelApplication,
    HotelDocument,
    HotelAgreement,
)

ROOM_AMENITIES = [
    "WiFi",
    "Air Conditioner",
    "Kitchen",
    "Bathtub",
    "Shower",
    "TV",
    "Mini Bar",
    "Balcony",
    "Parking",
    "Swimming Pool",
    "Gym",
    "Room Service",
]

try:
    import requests
except Exception:
    requests = None

try:
    import stripe
except Exception:
    stripe = None

try:
    import jwt  
    from jwt import PyJWKClient 
except Exception:
    jwt = None
    PyJWKClient = None


def _booking_tables_ready():
    required_tables = {Room._meta.db_table, Booking._meta.db_table, Hotel._meta.db_table}
    try:
        existing_tables = set(connection.introspection.table_names())
    except (ProgrammingError, OperationalError):
        return False
    return required_tables.issubset(existing_tables)


def _get_or_create_profile(user):
    if not user or not user.is_authenticated:
        return None
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def _ensure_owner_profile(user):
    profile = _get_or_create_profile(user)
    if profile and profile.user_type != 'OWNER':
        profile.user_type = 'OWNER'
        profile.save(update_fields=['user_type'])
    return profile


def _owner_has_hotel(user):
    if not user or not user.is_authenticated:
        return False
    return Hotel.objects.filter(owner=user).exists()


def _get_admin_emails():
    admin_emails = [email for _, email in getattr(settings, 'ADMINS', []) if email]
    if admin_emails:
        return list(dict.fromkeys(admin_emails))
    try:
        return list(
            User.objects.filter(is_staff=True)
            .exclude(email__isnull=True)
            .exclude(email='')
            .values_list('email', flat=True)
        )
    except Exception:
        return []


def _get_notification_emails():
    emails = _get_admin_emails()
    if emails:
        return emails

    fallback = (getattr(settings, "EMAIL_HOST_USER", "") or "").strip()
    if fallback:
        return [fallback]

    return []


def owner_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        profile = _get_or_create_profile(request.user)
        if not profile or profile.user_type != 'OWNER':
            messages.info(request, "Please complete the partnership form to access the owner dashboard.")
            return redirect('hotel_partner_apply')
        return view_func(request, *args, **kwargs)

    return _wrapped


def _with_booking_status(queryset):
    if not _booking_tables_ready():
        return queryset.none()
    today = datetime.now().date()
    confirmed_bookings = Booking.objects.filter(
        room=OuterRef('pk'),
        status='CONFIRMED',
        check_out__gt=today,
    )
    return queryset.annotate(is_booked=Exists(confirmed_bookings))


BOOKING_PAYMENT_WINDOW = timedelta(hours=24)


def _expire_stale_pending_bookings():
    cutoff = timezone.now() - BOOKING_PAYMENT_WINDOW
    succeeded_payments = Payment.objects.filter(booking=OuterRef("pk"), status="SUCCEEDED")
    try:
        stale = (
            Booking.objects.filter(status="PENDING", created_at__lte=cutoff)
            .annotate(has_success=Exists(succeeded_payments))
            .filter(has_success=False)
        )
        return stale.update(status="CANCELLED", updated_at=timezone.now())
    except (ProgrammingError, OperationalError):
        return 0


def _booking_is_expired_for_payment(booking: Booking) -> bool:
    if booking.status != "PENDING":
        return False
    if booking.created_at is None:
        return False
    if booking.created_at > timezone.now() - BOOKING_PAYMENT_WINDOW:
        return False
    return not booking.payments.filter(status="SUCCEEDED").exists()


def _redirect_booking_expired(request, booking: Booking):
    if booking.status == "PENDING":
        booking.status = "CANCELLED"
        booking.save(update_fields=["status", "updated_at"])

    messages.error(
        request,
        "This booking expired because payment was not completed within 24 hours. Please book again.",
    )

    params = {}
    if booking.room_id:
        params["room"] = booking.room_id
    if booking.check_in:
        params["check_in"] = booking.check_in.isoformat()
    if booking.check_out:
        params["check_out"] = booking.check_out.isoformat()
    if booking.guests:
        params["guests"] = booking.guests

    if params:
        return redirect(f"{reverse('booking')}?{urlencode(params)}")
    return redirect("booking")


def _mark_completed_bookings():
    today = datetime.now().date()
    try:
        _expire_stale_pending_bookings()
        Booking.objects.filter(
            status='CONFIRMED',
            check_out__lte=today,
        ).update(status='COMPLETED')
    except (ProgrammingError, OperationalError):
        return


# Home page view
def home(request):
    _mark_completed_bookings()
    if not _booking_tables_ready():
        return render(
            request,
            'home.html',
            {
                'hotels': [],
                'home_hotels': [],
                'hotels_count': 0,
                'map_query': 'Kenya',
                'star_filter_options': [],
            },
        )

    base_hotels = Hotel.objects.filter(is_active=True, is_approved=True)
    hotels = base_hotels.order_by('name')
    home_hotels = (
        base_hotels.annotate(
            starting_price=Min(
                'rooms__price',
                filter=Q(rooms__available=True, rooms__is_approved=True),
            ),
            review_count=Count('rooms__reviews', distinct=True),
            review_score=ExpressionWrapper(
                Avg('rooms__reviews__rating') * Value(2.0),
                output_field=FloatField(),
            ),
        )
        .order_by('-created_at')
        .select_related('owner')
    )[:6]

    hotels_count = base_hotels.count()
    star_counts = {
        row['star_rating']: row['count']
        for row in (
            base_hotels.exclude(star_rating__isnull=True)
            .values('star_rating')
            .annotate(count=Count('id'))
        )
    }
    star_filter_options = [
        {'stars': stars, 'count': star_counts.get(stars, 0)}
        for stars in (2, 3, 4, 5)
    ]

    map_query = 'Kenya'
    location_hotel = base_hotels.exclude(city='').exclude(country='').order_by('-created_at').first()
    if location_hotel:
        map_query = ", ".join([part for part in [location_hotel.city, location_hotel.country] if part]) or map_query
    return render(
        request,
        'home.html',
        {
            'hotels': hotels,
            'home_hotels': home_hotels,
            'hotels_count': hotels_count,
            'map_query': map_query,
            'star_filter_options': star_filter_options,
        },
    )

# Search view for home page form
def search(request):
    _mark_completed_bookings()
    search_type = (request.GET.get('search_type') or '').strip().lower()
    search_query = (request.GET.get('search') or '').strip()
    selected_hotel_id = (request.GET.get('hotel') or '').strip()

    if not _booking_tables_ready():
        messages.error(request, "Database is initializing. Please try again shortly.")
        if search_type == 'hotel':
            return redirect('hotel_list')
        return render(request, 'room.html', {'rooms': [], 'check_in': None, 'check_out': None})

    if search_type == 'hotel':
        if selected_hotel_id:
            try:
                hotel_id_int = int(selected_hotel_id)
            except (TypeError, ValueError):
                hotel_id_int = None
            if hotel_id_int and Hotel.objects.filter(
                id=hotel_id_int,
                is_active=True,
                is_approved=True,
            ).exists():
                return redirect('hotel_detail', hotel_id=hotel_id_int)

        params = {}
        if search_query:
            params['q'] = search_query
        params['view'] = 'list'
        params['sort'] = 'top'
        if params:
            return redirect(f"{reverse('hotel_list')}?{urlencode(params)}")
        return redirect('hotel_list')

    return room_list(request)


def room_list(request):
    _mark_completed_bookings()
    if not _booking_tables_ready():
        messages.error(request, "Database is initializing. Please try again shortly.")
        return render(request, 'room.html', {'rooms': [], 'check_in': None, 'check_out': None})
    rooms = _with_booking_status(
        Room.objects.filter(
            available=True,
            is_approved=True,
            hotel__is_approved=True,
            hotel__is_active=True,
        )
    )
    hotels = Hotel.objects.filter(is_active=True, is_approved=True).order_by('name')
    hotel_id = request.GET.get('hotel')
    date_in = request.GET.get('check_in')
    date_out = request.GET.get('check_out')
    guests = request.GET.get('guests')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    category = request.GET.get('category')
    sort = request.GET.get('sort')
    search_query = (request.GET.get('search') or '').strip()
    search_type = (request.GET.get('search_type') or '').strip().lower()
    check_in = None
    check_out = None

    if date_in and date_out:
        try:
            check_in = datetime.strptime(date_in, '%Y-%m-%d').date()
            check_out = datetime.strptime(date_out, '%Y-%m-%d').date()
            if check_in >= check_out:
                messages.error(request, "Check-out date must be after check-in date.")
            else:
                rooms = rooms.exclude(
                    booking__status='CONFIRMED',
                    booking__check_in__lt=check_out,
                    booking__check_out__gt=check_in,
                )
        except ValueError:
            messages.error(request, "Invalid date format. Please use YYYY-MM-DD.")

    if hotel_id:
        try:
            rooms = rooms.filter(hotel_id=int(hotel_id))
        except (TypeError, ValueError):
            messages.error(request, "Invalid hotel selection.")

    if guests:
        try:
            guests_int = int(guests)
            if guests_int > 0:
                rooms = rooms.filter(capacity__gte=guests_int)
        except (TypeError, ValueError):
            messages.error(request, "Guests must be a valid number.")

    if min_price:
        try:
            rooms = rooms.filter(price__gte=Decimal(min_price))
        except (InvalidOperation, TypeError, ValueError):
            messages.error(request, "Minimum price must be a valid number.")

    if max_price:
        try:
            rooms = rooms.filter(price__lte=Decimal(max_price))
        except (InvalidOperation, TypeError, ValueError):
            messages.error(request, "Maximum price must be a valid number.")

    if category:
        rooms = rooms.filter(category=category)

    if search_query or search_type:
        if search_type == 'hotel':
            if search_query:
                rooms = rooms.filter(hotel__name__icontains=search_query)
            else:
                rooms = rooms.filter(hotel__is_approved=True, hotel__is_active=True)
        elif search_type == 'room':
            if search_query:
                rooms = rooms.filter(
                    Q(title__icontains=search_query) | Q(description__icontains=search_query)
                )
        elif search_type == 'apartment':
            rooms = rooms.filter(category='APT')
            if search_query:
                rooms = rooms.filter(
                    Q(title__icontains=search_query) | Q(description__icontains=search_query)
                )
        elif search_query:
            rooms = rooms.filter(
                Q(title__icontains=search_query)
                | Q(description__icontains=search_query)
                | Q(hotel__name__icontains=search_query)
            )

    if sort == 'price_asc':
        rooms = rooms.order_by('price')
    elif sort == 'price_desc':
        rooms = rooms.order_by('-price')
    elif sort == 'size_desc':
        rooms = rooms.order_by('-size')

    return render(
        request,
        'room.html',
        {
            'rooms': rooms,
            'check_in': check_in,
            'check_out': check_out,
            'guests': guests or '',
            'min_price': min_price or '',
            'max_price': max_price or '',
            'category': category or '',
            'sort': sort or '',
            'categories': Room.ROOM_CATEGORIES,
            'hotels': hotels,
            'hotel_id': hotel_id or '',
            'search_query': search_query,
            'search_type': search_type,
        },
    )

# Room detail view
def room_detail(request, room_id):
    _mark_completed_bookings()
    if not _booking_tables_ready():
        messages.error(request, "Database is initializing. Please try again shortly.")
        return redirect('room_list')
    room = get_object_or_404(
        _with_booking_status(
            Room.objects.filter(
                is_approved=True,
                hotel__is_approved=True,
                hotel__is_active=True,
            )
        ),
        id=room_id,
    )
    reviews = Review.objects.filter(room=room).select_related('user').order_by('-created_at')
    return render(
        request,
        'room_detail.html',
        {
            'room': room,
            'reviews': reviews,
            'check_in': request.GET.get('check_in', ''),
            'check_out': request.GET.get('check_out', ''),
            'guests': request.GET.get('guests', ''),
        },
    )

#Index view (alternative to room_list)
def index(request):
    _mark_completed_bookings()
    if not _booking_tables_ready():
        messages.error(request, "Database is initializing. Please try again shortly.")
        return render(request, 'room.html', {'rooms': []})
    rooms = _with_booking_status(
        Room.objects.filter(
            available=True,
            is_approved=True,
            hotel__is_approved=True,
            hotel__is_active=True,
        )
    )
    return render(request, 'room.html', {'rooms': rooms})

# Static pages
def about(request):
    return render(request, 'about.html')

def amenities(request):
    return render(request, 'amenities.html')


def hotel_list(request):
    if not _booking_tables_ready():
        messages.error(request, "Database is initializing. Please try again shortly.")
        return render(
            request,
            'hotel_list.html',
            {
                'hotels': [],
                'hotels_count': 0,
                'query': '',
                'view_mode': 'list',
                'sort': 'top',
                'min_price': '',
                'max_price': '',
                'map_query': 'Kenya',
                'star_filter_options': [],
                'selected_stars': [],
            },
        )

    query = (request.GET.get('q') or '').strip()
    view_mode = (request.GET.get('view') or 'list').strip().lower()
    sort = (request.GET.get('sort') or 'top').strip().lower()
    min_price = (request.GET.get('min_price') or '').strip()
    max_price = (request.GET.get('max_price') or '').strip()

    selected_stars = []
    for value in request.GET.getlist('stars'):
        try:
            stars = int(value)
        except (TypeError, ValueError):
            continue
        if stars in {2, 3, 4, 5}:
            selected_stars.append(stars)
    selected_stars = sorted(set(selected_stars))

    star_counts_base = Hotel.objects.filter(is_active=True, is_approved=True)
    if query:
        star_counts_base = star_counts_base.filter(
            Q(name__icontains=query)
            | Q(city__icontains=query)
            | Q(country__icontains=query)
            | Q(address__icontains=query)
        )
    star_counts = {
        row['star_rating']: row['count']
        for row in (
            star_counts_base.exclude(star_rating__isnull=True)
            .values('star_rating')
            .annotate(count=Count('id'))
        )
    }
    star_filter_options = [
        {'stars': stars, 'count': star_counts.get(stars, 0)}
        for stars in (2, 3, 4, 5)
    ]

    hotels = (
        Hotel.objects.filter(is_active=True, is_approved=True)
        .annotate(
            starting_price=Min(
                'rooms__price',
                filter=Q(rooms__available=True, rooms__is_approved=True),
            )
        )
        .annotate(
            review_count=Count('rooms__reviews', distinct=True),
            review_score=ExpressionWrapper(
                Avg('rooms__reviews__rating') * Value(2.0),
                output_field=FloatField(),
            ),
        )
        .order_by('name')
    )

    if query:
        hotels = hotels.filter(
            Q(name__icontains=query)
            | Q(city__icontains=query)
            | Q(country__icontains=query)
            | Q(address__icontains=query)
        )

    if selected_stars:
        hotels = hotels.filter(star_rating__in=selected_stars)

    min_price_value = None
    max_price_value = None
    if min_price:
        try:
            min_price_value = Decimal(min_price)
        except (InvalidOperation, TypeError, ValueError):
            min_price_value = None
    if max_price:
        try:
            max_price_value = Decimal(max_price)
        except (InvalidOperation, TypeError, ValueError):
            max_price_value = None

    if min_price_value is not None:
        hotels = hotels.exclude(starting_price__isnull=True).filter(starting_price__gte=min_price_value)
    if max_price_value is not None:
        hotels = hotels.exclude(starting_price__isnull=True).filter(starting_price__lte=max_price_value)

    if sort == 'price_asc':
        hotels = hotels.order_by('starting_price', 'name')
    elif sort == 'price_desc':
        hotels = hotels.order_by('-starting_price', 'name')
    elif sort == 'stars_desc':
        hotels = hotels.order_by('-star_rating', 'name')
    elif sort == 'newest':
        hotels = hotels.order_by('-created_at', 'name')
    else:
        hotels = hotels.order_by('name')

    if view_mode not in {'list', 'grid'}:
        view_mode = 'list'

    map_query = query or "Kenya"
    return render(
        request,
        'hotel_list.html',
        {
            'hotels': hotels,
            'hotels_count': hotels.count(),
            'query': query,
            'view_mode': view_mode,
            'sort': sort,
            'min_price': min_price,
            'max_price': max_price,
            'map_query': map_query,
            'star_filter_options': star_filter_options,
            'selected_stars': selected_stars,
        },
    )


def hotel_detail(request, hotel_id):
    if not _booking_tables_ready():
        messages.error(request, "Database is initializing. Please try again shortly.")
        return redirect('hotel_list')
    hotel = get_object_or_404(Hotel, id=hotel_id, is_active=True, is_approved=True)
    rooms = _with_booking_status(
        Room.objects.filter(hotel=hotel, available=True, is_approved=True)
    )
    location_parts = [hotel.address, hotel.city, hotel.country]
    map_query = ", ".join([part for part in location_parts if part]) or (hotel.name or "")
    return render(
        request,
        'hotel_detail.html',
        {
            'hotel': hotel,
            'rooms': rooms,
            'map_query': map_query,
        },
    )

# Contact view with form handling
def contact(request):
    if request.method == "POST":
        name = request.POST.get('name')
        email = request.POST.get('email')
        subject = request.POST.get('subject')
        message_text = request.POST.get('message')

        if name and email and subject and message_text:
            ContactMessage.objects.create(
                full_name=name,
                email=email,
                subject=subject,
                message=message_text
            )

            admin_emails = _get_notification_emails()
            if admin_emails:
                message = EmailMessage(
                    subject=f"Contact Form: {subject}",
                    body=(
                        "New contact form message:\n\n"
                        f"Name: {name}\n"
                        f"Email: {email}\n"
                        f"Subject: {subject}\n\n"
                        f"Message:\n{message_text}\n"
                    ),
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    to=admin_emails,
                    reply_to=[email],
                )
                try:
                    message.send(fail_silently=False)
                except Exception:
                    messages.error(request, "Your message was saved, but we could not send it by email right now.")
                    return redirect('contact')

            messages.success(request, "Thank you! Your message has been sent successfully.")
            return redirect('contact')
        else:
            messages.error(request, "Please fill in all fields.")
    
    return render(request, 'contact.html')

# Booking view
def _room_is_available(room, check_in, check_out):
    return not Booking.objects.filter(
        room=room,
        status='CONFIRMED',
        check_in__lt=check_out,
        check_out__gt=check_in,
    ).exists()

def _get_booking_amount(booking):
    if booking.total_price:
        return booking.total_price
    if booking.room and booking.check_in and booking.check_out:
        nights = (booking.check_out - booking.check_in).days
        if nights > 0:
            return booking.room.price * nights
    return Decimal('0.00')

def _ensure_booking_total(booking):
    amount = _get_booking_amount(booking)
    if not booking.total_price and amount > 0:
        booking.total_price = amount
        booking.save(update_fields=['total_price', 'updated_at'])
    return amount

def _send_receipt_email(request, booking):
    if not booking.email:
        return
    amount = _ensure_booking_total(booking)
    invoice_url = request.build_absolute_uri(reverse('invoice_pdf', args=[booking.id]))
    room_title = booking.room.title if booking.room else "N/A"
    receipt_subject = f"Royal Hotel Receipt - {room_title}" if room_title != "N/A" else "Royal Hotel Receipt"
    html_message = (
        f"<p>Hello {booking.first_name},</p>"
        f"<p>Payment received for {room_title}.</p>"
        "<table style=\"border-collapse: collapse; width: 100%;\">"
        "<tr><th style=\"text-align:left; padding: 6px; border-bottom: 1px solid #ddd;\">Detail</th>"
        "<th style=\"text-align:left; padding: 6px; border-bottom: 1px solid #ddd;\">Value</th></tr>"
        f"<tr><td style=\"padding: 6px;\">Room</td><td style=\"padding: 6px;\">{room_title}</td></tr>"
        f"<tr><td style=\"padding: 6px;\">Check-in</td><td style=\"padding: 6px;\">{booking.check_in}</td></tr>"
        f"<tr><td style=\"padding: 6px;\">Check-out</td><td style=\"padding: 6px;\">{booking.check_out}</td></tr>"
        f"<tr><td style=\"padding: 6px;\">Guests</td><td style=\"padding: 6px;\">{booking.guests}</td></tr>"
        f"<tr><td style=\"padding: 6px;\">Total</td><td style=\"padding: 6px;\">{amount}</td></tr>"
        "</table>"
        f"<p>Invoice: <a href=\"{invoice_url}\">{invoice_url}</a></p>"
        "<p>Thank you for choosing Royal Hotel.</p>"
    )
    import contextlib
    with contextlib.suppress(Exception):
        send_mail(
            subject=receipt_subject,
            message=(
                f"Hello {booking.first_name},\n\n"
                f"Payment received for {room_title}.\n"
                f"Room: {room_title}\n"
                f"Check-in: {booking.check_in}\n"
                f"Check-out: {booking.check_out}\n"
                f"Guests: {booking.guests}\n"
                f"Total: {amount}\n\n"
                f"Invoice: {invoice_url}\n\n"
                "Thank you for choosing Royal Hotel."
            ),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            recipient_list=[booking.email],
            html_message=html_message,
            fail_silently=True,
        )

    owner_email = None
    if booking.room and booking.room.owner and booking.room.owner.email:
        owner_email = booking.room.owner.email
    if owner_email:
        with contextlib.suppress(Exception):
            send_mail(
                subject=f"New Booking Confirmed - {room_title}",
                message=(
                    f"A booking has been confirmed.\n\n"
                    f"Guest: {booking.first_name} {booking.last_name}\n"
                    f"Room: {room_title}\n"
                    f"Check-in: {booking.check_in}\n"
                    f"Check-out: {booking.check_out}\n"
                ),
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                recipient_list=[owner_email],
                html_message=(
                    f"<p>A booking has been confirmed.</p>"
                    "<ul>"
                    f"<li>Guest: {booking.first_name} {booking.last_name}</li>"
                    f"<li>Room: {room_title}</li>"
                    f"<li>Check-in: {booking.check_in}</li>"
                    f"<li>Check-out: {booking.check_out}</li>"
                    "</ul>"
                ),
                fail_silently=True,
            )

    admin_emails = _get_notification_emails()
    if admin_emails:
        with contextlib.suppress(Exception):
            send_mail(
                subject=f"Payment Confirmed - {room_title}",
                message=(
                    "A booking payment has been confirmed.\n\n"
                    f"Booking ID: {booking.id}\n"
                    f"Guest: {booking.first_name} {booking.last_name}\n"
                    f"Room: {room_title}\n"
                    f"Check-in: {booking.check_in}\n"
                    f"Check-out: {booking.check_out}\n"
                    f"Guests: {booking.guests}\n"
                    f"Total: {amount} {getattr(settings, 'DEFAULT_CURRENCY', 'KES')}\n"
                    f"Invoice: {invoice_url}\n"
                ),
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                recipient_list=admin_emails,
                html_message=(
                    "<p>A booking payment has been confirmed.</p>"
                    "<ul>"
                    f"<li>Booking ID: {booking.id}</li>"
                    f"<li>Guest: {booking.first_name} {booking.last_name}</li>"
                    f"<li>Room: {room_title}</li>"
                    f"<li>Check-in: {booking.check_in}</li>"
                    f"<li>Check-out: {booking.check_out}</li>"
                    f"<li>Guests: {booking.guests}</li>"
                    f"<li>Total: {amount} {getattr(settings, 'DEFAULT_CURRENCY', 'KES')}</li>"
                    "</ul>"
                    f"<p>Invoice: <a href=\"{invoice_url}\">{invoice_url}</a></p>"
                ),
                fail_silently=True,
            )

def booking_view(request):  # sourcery skip: low-code-quality
    _mark_completed_bookings()
    if not _booking_tables_ready():
        messages.error(request, "Database is initializing. Please try again shortly.")
        if request.method == "POST":
            return redirect('booking')
        return render(request, 'booking.html', {'rooms': [], 'selected_room_id': ''})
    if request.method == "POST":
        # Get form data
        fname = (request.POST.get('fname') or '').strip()
        lname = (request.POST.get('lname') or '').strip()
        mobile = (request.POST.get('mobile') or '').strip()
        email = (request.POST.get('email') or '').strip()
        guests = request.POST.get('guests', 1)
        room_id = request.POST.get('room_id')
        date_in = request.POST.get('date-1')
        date_out = request.POST.get('date-2')
        request_text = request.POST.get('request', '')

        profile = None
        if request.user.is_authenticated:
            profile = _get_or_create_profile(request.user)
            if not fname:
                fname = request.user.first_name or request.user.username
            if not lname:
                lname = request.user.last_name or request.user.first_name or "Guest"
            if not email:
                email = request.user.email or request.user.username
            if not mobile and profile and profile.mobile:
                mobile = profile.mobile

        # Validation
        if not all([fname, lname, mobile, email, date_in, date_out, room_id]):
            messages.error(request, "Please fill in all required fields.")
            return redirect('booking')

        try:
            # Date conversion
            try:
                check_in = datetime.strptime(date_in, '%m/%d/%Y').date()
                check_out = datetime.strptime(date_out, '%m/%d/%Y').date()
            except ValueError:
                check_in = datetime.strptime(date_in, '%Y-%m-%d').date()
                check_out = datetime.strptime(date_out, '%Y-%m-%d').date()
            
            # Validate dates
            if check_in >= check_out:
                messages.error(request, "Check-out date must be after check-in date.")
                return redirect('booking')

            # Parse guests count
            try:
                guests = int(guests)
            except (TypeError, ValueError):
                guests = 1

            room = get_object_or_404(
                Room.objects.filter(
                    available=True,
                    is_approved=True,
                    hotel__is_approved=True,
                    hotel__is_active=True,
                ),
                id=room_id,
            )

            if not _room_is_available(room, check_in, check_out):
                messages.error(request, "Selected room is not available for those dates.")
                return redirect('booking')

            # Create booking
            new_booking = Booking(
                room=room,
                first_name=fname,
                last_name=lname,
                mobile=mobile,
                email=email,
                guests=guests,
                check_in=check_in,
                check_out=check_out,
                special_request=request_text
            )
            
            # If user is logged in, associate booking with user
            if request.user.is_authenticated:
                new_booking.user = request.user
                if profile and mobile and not profile.mobile:
                    profile.mobile = mobile
                    profile.save(update_fields=['mobile'])

            # Calculate total price
            nights = (check_out - check_in).days
            new_booking.total_price = room.price * nights

            new_booking.save()

            admin_emails = _get_notification_emails()
            if admin_emails:
                import contextlib
                payment_url = request.build_absolute_uri(reverse('payment_page', args=[new_booking.id]))
                with contextlib.suppress(Exception):
                    send_mail(
                        subject=f"New Booking Created (Pending Payment) #{new_booking.id}",
                        message=(
                            "A new booking has been created and is pending payment.\n\n"
                            f"Booking ID: {new_booking.id}\n"
                            f"Guest: {new_booking.first_name} {new_booking.last_name}\n"
                            f"Email: {new_booking.email}\n"
                            f"Mobile: {new_booking.mobile}\n"
                            f"Room: {new_booking.room.title if new_booking.room else 'N/A'}\n"
                            f"Check-in: {new_booking.check_in}\n"
                            f"Check-out: {new_booking.check_out}\n"
                            f"Guests: {new_booking.guests}\n"
                            f"Total: {getattr(settings, 'DEFAULT_CURRENCY', 'KES')} {new_booking.total_price}\n\n"
                            f"Payment link: {payment_url}\n"
                        ),
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                        recipient_list=admin_emails,
                        fail_silently=True,
                    )

            if new_booking.email:
                import contextlib
                with contextlib.suppress(Exception):
                    send_mail(
                        subject=f"Royal Hotel Booking Confirmation #{new_booking.id}",
                        message=(
                            f"Hello {new_booking.first_name},\n\n"
                            f"Your booking is received.\n"
                            f"Room: {new_booking.room.title if new_booking.room else 'N/A'}\n"
                            f"Check-in: {new_booking.check_in}\n"
                            f"Check-out: {new_booking.check_out}\n"
                            f"Guests: {new_booking.guests}\n"
                            f"Total: KES {new_booking.total_price}\n\n"
                            "Thank you for choosing Royal Hotel."
                        ),
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                        recipient_list=[new_booking.email],
                        fail_silently=True,
                    )

            messages.success(request, "Your reservation has been submitted successfully!")
            return redirect('booking_confirmation', booking_id=new_booking.id)
            
        except ValueError as e:
            messages.error(request, "Invalid date format. Please use MM/DD/YYYY.")
            return redirect('booking')
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            return redirect('booking')

    # GET request - show booking form
    rooms = Room.objects.filter(
        available=True,
        is_approved=True,
        hotel__is_approved=True,
        hotel__is_active=True,
    )
    selected_room_id = request.GET.get('room', '')
    prefill_check_in = request.GET.get('check_in', '')
    prefill_check_out = request.GET.get('check_out', '')
    prefill_guests = request.GET.get('guests', '')
    prefill_fname = ''
    prefill_lname = ''
    prefill_email = ''
    prefill_mobile = ''
    if request.user.is_authenticated:
        profile = _get_or_create_profile(request.user)
        prefill_fname = request.user.first_name or request.user.username
        prefill_lname = request.user.last_name or ''
        prefill_email = request.user.email or request.user.username
        prefill_mobile = profile.mobile if profile else ''
    return render(
        request,
        'booking.html',
        {
            'rooms': rooms,
            'selected_room_id': str(selected_room_id) if selected_room_id else '',
            'prefill_check_in': prefill_check_in,
            'prefill_check_out': prefill_check_out,
            'prefill_guests': prefill_guests,
            'prefill_fname': prefill_fname,
            'prefill_lname': prefill_lname,
            'prefill_email': prefill_email,
            'prefill_mobile': prefill_mobile,
        },
    )

# Booking confirmation
def booking_confirmation(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    if _booking_is_expired_for_payment(booking) or booking.status == "CANCELLED":
        return _redirect_booking_expired(request, booking)
    return render(request, 'booking_confirmation.html', {'booking': booking})


def _redirect_to_booked_room(request, booking, message_text=None):
    if message_text:
        messages.success(request, message_text)
    if booking.room_id:
        return redirect('room_detail', room_id=booking.room_id)
    return redirect('booking_confirmation', booking_id=booking.id)


# Payment result pages
def payment_success(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    _send_receipt_email(request, booking)
    return _redirect_to_booked_room(
        request,
        booking,
        "Payment confirmed. Your booking is successful. Here is your booked room.",
    )

def payment_failed(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    if reason := request.GET.get('reason'):
        messages.error(request, f"Payment was not successful: {reason}")
    else:
        messages.error(request, "Payment was not successful. Please try again.")
    return redirect('payment_page', booking_id=booking.id)

# Payment page
def payment_page(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    if _booking_is_expired_for_payment(booking) or booking.status == "CANCELLED":
        return _redirect_booking_expired(request, booking)
    amount = _ensure_booking_total(booking)
    return render(
        request,
        'payment_page.html',
        {
            'booking': booking,
            'amount': amount,
            'currency': getattr(settings, 'DEFAULT_CURRENCY', 'KES'),
            'stripe_publishable_key': getattr(settings, 'STRIPE_PUBLISHABLE_KEY', ''),
            'paypal_configured': _is_paypal_configured(),
            'mpesa_configured': _is_mpesa_configured(),
        },
    )

# Stripe: create payment intent
def stripe_create_intent(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid method")

    booking_id = request.POST.get('booking_id')
    if not booking_id:
        return JsonResponse({'error': 'Missing booking_id'}, status=400)

    booking = get_object_or_404(Booking, id=booking_id)
    if _booking_is_expired_for_payment(booking) or booking.status == "CANCELLED":
        if booking.status == "PENDING":
            booking.status = "CANCELLED"
            booking.save(update_fields=["status", "updated_at"])
        return JsonResponse({'error': 'Booking expired. Please book again.'}, status=410)
    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({'error': 'Stripe not configured'}, status=400)
    if requests is None:
        return JsonResponse({'error': 'Payment dependency not installed'}, status=503)

    amount = _ensure_booking_total(booking)
    try:
        amount_cents = int(Decimal(amount) * 100)
    except (InvalidOperation, TypeError):
        return JsonResponse({'error': 'Invalid amount'}, status=400)

    payload = {
        'amount': amount_cents,
        'currency': getattr(settings, 'DEFAULT_CURRENCY', 'KES').lower(),
        'automatic_payment_methods[enabled]': 'true',
        'metadata[booking_id]': str(booking.id),
        'receipt_email': booking.email,
    }

    try:
        response = requests.post(
            'https://api.stripe.com/v1/payment_intents',
            data=payload,
            auth=(settings.STRIPE_SECRET_KEY, ''),
            timeout=15,
        )
    except Exception:
        return JsonResponse({'error': 'Unable to reach Stripe'}, status=502)

    if response.status_code >= 300:
        return JsonResponse({'error': 'Stripe error', 'details': response.text}, status=400)

    intent = response.json()
    payment = Payment.objects.create(
        booking=booking,
        provider='STRIPE',
        status='PENDING',
        amount=amount,
        currency=getattr(settings, 'DEFAULT_CURRENCY', 'KES'),
        reference=intent.get('id'),
        raw_response=intent,
    )

    return JsonResponse({'client_secret': intent.get('client_secret'), 'payment_id': payment.id})

# Stripe: confirm intent server-side
def stripe_confirm(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid method")

    payment_id = request.POST.get('payment_id')
    intent_id = request.POST.get('payment_intent_id')
    if not payment_id or not intent_id:
        return JsonResponse({'error': 'Missing payment_id or payment_intent_id'}, status=400)

    payment = get_object_or_404(Payment, id=payment_id, provider='STRIPE')
    if _booking_is_expired_for_payment(payment.booking) or payment.booking.status == "CANCELLED":
        if payment.booking.status == "PENDING":
            payment.booking.status = "CANCELLED"
            payment.booking.save(update_fields=["status", "updated_at"])
        payment.status = "CANCELLED"
        payment.save(update_fields=["status", "updated_at"])

        params = {}
        if payment.booking.room_id:
            params["room"] = payment.booking.room_id
        if payment.booking.check_in:
            params["check_in"] = payment.booking.check_in.isoformat()
        if payment.booking.check_out:
            params["check_out"] = payment.booking.check_out.isoformat()
        if payment.booking.guests:
            params["guests"] = payment.booking.guests
        redirect_url = f"{reverse('booking')}?{urlencode(params)}" if params else reverse("booking")
        return JsonResponse(
            {"status": payment.status, "redirect_url": redirect_url, "error": "Booking expired. Please book again."},
            status=410,
        )
    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({'error': 'Stripe not configured'}, status=400)
    if requests is None:
        return JsonResponse({'error': 'Payment dependency not installed'}, status=503)

    try:
        response = requests.get(
            f'https://api.stripe.com/v1/payment_intents/{intent_id}',
            auth=(settings.STRIPE_SECRET_KEY, ''),
            timeout=15,
        )
    except Exception:
        return JsonResponse({'error': 'Unable to reach Stripe'}, status=502)

    if response.status_code >= 300:
        return JsonResponse({'error': 'Stripe error', 'details': response.text}, status=400)

    intent = response.json()
    payment.raw_response = intent
    payment.reference = intent.get('id')
    if intent.get('status') == 'succeeded':
        payment.status = 'SUCCEEDED'
        payment.booking.status = 'CONFIRMED'
        payment.booking.save()
        _send_receipt_email(request, payment.booking)
    elif intent.get('status') in ['canceled', 'requires_payment_method']:
        payment.status = 'FAILED'
    payment.save()

    if payment.status == 'SUCCEEDED':
        redirect_url = reverse('payment_success', args=[payment.booking.id])
    else:
        reason = intent.get('last_payment_error', {}).get('message') or intent.get('status', 'payment_failed')
        redirect_url = f"{reverse('payment_failed', args=[payment.booking.id])}?{urlencode({'reason': reason})}"
    return JsonResponse({'status': payment.status, 'redirect_url': redirect_url})

@csrf_exempt
def stripe_webhook(request):
    if stripe is None:
        return HttpResponseBadRequest("Stripe package not installed.")
    if not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponseBadRequest("Stripe webhook secret not configured.")

    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return HttpResponseBadRequest("Invalid payload")
    except Exception:
        return HttpResponseBadRequest("Invalid signature")

    event_type = event.get('type')
    data = event.get('data', {}).get('object', {})
    intent_id = data.get('id')

    if event_type == 'payment_intent.succeeded':
        if payment := Payment.objects.filter(reference=intent_id, provider='STRIPE').first():
            payment.status = 'SUCCEEDED'
            payment.raw_response = data
            payment.booking.status = 'CONFIRMED'
            payment.booking.save()
            payment.save()
            import contextlib
            with contextlib.suppress(Exception):
                _send_receipt_email(request, payment.booking)
    elif event_type == 'payment_intent.payment_failed':
        if payment := Payment.objects.filter(reference=intent_id, provider='STRIPE').first():
            payment.status = 'FAILED'
            payment.raw_response = data
            payment.save(update_fields=['status', 'raw_response', 'updated_at'])

    return JsonResponse({'received': True})

# PayPal helpers
def _is_paypal_configured():
    return bool(
        getattr(settings, "PAYPAL_CLIENT_ID", "")
        and getattr(settings, "PAYPAL_CLIENT_SECRET", "")
        and getattr(settings, "PAYPAL_BASE_URL", "")
        and requests is not None
    )


def _paypal_get_access_token():
    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        return None
    if requests is None:
        return None

    try:
        response = requests.post(
            f"{settings.PAYPAL_BASE_URL}/v1/oauth2/token",
            data={'grant_type': 'client_credentials'},
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            timeout=15,
        )
    except Exception:
        return None
    if response.status_code >= 300:
        return None
    return response.json().get('access_token')


def _handle_paypal_successful_payment(request, payment, capture):
    capture_status = (capture.get("status") or "").upper()
    payment.raw_response = capture
    payment.reference = capture.get("id") or payment.reference

    if capture_status == "COMPLETED":
        payment.status = 'SUCCEEDED'
        if payment.booking.status == 'PENDING':
            payment.booking.status = 'CONFIRMED'
            payment.booking.save(update_fields=['status', 'updated_at'])
        payment.save(update_fields=['status', 'raw_response', 'reference', 'updated_at'])
        _send_receipt_email(request, payment.booking)
        return True

    if capture_status in {"APPROVED", "PAYER_ACTION_REQUIRED"}:
        payment.status = 'PENDING'
    else:
        payment.status = 'FAILED'

    payment.save(update_fields=['status', 'raw_response', 'reference', 'updated_at'])
    return False


def paypal_create_order(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid method")

    booking_id = request.POST.get('booking_id')
    if not booking_id:
        return HttpResponseBadRequest("Missing booking_id")

    booking = get_object_or_404(Booking, id=booking_id)
    if _booking_is_expired_for_payment(booking) or booking.status == "CANCELLED":
        return _redirect_booking_expired(request, booking)
    if requests is None:
        messages.error(request, "Payment dependency is not installed.")
        return redirect('payment_page', booking_id=booking.id)
    access_token = _paypal_get_access_token()
    if not access_token:
        messages.error(request, "PayPal is not configured.")
        return redirect('payment_page', booking_id=booking.id)

    amount = _ensure_booking_total(booking)
    return_url = request.build_absolute_uri(reverse('paypal_return')) + f"?booking_id={booking.id}"
    cancel_url = request.build_absolute_uri(reverse('paypal_cancel')) + f"?booking_id={booking.id}"
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "amount": {
                    "currency_code": getattr(settings, 'DEFAULT_CURRENCY', 'KES'),
                    "value": str(amount),
                }
            }
        ],
        "application_context": {
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }

    try:
        response = requests.post(
            f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=15,
        )
    except Exception:
        messages.error(request, "PayPal service is unavailable. Please try again.")
        return redirect('payment_page', booking_id=booking.id)

    if response.status_code >= 300:
        messages.error(request, "PayPal error. Please try again.")
        return redirect('payment_page', booking_id=booking.id)

    order = response.json()
    payment = Payment.objects.create(
        booking=booking,
        provider='PAYPAL',
        status='PENDING',
        amount=amount,
        currency=getattr(settings, 'DEFAULT_CURRENCY', 'KES'),
        reference=order.get('id'),
        raw_response=order,
    )

    approve_url = next((link.get('href') for link in order.get('links', []) if link.get('rel') == 'approve'), None)

    if not approve_url:
        messages.error(request, "PayPal approval link not found.")
        return redirect('payment_page', booking_id=booking.id)

    return redirect(approve_url)

def _paypal_error_redirect(request, message, booking_id=None, reason=None):
    messages.error(request, message)
    if booking_id:
        reason_param = f"?reason={reason}" if reason else ""
        return redirect(f"{reverse('payment_failed', args=[booking_id])}{reason_param}")
    return redirect('index')

def paypal_return(request):
    order_id = request.GET.get('token')
    booking_id = request.GET.get('booking_id')
    if not order_id:
        return _paypal_error_redirect(request, "Missing PayPal token.", booking_id, "missing_paypal_token")

    if booking_id:
        booking = get_object_or_404(Booking, id=booking_id)
        if _booking_is_expired_for_payment(booking) or booking.status == "CANCELLED":
            return _redirect_booking_expired(request, booking)

    access_token = _paypal_get_access_token()
    if requests is None:
        return _paypal_error_redirect(request, "Payment dependency is not installed.", booking_id, "payment_dependency_missing")
    if not access_token:
        return _paypal_error_redirect(request, "PayPal is not configured.", booking_id, "paypal_not_configured")

    try:
        response = requests.post(
            f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}/capture",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=15,
        )
    except Exception:
        messages.error(request, "PayPal service is unavailable. Please try again.")
        if booking_id:
            return redirect(f"{reverse('payment_failed', args=[booking_id])}?reason=paypal_service_unavailable")

    payment = Payment.objects.filter(reference=order_id, provider='PAYPAL').first()
    if response.status_code >= 300:
        if payment:
            payment.status = 'FAILED'
            payment.raw_response = response.text
            payment.save()
        messages.error(request, "PayPal capture failed.")
        if payment:
            return redirect(f"{reverse('payment_failed', args=[payment.booking.id])}?reason=paypal_capture_failed")
        if booking_id:
            return redirect(f"{reverse('payment_failed', args=[booking_id])}?reason=paypal_capture_failed")
        return redirect('index')

    try:
        capture = response.json()
    except Exception:
        messages.error(request, "PayPal response could not be parsed.")
        if booking_id:
            return redirect(f"{reverse('payment_failed', args=[booking_id])}?reason=paypal_invalid_response")
        return redirect('index')

    if not payment and booking_id:
        booking = get_object_or_404(Booking, id=booking_id)
        payment = Payment.objects.create(
            booking=booking,
            provider='PAYPAL',
            status='PENDING',
            amount=_ensure_booking_total(booking),
            currency=getattr(settings, 'DEFAULT_CURRENCY', 'KES'),
            reference=order_id,
            raw_response=capture,
        )

    if payment:
        succeeded = _handle_paypal_successful_payment(request, payment, capture)
        if succeeded:
            return redirect('payment_success', booking_id=payment.booking.id)
        return redirect(f"{reverse('payment_failed', args=[payment.booking.id])}?reason=paypal_not_completed")
    if booking_id:
        return redirect(f"{reverse('payment_failed', args=[booking_id])}?reason=paypal_payment_missing")
    return redirect('index')

def paypal_cancel(request):
    messages.info(request, "PayPal payment cancelled.")
    booking_id = request.GET.get('booking_id')
    if booking_id:
        return redirect(f"{reverse('payment_failed', args=[booking_id])}?reason=paypal_payment_cancelled")
    return redirect('index')

def invoice_pdf(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    amount = _ensure_booking_total(booking)
    currency = getattr(settings, "DEFAULT_CURRENCY", "KES")

    try:
        from reportlab.pdfgen import canvas
    except Exception:
        return render(
            request,
            "invoice.html",
            {
                "booking": booking,
                "amount": amount,
                "currency": currency,
                "pdf_available": False,
            },
        )

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(40, 800, "Royal Hotel Booking Receipt")
    p.setFont("Helvetica", 12)
    y = 770
    lines = [
        f"Booking ID: {booking.id}",
        f"Name: {booking.first_name} {booking.last_name}",
        f"Email: {booking.email}",
        f"Room: {booking.room.title if booking.room else 'N/A'}",
        f"Check-in: {booking.check_in}",
        f"Check-out: {booking.check_out}",
        f"Guests: {booking.guests}",
        f"Total: {amount}",
    ]
    for line in lines:
        p.drawString(40, y, line)
        y -= 20
    p.showPage()
    p.save()

    pdf = buffer.getvalue()
    buffer.close()
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="invoice_{booking.id}.pdf"'
    return response

# M-Pesa STK Push
def _normalize_mpesa_phone(phone):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        return f"254{digits[1:]}"
    elif digits.startswith("254") and len(digits) == 12:
        return digits
    elif digits.startswith("7") and len(digits) == 9:
        return f"254{digits}"
    else:
        return None


def _mpesa_get_access_token():
    if requests is None:
        return None
    if not settings.MPESA_CONSUMER_KEY or not settings.MPESA_CONSUMER_SECRET:
        return None
    auth_url = getattr(settings, "MPESA_AUTH_URL", "")
    if not auth_url:
        return None

    try:
        response = requests.get(
            auth_url,
            auth=(settings.MPESA_CONSUMER_KEY, settings.MPESA_CONSUMER_SECRET),
            timeout=15,
        )
    except Exception:
        return None

    if response.status_code >= 300:
        return None
    return (response.json() or {}).get("access_token")


def _is_mpesa_configured():
    required_values = [
        getattr(settings, "MPESA_CONSUMER_KEY", ""),
        getattr(settings, "MPESA_CONSUMER_SECRET", ""),
        getattr(settings, "MPESA_SHORTCODE", ""),
        getattr(settings, "MPESA_PASSKEY", ""),
        getattr(settings, "MPESA_STK_URL", ""),
        getattr(settings, "MPESA_CALLBACK_URL", ""),
        getattr(settings, "MPESA_AUTH_URL", ""),
    ]
    return bool(requests is not None and all(required_values))


def _mpesa_query_stk_status(payment):
    if requests is None:
        return None, "Payment dependency is not installed."
    if payment.provider != "MPESA" or not payment.reference:
        return None, "Invalid M-Pesa payment reference."

    required_values = [
        settings.MPESA_SHORTCODE,
        settings.MPESA_PASSKEY,
        getattr(settings, "MPESA_STK_QUERY_URL", ""),
    ]
    if not all(required_values):
        return None, "M-Pesa query settings are incomplete."

    access_token = _mpesa_get_access_token()
    if not access_token:
        return None, "Unable to authenticate with M-Pesa."

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}".encode("utf-8")
    ).decode("utf-8")
    payload = {
        "BusinessShortCode": settings.MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": payment.reference,
    }

    try:
        response = requests.post(
            settings.MPESA_STK_QUERY_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=20,
        )
    except Exception:
        return None, "Unable to reach M-Pesa query service."

    try:
        query_response = response.json() or {}
    except Exception:
        query_response = {"raw_text": response.text}

    if response.status_code >= 300 or query_response.get("ResponseCode") != "0":
        return query_response, query_response.get("errorMessage") or query_response.get("ResponseDescription") or "STK query failed."

    return query_response, None


def mpesa_stk_push(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid method")

    booking_id = request.POST.get('booking_id')
    phone = request.POST.get('phone')
    if not booking_id or not phone:
        messages.error(request, "Missing booking or phone number.")
        return redirect('index')

    booking = get_object_or_404(Booking, id=booking_id)
    if _booking_is_expired_for_payment(booking) or booking.status == "CANCELLED":
        return _redirect_booking_expired(request, booking)
    normalized_phone = _normalize_mpesa_phone(phone)
    if not normalized_phone:
        messages.error(request, "Invalid phone number. Use format 07XXXXXXXX or 2547XXXXXXXX.")
        return redirect('payment_page', booking_id=booking.id)

    if requests is None:
        messages.error(request, "Payment dependency is not installed.")
        return redirect('payment_page', booking_id=booking.id)

    required_values = [
        settings.MPESA_CONSUMER_KEY,
        settings.MPESA_CONSUMER_SECRET,
        settings.MPESA_SHORTCODE,
        settings.MPESA_PASSKEY,
        settings.MPESA_STK_URL,
        settings.MPESA_CALLBACK_URL,
        getattr(settings, "MPESA_AUTH_URL", ""),
    ]
    if not all(required_values):
        messages.error(request, "M-Pesa is not configured.")
        return redirect('payment_page', booking_id=booking.id)

    access_token = _mpesa_get_access_token()
    if not access_token:
        messages.error(request, "Unable to authenticate with M-Pesa.")
        return redirect('payment_page', booking_id=booking.id)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}".encode("utf-8")
    ).decode("utf-8")
    amount = _ensure_booking_total(booking)
    try:
        amount_int = max(1, int(Decimal(amount)))
    except (InvalidOperation, TypeError, ValueError):
        messages.error(request, "Invalid booking amount for M-Pesa payment.")
        return redirect('payment_page', booking_id=booking.id)

    payload = {
        "BusinessShortCode": settings.MPESA_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": getattr(settings, "MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline"),
        "Amount": amount_int,
        "PartyA": normalized_phone,
        "PartyB": settings.MPESA_SHORTCODE,
        "PhoneNumber": normalized_phone,
        "CallBackURL": settings.MPESA_CALLBACK_URL,
        "AccountReference": f"BOOKING-{booking.id}",
        "TransactionDesc": getattr(settings, "MPESA_TRANSACTION_DESC", "Hotel Booking Payment"),
    }

    try:
        response = requests.post(
            settings.MPESA_STK_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=20,
        )
    except Exception:
        messages.error(request, "M-Pesa service is unavailable. Please try again.")
        return redirect('payment_page', booking_id=booking.id)

    response_data = {}
    try:
        response_data = response.json() or {}
    except Exception:
        response_data = {"raw_text": response.text}

    if response.status_code >= 300 or response_data.get("ResponseCode") != "0":
        Payment.objects.create(
            booking=booking,
            provider='MPESA',
            status='FAILED',
            amount=_ensure_booking_total(booking),
            currency=getattr(settings, 'DEFAULT_CURRENCY', 'KES'),
            reference=response_data.get("CheckoutRequestID"),
            raw_response={"request": payload, "response": response_data},
        )
        messages.error(
            request,
            response_data.get("errorMessage")
            or response_data.get("ResponseDescription")
            or "M-Pesa STK Push failed.",
        )
        return redirect('payment_page', booking_id=booking.id)

    payment = Payment.objects.create(
        booking=booking,
        provider='MPESA',
        status='PENDING',
        amount=_ensure_booking_total(booking),
        currency=getattr(settings, 'DEFAULT_CURRENCY', 'KES'),
        reference=response_data.get("CheckoutRequestID"),
        raw_response={
            "request": payload,
            "response": response_data,
            "phone": normalized_phone,
            "merchant_request_id": response_data.get("MerchantRequestID"),
        },
    )

    messages.info(
        request,
        "STK Push sent to your phone. Complete payment to confirm booking. "
        "You will be notified once payment is verified.",
    )
    return redirect('booking_confirmation', booking_id=booking.id)


@csrf_exempt
def mpesa_callback(request):
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

    callback = (payload.get("Body") or {}).get("stkCallback") or {}
    checkout_request_id = callback.get("CheckoutRequestID")
    result_code = callback.get("ResultCode")
    result_code_str = str(result_code) if result_code is not None else ""
    result_desc = callback.get("ResultDesc")

    payment = Payment.objects.filter(
        provider='MPESA',
        reference=checkout_request_id,
    ).order_by("-id").first()

    if not payment:
        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

    metadata = {}
    items = ((callback.get("CallbackMetadata") or {}).get("Item") or [])
    for item in items:
        name = item.get("Name")
        value = item.get("Value")
        if name:
            metadata[name] = value

    existing_raw = payment.raw_response if isinstance(payment.raw_response, dict) else {}
    updated_raw = dict(existing_raw)
    updated_raw["callback"] = callback
    updated_raw["metadata"] = metadata
    if result_desc:
        updated_raw["callback_result_desc"] = result_desc
    payment.raw_response = updated_raw

    previous_status = payment.status
    if result_code_str == "0":
        payment.status = 'SUCCEEDED'
        payment.booking.status = 'CONFIRMED'
        payment.booking.save(update_fields=['status', 'updated_at'])
    elif result_code_str == "1032":
        payment.status = 'CANCELLED'
    else:
        payment.status = 'FAILED'
    payment.save(update_fields=['status', 'raw_response', 'updated_at'])

    if previous_status != 'SUCCEEDED' and payment.status == 'SUCCEEDED':
        _send_receipt_email(request, payment.booking)

    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

# Google OAuth (Login with Google / Gmail)
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ALLOWED_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


def _google_oauth_config():
    client_id = (getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
    client_secret = (getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip()
    return client_id, client_secret


@lru_cache(maxsize=2)
def _google_jwks_client():
    if PyJWKClient is None:  # pragma: no cover
        raise RuntimeError("PyJWT is required for Google login. Install with: pip install PyJWT[crypto]")
    return PyJWKClient(_GOOGLE_JWKS_URL)


def _verify_google_id_token(id_token: str, client_id: str) -> dict:
    if jwt is None:  # pragma: no cover
        raise RuntimeError("PyJWT is required for Google login. Install with: pip install PyJWT[crypto]")

    signing_key = _google_jwks_client().get_signing_key_from_jwt(id_token).key
    claims = jwt.decode(
        id_token,
        signing_key,
        algorithms=["RS256"],
        audience=client_id,
        options={
            "verify_signature": True,
            "verify_exp": True,
            "verify_aud": True,
            "verify_iss": False,
        },
        leeway=60,
    )

    issuer = (claims.get("iss") or "").strip()
    if issuer not in _GOOGLE_ALLOWED_ISSUERS:
        raise ValueError("Invalid token issuer.")

    return claims


def _safe_next_url(request, next_url: str) -> str:
    next_url = (next_url or "").strip()
    if not next_url:
        return ""
    if url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return ""


def google_login(request):
    client_id, client_secret = _google_oauth_config()
    if not client_id or not client_secret:
        messages.error(request, "Google login is not configured.")
        return redirect("login")

    state = secrets.token_urlsafe(32)
    request.session["google_oauth_state"] = state

    next_url = (request.GET.get("next") or "").strip()
    if next_url:
        request.session["google_oauth_next"] = next_url

    redirect_uri = request.build_absolute_uri(reverse("google_callback"))
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return redirect(f"{_GOOGLE_AUTH_URL}?{urlencode(params)}")


def google_callback(request):
    client_id, client_secret = _google_oauth_config()
    if not client_id or not client_secret:
        messages.error(request, "Google login is not configured.")
        return redirect("login")

    if request.GET.get("error"):
        messages.error(request, "Google login was cancelled.")
        return redirect("login")

    state = (request.GET.get("state") or "").strip()
    expected_state = (request.session.pop("google_oauth_state", "") or "").strip()
    if not state or not expected_state or state != expected_state:
        messages.error(request, "Google login failed. Please try again.")
        return redirect("login")

    code = (request.GET.get("code") or "").strip()
    if not code:
        messages.error(request, "Google login failed. Missing authorization code.")
        return redirect("login")

    if requests is None:  # pragma: no cover
        messages.error(request, "Google login is unavailable (requests not installed).")
        return redirect("login")

    redirect_uri = request.build_absolute_uri(reverse("google_callback"))
    try:
        response = requests.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        token_data = response.json() if response.content else {}
    except Exception:
        token_data = {}
        response = None

    if not token_data or (response is not None and response.status_code >= 400):
        message = token_data.get("error_description") or token_data.get("error") or "Token exchange failed."
        messages.error(request, f"Google login failed: {message}")
        return redirect("login")

    id_token = (token_data.get("id_token") or "").strip()
    if not id_token:
        messages.error(request, "Google login failed: missing ID token.")
        return redirect("login")

    try:
        claims = _verify_google_id_token(id_token, client_id=client_id)
    except Exception:
        messages.error(request, "Google login failed: invalid ID token.")
        return redirect("login")

    email = (claims.get("email") or "").strip().lower()
    if not email:
        messages.error(request, "Google login failed: email not available.")
        return redirect("login")

    email_verified = claims.get("email_verified")
    if email_verified in (False, "false", "False", "0", 0):
        messages.error(request, "Google login failed: email not verified.")
        return redirect("login")

    given_name = (claims.get("given_name") or "").strip()
    family_name = (claims.get("family_name") or "").strip()
    full_name = (claims.get("name") or "").strip()

    if not given_name and full_name:
        parts = [part for part in full_name.split(" ") if part]
        given_name = parts[0] if parts else ""
        if not family_name and len(parts) > 1:
            family_name = " ".join(parts[1:]).strip()

    user = User.objects.filter(username__iexact=email).first() or User.objects.filter(email__iexact=email).first()
    if user is None:
        user = User(username=email, email=email)
        user.set_unusable_password()

    user.username = email
    user.email = email
    if given_name and not user.first_name:
        user.first_name = given_name
    if family_name and not user.last_name:
        user.last_name = family_name
    if not user.is_active:
        user.is_active = True
    user.save()

    login(request, user)
    _get_or_create_profile(user)

    messages.success(request, f"Welcome, {user.first_name or user.username}!")
    next_url = (request.session.pop("google_oauth_next", "") or "").strip()
    return redirect(next_url or "index")


PASSWORD_RESET_CODE_TTL = timedelta(minutes=10)
PASSWORD_RESET_CODE_RESEND_WAIT = timedelta(seconds=60)
PASSWORD_RESET_CODE_MAX_ATTEMPTS = 5


def _find_user_for_password_reset(email: str):
    email = (email or "").strip().lower()
    if not email:
        return None

    user = User.objects.filter(username__iexact=email).first()
    if user is None:
        user = User.objects.filter(email__iexact=email).order_by("-id").first()
    return user


def _send_password_reset_code(email: str):
    user = _find_user_for_password_reset(email)
    if user is None or not user.is_active:
        return

    normalized_email = (email or "").strip().lower()
    if normalized_email and not (user.email or "").strip():
        user.email = normalized_email
        user.save(update_fields=["email"])

    now = timezone.now()
    recent_code = (
        PasswordResetCode.objects.filter(
            user=user,
            used_at__isnull=True,
            expires_at__gt=now,
            created_at__gte=now - PASSWORD_RESET_CODE_RESEND_WAIT,
        )
        .order_by("-created_at")
        .first()
    )
    if recent_code is not None:
        return

    code = f"{secrets.randbelow(1_000_000):06d}"
    PasswordResetCode.objects.filter(user=user, used_at__isnull=True).delete()
    PasswordResetCode.objects.create(
        user=user,
        code_hash=make_password(code),
        expires_at=now + PASSWORD_RESET_CODE_TTL,
    )

    subject = "Your password reset code"
    greeting = user.first_name or "there"
    body = (
        f"Hi {greeting},\n\n"
        f"Your verification code is: {code}\n"
        f"This code expires in {int(PASSWORD_RESET_CODE_TTL.total_seconds() // 60)} minutes.\n\n"
        "If you did not request this, you can ignore this email.\n"
    )

    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[(user.email or normalized_email).strip()],
        fail_silently=False,
    )


def password_reset_request(request):
    prefill_email = (request.session.get("pwd_reset_email") or "").strip()
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        if not email:
            messages.error(request, "Email is required.")
            return redirect("password_reset")

        request.session["pwd_reset_email"] = email

        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Enter a valid email address.")
            return redirect("password_reset")

        try:
            _send_password_reset_code(email)
        except Exception:
            messages.error(request, "Could not send the verification code. Please try again later.")
            return redirect("password_reset")

        messages.success(request, "If an account exists for that email, a verification code has been sent.")
        return redirect("password_reset_verify")

    return render(request, "registration/password_reset_form.html", {"prefill_email": prefill_email})


def password_reset_verify(request):
    prefill_email = (request.session.get("pwd_reset_email") or "").strip()
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()
        email = (request.POST.get("email") or prefill_email or "").strip().lower()
        if email:
            request.session["pwd_reset_email"] = email

        if action == "resend":
            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, "Enter a valid email address.")
                return redirect("password_reset_verify")

            try:
                _send_password_reset_code(email)
            except Exception:
                messages.error(request, "Could not resend the verification code. Please try again later.")
                return redirect("password_reset_verify")

            messages.success(request, "If an account exists for that email, a verification code has been sent.")
            return redirect("password_reset_verify")

        code = (request.POST.get("code") or "").strip()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""

        if not email or not code or not password1 or not password2:
            messages.error(request, "All fields are required.")
            return redirect("password_reset_verify")

        if password1 != password2:
            messages.error(request, "Passwords do not match.")
            return redirect("password_reset_verify")

        user = _find_user_for_password_reset(email)
        if user is None or not user.is_active:
            messages.error(request, "Invalid verification code.")
            return redirect("password_reset_verify")

        now = timezone.now()
        reset_code = (
            PasswordResetCode.objects.filter(
                user=user,
                used_at__isnull=True,
                expires_at__gt=now,
            )
            .order_by("-created_at")
            .first()
        )
        if reset_code is None:
            messages.error(request, "No active verification code found. Please request a new one.")
            return redirect("password_reset")

        is_match = False
        if code.isdigit() and len(code) == 6:
            is_match = check_password(code, reset_code.code_hash)
        if not is_match:
            reset_code.attempts += 1
            if reset_code.attempts >= PASSWORD_RESET_CODE_MAX_ATTEMPTS:
                reset_code.used_at = now
                reset_code.save(update_fields=["attempts", "used_at"])
            else:
                reset_code.save(update_fields=["attempts"])
            messages.error(request, "Invalid verification code.")
            return redirect("password_reset_verify")

        try:
            validate_password(password1, user=user)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if getattr(exc, "messages", None) else str(exc))
            return redirect("password_reset_verify")

        user.set_password(password1)
        user.save(update_fields=["password"])
        reset_code.used_at = now
        reset_code.save(update_fields=["used_at"])
        request.session.pop("pwd_reset_email", None)

        messages.success(request, "Your password has been reset. Please login.")
        return redirect("login")

    return render(request, "registration/password_reset_verify.html", {"prefill_email": prefill_email})


# Login view
def login_view(request):
    if request.method == "POST":
        identifier = (request.POST.get('login_email') or '').strip()
        password = request.POST.get('login_password')

        user = authenticate(request, username=identifier, password=password)

        if user is None and identifier and "@" in identifier:
            user_obj = User.objects.filter(email__iexact=identifier).order_by("-id").first()
            if user_obj:
                user = authenticate(request, username=user_obj.username, password=password)

        if user is not None:
            login(request, user)
            _get_or_create_profile(user)
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")

            next_page = request.GET.get('next', 'index')
            return redirect(next_page)

        messages.error(request, "Invalid email or password.")

    return render(request, 'login.html')

# Register view
def register_view(request):
    if request.method == "POST":
        name = (request.POST.get('name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        password = request.POST.get('password')
        repeat_password = request.POST.get('repeat_password')
        user_type = request.POST.get('user_type', 'GUEST')

        if not all([name, email, password, repeat_password]):
            messages.error(request, "All fields are required.")
            return redirect('register')

        if password != repeat_password:
            messages.error(request, "Passwords do not match!")
            return redirect('register')

        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            messages.error(request, "An account with this email already exists.")
            return redirect('register')

        if len(password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return redirect('register')

        try:
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=name
            )
            valid_user_types = {code for code, _ in UserProfile.USER_TYPES}
            if user_type not in valid_user_types:
                user_type = 'GUEST'
            wants_owner = user_type == 'OWNER'
            profile_type = 'GUEST' if wants_owner else user_type
            UserProfile.objects.update_or_create(
                user=user,
                defaults={'user_type': profile_type},
            )
            if wants_owner:
                login(request, user)
                messages.success(request, "Account created. Please complete the partnership form.")
                return redirect('hotel_partner_apply')
            messages.success(request, "Registration successful! Please login.")
            return redirect('login')
        except Exception as e:
            messages.error(request, f"Registration failed: {str(e)}")
            return redirect('register')

    return render(request, 'register.html')

# Logout view
def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('index')


@login_required(login_url='login')
def profile_view(request):
    profile = _get_or_create_profile(request.user)
    if request.method == "POST":
        action = request.POST.get('action', 'update')
        if action == "reset_profile":
            request.user.first_name = ""
            request.user.last_name = ""
            if profile:
                profile.mobile = ""
                profile.save(update_fields=['mobile'])
            request.user.save(update_fields=['first_name', 'last_name'])
            messages.success(request, "Your profile has been reset.")
            return redirect('profile')

        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        mobile = (request.POST.get('mobile') or '').strip()

        if not email:
            messages.error(request, "Email is required.")
            return redirect('profile')

        if (
            User.objects.filter(username__iexact=email).exclude(id=request.user.id).exists()
            or User.objects.filter(email__iexact=email).exclude(id=request.user.id).exists()
        ):
            messages.error(request, "That email is already in use.")
            return redirect('profile')

        request.user.first_name = first_name
        request.user.last_name = last_name
        request.user.email = email
        request.user.username = email
        request.user.save(update_fields=['first_name', 'last_name', 'email', 'username'])

        if profile is not None:
            profile.mobile = mobile
            profile.save(update_fields=['mobile'])

        messages.success(request, "Profile updated successfully.")
        return redirect('profile')

    return render(request, 'profile.html', {'profile': profile})


@login_required(login_url='login')
def my_bookings_view(request):
    _mark_completed_bookings()
    bookings = (
        Booking.objects.filter(user=request.user)
        .select_related('room')
        .prefetch_related('review')
        .order_by('-created_at')
    )
    hotels_qs = Hotel.objects.filter(is_active=True, is_approved=True)
    kenya_hotels = hotels_qs.filter(country__iexact='Kenya')
    use_kenya_stats = kenya_hotels.exists()
    if use_kenya_stats:
        hotels_qs = kenya_hotels

    rooms_qs = Room.objects.filter(is_approved=True, available=True)
    if use_kenya_stats:
        rooms_qs = rooms_qs.filter(hotel__in=hotels_qs)

    apartments_qs = rooms_qs.filter(category='APT')

    destinations_count = (
        hotels_qs.exclude(city__isnull=True)
        .exclude(city__exact='')
        .values('city')
        .distinct()
        .count()
    )
    reviews_qs = Review.objects.all()
    if use_kenya_stats:
        reviews_qs = reviews_qs.filter(room__hotel__in=hotels_qs)

    figures = [
        {
            "label": "Hotels",
            "value": hotels_qs.count(),
        },
        {
            "label": "Rooms",
            "value": rooms_qs.count(),
        },
        {
            "label": "Apartments",
            "value": apartments_qs.count(),
        },
        {
            "label": "Destinations",
            "value": destinations_count,
        },
        {
            "label": "Reviews",
            "value": reviews_qs.count(),
        },
    ]
    return render(request, 'my_bookings.html', {'bookings': bookings, 'figures': figures})


@login_required(login_url='login')
def submit_review(request, booking_id):
    booking = get_object_or_404(
        Booking,
        id=booking_id,
        user=request.user,
        status='COMPLETED',
    )
    if not booking.room:
        messages.error(request, "This booking does not have a room to review.")
        return redirect('my_bookings')
    if hasattr(booking, 'review'):
        messages.info(request, "You have already reviewed this booking.")
        return redirect('room_detail', room_id=booking.room_id)

    if request.method == "POST":
        rating = request.POST.get('rating')
        title = request.POST.get('title')
        comment = request.POST.get('comment')

        if not all([rating, title, comment]):
            messages.error(request, "Please complete all review fields.")
            return redirect('submit_review', booking_id=booking.id)

        try:
            rating_value = int(rating)
        except (TypeError, ValueError):
            messages.error(request, "Rating must be a number between 1 and 5.")
            return redirect('submit_review', booking_id=booking.id)

        if rating_value < 1 or rating_value > 5:
            messages.error(request, "Rating must be between 1 and 5.")
            return redirect('submit_review', booking_id=booking.id)

        Review.objects.create(
            booking=booking,
            room=booking.room,
            user=request.user,
            rating=rating_value,
            title=title,
            comment=comment,
        )
        messages.success(request, "Thanks for your review!")
        return redirect('room_detail', room_id=booking.room_id)

    return render(request, 'submit_review.html', {'booking': booking})


@owner_required
def owner_dashboard(request):
    hotels = Hotel.objects.filter(owner=request.user).order_by('-id')
    hotel = hotels.first()
    if hotels.count() > 1:
        messages.warning(
            request,
            "Multiple hotels found. Only your most recent hotel is active in the dashboard.",
        )

    if request.method == "POST":
        if not hotel:
            messages.error(request, "No hotel profile found to update.")
            return redirect('owner_dashboard')
        image = request.FILES.get('image')
        if not image:
            messages.error(request, "Please choose an image to upload.")
            return redirect('owner_dashboard')
        hotel.image = image
        hotel.save(update_fields=['image'])
        messages.success(request, "Hotel image updated successfully.")
        return redirect('owner_dashboard')

    if hotel:
        rooms = Room.objects.filter(owner=request.user, hotel=hotel).order_by('-id')
        confirmed_bookings = Booking.objects.filter(
            room__owner=request.user,
            room__hotel=hotel,
            status='CONFIRMED',
        ).count()
        pending_bookings = Booking.objects.filter(
            room__owner=request.user,
            room__hotel=hotel,
            status='PENDING',
        ).count()
        revenue_total = (
            Payment.objects.filter(
                booking__room__owner=request.user,
                booking__room__hotel=hotel,
                status='SUCCEEDED',
            )
            .aggregate(total=Sum('amount'))
            .get('total')
            or Decimal('0.00')
        )
        recent_bookings = (
            Booking.objects.filter(room__owner=request.user, room__hotel=hotel)
            .select_related('room', 'user')
            .order_by('-created_at')[:10]
        )
    else:
        rooms = Room.objects.none()
        confirmed_bookings = 0
        pending_bookings = 0
        revenue_total = Decimal('0.00')
        recent_bookings = []

    total_rooms = rooms.count()
    total_hotels = 1 if hotel else 0
    return render(
        request,
        'owner_dashboard.html',
        {
            'rooms': rooms,
            'hotels': hotels[:1],
            'hotel': hotel,
            'total_hotels': total_hotels,
            'total_rooms': total_rooms,
            'confirmed_bookings': confirmed_bookings,
            'pending_bookings': pending_bookings,
            'revenue_total': revenue_total,
            'recent_bookings': recent_bookings,
        },
    )


@owner_required
def owner_add_hotel(request):
    if _owner_has_hotel(request.user):
        messages.info(request, "You already have a hotel on the platform.")
        return redirect('owner_dashboard')

    messages.info(request, "Please complete the partnership form to list your hotel.")
    return redirect('hotel_partner_apply')


@owner_required
def owner_add_room(request):
    owner_hotels = Hotel.objects.filter(owner=request.user, is_approved=True, is_active=True).order_by('name')
    if not owner_hotels.exists():
        latest_application = (
            HotelApplication.objects.filter(user=request.user)
            .order_by('-created_at')
            .first()
        )
        if latest_application and latest_application.status == 'PENDING':
            messages.info(request, "Your partnership application is still under review.")
            return redirect('hotel_application_status')
        messages.info(request, "Please complete the partnership form before creating rooms.")
        return redirect('hotel_partner_apply')

    if owner_hotels.count() > 1:
        messages.error(request, "Multiple hotels detected. Please contact support.")
        return redirect('owner_dashboard')

    single_hotel = owner_hotels.first()

    if request.method == "POST":
        title = request.POST.get('title')
        category = request.POST.get('category')
        description = request.POST.get('description')
        amenities_list = request.POST.getlist('amenities')
        amenities = ", ".join([item.strip() for item in amenities_list if item.strip()])
        price = request.POST.get('price')
        size = request.POST.get('size')
        beds = request.POST.get('beds')
        capacity = request.POST.get('capacity')
        hotel_id = request.POST.get('hotel_id')
        image = request.FILES.get('image')

        if not all([title, category, description, price, size, beds, capacity]):
            messages.error(request, "Please fill in all required fields.")
            return redirect('owner_add_room')

        try:
            price_value = Decimal(price)
            size_value = int(size)
            capacity_value = int(capacity)
        except (InvalidOperation, TypeError, ValueError):
            messages.error(request, "Price, size, and capacity must be valid numbers.")
            return redirect('owner_add_room')

        if single_hotel:
            hotel = single_hotel
        else:
            hotel = get_object_or_404(owner_hotels, id=hotel_id)
        Room.objects.create(
            title=title,
            category=category,
            description=description,
            amenities=amenities,
            price=price_value,
            size=size_value,
            beds=beds,
            capacity=capacity_value,
            image=image,
            owner=request.user,
            hotel=hotel,
            available=True,
            is_approved=True,
        )
        admin_emails = _get_notification_emails()
        if admin_emails:
            import contextlib
            with contextlib.suppress(Exception):
                send_mail(
                    subject=f"New Room Published - {title}",
                    message=(
                        "A new room has been published by a hotel owner.\n\n"
                        f"Room: {title}\n"
                        f"Hotel: {hotel.name}\n"
                        f"Owner: {request.user.first_name} {request.user.last_name}\n"
                        f"Price: KES {price_value}\n"
                        f"Capacity: {capacity_value}\n"
                    ),
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                    recipient_list=admin_emails,
                    fail_silently=True,
                )
        messages.success(request, "Room added successfully and is now live.")
        return redirect('owner_dashboard')

    return render(
        request,
        'owner_add_room.html',
        {
            'categories': Room.ROOM_CATEGORIES,
            'hotels': owner_hotels,
            'single_hotel': single_hotel,
            'amenities': ROOM_AMENITIES,
        },
    )


@login_required(login_url='login')
def hotel_partner_apply(request):
    if request.user.is_staff or request.user.is_superuser:
        messages.info(request, "Admin accounts do not submit partnership applications.")
        return redirect('admin_dashboard')
    if _owner_has_hotel(request.user):
        messages.info(request, "You already have a hotel on the platform.")
        return redirect('owner_dashboard')
    existing_application = (
        HotelApplication.objects.filter(user=request.user)
        .order_by('-created_at')
        .first()
    )
    if existing_application and existing_application.status == 'APPROVED':
        messages.info(request, "Your partnership application has already been approved.")
        return redirect('owner_dashboard')
    if existing_application and existing_application.status == 'PENDING':
        messages.info(request, "You already have a pending hotel application.")
        return redirect('hotel_application_status')

    if request.method == "POST":
        hotel_name = (request.POST.get('hotel_name') or '').strip()
        star_rating = request.POST.get('star_rating')
        description = request.POST.get('description') or ''
        address = request.POST.get('address') or ''
        city = request.POST.get('city') or ''
        country = request.POST.get('country') or ''
        contact_name = (request.POST.get('contact_name') or '').strip()
        contact_email = (request.POST.get('contact_email') or '').strip()
        contact_phone = (request.POST.get('contact_phone') or '').strip()
        room_types = request.POST.get('room_types') or ''
        room_pricing = request.POST.get('room_pricing') or ''
        availability_details = request.POST.get('availability_details') or ''
        commission_rate = request.POST.get('commission_rate') or ''
        payout_method = request.POST.get('payout_method') or 'BANK'
        payout_schedule = request.POST.get('payout_schedule') or 'WEEKLY'
        bank_name = request.POST.get('bank_name') or ''
        bank_account_name = request.POST.get('bank_account_name') or ''
        bank_account_number = request.POST.get('bank_account_number') or ''
        bank_branch = request.POST.get('bank_branch') or ''
        bank_swift = request.POST.get('bank_swift') or ''
        mobile_money_provider = request.POST.get('mobile_money_provider') or ''
        mobile_money_number = request.POST.get('mobile_money_number') or ''
        paypal_email = request.POST.get('paypal_email') or ''
        agreed_to_terms = request.POST.get('agreed_to_terms') == 'on'

        if not hotel_name or not contact_name or not contact_email or not contact_phone:
            messages.error(request, "Please complete all required fields.")
            return redirect('hotel_partner_apply')
        if not agreed_to_terms:
            messages.error(request, "You must accept the partnership terms to continue.")
            return redirect('hotel_partner_apply')

        rating_value = None
        if star_rating:
            try:
                rating_value = int(star_rating)
            except (TypeError, ValueError):
                rating_value = None

        commission_value = None
        if commission_rate:
            try:
                commission_value = Decimal(commission_rate)
            except (InvalidOperation, TypeError, ValueError):
                commission_value = None

        application = HotelApplication.objects.create(
            user=request.user,
            hotel_name=hotel_name,
            star_rating=rating_value,
            description=description,
            address=address,
            city=city,
            country=country,
            contact_name=contact_name,
            contact_email=contact_email,
            contact_phone=contact_phone,
            room_types=room_types,
            room_pricing=room_pricing,
            availability_details=availability_details,
            commission_rate=commission_value or HotelApplication._meta.get_field('commission_rate').default,
            payout_method=payout_method,
            payout_schedule=payout_schedule,
            bank_name=bank_name,
            bank_account_name=bank_account_name,
            bank_account_number=bank_account_number,
            bank_branch=bank_branch,
            bank_swift=bank_swift,
            mobile_money_provider=mobile_money_provider,
            mobile_money_number=mobile_money_number,
            paypal_email=paypal_email,
            agreed_to_terms=agreed_to_terms,
            status='PENDING',
        )

        license_file = request.FILES.get('license_doc')
        if license_file:
            HotelDocument.objects.create(
                application=application,
                document_type='LICENSE',
                file=license_file,
            )
        for photo in request.FILES.getlist('property_photos'):
            HotelDocument.objects.create(
                application=application,
                document_type='PHOTOS',
                file=photo,
            )
        amenities_doc = request.FILES.get('amenities_doc')
        if amenities_doc:
            HotelDocument.objects.create(
                application=application,
                document_type='AMENITIES',
                file=amenities_doc,
            )
        agreement_doc = request.FILES.get('agreement_doc')
        if agreement_doc:
            HotelDocument.objects.create(
                application=application,
                document_type='AGREEMENT',
                file=agreement_doc,
            )
        for other_doc in request.FILES.getlist('other_docs'):
            HotelDocument.objects.create(
                application=application,
                document_type='OTHER',
                file=other_doc,
            )

        admin_emails = _get_notification_emails()
        if admin_emails:
            import contextlib
            detail_url = request.build_absolute_uri(
                reverse('admin_hotel_application_detail', args=[application.id])
            )
            with contextlib.suppress(Exception):
                send_mail(
                    subject=f"New Hotel Partnership Application #{application.id}",
                    message=(
                        "A new hotel partnership application was submitted.\n\n"
                        f"Application ID: {application.id}\n"
                        f"Hotel: {application.hotel_name}\n"
                        f"Contact: {application.contact_name}\n"
                        f"Email: {application.contact_email}\n"
                        f"Phone: {application.contact_phone}\n"
                        f"City/Country: {application.city} {application.country}\n"
                        f"Payout: {application.payout_method} ({application.payout_schedule})\n\n"
                        f"Review in admin dashboard: {detail_url}\n"
                    ),
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                    recipient_list=admin_emails,
                    fail_silently=True,
                )

        messages.success(request, "Your hotel application has been submitted for review.")
        return redirect('hotel_application_status')

    return render(
        request,
        'hotel_partner_apply.html',
        {
            'application': existing_application,
            'payout_methods': HotelApplication.PAYOUT_METHODS,
            'payout_schedules': HotelApplication.PAYOUT_SCHEDULES,
            'prefill_name': request.user.get_full_name() or request.user.username,
            'prefill_email': request.user.email or '',
        },
    )


@login_required(login_url='login')
def hotel_application_status(request):
    if request.user.is_staff or request.user.is_superuser:
        return redirect('admin_dashboard')
    application = (
        HotelApplication.objects.filter(user=request.user)
        .order_by('-created_at')
        .first()
    )
    return render(request, 'hotel_application_status.html', {'application': application})


@login_required(login_url='login')
def admin_hotel_applications_view(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    applications = HotelApplication.objects.select_related('user').order_by('-created_at')
    status_filter = request.GET.get('status')
    if status_filter:
        applications = applications.filter(status=status_filter)

    return render(
        request,
        'admin_hotel_applications.html',
        {
            'applications': applications,
            'statuses': HotelApplication.STATUS,
            'selected_status': status_filter or '',
        },
    )


@login_required(login_url='login')
def admin_hotel_application_detail(request, application_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    application = get_object_or_404(HotelApplication, id=application_id)
    documents = application.documents.all().order_by('uploaded_at')

    if request.method == "POST":
        action = request.POST.get('action')
        admin_notes = (request.POST.get('admin_notes') or '').strip()
        if action == 'approve':
            commission_rate = request.POST.get('commission_rate') or application.commission_rate
            payout_method = request.POST.get('payout_method') or application.payout_method
            payout_schedule = request.POST.get('payout_schedule') or application.payout_schedule
            cancellation_policy = request.POST.get('cancellation_policy') or ''
            refund_policy = request.POST.get('refund_policy') or ''

            try:
                commission_value = Decimal(commission_rate)
            except (InvalidOperation, TypeError, ValueError):
                commission_value = application.commission_rate

            if application.user and _owner_has_hotel(application.user):
                messages.error(
                    request,
                    "This owner already has a hotel. Reject the application or update the existing hotel.",
                )
                return redirect('admin_hotel_application_detail', application_id=application.id)

            hotel = Hotel.objects.create(
                owner=application.user,
                name=application.hotel_name,
                star_rating=application.star_rating,
                description=application.description,
                address=application.address,
                city=application.city,
                country=application.country,
                phone=application.contact_phone,
                email=application.contact_email,
                commission_rate=commission_value,
                payout_method=payout_method,
                payout_schedule=payout_schedule,
                bank_name=application.bank_name,
                bank_account_name=application.bank_account_name,
                bank_account_number=application.bank_account_number,
                bank_branch=application.bank_branch,
                bank_swift=application.bank_swift,
                mobile_money_provider=application.mobile_money_provider,
                mobile_money_number=application.mobile_money_number,
                paypal_email=application.paypal_email,
                is_approved=True,
                is_active=True,
            )

            HotelAgreement.objects.create(
                hotel=hotel,
                commission_rate=commission_value,
                payout_schedule=payout_schedule,
                cancellation_policy=cancellation_policy,
                refund_policy=refund_policy,
                status='DRAFT',
                signed_by_hotel=False,
            )

            if application.user:
                _ensure_owner_profile(application.user)

            application.status = 'APPROVED'
            application.admin_notes = admin_notes
            application.save(update_fields=['status', 'admin_notes', 'updated_at'])

            messages.success(request, "Hotel application approved and hotel created.")
            return redirect('admin_hotel_applications')

        if action == 'reject':
            application.status = 'REJECTED'
            application.admin_notes = admin_notes
            application.save(update_fields=['status', 'admin_notes', 'updated_at'])
            messages.success(request, "Hotel application rejected.")
            return redirect('admin_hotel_applications')

    return render(
        request,
        'admin_hotel_application_detail.html',
        {
            'application': application,
            'documents': documents,
            'payout_methods': HotelApplication.PAYOUT_METHODS,
            'payout_schedules': HotelApplication.PAYOUT_SCHEDULES,
        },
    )


@login_required(login_url='login')
def admin_dashboard(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    query = (request.GET.get('q') or '').strip()
    users_qs = User.objects.all().order_by('-date_joined')
    bookings_qs = Booking.objects.select_related('room', 'user').order_by('-created_at')
    rooms_qs = Room.objects.select_related('owner', 'hotel').order_by('-id')
    hotels_qs = Hotel.objects.select_related('owner').order_by('-created_at')
    payments_qs = Payment.objects.select_related('booking').order_by('-created_at')
    applications_qs = HotelApplication.objects.select_related('user').order_by('-created_at')

    q_int = None
    if query:
        try:
            q_int = int(query)
        except (TypeError, ValueError):
            q_int = None

        users_qs = users_qs.filter(
            Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
        bookings_filter = (
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(room__title__icontains=query)
            | Q(room__hotel__name__icontains=query)
        )
        if q_int is not None:
            bookings_filter |= Q(id=q_int)
        bookings_qs = bookings_qs.filter(bookings_filter)
        rooms_qs = rooms_qs.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(hotel__name__icontains=query)
            | Q(owner__username__icontains=query)
            | Q(owner__email__icontains=query)
        )
        hotels_qs = hotels_qs.filter(
            Q(name__icontains=query)
            | Q(city__icontains=query)
            | Q(country__icontains=query)
            | Q(owner__username__icontains=query)
            | Q(owner__email__icontains=query)
        )
        payments_filter = (
            Q(reference__icontains=query)
            | Q(provider__icontains=query)
        )
        if q_int is not None:
            payments_filter |= Q(id=q_int) | Q(booking__id=q_int)
        payments_qs = payments_qs.filter(payments_filter)
        applications_qs = applications_qs.filter(
            Q(hotel_name__icontains=query)
            | Q(contact_name__icontains=query)
            | Q(contact_email__icontains=query)
            | Q(contact_phone__icontains=query)
            | Q(status__icontains=query)
        )

    context = {
        'query': query,
        'users': users_qs[:10],
        'bookings': bookings_qs[:10],
        'rooms': rooms_qs[:10],
        'hotels': hotels_qs[:10],
        'payments': payments_qs[:10],
        'applications': applications_qs[:10],
        'stats': {
            'users': users_qs.count(),
            'bookings': bookings_qs.count(),
            'rooms': rooms_qs.count(),
            'hotels': hotels_qs.count(),
            'payments': payments_qs.count(),
            'applications': applications_qs.count(),
        },
    }
    return render(request, 'admin_dashboard.html', context)


@login_required(login_url='login')
def admin_users_view(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    users = User.objects.select_related('profile').all().annotate(
        total_bookings=Count('booking', distinct=True),
        confirmed_bookings=Count('booking', filter=Q(booking__status='CONFIRMED'), distinct=True),
    ).order_by('-date_joined')
    return render(request, 'admin_users.html', {'users': users})


@login_required(login_url='login')
def admin_user_detail(request, user_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    account = get_object_or_404(User.objects.select_related('profile'), id=user_id)
    profile = getattr(account, 'profile', None)

    owned_hotels = Hotel.objects.filter(owner=account).order_by('-created_at')
    owned_rooms = Room.objects.filter(owner=account).select_related('hotel').order_by('-id')
    bookings = Booking.objects.filter(user=account).select_related('room', 'room__hotel').order_by('-created_at')[:20]

    return render(
        request,
        'admin_user_detail.html',
        {
            'account': account,
            'profile': profile,
            'owned_hotels': owned_hotels,
            'owned_rooms': owned_rooms,
            'bookings': bookings,
        },
    )


@login_required(login_url='login')
def admin_user_edit(request, user_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    account = get_object_or_404(User.objects.select_related('profile'), id=user_id)
    profile = _get_or_create_profile(account)

    if request.method == "POST":
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        mobile = (request.POST.get('mobile') or '').strip()
        user_type = (request.POST.get('user_type') or '').strip()
        is_active = bool(request.POST.get('is_active'))

        if email:
            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, "Please enter a valid email address.")
                return redirect('admin_user_edit', user_id=account.id)

        allowed_user_types = {choice for choice, _ in UserProfile.USER_TYPES}
        if user_type and user_type not in allowed_user_types:
            messages.error(request, "Invalid user type selected.")
            return redirect('admin_user_edit', user_id=account.id)

        account.first_name = first_name
        account.last_name = last_name
        account.email = email
        account.is_active = is_active
        account.save(update_fields=['first_name', 'last_name', 'email', 'is_active'])

        profile.mobile = mobile
        if user_type:
            profile.user_type = user_type
        profile.save(update_fields=['mobile', 'user_type'])

        messages.success(request, "User profile updated successfully.")
        return redirect('admin_user_detail', user_id=account.id)

    return render(
        request,
        'admin_user_edit.html',
        {
            'account': account,
            'profile': profile,
            'user_types': UserProfile.USER_TYPES,
        },
    )


@login_required(login_url='login')
def admin_user_toggle_active(request, user_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to perform this action.")
        return redirect('index')
    if request.method != "POST":
        return redirect('admin_users')

    account = get_object_or_404(User, id=user_id)
    if account.is_superuser and not request.user.is_superuser:
        messages.error(request, "You do not have permission to modify this account.")
        return redirect('admin_users')

    account.is_active = not account.is_active
    account.save(update_fields=['is_active'])
    messages.success(request, f"User {account.username} is now {'active' if account.is_active else 'inactive'}.")
    return redirect(request.META.get('HTTP_REFERER') or 'admin_users')


@login_required(login_url='login')
def admin_hotels_view(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    status = request.GET.get('status', 'active')
    hotels = Hotel.objects.select_related('owner').order_by('-created_at')
    if status == 'active':
        hotels = hotels.filter(is_active=True)
    elif status == 'inactive':
        hotels = hotels.filter(is_active=False)
    elif status == 'unapproved':
        hotels = hotels.filter(is_approved=False)

    return render(
        request,
        'admin_hotels.html',
        {
            'hotels': hotels,
            'status': status,
        },
    )


@login_required(login_url='login')
def admin_hotel_detail(request, hotel_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    hotel = get_object_or_404(Hotel.objects.select_related('owner'), id=hotel_id)
    rooms = Room.objects.filter(hotel=hotel).select_related('owner').order_by('-id')
    return render(request, 'admin_hotel_detail.html', {'hotel': hotel, 'rooms': rooms})


@login_required(login_url='login')
def admin_hotel_edit(request, hotel_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    hotel = get_object_or_404(Hotel.objects.select_related('owner'), id=hotel_id)

    if request.method == "POST":
        is_active = bool(request.POST.get('is_active'))
        is_approved = bool(request.POST.get('is_approved'))
        remove_image = bool(request.POST.get('remove_image'))
        image = request.FILES.get('image')

        hotel.is_active = is_active
        hotel.is_approved = is_approved
        if remove_image:
            hotel.image = None
        elif image:
            hotel.image = image
        hotel.save(update_fields=['is_active', 'is_approved', 'image'])

        messages.success(request, "Hotel profile updated.")
        return redirect('admin_hotel_detail', hotel_id=hotel.id)

    return render(request, 'admin_hotel_edit.html', {'hotel': hotel})


@login_required(login_url='login')
def admin_disable_hotel(request, hotel_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to perform this action.")
        return redirect('index')
    if request.method != "POST":
        return redirect('admin_hotels')

    hotel = get_object_or_404(Hotel, id=hotel_id)
    hotel.is_active = False
    hotel.save(update_fields=['is_active'])
    messages.success(request, f"Hotel \"{hotel.name}\" has been deactivated.")
    return redirect(request.META.get('HTTP_REFERER') or 'admin_hotels')


@login_required(login_url='login')
def admin_room_detail(request, room_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    room = get_object_or_404(Room.objects.select_related('hotel', 'owner'), id=room_id)
    return render(request, 'admin_room_detail.html', {'room': room})


@login_required(login_url='login')
def admin_room_edit(request, room_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    room = get_object_or_404(Room.objects.select_related('hotel', 'owner'), id=room_id)

    if request.method == "POST":
        is_approved = bool(request.POST.get('is_approved'))
        available = bool(request.POST.get('available'))
        remove_image = bool(request.POST.get('remove_image'))
        image = request.FILES.get('image')

        room.is_approved = is_approved
        room.available = available if is_approved else False
        if remove_image:
            room.image = None
        elif image:
            room.image = image
        room.save(update_fields=['is_approved', 'available', 'image'])

        messages.success(request, "Room profile updated.")
        return redirect('admin_room_detail', room_id=room.id)

    return render(request, 'admin_room_edit.html', {'room': room})


@login_required(login_url='login')
def admin_disable_room(request, room_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to perform this action.")
        return redirect('index')
    if request.method != "POST":
        return redirect('admin_rooms')

    room = get_object_or_404(Room, id=room_id)
    room.is_approved = False
    room.available = False
    room.save(update_fields=['is_approved', 'available'])
    messages.success(request, f"Room \"{room.title}\" has been disabled.")
    return redirect(request.META.get('HTTP_REFERER') or 'admin_rooms')


@login_required(login_url='login')
def admin_payments_view(request):  # sourcery skip: low-code-quality
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    if request.method == "POST":
        payment_id = request.POST.get('payment_id')
        action = request.POST.get('action', 'update_status')
        new_status = request.POST.get('status')
        valid_statuses = {code for code, _ in Payment.STATUSES}

        payment = get_object_or_404(Payment, id=payment_id)
        if action == "query_mpesa":
            query_response, query_error = _mpesa_query_stk_status(payment)
            if query_error:
                messages.error(request, query_error)
                return redirect('admin_payments')

            existing_raw = payment.raw_response if isinstance(payment.raw_response, dict) else {}
            updated_raw = dict(existing_raw)
            updated_raw["stk_query"] = query_response

            result_code = query_response.get("ResultCode")
            result_code_str = str(result_code) if result_code is not None else ""
            previous_status = payment.status
            if result_code_str == "0":
                payment.status = 'SUCCEEDED'
                if payment.booking.status == 'PENDING':
                    payment.booking.status = 'CONFIRMED'
                    payment.booking.save(update_fields=['status', 'updated_at'])
            elif result_code_str == "1032":
                payment.status = 'CANCELLED'
                if payment.booking.status in ['PENDING', 'CONFIRMED']:
                    payment.booking.status = 'CANCELLED'
                    payment.booking.save(update_fields=['status', 'updated_at'])
            elif result_code_str in {'1', '1037', '2001'}:
                payment.status = 'FAILED'

            payment.raw_response = updated_raw
            payment.save(update_fields=['status', 'raw_response', 'updated_at'])
            if previous_status != 'SUCCEEDED' and payment.status == 'SUCCEEDED':
                _send_receipt_email(request, payment.booking)
            messages.success(
                request,
                f"STK query complete for payment #{payment.id}. ResultCode: {query_response.get('ResultCode', 'N/A')}.",
            )
            return redirect('admin_payments')

        if new_status not in valid_statuses:
            messages.error(request, "Invalid payment status selected.")
            return redirect('admin_payments')

        payment.status = new_status
        payment.save(update_fields=['status', 'updated_at'])

        if new_status == 'SUCCEEDED' and payment.booking.status == 'PENDING':
            payment.booking.status = 'CONFIRMED'
            payment.booking.save(update_fields=['status', 'updated_at'])
        elif new_status in ['CANCELLED', 'REFUNDED'] and payment.booking.status in ['PENDING', 'CONFIRMED']:
            payment.booking.status = 'CANCELLED'
            payment.booking.save(update_fields=['status', 'updated_at'])

        messages.success(request, f"Payment #{payment.id} updated to {new_status}.")
        return redirect('admin_payments')

    payments = Payment.objects.select_related('booking', 'booking__room').order_by('-created_at')
    status_filter = request.GET.get('status')
    if status_filter:
        payments = payments.filter(status=status_filter)

    context = {
        'payments': payments,       
        'statuses': Payment.STATUSES,
        'selected_status': status_filter or '',
    }
    return render(request, 'admin_payments.html', context)


@login_required(login_url='login')
def admin_booked_rooms_view(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    _mark_completed_bookings()
    today = datetime.now().date()
    bookings = Booking.objects.filter(
        status='CONFIRMED',
        check_out__gt=today,
    ).select_related('room', 'user').order_by('check_in', 'room__title')

    return render(request, 'admin_booked_rooms.html', {'bookings': bookings})


@login_required(login_url='login')
def admin_rooms_view(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    status = request.GET.get('status', 'pending')
    rooms = Room.objects.select_related('owner', 'hotel').order_by('-id')
    if status == 'approved':
        rooms = rooms.filter(is_approved=True)
    elif status == 'pending':
        rooms = rooms.filter(is_approved=False)

    return render(
        request,
        'admin_rooms.html',
        {
            'rooms': rooms,
            'status': status,
        },
    )


@login_required(login_url='login')
def admin_approve_room(request, room_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to perform this action.")
        return redirect('index')
    if request.method != "POST":
        return redirect('admin_rooms')

    room = get_object_or_404(Room, id=room_id)
    room.is_approved = True
    room.available = True
    room.save(update_fields=['is_approved', 'available'])

    if room.owner and room.owner.email:
        send_mail(
            subject="Your room has been approved",
            message=(
                f"Hello {room.owner.first_name or room.owner.username},\n\n"
                f"Your room listing \"{room.title}\" has been approved and is now live."
            ),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            recipient_list=[room.owner.email],
            fail_silently=True,
        )

    messages.success(request, f"Room '{room.title}' approved.")
    return redirect('admin_rooms')


@login_required(login_url='login')
def admin_reject_room(request, room_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to perform this action.")
        return redirect('index')
    if request.method != "POST":
        return redirect('admin_rooms')

    room = get_object_or_404(Room, id=room_id)
    room.is_approved = False
    room.available = False
    room.save(update_fields=['is_approved', 'available'])

    reason = (request.POST.get('reason') or "").strip()
    if room.owner and room.owner.email:
        message = (
            f"Hello {room.owner.first_name or room.owner.username},\n\n"
            f"Your room listing \"{room.title}\" was not approved."
        )
        if reason:
            message += f"\n\nReason: {reason}"
        send_mail(
            subject="Your room listing was rejected",
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            recipient_list=[room.owner.email],
            fail_silently=True,
        )

    messages.success(request, f"Room '{room.title}' rejected.")
    return redirect('admin_rooms')

# Room view (legacy, redirect to room_list)
def room(request):
    return redirect('room_list')


def subscribe(request):
    if request.method != "POST":
        return redirect('index')
    if email := request.POST.get('email'):
        messages.success(request, "Thanks for subscribing to our offers.")
        return redirect('index')
    messages.error(request, "Please enter a valid email address.")
    return redirect('index')
