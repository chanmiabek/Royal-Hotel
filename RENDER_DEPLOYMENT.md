# Render Deployment Guide

This project is now wired for a safer Render deployment:

- `build.sh` installs dependencies, runs `check --deploy`, and collects static files.
- `Procfile` no longer runs migrations at app startup.
- `/health/` checks database connectivity and can be used as Render's health check path.
- Production startup now fails fast if `SECRET_KEY` or `DATABASE_URL` are missing or unsafe.
- Environment variables from Render or CI now override `.env`, instead of being overwritten by it.

## Before you deploy

- Rotate any secret that may already have been committed to Git history before going live.
- Make sure you are using PostgreSQL in production. SQLite is intentionally blocked when `DEBUG=False`.
- Decide how uploaded media will persist. Render's default filesystem is ephemeral, so use `Cloudinary` or attach a persistent disk.
- If you use a custom domain, add that domain to both `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
- If you use Google OAuth, add the live callback URL in Google Cloud:
  `https://your-service.onrender.com/auth/google/callback/`
- If you use Stripe, point the live webhook endpoint to:
  `https://your-service.onrender.com/payments/stripe/webhook/`
- If you use M-Pesa, set `MPESA_CALLBACK_URL` to your live HTTPS callback URL.

## Manual Render setup

1. Push the repository to GitHub, GitLab, or Bitbucket.
2. In Render, create a new `Web Service` from the repo.
3. Select `Python 3` as the runtime.
4. Set the build command to `bash build.sh`.
5. Set the pre-deploy command to `python manage.py migrate --noinput`.
6. Set the start command to `gunicorn room_booking.wsgi:application --bind 0.0.0.0:$PORT --log-file -`.
7. Set the health check path to `/health/`.
8. Choose an instance plan that matches your budget and uptime needs.
9. Add the environment variables listed below.
10. Deploy the service.

## Required environment variables

- `DEBUG=False`
- `SECRET_KEY=<generate a new secret in Render>`
- `DATABASE_URL=<your production PostgreSQL URL>`
- `ALLOWED_HOSTS=your-service.onrender.com`
- `CSRF_TRUSTED_ORIGINS=https://your-service.onrender.com`

## Usually required in production

- `USE_CLOUDINARY=True`
- `CLOUDINARY_URL=<your cloudinary url>`
- `DEFAULT_FROM_EMAIL=<your sender address>`
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS=True`
- `SECURE_SSL_REDIRECT=True`
- `SECURE_HSTS_SECONDS=31536000`
- `CONN_MAX_AGE=60`

## Optional environment variables

- `PAYPAL_BASE_URL=https://api-m.paypal.com`
- `PAYPAL_CLIENT_ID`
- `PAYPAL_CLIENT_SECRET`
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `MPESA_CONSUMER_KEY`
- `MPESA_CONSUMER_SECRET`
- `MPESA_SHORTCODE`
- `MPESA_PASSKEY`
- `MPESA_CALLBACK_URL`
- `MPESA_AUTH_URL`
- `MPESA_STK_URL`
- `MPESA_STK_QUERY_URL`
- `GOOGLE_MAPS_API_KEY`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `JWT_ISSUER`
- `JWT_JWKS_URL`
- `JWT_AUDIENCE`

## Post-deploy validation

- Open `https://your-service.onrender.com/health/` and confirm it returns `{"status":"ok"}`.
- Open the home page and confirm CSS, images, and JavaScript load correctly.
- In the Render logs, confirm the pre-deploy migration step completed successfully.
- Create a Django admin user from the Render Shell:
  `python manage.py createsuperuser`
- Test login, registration, booking, contact form email, and any payment method you enabled.
- Test one image upload and confirm the file persists after a redeploy.
- If you add a custom domain, update `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, OAuth callback URLs, and webhook URLs.

## Zero-failure deployment routine

1. Push changes to a feature branch.
2. Let GitHub Actions run `python manage.py test` and `python manage.py check --deploy`.
3. Merge only after CI passes.
4. Deploy on Render and watch the build log, pre-deploy migration log, and health check.
5. Run the post-deploy validation checklist above before announcing the release live.
