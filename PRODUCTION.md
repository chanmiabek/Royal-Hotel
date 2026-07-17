# Royal Hotel production runbook

## Required services

- PostgreSQL with automated daily backups and point-in-time recovery.
- Redis for shared throttling/cache (`CACHE_URL`).
- Cloudinary for public images. Keep contracts, licenses, banking documents, and agreements in a private authenticated object store before accepting real partner documents.
- SMTP provider credentials.
- A web process plus two scheduled jobs.

## Release and runtime

The release command is `python manage.py migrate --noinput`. The web command is defined in `Procfile` and the container exposes `/health/live/` for liveness and `/health/` for database readiness.

Run these jobs every minute (or continuously from a worker supervisor):

```bash
python manage.py send_queued_email --limit 50
python manage.py maintain_bookings
```

`maintain_bookings` expires unpaid reservations, completes checked-out stays, and reconciles pending PayPal, Paystack, and M-Pesa attempts. M-Pesa success remains callback-driven because the STK query response does not provide enough receipt evidence to safely settle a payment.

## Secrets and HTTPS

Copy variable names from `.env.example`; never copy local values. Production requires `DEBUG=False`, a unique `SECRET_KEY`, PostgreSQL `DATABASE_URL`, HTTPS-only trusted origins, and a durable media configuration. Enable HSTS only after the domain and all subdomains are permanently HTTPS.

Configure provider webhooks:

- PayPal: `/payments/paypal/webhook/`, events `PAYMENT.CAPTURE.COMPLETED`; save the webhook ID as `PAYPAL_WEBHOOK_ID`.
- Paystack: `/payments/paystack/webhook/`; `PAYSTACK_WEBHOOK_SECRET` normally equals the Paystack secret key.
- M-Pesa: `/payments/mpesa/callback/` through `MPESA_CALLBACK_URL`.

## Access control

Custom platform administration requires either superuser status or the `booking.access_platform_admin` permission. Do not grant this permission to ordinary hotel staff. Django's built-in `/admin/` continues to use Django staff/model permissions.

## Backups and recovery

Enable provider-managed encrypted PostgreSQL backups with at least 30-day retention and point-in-time recovery. Perform and document a restore test at least quarterly. Cloud media/object storage needs versioning or an equivalent recovery policy. Database backups do not contain uploaded files.

## Monitoring

Set `SENTRY_DSN` for exception monitoring. JSON logs go to stdout. Alert on 5xx rate, readiness failures, failed queued email, pending payments older than one hour, failed maintenance jobs, disk/storage failures, and database saturation.

## Release checklist

```bash
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py test
python manage.py collectstatic --noinput
```

Rotate payment and SMTP credentials after staff departures or suspected exposure. Test payment webhooks in provider sandboxes before switching provider base URLs and credentials to live mode.
