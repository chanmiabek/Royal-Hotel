from django.contrib import admin
from django.db.models import Exists, OuterRef
from django.utils import timezone
from .models import Room, Booking, ContactMessage, Payment


class RoomOccupancyFilter(admin.SimpleListFilter):
    title = "room status"
    parameter_name = "room_status"

    def lookups(self, request, model_admin):
        return (
            ("booked", "Booked"),
            ("available", "Available"),
        )

    def queryset(self, request, queryset):
        today = timezone.localdate()
        booked_room_ids = Booking.objects.filter(
            status="CONFIRMED",
            check_out__gt=today,
            room__isnull=False,
        ).values_list("room_id", flat=True)

        if self.value() == "booked":
            return queryset.filter(id__in=booked_room_ids)
        if self.value() == "available":
            return queryset.exclude(id__in=booked_room_ids)
        return queryset


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'price', 'size', 'beds', 'booking_status', 'available']
    list_filter = ['category', RoomOccupancyFilter, 'available']
    search_fields = ['title', 'description']

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        today = timezone.localdate()
        active_confirmed = Booking.objects.filter(
            room=OuterRef("pk"),
            status="CONFIRMED",
            check_out__gt=today,
        )
        return qs.annotate(is_booked=Exists(active_confirmed))

    @admin.display(description="Status", ordering="is_booked")
    def booking_status(self, obj):
        if getattr(obj, "is_booked", False):
            return "Booked"
        return "Available"

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
