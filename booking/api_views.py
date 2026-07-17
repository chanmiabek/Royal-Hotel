from django.http import JsonResponse
from django.db import connection
from django.db.utils import OperationalError, ProgrammingError
from django.views.decorators.http import require_GET
from django.core.cache import cache

from .jwt_auth import jwt_required


@require_GET
def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except (OperationalError, ProgrammingError):
        return JsonResponse({"status": "error", "database": "unavailable"}, status=503)

    try:
        cache.set('health-check', 'ok', timeout=10)
        if cache.get('health-check') != 'ok':
            raise RuntimeError('Cache read failed')
    except Exception:
        return JsonResponse(
            {"status": "error", "database": "ok", "cache": "unavailable"}, status=503,
        )

    return JsonResponse({"status": "ok", "database": "ok", "cache": "ok"})


@require_GET
def liveness_check(request):
    return JsonResponse({"status": "ok"})


@jwt_required
def jwt_me(request):
    return JsonResponse({"claims": getattr(request, "jwt_claims", {})})
