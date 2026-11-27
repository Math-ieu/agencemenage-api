"""
Django settings for agencemenage-api project.
"""
from datetime import timedelta
from pathlib import Path
from decouple import Csv, config
from django.core.exceptions import ImproperlyConfigured
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-changeme')
# True en local (.env), False en production (défaut sécurisé)
DEBUG = config('DEBUG', default=False, cast=bool)
if not DEBUG and (not SECRET_KEY or SECRET_KEY == 'django-insecure-changeme' or len(SECRET_KEY) < 32):
    raise ImproperlyConfigured("SECRET_KEY sécurisée (>= 32 caractères) requise lorsque DEBUG=False.")

ALLOWED_HOSTS = [
    h for h in config(
        'ALLOWED_HOSTS',
        default='localhost,127.0.0.1,testserver,api.agencemenage.ma,agencemenage-api.up.railway.app' if DEBUG else 'api.agencemenage.ma,agencemenage-api.up.railway.app',
        cast=Csv(),
    ) if h
]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    'storages',

    # Local apps
    'accounts',
    'clients',
    'agents',
    'demandes',
    'missions',
    'finance',
    'feedback',
    'blog',
    'marketing',
    'airbnb',
    'site_settings',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'config.middleware.CurrentUserMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database — PostgreSQL in production (Railway DATABASE_URL), SQLite fallback for dev
DATABASES = {
    'default': dj_database_url.config(
        default=config('DATABASE_URL', default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTH_USER_MODEL = 'accounts.User'

LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'Africa/Casablanca'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ─── Storage Configuration (Railway Bucket / S3) ───────────────────────────
AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default=None)
AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default=None)
AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME', default=config('AWS_S3_BUCKET_NAME', default=None))
_raw_endpoint = config('AWS_S3_ENDPOINT_URL', default=config('AWS_ENDPOINT_URL', default=None))
AWS_S3_ENDPOINT_URL = _raw_endpoint.rstrip('/') if _raw_endpoint else None
AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default=config('AWS_DEFAULT_REGION', default='auto'))
AWS_S3_FILE_OVERWRITE = False
# Tigris (Railway) ne supporte pas les ACLs d'objets (comme 'public-read')
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = False
AWS_S3_VERIFY = True

if AWS_STORAGE_BUCKET_NAME:
    STORAGES = {
        "default": {
            "BACKEND": "config.storage_backends.ProxyS3Boto3Storage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
    MEDIA_URL = '/api/media/'
else:
    if not DEBUG:
        raise ImproperlyConfigured(
            "AWS_STORAGE_BUCKET_NAME est requis en production pour éviter le stockage local."
        )
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
    MEDIA_ROOT = BASE_DIR / 'media'
    MEDIA_URL = '/media/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── Django REST Framework ─────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'accounts.authentication.CookieJWTAuthentication',
        'accounts.authentication.ThreadSafeJWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'config.pagination.CustomPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': config('THROTTLE_ANON', default='120/min'),
        'user': config('THROTTLE_USER', default='600/min'),
        'auth_login': config('THROTTLE_AUTH_LOGIN', default='15/min'),
        'auth_forgot_password': config('THROTTLE_AUTH_FORGOT', default='5/hour'),
        'auth_reset_password': config('THROTTLE_AUTH_RESET', default='10/hour'),
        'public_write': config('THROTTLE_PUBLIC_WRITE', default='60/min'),
        'public_promo_validate': config('THROTTLE_PUBLIC_PROMO', default='60/min'),
    },
}

# ─── JWT ──────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=config('JWT_ACCESS_TOKEN_LIFETIME_MINUTES', default=60, cast=int)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=config('JWT_REFRESH_TOKEN_LIFETIME_DAYS', default=7, cast=int)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ─── Auth Cookies & HTTP Security ─────────────────────────────────────────────
AUTH_COOKIE_SECURE = not DEBUG
AUTH_COOKIE_HTTP_ONLY = True
AUTH_COOKIE_SAMESITE = config('AUTH_COOKIE_SAMESITE', default='Lax' if DEBUG else 'None')
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = AUTH_COOKIE_SAMESITE
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = AUTH_COOKIE_SAMESITE

X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if not DEBUG else None
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=not DEBUG, cast=bool)
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=0 if DEBUG else 31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG

# ─── CORS & CSRF ──────────────────────────────────────────────────────────
_PROD_ORIGINS = (
    'https://agencemenage.ma,https://www.agencemenage.ma,'
    'https://app.agencemenage.ma,https://profil.agencemenage.ma,'
    'https://feedback.agencemenage.ma'
)
_DEFAULT_ORIGINS = (
    f'http://localhost:3000,http://localhost:5173,http://localhost:5174,http://localhost:8080,{_PROD_ORIGINS}'
    if DEBUG else _PROD_ORIGINS
)

CORS_ALLOWED_ORIGINS = [
    o.rstrip('/') for o in config('CORS_ALLOWED_ORIGINS', default=_DEFAULT_ORIGINS, cast=Csv()) if o
]
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = [
    o.rstrip('/') for o in config('CSRF_TRUSTED_ORIGINS', default=_DEFAULT_ORIGINS, cast=Csv()) if o
]

# ─── DRF Spectacular (OpenAPI) ────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    'TITLE': 'Agence Ménage API',
    'DESCRIPTION': 'API pour la gestion du back-office de agencemenage.ma',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SERVE_PERMISSIONS': ['accounts.permissions.IsAdminOrDebugOnly'],
    'SERVE_PUBLIC': DEBUG,
}
# ─── 360 Dialog WhatsApp Integration ───────────────────────────────────────
D360_API_KEY = config('D360_API_KEY', default='')
API_BASE_URL = config('API_BASE_URL', default='http://localhost:8000').rstrip('/')
D360_API_URL = config('D360_API_URL', default='https://waba-v2.360dialog.io/messages')

# ─── Resend & Frontend settings ──────────────────────────────────────────
RESEND_API_KEY = config('RESEND_API_KEY', default=None)
FRONTEND_URL = config('FRONTEND_URL', default='https://app.agencemenage.ma').rstrip('/')

AUTHENTICATION_BACKENDS = [
    'accounts.backends.EmailOrUsernameModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]
