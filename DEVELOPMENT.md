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

## 6) Run tests
```powershell
python manage.py test
```

## Production baseline
- Set `DEBUG=False`
- Set strong `SECRET_KEY`
- Set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
- Set PostgreSQL `DATABASE_URL`
- Run `python manage.py collectstatic --noinput`
- Start app with `gunicorn room_booking.wsgi --log-file -`
