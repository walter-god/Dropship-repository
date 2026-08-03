"""udom_backend package.

Importing the Celery app here ensures @shared_task decorators across the
project bind to it when Django starts.
"""

from .celery import app as celery_app

__all__ = ('celery_app',)
