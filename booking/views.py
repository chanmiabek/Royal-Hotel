from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.mail import send_mail
from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db.models import Exists, OuterRef, Count, Q
from django.db import connection
from django.db.utils import ProgrammingError, OperationalError
from decimal import Decimal, InvalidOperation
import json
import io
import base64
from urllib.parse import urlencode
from django.contrib.auth.models import User
from datetime import datetime
from .models import Room, Booking, ContactMessage, Payment

try:
    import requests
except Exception:
    requests = None


def _booking_tables_ready():
    required_tables = {Room._meta.db_table, Booking._meta.db_table}
    try:
        existing_tables = set(connection.introspection.table_names())
    except (ProgrammingError, OperationalError):
        return False
    return required_tables.issubset(existing_tables)


def _with_booking_status(queryset):
    if not _booking_tables_ready():
        return queryset.none()
    today = datetime.today().date()
    confirmed_bookings = Booking.objects.filter(
        room=OuterRef('pk'),
        status='CONFIRMED',
        check_out__gt=today,
    )
    return queryset.annotate(is_booked=Exists(confirmed_bookings))


def _mark_completed_bookings():
    today = datetime.today().date()
    try:
        Booking.objects.filter(
            status='CONFIRMED',
            check_out__lte=today,
        ).update(status='COMPLETED')
    except (ProgrammingError, OperationalError):
        # Database tables may not exist yet during first deploy before migrations.
        return


# Home page view
def home(request):
    _mark_completed_bookings()
    if not _booking_tables_ready():
        return render(request, 'home.html', {'featured_rooms': []})
    # Get featured rooms for homepage
    featured_rooms = list(_with_booking_status(Room.objects.all())[:3])
    return render(request, 'home.html', {'featured_rooms': featured_rooms})

# Room listing view
def room_list(request):
    _mark_completed_bookings()
    if not _booking_tables_ready():
        messages.error(request, "Database is initializing. Please try again shortly.")
        return render(request, 'room.html', {'rooms': [], 'check_in': None, 'check_out': None})
    rooms = _with_booking_status(Room.objects.filter(available=True))
    date_in = request.GET.get('check_in')
    date_out = request.GET.get('check_out')
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

    return render(
        request,
        'room.html',
        {'rooms': rooms, 'check_in': check_in, 'check_out': check_out},
    )

# Room detail view
def room_detail(request, room_id):
    _mark_completed_bookings()
    if not _booking_tables_ready():
        messages.error(request, "Database is initializing. Please try again shortly.")
        return redirect('room_list')
    room = get_object_or_404(_with_booking_status(Room.objects.all()), id=room_id)
    return render(request, 'room_detail.html', {'room': room})

#Index view (alternative to room_list)
def index(request):
    _mark_completed_bookings()
    if not _booking_tables_ready():
        messages.error(request, "Database is initializing. Please try again shortly.")
        return render(request, 'room.html', {'rooms': []})
    rooms = _with_booking_status(Room.objects.all())
    return render(request, 'room.html', {'rooms': rooms})

# Static pages
def about(request):
    return render(request, 'about.html')

def amenities(request):
    return render(request, 'amenities.html')

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
    if booking.room:
        nights = (booking.check_out - booking.check_in).days
        return booking.room.price * nights
    return Decimal('0.00')

