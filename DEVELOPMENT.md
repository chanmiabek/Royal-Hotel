# Development Setup

## Prerequisites
- Python 3.11+
- pip

## 1) Create virtual environment (PowerShell)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

## 2) Install dependencies
```powershell
pip install -r requirements.txt
```

## 3) Configure environment
```powershell
Copy-Item .env.example .env
```

Edit `.env`:
- Keep `DATABASE_URL` empty for SQLite.
- Or set Neon/PostgreSQL URL in `DATABASE_URL`.
- If `DEBUG=True`, set `USE_DATABASE_URL_IN_DEBUG=True` to use Neon locally (set it to `False` to force SQLite).
- Optional (Neon Auth JWT): set `JWT_ISSUER` + `JWT_JWKS_URL`.

## 4) Prepare database
```powershell
python manage.py migrate
python manage.py createsuperuser
```

## 5) Run app
```powershell
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

If you see "You're accessing the development server over HTTPS", make sure you're using `http://` (not `https://`) and keep `DEBUG=True` in `.env`.

## 5b) Seed demo hotels/rooms (optional)
```powershell
python manage.py seed_demo_hotels
```

## 5c) Enable Google (Gmail) login (optional)
Add these to `.env`:
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`

## 6) Run tests
```powershell
python manage.py test
```

## Production baseline
- Set `DEBUG=False`
- Set strong `SECRET_KEY`
- Set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
- Set PostgreSQL `DATABASE_URL`
- If using JWT-protected endpoints, set `JWT_ISSUER` + `JWT_JWKS_URL`
- Set Cloudinary credentials (`CLOUDINARY_URL` or `CLOUDINARY_CLOUD_NAME`/`CLOUDINARY_API_KEY`/`CLOUDINARY_API_SECRET`) so uploaded images persist
- Run `python manage.py collectstatic --noinput`
- Start app with `gunicorn room_booking.wsgi --log-file -`
