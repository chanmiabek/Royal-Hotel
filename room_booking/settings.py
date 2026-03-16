

from pathlib import Path
import os
import sys
import importlib.util
from urllib.parse import urlparse, parse_qs, unquote
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
if not RUNNING_TESTS:
    _load_dotenv(BASE_DIR / ".env", override=True)

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


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY', 'dev-only-change-this-to-a-long-random-secret-key-value-1234567890')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = _env_bool("DEBUG", default=True)
if RUNNING_TESTS:
    DEBUG = True

ALLOWED_HOSTS = _normalize_allowed_hosts(
    _env_csv("ALLOWED_HOSTS", default="royal-hotel-mwb5.onrender.com,localhost,127.0.0.1")
)
if DEBUG:
    ALLOWED_HOSTS.append("testserver")
CSRF_TRUSTED_ORIGINS = _env_csv(
    "CSRF_TRUSTED_ORIGINS",
    default="https://royal-hotel-mwb5.onrender.com",
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
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
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
    }
    if options:
        config['OPTIONS'] = options
    return config


database_url = os.getenv('DATABASE_URL')
use_database_url_in_debug = _env_bool('USE_DATABASE_URL_IN_DEBUG', default=False)
if DEBUG and not use_database_url_in_debug:
    database_url = None

DATABASES = {
    'default': _database_config_from_url(database_url),
}


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

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'), 
]

WHITENOISE_AVAILABLE = importlib.util.find_spec("whitenoise") is not None
if WHITENOISE_AVAILABLE:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

if not DEBUG:
    SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

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
    if cloudinary_url:
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
USE_CLOUDINARY = _env_bool("USE_CLOUDINARY", default=bool(_cloudinary_config and not DEBUG))

if USE_CLOUDINARY and CLOUDINARY_AVAILABLE and _cloudinary_config:
    CLOUDINARY_STORAGE = _cloudinary_config

    # Ensure template tags + storage backend are available.
    insert_at = INSTALLED_APPS.index("booking") if "booking" in INSTALLED_APPS else len(INSTALLED_APPS)
    for app in ("cloudinary_storage", "cloudinary"):
        if app not in INSTALLED_APPS:
            INSTALLED_APPS.insert(insert_at, app)
            insert_at += 1

    STORAGES["default"]["BACKEND"] = "cloudinary_storage.storage.MediaCloudinaryStorage"

# Email
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = _env_bool("EMAIL_USE_SSL", default=False)
if EMAIL_USE_SSL:
    EMAIL_USE_TLS = False
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))

_email_backend = (os.getenv("EMAIL_BACKEND") or "").strip()
if _email_backend:
    EMAIL_BACKEND = _email_backend
elif EMAIL_HOST_USER and EMAIL_HOST != "localhost":
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = (
    (os.getenv("DEFAULT_FROM_EMAIL") or "").strip()
    or (EMAIL_HOST_USER or "royal-hotel@example.com")
)

# Payments (use environment variables for real credentials)
DEFAULT_CURRENCY = os.getenv('DEFAULT_CURRENCY', 'KES')

STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')

PAYPAL_BASE_URL = os.getenv('PAYPAL_BASE_URL', 'https://api-m.sandbox.paypal.com')
PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID', '')
PAYPAL_CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET', '')

MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY', '')
MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET', '')
MPESA_SHORTCODE = os.getenv('MPESA_SHORTCODE', '')
MPESA_PASSKEY = os.getenv('MPESA_PASSKEY', '')
MPESA_CALLBACK_URL = os.getenv('MPESA_CALLBACK_URL', '')
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

# Google Maps
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')

# Google OAuth (Login with Google / Gmail)
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()

# JWT / OIDC (optional)
# Used by booking.jwt_auth to validate Bearer tokens against a JWKS endpoint.
JWT_ISSUER = os.getenv("JWT_ISSUER", "").strip()
JWT_JWKS_URL = os.getenv("JWT_JWKS_URL", "").strip()
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "").strip()
JWT_ALGORITHMS = _env_csv("JWT_ALGORITHMS", default="RS256") or ["RS256"]
JWT_LEEWAY_SECONDS = int(os.getenv("JWT_LEEWAY_SECONDS", "60"))
