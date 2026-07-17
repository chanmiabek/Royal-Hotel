

from pathlib import Path
import os
import sys
import importlib.util
import logging
from urllib.parse import urlparse, parse_qs, unquote
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

def _load_dotenv(dotenv_path, override=True):
    if not os.path.exists(dotenv_path):
        return
    with open(dotenv_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if override or key not in os.environ:
                os.environ[key] = value


RUNNING_TESTS = "test" in sys.argv
RUNNING_LOCAL_DEV_SERVER = (
    "runserver" in sys.argv
)
RUNNING_DEPLOYED_APP = bool(
    os.getenv("RENDER", "").strip()
    or os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    or os.getenv("RENDER_EXTERNAL_URL", "").strip()
)
if not RUNNING_TESTS:
    # In local development, the project .env should control the runserver
    # process. Deployed environments keep platform-provided variables.
    _load_dotenv(BASE_DIR / ".env", override=not RUNNING_DEPLOYED_APP)

def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_csv(name, default=""):
    raw = os.getenv(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _normalize_allowed_hosts(values):
    hosts = []
    for value in values:
        parsed = urlparse(value)
        host = parsed.netloc or parsed.path
        if host := host.split("/")[0].strip():
            hosts.append(host)
    if render_host := os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip():
        hosts.append(render_host)
    if not hosts:
        return ["royal-hotel-mwb5.onrender.com", "localhost", "127.0.0.1"]
    return list(dict.fromkeys(hosts))


def _default_csrf_trusted_origins():
    origins = ["https://royal-hotel-mwb5.onrender.com"]
    if render_external_url := os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/"):
        origins.append(render_external_url)
    if render_host := os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip():
        origins.append(f"https://{render_host}")
    if DEBUG:
        origins.extend([
            "http://localhost",
            "http://localhost:8000",
            "http://127.0.0.1",
            "http://127.0.0.1:8000",
        ])
    return ",".join(dict.fromkeys(origins))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
DEV_ONLY_SECRET_KEY = 'dev-only-change-this-to-a-long-random-secret-key-value-1234567890'
EXAMPLE_SECRET_KEY = 'changeme-in-render-use-a-generated-secret-key'
SECRET_KEY = os.getenv('SECRET_KEY', DEV_ONLY_SECRET_KEY).strip()

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = _env_bool("DEBUG", default=False)
if RUNNING_TESTS:
    DEBUG = False

if not DEBUG and not RUNNING_TESTS and SECRET_KEY in {DEV_ONLY_SECRET_KEY, EXAMPLE_SECRET_KEY}:
    raise ImproperlyConfigured("Set a unique SECRET_KEY for production.")

ALLOWED_HOSTS = _normalize_allowed_hosts(
    _env_csv("ALLOWED_HOSTS", default="royal-hotel-mwb5.onrender.com,localhost,127.0.0.1")
)
if DEBUG:
    ALLOWED_HOSTS.append("testserver")
CSRF_TRUSTED_ORIGINS = _env_csv(
    "CSRF_TRUSTED_ORIGINS",
    default=_default_csrf_trusted_origins(),
)


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'booking',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'booking.middleware.ProductionSecurityHeadersMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'booking.middleware.UploadSafetyMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'booking.middleware.PlatformAdminPermissionMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'room_booking.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'builtins': [
                'booking.templatetags.booking_extras',
            ],
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'booking.context_processors.google_maps_api_key',
            ],
        },
    },
]

WSGI_APPLICATION = 'room_booking.wsgi.application'


# Database
def _database_config_from_url(database_url):
    sqlite_fallback = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
        'CONN_MAX_AGE': 0,
    }
    if not database_url:
        return sqlite_fallback

    parsed = urlparse(database_url)
    if parsed.scheme not in ('postgres', 'postgresql'):
        return sqlite_fallback

    has_postgres_driver = (
        importlib.util.find_spec("psycopg") is not None
        or importlib.util.find_spec("psycopg2") is not None
    )
    if not has_postgres_driver:
        return sqlite_fallback

    query = parse_qs(parsed.query)
    options = {}
    if query.get('sslmode'):
        options['sslmode'] = query['sslmode'][0]
    if query.get('channel_binding'):
        options['channel_binding'] = query['channel_binding'][0]

    config = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': unquote(parsed.path.lstrip('/')),
        'USER': unquote(parsed.username or ''),
        'PASSWORD': unquote(parsed.password or ''),
        'HOST': parsed.hostname or '',
        'PORT': str(parsed.port or '5432'),
        'CONN_MAX_AGE': int(os.getenv("CONN_MAX_AGE", "60" if not DEBUG else "0")),
    }
    if options:
        config['OPTIONS'] = options
    return config


database_url = os.getenv('DATABASE_URL')
use_database_url_in_debug = _env_bool('USE_DATABASE_URL_IN_DEBUG', default=False)
if RUNNING_TESTS or (DEBUG and not use_database_url_in_debug):
    database_url = None

DATABASES = {
    'default': _database_config_from_url(database_url),
}

