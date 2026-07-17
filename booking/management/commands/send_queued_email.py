import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from booking.models import EmailOutbox


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Deliver queued email with bounded retries. Run every minute.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50)

    def handle(self, *args, **options):
        sent = failed = 0
        for message_id in EmailOutbox.objects.filter(
            status='PENDING', available_at__lte=timezone.now(), attempts__lt=5,
        ).values_list('id', flat=True)[:max(1, options['limit'])]:
            with transaction.atomic():
                item = EmailOutbox.objects.select_for_update(skip_locked=True).filter(pk=message_id).first()
                if not item or item.status != 'PENDING':
                    continue
                item.attempts += 1
                try:
                    delivered = send_mail(
                        item.subject, item.body,
                        item.from_email or settings.DEFAULT_FROM_EMAIL,
                        item.recipients, fail_silently=False,
                    )
                    if delivered:
                        item.status = 'SENT'; item.sent_at = timezone.now(); item.last_error = ''
                        sent += 1
                    else:
                        raise RuntimeError('Email backend reported no delivery.')
                except Exception as exc:
                    logger.exception('Queued email %s failed', item.pk)
                    item.last_error = str(exc)[:2000]
                    item.available_at = timezone.now() + timedelta(minutes=min(60, 2 ** item.attempts))
                    if item.attempts >= 5:
                        item.status = 'FAILED'; failed += 1
                item.save(update_fields=['attempts', 'status', 'sent_at', 'last_error', 'available_at'])
        self.stdout.write(self.style.SUCCESS(f'Sent {sent}; permanently failed {failed}.'))
