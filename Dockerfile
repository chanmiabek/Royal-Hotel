FROM python:3.12.8-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7-dev \
    libtiff-dev \
    libwebp-dev \
    tcl-dev \
    tk-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip setuptools && \
    pip install -r requirements.txt

COPY . .

RUN DEBUG=true \
    SECRET_KEY=build-time-only-secret-key-not-used-at-runtime \
    USE_CLOUDINARY=false \
    python manage.py collectstatic --noinput

RUN chmod +x /app/entrypoint.sh && \
    groupadd -r app && useradd -r -g app app && \
    chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live/', timeout=5).read()" || exit 1

CMD ["/app/entrypoint.sh"]
