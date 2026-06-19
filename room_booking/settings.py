

from pathlib import Path
import os
import sys
import importlib.util
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
    and not any(arg.startswith(("0.0.0.0:", "0:")) for arg in sys.argv)
)
RUNNING_DEPLOYED_APP = bool(
    os.getenv("RENDER", "").strip()
    or os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    or os.getenv("RENDER_EXTERNAL_URL", "").strip()
)
if not RUNNING_TESTS:
    # Load local development overrides without clobbering real environment
    # variables from Render, CI, or the shell.
    _load_dotenv(BASE_DIR / ".env", override=False)

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
        origins.extend(["http://localhost", "http://127.0.0.1"])
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
if DEBUG and not use_database_url_in_debug:
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

if not DEBUG and not RUNNING_TESTS:
    SECURE_SSL_REDIRECT = (
        _env_bool("SECURE_SSL_REDIRECT", default=True)
        if RUNNING_DEPLOYED_APP and not RUNNING_LOCAL_DEV_SERVER
        else False
    )
    SESSION_COOKIE_SECURE = RUNNING_DEPLOYED_APP and not RUNNING_LOCAL_DEV_SERVER
    CSRF_COOKIE_SECURE = RUNNING_DEPLOYED_APP and not RUNNING_LOCAL_DEV_SERVER
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
    SECURE_HSTS_PRELOAD = _env_bool("SECURE_HSTS_PRELOAD", default=False)
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = os.getenv("SECURE_REFERRER_POLICY", "same-origin")

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
USE_CLOUDINARY = _env_bool("USE_CLOUDINARY", default=bool(_cloudinary_config))

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
EMAIL_HOST = os.getenv("EMAIL_HOST", "https://royal-hotel-mwb5.onrender.com") or 'smtp.gmail.com'
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "") or 'chanjak03@gmailc.om'
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "") or 'hxxvvlojkmvsaiti'
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", default=False)
if (EMAIL_USE_SSL := _env_bool("EMAIL_USE_SSL", default=False)):
    EMAIL_USE_TLS = False
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))

if (_email_backend := (os.getenv("EMAIL_BACKEND") or "").strip()):
    EMAIL_BACKEND = _email_backend
elif EMAIL_HOST_USER and EMAIL_HOST != "https://royal-hotel-mwb5.onrender.com":
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = (
    (os.getenv("DEFAULT_FROM_EMAIL") or "").strip()
    or (EMAIL_HOST_USER or "chanjak03@gmail.com")
)

# Payments (use environment variables for real credentials)
DEFAULT_CURRENCY = os.getenv('DEFAULT_CURRENCY', 'KES')

STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY') or ''
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY') or ''
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET') or ''

PAYPAL_BASE_URL = os.getenv('PAYPAL_BASE_URL', 'https://api-m.sandbox.paypal.com')
PAYPAL_CLIENT_ID = os.getenv('PAYPAL_CLIENT_ID', '') or ''
PAYPAL_CLIENT_SECRET = os.getenv('PAYPAL_CLIENT_SECRET', '') or ''

MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY') or 'gN43u6RBle3pldlpY0LsqtyOxQbcAHHzqg6AcCwB0WLgeH1Z'
MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET') or 'kJb1o5bD024u7EGz22vfGkMMO84AT6c0ywuqPFgkthjSyFXGGsI95B3pK463GINz'
MPESA_SHORTCODE = os.getenv('MPESA_SHORTCODE') or '174379'
MPESA_PASSKEY = os.getenv('MPESA_PASSKEY') or 'bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919'
MPESA_CALLBACK_URL = os.getenv('MPESA_CALLBACK_URL') or 'https://https://royal-hotel-mwb5.onrender.com/payments/mpesa/callback/'
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
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY'or  '')

# Google OAuth (Login with Google / Gmail)
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID" or "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET" or "").strip()

# JWT / OIDC (optional)
# Used by booking.jwt_auth to validate Bearer tokens against a JWKS endpoint.
JWT_ISSUER = os.getenv("JWT_ISSUER", "").strip()
JWT_JWKS_URL = os.getenv("JWT_JWKS_URL", "").strip()
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "").strip()
JWT_ALGORITHMS = _env_csv("JWT_ALGORITHMS", default="RS256") or ["RS256"]
JWT_LEEWAY_SECONDS = int(os.getenv("JWT_LEEWAY_SECONDS", "60"))
