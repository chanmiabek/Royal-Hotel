from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

from .models import BusinessPartner, Hotel


def google_maps_api_key(request):
    try:
        footer_business_partners = list(BusinessPartner.objects.filter(is_active=True)[:8])
    except (OperationalError, ProgrammingError):
        footer_business_partners = []

    try:
        footer_approved_hotels = list(
            Hotel.objects.filter(is_approved=True, is_active=True).order_by('-created_at', 'name')[:20]
        )
    except (OperationalError, ProgrammingError):
        footer_approved_hotels = []

    return {
        "GOOGLE_MAPS_API_KEY": getattr(settings, "GOOGLE_MAPS_API_KEY", ""),
        "footer_business_partners": footer_business_partners,
        "footer_approved_hotels": footer_approved_hotels,
    }
