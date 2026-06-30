from django.conf import settings


def google_maps_api_key(request):
    return {
        "GOOGLE_MAPS_API_KEY": getattr(settings, "GOOGLE_MAPS_API_KEY", ""),
        "CLERK_PUBLISHABLE_KEY": getattr(settings, "CLERK_PUBLISHABLE_KEY", ""),
        "CLERK_AUTH_ENABLED": bool(
            (getattr(settings, "CLERK_PUBLISHABLE_KEY", "") or "").strip()
            and (getattr(settings, "CLERK_SECRET_KEY", "") or "").strip()
            and (getattr(settings, "CLERK_JWKS_URL", "") or "").strip()
        ),
    }
