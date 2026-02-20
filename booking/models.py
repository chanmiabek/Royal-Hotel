from django.db import models
from django.contrib.auth.models import User

class Room(models.Model):
    ROOM_CATEGORIES = (
        ('STD', 'Standard'),
        ('PRE', 'Premium'),
        ('SLV', 'Silver'),
        ('DLX', 'Deluxe'),
        ('EXE', 'Executive'),
    )
    
    title = models.CharField(max_length=100)
    category = models.CharField(max_length=3, choices=ROOM_CATEGORIES)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    size = models.IntegerField(help_text="Size in sq ft")
    beds = models.CharField(max_length=50, help_text="e.g. 2 Single(s)")
    image = models.ImageField(upload_to='room/', blank=True, null=True)
    available = models.BooleanField(default=True)
    capacity = models.IntegerField(default=2, help_text="Max guests")
    
    def __str__(self):
        return f"{self.title} - ${self.price}/night"

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
