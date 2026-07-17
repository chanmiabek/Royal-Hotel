from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.http import JsonResponse
from django.core.exceptions import ValidationError
from django.urls import resolve, Resolver404, reverse


class ProductionSecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault('Content-Security-Policy', settings.CONTENT_SECURITY_POLICY)
        response.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=(self), payment=(self)')
        response.setdefault('Cross-Origin-Opener-Policy', 'same-origin-allow-popups')
        return response


class UploadSafetyMiddleware:
    """Apply a single upload policy even to views that do not use Django forms."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in {'POST', 'PUT', 'PATCH'} and request.FILES:
            from booking.models import validate_private_document
            uploads = [item for _, values in request.FILES.lists() for item in values]
            if len(uploads) > 12:
                return JsonResponse({'detail': 'Upload no more than 12 files at once.'}, status=400)
            try:
                for upload in uploads:
                    validate_private_document(upload)
            except ValidationError as exc:
                return JsonResponse({'detail': ' '.join(exc.messages)}, status=400)
        return self.get_response(request)


class PlatformAdminPermissionMiddleware:
    """Require a dedicated permission for every custom platform-admin route."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            match = resolve(request.path_info)
        except Resolver404:
            match = None

        url_name = match.url_name if match else ""
        if url_name in getattr(settings, "PLATFORM_ADMIN_URL_NAMES", set()):
            user = request.user
            if not user.is_authenticated:
                return redirect(f"{reverse('login')}?next={request.get_full_path()}")
            if not (user.is_superuser or user.has_perm("booking.access_platform_admin")):
                messages.error(request, "You do not have permission to access platform administration.")
                return redirect("index")

        return self.get_response(request)
