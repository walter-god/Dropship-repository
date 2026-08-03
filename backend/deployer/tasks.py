"""Celery tasks for the deployment pipeline.

Deliberately thin: every task resolves its models, guards against double
execution, and hands off to `services`. Keeping the logic out of here means the
pipeline can be run synchronously in a test or a shell without a broker.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from gateway.models import HostedApp

from . import services
from .models import Deployment

logger = logging.getLogger(__name__)


def _load(hosted_app_id: int, deployment_id: int):
    hosted_app = (
        HostedApp.objects
        .select_related('application', 'application__developer', 'runtime_template')
        .get(pk=hosted_app_id)
    )
    deployment = Deployment.objects.get(pk=deployment_id)
    return hosted_app, deployment


@shared_task(name='deployer.tasks.deploy_app', bind=True)
def deploy_app(self, hosted_app_id: int, deployment_id: int):
    """Build, start, and health-check an app."""
    try:
        hosted_app, deployment = _load(hosted_app_id, deployment_id)
    except (HostedApp.DoesNotExist, Deployment.DoesNotExist):
        logger.error(
            'deploy_app: HostedApp %s / Deployment %s no longer exist',
            hosted_app_id, deployment_id,
        )
        return {'status': 'missing'}

    # acks_late means a worker restart can redeliver this message; a finished
    # deployment must not be rebuilt on top of a running container.
    if deployment.is_finished:
        logger.info('Deployment %s already finished (%s)', deployment.pk, deployment.status)
        return {'status': deployment.status}

    services.run_deployment(hosted_app, deployment)
    deployment.refresh_from_db(fields=['status', 'error_summary'])
    return {'status': deployment.status, 'error_summary': deployment.error_summary}


@shared_task(name='deployer.tasks.stop_app')
def stop_app(hosted_app_id: int, paused: bool = False):
    try:
        hosted_app = HostedApp.objects.select_related('application').get(pk=hosted_app_id)
    except HostedApp.DoesNotExist:
        return {'status': 'missing'}
    services.stop_app(
        hosted_app,
        status=HostedApp.STATUS_PAUSED if paused else HostedApp.STATUS_STOPPED,
    )
    return {'status': hosted_app.status}


@shared_task(name='deployer.tasks.restart_app')
def restart_app(hosted_app_id: int):
    try:
        hosted_app = HostedApp.objects.select_related('application').get(pk=hosted_app_id)
    except HostedApp.DoesNotExist:
        return {'status': 'missing'}
    ok = services.restart_app(hosted_app)
    return {'status': hosted_app.status, 'restarted': ok}


@shared_task(name='deployer.tasks.destroy_app')
def destroy_app(hosted_app_id: int, drop_database: bool = False):
    try:
        hosted_app = HostedApp.objects.select_related('application').get(pk=hosted_app_id)
    except HostedApp.DoesNotExist:
        return {'status': 'missing'}
    services.destroy_app(hosted_app, drop_database=drop_database)
    return {'status': hosted_app.status}


@shared_task(name='deployer.tasks.stop_idle_apps')
def stop_idle_apps():
    """Park apps nobody has used recently.

    Only a handful of containers fit in memory on a laptop, so a live app with
    no recent AppSession activity is stopped and marked 'paused'. The launch
    path calls services.ensure_running() to bring it back on demand.
    """
    minutes = settings.DEPLOYER_IDLE_STOP_MINUTES
    cutoff = timezone.now() - timedelta(minutes=minutes)
    paused = []

    live_apps = HostedApp.objects.filter(status=HostedApp.STATUS_LIVE).select_related(
        'application'
    )
    for hosted_app in live_apps:
        last_session = (
            hosted_app.sessions.order_by('-last_seen_at')
            .values_list('last_seen_at', flat=True)
            .first()
        )
        # Fall back to when the app went live, so a freshly deployed app that
        # nobody has opened yet is not killed on the very next sweep.
        candidates = [t for t in (last_session, hosted_app.last_active_at) if t]
        last_activity = max(candidates) if candidates else hosted_app.updated_at

        if last_activity < cutoff:
            try:
                services.stop_app(hosted_app, status=HostedApp.STATUS_PAUSED)
                paused.append(hosted_app.application.slug)
            except Exception as exc:  # noqa: BLE001 - one bad app must not stop the sweep
                logger.warning('Could not pause %s: %s', hosted_app.application.slug, exc)

    if paused:
        logger.info('Paused %s idle app(s): %s', len(paused), ', '.join(paused))
    return {'paused': paused, 'idle_minutes': minutes}
