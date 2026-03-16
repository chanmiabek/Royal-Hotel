from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from decimal import Decimal


class UserProfile(models.Model):
    USER_TYPES = (
        ('GUEST', 'Guest'),
        ('OWNER', 'Owner'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    user_type = models.CharField(max_length=10, choices=USER_TYPES, default='GUEST')
    mobile = models.CharField(max_length=30, blank=True)

    @property
    def is_owner(self):
        return self.user_type == 'OWNER'

    def __str__(self):
        return f"{self.user.username} ({self.user_type})"


class PasswordResetCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_codes")
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    @property
    def is_used(self):
        return self.used_at is not None

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    def __str__(self):
        return f"Password reset code for {self.user.username}"

class Hotel(models.Model):
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='hotels')
    name = models.CharField(max_length=150)
    star_rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    description = models.TextField(blank=True)
    address = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    image = models.ImageField(upload_to='hotel/', blank=True, null=True)
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.1500'),
        validators=[MinValueValidator(Decimal('0.05')), MaxValueValidator(Decimal('0.30'))],
        help_text="Commission rate as a decimal (e.g. 0.15 = 15%).",
    )
    payout_method = models.CharField(
        max_length=20,
        blank=True,
        default='BANK',
        choices=(
            ('BANK', 'Bank Transfer'),
            ('MOBILE_MONEY', 'Mobile Money'),
            ('PAYPAL', 'PayPal'),
            ('STRIPE', 'Stripe Connect'),
            ('PAYSTACK', 'Paystack'),
            
        ),
    )
    payout_schedule = models.CharField(
        max_length=20,
        blank=True,
        default='WEEKLY',
        choices=(
            ('WEEKLY', 'Weekly'),
            ('MONTHLY', 'Monthly'),
        ),
    )
    payout_hold_days = models.PositiveSmallIntegerField(
        default=2,
        help_text="Hold period (days) after check-in before payout is released.",
    )
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_name = models.CharField(max_length=120, blank=True)
    bank_account_number = models.CharField(max_length=60, blank=True)
    bank_branch = models.CharField(max_length=120, blank=True)
    bank_swift = models.CharField(max_length=60, blank=True)
    mobile_money_provider = models.CharField(max_length=40, blank=True)
    mobile_money_number = models.CharField(max_length=30, blank=True)
    paypal_email = models.EmailField(blank=True)
    payout_account_reference = models.CharField(
        max_length=120,
        blank=True,
        help_text="Connected account or wallet reference for payouts.",
    )
    is_approved = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Room(models.Model):
    ROOM_CATEGORIES = (
        ('STD', 'Standard'),
        ('PRE', 'Premium'),
        ('SLV', 'Silver'),
        ('DLX', 'Deluxe'),
        ('EXE', 'Executive'),
        ('APT', 'Apartment'),
    )
    
    title = models.CharField(max_length=100)
    category = models.CharField(max_length=3, choices=ROOM_CATEGORIES)
    description = models.TextField()
    amenities = models.TextField(blank=True, help_text="Comma-separated amenities")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    size = models.IntegerField(help_text="Size in sq ft")
    beds = models.CharField(max_length=50, help_text="e.g. 2 Single(s)")
    image = models.ImageField(upload_to='room/', blank=True, null=True)
    available = models.BooleanField(default=True)
    capacity = models.IntegerField(default=2, help_text="Max guests")
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='rooms')
    is_approved = models.BooleanField(default=True)
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='rooms')
    
    @property
    def amenities_list(self):
        if not self.amenities:
            return []
        return [item.strip() for item in self.amenities.split(',') if item.strip()]

    def __str__(self):
        return f"{self.title} - KES {self.price}/night"

class Booking(models.Model):
    BOOKING_STATUS = (
        ('PENDING', 'Pending'),
        ('CONFIRMED', 'Confirmed'),
        ('CANCELLED', 'Cancelled'),
        ('COMPLETED', 'Completed'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, null=True, blank=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    mobile = models.CharField(max_length=15)
    email = models.EmailField()
    check_in = models.DateField()
    check_out = models.DateField()
    guests = models.IntegerField(default=1)
    special_request = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=BOOKING_STATUS, default='PENDING')
    total_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Booking #{self.id} - {self.first_name} {self.last_name}"


class Review(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='review')
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=200)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review #{self.id} - {self.room.title if self.room else 'Room'}"

class ContactMessage(models.Model):
    full_name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Message from {self.full_name} - {self.subject}"

