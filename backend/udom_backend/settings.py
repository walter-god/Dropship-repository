"""
Django settings for udom_backend project.
"""

from pathlib import Path
from datetime import timedelta
from decouple import config, Csv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

# Application definition
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
]

LOCAL_APPS = [
    'accounts',
    'marketplace',
    'subscriptions',
    'payments',
    'gateway',
    'deployer',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'udom_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'udom_backend.wsgi.application'
ASGI_APPLICATION = 'udom_backend.asgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='udom_estore'),
        'USER': config('DB_USER', default='postgres'),
        'PASSWORD': config('DB_PASSWORD', default='password'),
        'HOST': config('DB_HOST', default='db'),
        'PORT': config('DB_PORT', default='5432'),
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Dar_es_Salaam'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom user model
AUTH_USER_MODEL = 'accounts.CustomUser'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        # Scoped buckets for the endpoints an attacker actually targets.
        'login': '10/minute',
        'register': '5/hour',
        'payment_webhook': '60/minute',
        'detect_stack': '20/hour',
    },
    # Without this, AnonRateThrottle keys on the client-supplied
    # X-Forwarded-For, which anything on the Docker network (including a
    # student container) can rotate freely to defeat rate limiting entirely.
    # 1 == exactly one trusted proxy in front of Django (nginx).
    'NUM_PROXIES': config('NUM_PROXIES', default=1, cast=int),
}

# Throttle counters and the gateway hostname allowlist both live in the cache.
# With Django's default per-process LocMemCache, throttle limits would multiply
# by the number of workers and an allowlist revocation in the Celery worker
# would never reach the web process. Redis is already running for Celery.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': config('CACHE_URL', default='redis://redis:6379/2'),
    }
}

# JWT Settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'TOKEN_OBTAIN_SERIALIZER': 'rest_framework_simplejwt.serializers.TokenObtainPairSerializer',
    'TOKEN_REFRESH_SERIALIZER': 'rest_framework_simplejwt.serializers.TokenRefreshSerializer',
}

# CORS Settings
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000',
    cast=Csv()
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# drf-spectacular API docs settings
SPECTACULAR_SETTINGS = {
    'TITLE': 'UDOM Digital Marketplace API',
    'DESCRIPTION': (
        'University of Dodoma Digital Marketplace — a platform for discovering, '
        'downloading, and managing university applications.'
    ),
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': '/api/',
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': True,
    },
    'SECURITY': [{'BearerAuth': []}],
    # drf-spectacular serves the schema to anyone by default. A full API map is
    # free reconnaissance for an attacker — and every student container can
    # reach this backend.
    'SERVE_PERMISSIONS': ['rest_framework.permissions.IsAdminUser'],
    'APPEND_COMPONENTS': {
        'securitySchemes': {
            'BearerAuth': {
                'type': 'http',
                'scheme': 'bearer',
                'bearerFormat': 'JWT',
            }
        }
    },
}

# File upload settings
DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800   # 50 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800   # 50 MB

# Neither of the above caps an uploaded FILE's size — Django exempts file
# fields from DATA_UPLOAD_MAX_MEMORY_SIZE, and FILE_UPLOAD_MAX_MEMORY_SIZE is
# only the memory-vs-disk spill threshold. These are enforced explicitly in
# marketplace/validators.py, which also runs for requests that reach the
# backend directly and so bypass nginx's client_max_body_size.
MARKETPLACE_MAX_SOURCE_UPLOAD_MB = config('MARKETPLACE_MAX_SOURCE_UPLOAD_MB', default=100, cast=int)
MARKETPLACE_MAX_APP_FILE_MB = config('MARKETPLACE_MAX_APP_FILE_MB', default=500, cast=int)

# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
# Shared secret for verifying the HMAC-SHA256 signature on payment webhooks.
# The webhook is unauthenticated by necessity, so this signature IS its
# authentication. Empty means the endpoint rejects everything (fail closed).
PAYMENTS_WEBHOOK_SECRET = config('PAYMENTS_WEBHOOK_SECRET', default='')

