from django.contrib import admin
from .models import Room, Booking, ContactMessage, Payment

@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'price', 'size', 'beds', 'available']
    list_filter = ['category', 'available']
    search_fields = ['title', 'description']

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'first_name', 'last_name', 'room', 'check_in', 'check_out', 'status', 'total_price']
    list_filter = ['status', 'check_in', 'check_out', 'room']
    search_fields = ['first_name', 'last_name', 'email']
    date_hierarchy = 'check_in'
    list_editable = ['status']
    readonly_fields = ['created_at', 'updated_at', 'total_price']

@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'subject', 'created_at', 'is_resolved']
    list_filter = ['is_resolved', 'created_at']
    search_fields = ['full_name', 'email', 'subject']

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'provider', 'amount', 'currency', 'status', 'booking', 'created_at']
    list_filter = ['provider', 'status', 'currency', 'created_at']
    search_fields = ['reference', 'booking__email', 'booking__first_name', 'booking__last_name']
