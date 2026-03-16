from __future__ import annotations

from functools import lru_cache, wraps

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse


def _get_jwt_config():
    issuer = (getattr(settings, "JWT_ISSUER", "") or "").strip()
    jwks_url = (getattr(settings, "JWT_JWKS_URL", "") or "").strip()
    audience = (getattr(settings, "JWT_AUDIENCE", "") or "").strip()
    algorithms = getattr(settings, "JWT_ALGORITHMS", None) or ["RS256"]
    leeway_seconds = int(getattr(settings, "JWT_LEEWAY_SECONDS", 60) or 60)

    if not issuer or not jwks_url:
        raise ImproperlyConfigured("Set JWT_ISSUER and JWT_JWKS_URL in .env to enable JWT auth.")

    return issuer, jwks_url, audience, list(algorithms), leeway_seconds


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str):
    try:
        from jwt import PyJWKClient  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ImproperlyConfigured(
            "PyJWT is required for JWT verification. Install with: pip install PyJWT[crypto]"
        ) from exc
    return PyJWKClient(jwks_url)


def verify_bearer_token(token: str) -> dict:
    try:
        import jwt  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ImproperlyConfigured(
            "PyJWT is required for JWT verification. Install with: pip install PyJWT[crypto]"
        ) from exc

    issuer, jwks_url, audience, algorithms, leeway_seconds = _get_jwt_config()
    signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token).key

    options = {"verify_aud": bool(audience)}
    return jwt.decode(
        token,
        signing_key,
        algorithms=algorithms,
        audience=audience or None,
        issuer=issuer,
        leeway=leeway_seconds,
        options=options,
    )


def _extract_bearer_token(request) -> str | None:
    auth_header = (request.META.get("HTTP_AUTHORIZATION") or "").strip()
    if not auth_header:
        return None
    parts = auth_header.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts[0], parts[1].strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def jwt_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        token = _extract_bearer_token(request)
        if not token:
            return JsonResponse({"detail": "Missing Bearer token."}, status=401)

        try:
            request.jwt_claims = verify_bearer_token(token)
        except ImproperlyConfigured as exc:
            return JsonResponse({"detail": str(exc)}, status=503)
        except Exception:
            return JsonResponse({"detail": "Invalid token."}, status=401)

        return view_func(request, *args, **kwargs)

    return _wrapped