if not DEBUG and not RUNNING_TESTS and DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3':
    raise ImproperlyConfigured(
        "Set DATABASE_URL to a PostgreSQL database for production deployments."
    )


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en'

LANGUAGES = [
    ('en', _('English')),
    ('sw', _('Kiswahili')),
]

LOCALE_PATHS = [
    BASE_DIR / 'locale',
]

TIME_ZONE = os.getenv('TIME_ZONE', 'Africa/Nairobi')

USE_I18N = True

USE_TZ = True

PLATFORM_ADMIN_URL_NAMES = {
    'admin_dashboard', 'admin_users', 'admin_user_detail', 'admin_user_edit',
    'admin_user_toggle_active', 'admin_hotels', 'admin_hotel_detail',
    'admin_hotel_edit', 'admin_disable_hotel', 'admin_payments',
    'admin_booked_rooms', 'admin_team_members', 'admin_team_member_create',
    'admin_team_member_edit', 'admin_team_member_delete', 'admin_testimonials',
    'admin_testimonial_create', 'admin_testimonial_edit', 'admin_testimonial_delete',
    'admin_rooms', 'admin_room_detail', 'admin_room_edit', 'admin_disable_room',
    'admin_hotel_applications', 'admin_hotel_application_detail',
    'admin_approve_room', 'admin_reject_room',
}

CONTENT_SECURITY_POLICY = os.getenv('CONTENT_SECURITY_POLICY', '').strip() or (
    "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
    "form-action 'self' https://www.paypal.com https://*.paypal.com; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com https://www.paypal.com https://*.paypal.com https://js.paystack.co https://maps.googleapis.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data: blob: https:; connect-src 'self' https:; frame-src https://*.paypal.com https://checkout.paystack.com;"
)

# A shared Redis cache makes throttling and sessions consistent across workers.
CACHE_URL = os.getenv('CACHE_URL', os.getenv('REDIS_URL', '')).strip()
if CACHE_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': CACHE_URL,
            'TIMEOUT': 300,
            'OPTIONS': {'socket_connect_timeout': 3, 'socket_timeout': 3},
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'royal-hotel-local',
        }
    }


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'), 
]

WHITENOISE_AVAILABLE = importlib.util.find_spec("whitenoise") is not None
if WHITENOISE_AVAILABLE:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

if not DEBUG and not RUNNING_TESTS:
    SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", default=not RUNNING_LOCAL_DEV_SERVER)
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=not RUNNING_LOCAL_DEV_SERVER)
    CSRF_COOKIE_SECURE = _env_bool("CSRF_COOKIE_SECURE", default=not RUNNING_LOCAL_DEV_SERVER)
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
    SECURE_HSTS_PRELOAD = _env_bool("SECURE_HSTS_PRELOAD", default=False)
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = os.getenv("SECURE_REFERRER_POLICY", "same-origin")
    X_FRAME_OPTIONS = 'DENY'
else:
    # Django's development server only supports plain HTTP. Explicit values
    # prevent production-oriented environment flags from redirecting localhost.
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = int(os.getenv('SESSION_COOKIE_AGE', '43200'))
SESSION_SAVE_EVERY_REQUEST = False
FILE_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv('FILE_UPLOAD_MAX_MEMORY_SIZE', str(2 * 1024 * 1024)))
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv('DATA_UPLOAD_MAX_MEMORY_SIZE', str(128 * 1024 * 1024)))
DATA_UPLOAD_MAX_NUMBER_FILES = 12

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedStaticFilesStorage"
            if WHITENOISE_AVAILABLE
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


def _cloudinary_storage_config():
    cloudinary_url = os.getenv("CLOUDINARY_URL", "").strip()
    if cloudinary_url and cloudinary_url.lower() not in {"cloudinary", "cloudinary://"}:
        parsed = urlparse(cloudinary_url)
        if parsed.scheme == "cloudinary":
            cloud_name = (parsed.hostname or "").strip()
            api_key = unquote(parsed.username or "").strip()
            api_secret = unquote(parsed.password or "").strip()
            if cloud_name and api_key and api_secret:
                return {
                    "CLOUD_NAME": cloud_name,
                    "API_KEY": api_key,
                    "API_SECRET": api_secret,
                    "SECURE": True,
                    "RESOURCE_TYPE": "auto",
                }

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
    if cloud_name and api_key and api_secret:
        return {
            "CLOUD_NAME": cloud_name,
            "API_KEY": api_key,
            "API_SECRET": api_secret,
            "SECURE": True,
            "RESOURCE_TYPE": "auto",
        }

    return None


CLOUDINARY_AVAILABLE = (
    importlib.util.find_spec("cloudinary_storage") is not None
    and importlib.util.find_spec("cloudinary") is not None
)
_cloudinary_config = _cloudinary_storage_config()
USE_CLOUDINARY = _env_bool(
    "USE_CLOUDINARY",
    default=bool(_cloudinary_config) or RUNNING_DEPLOYED_APP,
)

if USE_CLOUDINARY and not CLOUDINARY_AVAILABLE:
    raise ImproperlyConfigured(
        "Install cloudinary and django-cloudinary-storage to use Cloudinary media storage."
    )

