release: python manage.py migrate --noinput
web: gunicorn room_booking.wsgi:application --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-4} --access-logfile - --error-logfile -
