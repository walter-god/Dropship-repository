"""Settings for the automated test suite.

SQLite in memory, locmem cache instead of Redis, and the transport-hardening
settings that assume HTTPS/a real Redis relaxed — the same profile used by the
security review's offline verification harness, formalized here as the
project's actual pytest configuration.
"""

from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}
}

# The test client speaks plain HTTP; production's redirect-to-HTTPS would
# otherwise turn every request into a 301.
SECURE_SSL_REDIRECT = False

EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# A known value so tests can compute an expected HMAC signature.
PAYMENTS_WEBHOOK_SECRET = 'test-webhook-secret'

# Fast health-check polling so deploy tests don't spend real wall-clock time.
DEPLOYER_HEALTH_TIMEOUT_SECONDS = 3
DEPLOYER_HEALTH_POLL_INTERVAL_SECONDS = 0.05
DEPLOYER_LOG_FLUSH_INTERVAL_SECONDS = 0.0
DEPLOYER_BUILD_ROOT = '/tmp/udom-test-builds'

# Exercises the swap seam exactly like the pipeline's own offline harness.
DEPLOYER_DOCKER_SERVICE = 'deployer.fakes.FakeDockerService'

LOGGING_CONFIG = None
