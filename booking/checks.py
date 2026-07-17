from django.conf import settings
from django.core.checks import Warning, register


@register(deploy=True)
def production_service_checks(app_configs, **kwargs):
    issues = []
    if not getattr(settings, 'CACHE_URL', ''):
        issues.append(Warning(
            'No shared CACHE_URL is configured; rate limits are per worker.',
            hint='Configure a managed Redis URL in production.', id='booking.W001',
        ))
    if getattr(settings, 'EMAIL_BACKEND', '').endswith('console.EmailBackend'):
        issues.append(Warning(
            'Production email uses the console backend.',
            hint='Configure SMTP credentials and run send_queued_email.', id='booking.W002',
        ))
    if not getattr(settings, 'SENTRY_DSN', ''):
        issues.append(Warning(
            'Error monitoring is not configured.',
            hint='Set SENTRY_DSN or connect an equivalent monitoring service.', id='booking.W003',
        ))
    if not getattr(settings, 'USE_CLOUDINARY', False):
        issues.append(Warning(
            'Media uses ephemeral local storage.',
            hint='Configure durable production object/media storage.', id='booking.W004',
        ))
    return issues