def _send_receipt_email(request, booking):
    if not booking.email:
        return
    amount = _get_booking_amount(booking)
    invoice_url = request.build_absolute_uri(reverse('invoice_pdf', args=[booking.id]))
    room_title = booking.room.title if booking.room else "N/A"
    try:
        send_mail(
            subject=f"Royal Hotel Receipt #{booking.id}",
            message=(
                f"Hello {booking.first_name},\n\n"
                f"Payment received for Booking #{booking.id}.\n"
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
            fail_silently=True,
        )
    except Exception:
        pass

def booking_view(request):
    _mark_completed_bookings()
    if not _booking_tables_ready():
        messages.error(request, "Database is initializing. Please try again shortly.")
        if request.method == "POST":
            return redirect('booking')
        return render(request, 'booking.html', {'rooms': [], 'selected_room_id': ''})
    if request.method == "POST":
        # Get form data
        fname = request.POST.get('fname')
        lname = request.POST.get('lname')
        mobile = request.POST.get('mobile')
        email = request.POST.get('email')
        guests = request.POST.get('guests', 1)
        room_id = request.POST.get('room_id')
        date_in = request.POST.get('date-1')
        date_out = request.POST.get('date-2')
        request_text = request.POST.get('request', '')

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

            room = get_object_or_404(Room, id=room_id)

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

            # Calculate total price
            nights = (check_out - check_in).days
            new_booking.total_price = room.price * nights

            new_booking.save()

            if new_booking.email:
                try:
                    send_mail(
                        subject=f"Royal Hotel Booking Confirmation #{new_booking.id}",
                        message=(
                            f"Hello {new_booking.first_name},\n\n"
                            f"Your booking is received.\n"
                            f"Room: {new_booking.room.title if new_booking.room else 'N/A'}\n"
                            f"Check-in: {new_booking.check_in}\n"
                            f"Check-out: {new_booking.check_out}\n"
                            f"Guests: {new_booking.guests}\n"
                            f"Total: ${new_booking.total_price}\n\n"
                            "Thank you for choosing Royal Hotel."
                        ),
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                        recipient_list=[new_booking.email],
                        fail_silently=True,
                    )
                except Exception:
                    pass

            messages.success(request, "Your reservation has been submitted successfully!")
            return redirect('booking_confirmation', booking_id=new_booking.id)
            
        except ValueError as e:
            messages.error(request, "Invalid date format. Please use MM/DD/YYYY.")
            return redirect('booking')
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            return redirect('booking')

    # GET request - show booking form
    rooms = Room.objects.filter(available=True)
    selected_room_id = request.GET.get('room', '')
    return render(
        request,
        'booking.html',
        {
            'rooms': rooms,
            'selected_room_id': str(selected_room_id) if selected_room_id else '',
        },
    )

# Booking confirmation
def booking_confirmation(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
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
    reason = request.GET.get('reason')
    if reason:
        messages.error(request, f"Payment was not successful: {reason}")
    else:
        messages.error(request, "Payment was not successful. Please try again.")
    return redirect('payment_page', booking_id=booking.id)

# Payment page
def payment_page(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    amount = _get_booking_amount(booking)
    return render(
        request,
        'payment_page.html',
        {
            'booking': booking,
            'amount': amount,
            'currency': getattr(settings, 'DEFAULT_CURRENCY', 'KES'),
            'stripe_publishable_key': getattr(settings, 'STRIPE_PUBLISHABLE_KEY', ''),
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
    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({'error': 'Stripe not configured'}, status=400)
    if requests is None:
        return JsonResponse({'error': 'Payment dependency not installed'}, status=500)

    amount = _get_booking_amount(booking)
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
    if not settings.STRIPE_SECRET_KEY:
        return JsonResponse({'error': 'Stripe not configured'}, status=400)
    if requests is None:
        return JsonResponse({'error': 'Payment dependency not installed'}, status=500)

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
    try:
        event = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid payload")

    event_type = event.get('type')
    data = event.get('data', {}).get('object', {})
    if event_type == 'payment_intent.succeeded':
        intent_id = data.get('id')
        payment = Payment.objects.filter(reference=intent_id, provider='STRIPE').first()
        if payment:
            payment.status = 'SUCCEEDED'
            payment.raw_response = data
            payment.booking.status = 'CONFIRMED'
            payment.booking.save()
            payment.save()
            try:
                _send_receipt_email(request, payment.booking)
            except Exception:
                pass

    return JsonResponse({'received': True})

# PayPal helpers
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

def paypal_create_order(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid method")

    booking_id = request.POST.get('booking_id')
    if not booking_id:
        return HttpResponseBadRequest("Missing booking_id")

    booking = get_object_or_404(Booking, id=booking_id)
    if requests is None:
        messages.error(request, "Payment dependency is not installed.")
        return redirect('payment_page', booking_id=booking.id)
    access_token = _paypal_get_access_token()
    if not access_token:
        messages.error(request, "PayPal is not configured.")
        return redirect('payment_page', booking_id=booking.id)

    amount = _get_booking_amount(booking)
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

    approve_url = None
    for link in order.get('links', []):
        if link.get('rel') == 'approve':
            approve_url = link.get('href')
            break

    if not approve_url:
        messages.error(request, "PayPal approval link not found.")
        return redirect('payment_page', booking_id=booking.id)

    return redirect(approve_url)

def paypal_return(request):
    order_id = request.GET.get('token')
    booking_id = request.GET.get('booking_id')
    if not order_id:
        messages.error(request, "Missing PayPal token.")
        if booking_id:
            return redirect(f"{reverse('payment_failed', args=[booking_id])}?reason=missing_paypal_token")
        return redirect('index')

    access_token = _paypal_get_access_token()
    if requests is None:
        messages.error(request, "Payment dependency is not installed.")
        if booking_id:
            return redirect(f"{reverse('payment_failed', args=[booking_id])}?reason=payment_dependency_missing")
        return redirect('index')
    if not access_token:
        messages.error(request, "PayPal is not configured.")
        if booking_id:
            return redirect(f"{reverse('payment_failed', args=[booking_id])}?reason=paypal_not_configured")
        return redirect('index')

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
        return redirect('index')

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

    capture = response.json()
    if payment:
        payment.raw_response = capture
        payment.status = 'SUCCEEDED'
        payment.booking.status = 'CONFIRMED'
        payment.booking.save()
        payment.save()
        _send_receipt_email(request, payment.booking)

    if payment:
        return redirect('payment_success', booking_id=payment.booking.id)
    return redirect('index')

def paypal_cancel(request):
    messages.info(request, "PayPal payment cancelled.")
    booking_id = request.GET.get('booking_id')
    if booking_id:
        return redirect(f"{reverse('payment_failed', args=[booking_id])}?reason=paypal_payment_cancelled")
    return redirect('index')

def invoice_pdf(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    amount = _get_booking_amount(booking)

    try:
        from reportlab.pdfgen import canvas
    except Exception:
        return HttpResponse("ReportLab not installed.", status=501)

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

# M-Pesa STK Push (stub until Daraja credentials are provided)
def _normalize_mpesa_phone(phone):
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        return "254" + digits[1:]
    if digits.startswith("254") and len(digits) == 12:
        return digits
    if digits.startswith("7") and len(digits) == 9:
        return "254" + digits
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
    if any(not value for value in required_values):
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
    if any(not value for value in required_values):
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
    amount = _get_booking_amount(booking)
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
            amount=_get_booking_amount(booking),
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
        amount=_get_booking_amount(booking),
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

    if result_code_str == "0":
        payment.status = 'SUCCEEDED'
        payment.booking.status = 'CONFIRMED'
        payment.booking.save(update_fields=['status', 'updated_at'])
    elif result_code_str == "1032":
        payment.status = 'CANCELLED'
    else:
        payment.status = 'FAILED'
    payment.save(update_fields=['status', 'raw_response', 'updated_at'])

    return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

# Login view
def login_view(request):
    if request.method == "POST":
        email = request.POST.get('login_email')
        password = request.POST.get('login_password')
        
        # Django uses username, not email, for authentication
        # We're using email as username in this case
        user = authenticate(request, username=email, password=password)

        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            
            # Redirect to next page if exists
            next_page = request.GET.get('next', 'index')
            return redirect(next_page)
        else:
            messages.error(request, "Invalid email or password.")
    
    return render(request, 'login.html')

# Register view
def register_view(request):
    if request.method == "POST":
        name = request.POST.get('name')
        email = request.POST.get('email')
        password = request.POST.get('password')
        repeat_password = request.POST.get('repeat_password')

        # Validation
        if not all([name, email, password, repeat_password]):
            messages.error(request, "All fields are required.")
            return redirect('register')

        if password != repeat_password:
            messages.error(request, "Passwords do not match!")
            return redirect('register')

        if User.objects.filter(username=email).exists():
            messages.error(request, "A user with this email already exists.")
            return redirect('register')
        
        if len(password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return redirect('register')

        # Create user
        try:
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=name
            )
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
    return render(request, 'profile.html')


@login_required(login_url='login')
def my_bookings_view(request):
    _mark_completed_bookings()
    bookings = Booking.objects.filter(user=request.user).select_related('room').order_by('-created_at')
    return render(request, 'my_bookings.html', {'bookings': bookings})


@login_required(login_url='login')
def admin_users_view(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You do not have permission to view this page.")
        return redirect('index')

    users = User.objects.all().annotate(
        total_bookings=Count('booking', distinct=True),
        confirmed_bookings=Count('booking', filter=Q(booking__status='CONFIRMED'), distinct=True),
    ).order_by('-date_joined')
    return render(request, 'admin_users.html', {'users': users})


@login_required(login_url='login')
def admin_payments_view(request):
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
            elif result_code_str in ['1', '1037', '2001']:
                payment.status = 'FAILED'

            payment.raw_response = updated_raw
            payment.save(update_fields=['status', 'raw_response', 'updated_at'])
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
    today = datetime.today().date()
    bookings = Booking.objects.filter(
        status='CONFIRMED',
        check_out__gt=today,
    ).select_related('room', 'user').order_by('check_in', 'room__title')

    return render(request, 'admin_booked_rooms.html', {'bookings': bookings})

# Room view (legacy, redirect to room_list)
def room(request):
    return redirect('room_list')


def subscribe(request):
    if request.method != "POST":
        return redirect('index')
    email = request.POST.get('email')
    if email:
        messages.success(request, "Thanks for subscribing to our offers.")
        return redirect('index')
    messages.error(request, "Please enter a valid email address.")
    return redirect('index')
