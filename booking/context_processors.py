from django.conf import settings


def google_maps_api_key(request):
    return {
        "GOOGLE_MAPS_API_KEY": getattr(settings, "GOOGLE_MAPS_API_KEY", ""),
        "GOOGLE_OAUTH_ENABLED": bool(
            (getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
            and (getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip()
        ),
    }