class Payment(models.Model):
    PROVIDERS = (
        ('STRIPE', 'Stripe'),
        ('PAYPAL', 'PayPal'),
        ('MPESA', 'M-Pesa'),
    )
    STATUSES = (
        ('PENDING', 'Pending'),
        ('SUCCEEDED', 'Succeeded'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
        ('REFUNDED', 'Refunded'),
    )

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='payments')
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    status = models.CharField(max_length=20, choices=STATUSES, default='PENDING')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='KES')
    reference = models.CharField(max_length=100, blank=True, null=True)
    raw_response = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider} {self.amount} {self.currency} - {self.status}"


class HotelApplication(models.Model):
    STATUS = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )
    PAYOUT_METHODS = (
        ('BANK', 'Bank Transfer'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('PAYPAL', 'PayPal'),
        ('STRIPE', 'Stripe Connect'),
        ('PAYSTACK', 'Paystack'),
        ('RAZORPAY', 'Razorpay'),
    )
    PAYOUT_SCHEDULES = (
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
    )

    hotel_name = models.CharField(max_length=150)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='hotel_applications')
    star_rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    description = models.TextField(blank=True)
    address = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, blank=True)
    contact_name = models.CharField(max_length=120)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=30)
    room_types = models.TextField(blank=True)
    room_pricing = models.TextField(blank=True)
    availability_details = models.TextField(blank=True)
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.1500'),
        validators=[MinValueValidator(Decimal('0.05')), MaxValueValidator(Decimal('0.30'))],
        help_text="Requested commission rate as a decimal (e.g. 0.15 = 15%).",
    )
    payout_method = models.CharField(max_length=20, choices=PAYOUT_METHODS, default='BANK')
    payout_schedule = models.CharField(max_length=20, choices=PAYOUT_SCHEDULES, default='WEEKLY')
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_name = models.CharField(max_length=120, blank=True)
    bank_account_number = models.CharField(max_length=60, blank=True)
    bank_branch = models.CharField(max_length=120, blank=True)
    bank_swift = models.CharField(max_length=60, blank=True)
    mobile_money_provider = models.CharField(max_length=40, blank=True)
    mobile_money_number = models.CharField(max_length=30, blank=True)
    paypal_email = models.EmailField(blank=True)
    agreed_to_terms = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS, default='PENDING')
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.hotel_name} - {self.contact_email}"


class HotelDocument(models.Model):
    DOC_TYPES = (
        ('LICENSE', 'Business License'),
        ('PHOTOS', 'Property Photos'),
        ('AMENITIES', 'Amenities Proof'),
        ('AGREEMENT', 'Signed Agreement'),
        ('OTHER', 'Other'),
    )
    application = models.ForeignKey(
        HotelApplication,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    document_type = models.CharField(max_length=20, choices=DOC_TYPES)
    file = models.FileField(upload_to='hotel_docs/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.application.hotel_name} - {self.document_type}"


class HotelAgreement(models.Model):
    STATUS = (
        ('DRAFT', 'Draft'),
        ('SIGNED', 'Signed'),
    )
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='agreements')
    commission_rate = models.DecimalField(max_digits=5, decimal_places=4)
    payout_schedule = models.CharField(max_length=20)
    cancellation_policy = models.TextField()
    refund_policy = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS, default='DRAFT')
    signed_by_hotel = models.BooleanField(default=False)
    signed_at = models.DateTimeField(null=True, blank=True)
    document = models.FileField(upload_to='hotel_agreements/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Agreement - {self.hotel.name}"


class BookingCommission(models.Model):
    STATUS = (
        ('PENDING', 'Pending'),
        ('RELEASED', 'Released'),
        ('REFUNDED', 'Refunded'),
        ('CANCELLED', 'Cancelled'),
    )
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='commission')
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='commissions')
    gross_amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=4)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2)
    hotel_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Commission for Booking #{self.booking_id}"


class HotelPayout(models.Model):
    STATUS = (
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    )
    METHODS = (
        ('BANK', 'Bank Transfer'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('PAYPAL', 'PayPal'),
        ('STRIPE', 'Stripe Connect'),
        ('PAYSTACK', 'Paystack'),
        ('RAZORPAY', 'Razorpay'),
    )
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='payouts')
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name='payouts')
    method = models.CharField(max_length=20, choices=METHODS, default='BANK')
    account_reference = models.CharField(max_length=120, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='KES')
    scheduled_for = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='PENDING')
    paid_at = models.DateTimeField(null=True, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payout #{self.id} - {self.hotel.name}"