# ---------------------------------------------------------------------------
# Transport / cookie hardening
# ---------------------------------------------------------------------------
# Applied only outside DEBUG so local HTTP development still works. Behind
# nginx, Django needs the forwarded-proto header to know a request was HTTPS.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

if not DEBUG:
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_SAMESITE = 'Lax'
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://redis:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://redis:6379/1')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# Must comfortably exceed build timeout + migrate + health poll, or Celery
# would kill a deploy mid-flight and leave orphaned containers behind.
CELERY_TASK_SOFT_TIME_LIMIT = config('CELERY_TASK_SOFT_TIME_LIMIT', default=1500, cast=int)
CELERY_TASK_TIME_LIMIT = config('CELERY_TASK_TIME_LIMIT', default=1800, cast=int)

# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------
# Student containers resolve only inside Docker DNS, so the SSRF resolver
# cannot validate them by IP. This list seeds the database-backed allowlist
# (see gateway/allowlist.py) — it is NOT the live source of truth, because the
# worker registers hostnames while the web process serves traffic, and the two
# run in separate containers.
GATEWAY_ALLOWED_HOSTNAMES = config(
    'GATEWAY_ALLOWED_HOSTNAMES',
    default='',
    cast=lambda v: [h.strip() for h in v.split(',') if h.strip()],
)

# ---------------------------------------------------------------------------
# Deployer
# ---------------------------------------------------------------------------
# Swap this for a remote deployer daemon without touching views or tasks.
DEPLOYER_DOCKER_SERVICE = config(
    'DEPLOYER_DOCKER_SERVICE',
    default='deployer.docker_service.LocalDockerService',
)

# Naming
DEPLOYER_CONTAINER_PREFIX = config('DEPLOYER_CONTAINER_PREFIX', default='udom-app-')
DEPLOYER_NETWORK_PREFIX = config('DEPLOYER_NETWORK_PREFIX', default='udom_app_')
DEPLOYER_IMAGE_PREFIX = config('DEPLOYER_IMAGE_PREFIX', default='udom-app')

# Platform containers that must join each per-app network.
# The backend proxies user traffic; the worker runs the health check. Omitting
# the worker makes every deploy fail at the health-check step.
DEPLOYER_ATTACH_CONTAINERS = config(
    'DEPLOYER_ATTACH_CONTAINERS',
    default='udom_backend,udom_celery_worker',
    cast=lambda v: [c.strip() for c in v.split(',') if c.strip()],
)

# Connected to an app network only when that app needs a database.
DEPLOYER_DB_CONTAINER_NAME = config('DEPLOYER_DB_CONTAINER_NAME', default='udom_db')

# Build limits
DEPLOYER_BUILD_ROOT = config('DEPLOYER_BUILD_ROOT', default='/tmp/udom-builds')
DEPLOYER_BUILD_TIMEOUT_SECONDS = config('DEPLOYER_BUILD_TIMEOUT_SECONDS', default=600, cast=int)
DEPLOYER_MAX_IMAGE_SIZE_MB = config('DEPLOYER_MAX_IMAGE_SIZE_MB', default=2048, cast=int)
DEPLOYER_MAX_EXTRACTED_MB = config('DEPLOYER_MAX_EXTRACTED_MB', default=512, cast=int)
DEPLOYER_MAX_EXTRACTED_FILES = config('DEPLOYER_MAX_EXTRACTED_FILES', default=20000, cast=int)
DEPLOYER_LOG_FLUSH_INTERVAL_SECONDS = config(
    'DEPLOYER_LOG_FLUSH_INTERVAL_SECONDS', default=1.0, cast=float
)

