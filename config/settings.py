"""
Django settings for agencemenage-api project.
"""
from datetime import timedelta
from pathlib import Path
from decouple import config
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-changeme')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

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

# Database — PostgreSQL in production, SQLite fallback for dev
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
AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME', default=None)
AWS_S3_ENDPOINT_URL = config('AWS_S3_ENDPOINT_URL', default=None) # ex: https://xxx.tigris.app
AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default='us-east-1')
AWS_S3_FILE_OVERWRITE = False
AWS_DEFAULT_ACL = 'public-read'
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
        from django.core.exceptions import ImproperlyConfigured
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
        'rest_framework_simplejwt.authentication.JWTAuthentication',
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
}

# ─── JWT ──────────────────────────────────────────────────────────────────
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=config('JWT_ACCESS_TOKEN_LIFETIME_MINUTES', default=60, cast=int)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=config('JWT_REFRESH_TOKEN_LIFETIME_DAYS', default=7, cast=int)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# ─── Auth Cookies ─────────────────────────────────────────────────────────────
AUTH_COOKIE_SECURE = not DEBUG
AUTH_COOKIE_HTTP_ONLY = True
AUTH_COOKIE_SAMESITE = 'None' if not DEBUG else 'Lax'

# ─── CORS ─────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = [
    origin.rstrip('/') for origin in config(
        'CORS_ALLOWED_ORIGINS',
        default='http://localhost:3000,http://localhost:5173,http://localhost:8080,https://profil.agencemenage.ma,https://feedback.agencemenage.ma'
    ).split(',') if origin
]

CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = [
    origin.rstrip('/') for origin in config(
        'CSRF_TRUSTED_ORIGINS',
        default='http://localhost:3000,http://localhost:5173,http://localhost:8080,https://profil.agencemenage.ma,https://feedback.agencemenage.ma'
    ).split(',') if origin
]

# ─── DRF Spectacular (OpenAPI) ────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    'TITLE': 'Agence Ménage API',
    'DESCRIPTION': 'API pour la gestion du back-office de agencemenage.ma',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}
# ─── 360 Dialog WhatsApp Integration ───────────────────────────────────────
D360_API_KEY = config('D360_API_KEY', default='')
API_BASE_URL = config('API_BASE_URL', default='http://localhost:8000').rstrip('/')
D360_API_URL = config('D360_API_URL', default='https://waba-v2.360dialog.io/messages')
