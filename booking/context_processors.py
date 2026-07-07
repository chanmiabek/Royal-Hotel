from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

from .models import BusinessPartner, Hotel


def google_maps_api_key(request):
    try:
        footer_business_partners = BusinessPartner.objects.filter(is_active=True)[:8]
    except (OperationalError, ProgrammingError):
        footer_business_partners = []

    try:
        footer_approved_hotels = Hotel.objects.filter(is_approved=True, is_active=True).order_by('-created_at', 'name')[:20]
    except (OperationalError, ProgrammingError):
        footer_approved_hotels = []

    return {
        "GOOGLE_MAPS_API_KEY": getattr(settings, "GOOGLE_MAPS_API_KEY", ""),
        "GOOGLE_OAUTH_ENABLED": bool(
            (getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
            and (getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip()
        ),
        "footer_business_partners": footer_business_partners,
        "footer_approved_hotels": footer_approved_hotels,
    }