# Runtime limits applied to every student container
DEPLOYER_CONTAINER_USER = config('DEPLOYER_CONTAINER_USER', default='1000:1000')
DEPLOYER_PIDS_LIMIT = config('DEPLOYER_PIDS_LIMIT', default=256, cast=int)
DEPLOYER_DEFAULT_MEMORY_MB = config('DEPLOYER_DEFAULT_MEMORY_MB', default=512, cast=int)
DEPLOYER_DEFAULT_CPU = config('DEPLOYER_DEFAULT_CPU', default=0.5, cast=float)

# The root filesystem is read-only, so writable paths are tmpfs. Sized, because
# an unbounded tmpfs is RAM a container can consume past its memory limit.
DEPLOYER_TMPFS_SIZE_MB = config('DEPLOYER_TMPFS_SIZE_MB', default=64, cast=int)

# nofile/nproc bound fd and thread exhaustion; fsize bounds how large a single
# file can grow inside the writable tmpfs layers.
DEPLOYER_ULIMITS = {
    'nofile': config('DEPLOYER_ULIMIT_NOFILE', default=1024, cast=int),
    'nproc': config('DEPLOYER_ULIMIT_NPROC', default=256, cast=int),
    'fsize': config('DEPLOYER_ULIMIT_FSIZE', default=256 * 1024 * 1024, cast=int),
}

# Zip bombs: total extracted size alone is not enough, because a small archive
# with an enormous ratio still costs CPU and I/O to discover.
DEPLOYER_MAX_COMPRESSION_RATIO = config('DEPLOYER_MAX_COMPRESSION_RATIO', default=100, cast=int)

# Health check
DEPLOYER_HEALTH_TIMEOUT_SECONDS = config('DEPLOYER_HEALTH_TIMEOUT_SECONDS', default=90, cast=int)
DEPLOYER_HEALTH_POLL_INTERVAL_SECONDS = config(
    'DEPLOYER_HEALTH_POLL_INTERVAL_SECONDS', default=2.0, cast=float
)

# Idle auto-stop — only a handful of containers fit on a laptop at once.
DEPLOYER_IDLE_STOP_MINUTES = config('DEPLOYER_IDLE_STOP_MINUTES', default=60, cast=int)
DEPLOYER_IDLE_CHECK_MINUTES = config('DEPLOYER_IDLE_CHECK_MINUTES', default=5, cast=int)

# Per-app Postgres provisioning. Needs superuser rights to CREATE DATABASE/ROLE.
DEPLOYER_APP_DB_HOST = config('DEPLOYER_APP_DB_HOST', default=DATABASES['default']['HOST'])
DEPLOYER_APP_DB_PORT = config('DEPLOYER_APP_DB_PORT', default=DATABASES['default']['PORT'])
DEPLOYER_APP_DB_SUPERUSER = config('DEPLOYER_APP_DB_SUPERUSER', default=DATABASES['default']['USER'])
DEPLOYER_APP_DB_PASSWORD = config(
    'DEPLOYER_APP_DB_PASSWORD', default=DATABASES['default']['PASSWORD']
)
# Hostname student containers use to reach Postgres (Docker DNS, not localhost).
DEPLOYER_APP_DB_INTERNAL_HOST = config('DEPLOYER_APP_DB_INTERNAL_HOST', default='db')

# Caps how many Postgres connections one student app can hold, so a hostile or
# leaking app cannot exhaust the shared instance's connection slots and take
# the platform down with it.
DEPLOYER_APP_DB_CONNECTION_LIMIT = config(
    'DEPLOYER_APP_DB_CONNECTION_LIMIT', default=20, cast=int
)

# Fernet key for HostedApp.env_vars. Defaults to a value derived from
# SECRET_KEY so development works unconfigured — set explicitly in production,
# because rotating SECRET_KEY would otherwise make stored env vars unreadable.
DEPLOYER_ENV_ENCRYPTION_KEY = config('DEPLOYER_ENV_ENCRYPTION_KEY', default='')
