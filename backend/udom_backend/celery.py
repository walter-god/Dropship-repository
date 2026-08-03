"""Celery application for udom_backend.

The deployment pipeline runs builds asynchronously: a Django request enqueues
`deployer.tasks.deploy_app` and returns immediately, while a worker streams the
Docker build into the Deployment row so an admin can watch it live.
"""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'udom_backend.settings')

app = Celery('udom_backend')

# Pull CELERY_* settings from Django settings.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Discover tasks.py in every installed app.
app.autodiscover_tasks()


@app.on_after_finalize.connect
def setup_periodic_tasks(sender, **kwargs):
    """Register the idle auto-stop sweep.

    Registered here (rather than in settings) so the interval can follow the
    DEPLOYER_IDLE_CHECK_MINUTES setting without a second source of truth.
    """
    from django.conf import settings

    interval = getattr(settings, 'DEPLOYER_IDLE_CHECK_MINUTES', 5)
    sender.add_periodic_task(
        interval * 60.0,
        sender.signature('deployer.tasks.stop_idle_apps'),
        name='stop idle hosted apps',
    )


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    return f'Request: {self.request!r}'
