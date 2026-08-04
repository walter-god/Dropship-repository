"""Settings for a quick local run without Docker (no Postgres/Redis needed).

Not for production — this exists so the app can be exercised directly via
`manage.py runserver` when Docker isn't available. Reuses the sqlite/locmem/
fake-Docker profile from settings_test.py but persists to a real file instead
of :memory:, since a dev server is a long-running process.
"""

from .settings_test import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': '/tmp/udom_dev.sqlite3',
    }
}

ALLOWED_HOSTS = ['*']
CORS_ALLOWED_ORIGINS = ['http://localhost:3000', 'http://127.0.0.1:3000']