if USE_CLOUDINARY and not _cloudinary_config:
    raise ImproperlyConfigured(
        "Set CLOUDINARY_URL=cloudinary://<api_key>:<api_secret>@<cloud_name> "
        "or set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET."
    )

if USE_CLOUDINARY:
    CLOUDINARY_STORAGE = _cloudinary_config

    # Ensure template tags + storage backend are available.
    insert_at = INSTALLED_APPS.index("booking") if "booking" in INSTALLED_APPS else len(INSTALLED_APPS)
    for app in ("cloudinary_storage", "cloudinary"):
        if app not in INSTALLED_APPS:
            INSTALLED_APPS.insert(insert_at, app)
            insert_at += 1

    STORAGES["default"]["BACKEND"] = "cloudinary_storage.storage.MediaCloudinaryStorage"

# Email
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com").strip()
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "").strip()
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", default=True)
if (EMAIL_USE_SSL := _env_bool("EMAIL_USE_SSL", default=False)):
    EMAIL_USE_TLS = False
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))
EMAIL_QUEUE_ENABLED = _env_bool('EMAIL_QUEUE_ENABLED', default=not DEBUG and not RUNNING_TESTS)

if (_email_backend := (os.getenv("EMAIL_BACKEND") or "").strip()):
    EMAIL_BACKEND = _email_backend
elif EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = (
    (os.getenv("DEFAULT_FROM_EMAIL") or "").strip()
    or (EMAIL_HOST_USER or "chanjak03@gmail.com")
)

# Payments (use environment variables for real credentials)
DEFAULT_CURRENCY = os.getenv('DEFAULT_CURRENCY', 'KES')

PAYPAL_BASE_URL = os.getenv('PAYPAL_BASE_URL', 'https://api-m.sandbox.paypal.com')
PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID', '') or ''
PAYPAL_CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET', '') or ''

PAYSTACK_BASE_URL = os.getenv('PAYSTACK_BASE_URL', 'https://api.paystack.co').rstrip('/')
PAYSTACK_PUBLIC_KEY = os.getenv('PAYSTACK_PUBLIC_KEY', '').strip()
PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY', '').strip()

MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY', '').strip()
MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET', '').strip()
MPESA_SHORTCODE = os.getenv('MPESA_SHORTCODE', '').strip()
MPESA_PASSKEY = os.getenv('MPESA_PASSKEY', '').strip()
_mpesa_callback_base_url = (
    os.getenv('RENDER_EXTERNAL_URL', '').strip().rstrip('/')
    or 'https://royal-hotel-mwb5.onrender.com'
)
MPESA_CALLBACK_URL = (
    os.getenv('MPESA_CALLBACK_URL', '').strip()
    or f'{_mpesa_callback_base_url}/payments/mpesa/callback/'
)
MPESA_AUTH_URL = os.getenv(
    'MPESA_AUTH_URL',
    'https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials'
)
MPESA_STK_URL = os.getenv(
    'MPESA_STK_URL',
    'https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest'
)
MPESA_STK_QUERY_URL = os.getenv(
    'MPESA_STK_QUERY_URL',
    'https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query'
)
MPESA_TRANSACTION_TYPE = os.getenv('MPESA_TRANSACTION_TYPE', 'CustomerPayBillOnline')
MPESA_TRANSACTION_DESC = os.getenv('MPESA_TRANSACTION_DESC', 'Hotel Booking Payment')
PAYPAL_WEBHOOK_ID = os.getenv('PAYPAL_WEBHOOK_ID', '').strip()
PAYSTACK_WEBHOOK_SECRET = os.getenv('PAYSTACK_WEBHOOK_SECRET', PAYSTACK_SECRET_KEY).strip()
PAYMENT_RECONCILE_MINUTES = int(os.getenv('PAYMENT_RECONCILE_MINUTES', '10'))

# Google Maps
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '').strip()

# JWT / OIDC (optional)
# Used by booking.jwt_auth to validate Bearer tokens against a JWKS endpoint.
JWT_ISSUER = os.getenv("JWT_ISSUER", "").strip()
JWT_JWKS_URL = os.getenv("JWT_JWKS_URL", "").strip()
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "").strip()
JWT_ALGORITHMS = _env_csv("JWT_ALGORITHMS", default="RS256") or ["RS256"]
JWT_LEEWAY_SECONDS = int(os.getenv("JWT_LEEWAY_SECONDS", "60"))

# Structured production logs go to stdout for collection by the hosting platform.
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            'format': '{{"time":"{asctime}","level":"{levelname}","logger":"{name}","message":"{message}"}}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'json'},
    },
    'root': {'handlers': ['console'], 'level': LOG_LEVEL},
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'booking': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
    },
}

SENTRY_DSN = os.getenv('SENTRY_DSN', '').strip()
if SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=os.getenv('APP_ENV', 'production'),
            release=os.getenv('RENDER_GIT_COMMIT', ''),
            traces_sample_rate=float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', '0.05')),
            send_default_pii=False,
        )
    except ImportError:
        logging.getLogger(__name__).warning('SENTRY_DSN is set but sentry-sdk is not installed.')
