"""Admin API for the deployment pipeline.

Every endpoint is keyed on the marketplace Application id — that is the object
an admin is looking at when they click Deploy — and the HostedApp is created
lazily on first deploy.
"""

from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from gateway.models import HostedApp
from marketplace.models import Application
from marketplace.permissions import IsAdminUser

from . import services, tasks
from .models import Deployment
from .serializers import (
    DeploymentDetailSerializer,
    DeploymentSummarySerializer,
    EnvVarsSerializer,
    HostedAppSerializer,
    LogsSerializer,
)

logger = logging.getLogger(__name__)

DEPLOYABLE_STATUSES = (Application.STATUS_APPROVED, Application.STATUS_PUBLISHED)


class DeployerViewSet(viewsets.GenericViewSet):
    """Deployment control surface. Administrators only."""

    queryset = Application.objects.select_related('developer').all()
    serializer_class = HostedAppSerializer
    # marketplace's role-aware IsAdminUser, not DRF's is_staff-only class.
    permission_classes = [IsAuthenticated, IsAdminUser]

    # -- helpers -----------------------------------------------------------

    def _application(self) -> Application:
        return get_object_or_404(Application, pk=self.kwargs['pk'])

    def _hosted_app(self, application: Application) -> HostedApp:
        hosted_app, created = HostedApp.objects.get_or_create(application=application)
        if created:
            logger.info('Created HostedApp for %s', application.slug)
        return hosted_app

    @staticmethod
    def _conflict(message: str) -> Response:
        return Response({'error': message}, status=status.HTTP_409_CONFLICT)

    def _enqueue_build(self, request, hosted_app: HostedApp, application: Application):
        """Shared by deploy and redeploy."""
        if application.status not in DEPLOYABLE_STATUSES:
            return Response(
                {
                    'error': (
                        f'Only approved projects can be deployed '
                        f'(this one is "{application.status}").'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not application.source_code:
            return Response(
                {'error': 'This project has no source archive uploaded.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if hosted_app.is_busy:
            return self._conflict(
                f'A deployment is already in progress (status: {hosted_app.status}).'
            )

        deployment = Deployment.objects.create(
            hosted_app=hosted_app,
            status=Deployment.STATUS_QUEUED,
            triggered_by=request.user,
        )
        hosted_app.mark(HostedApp.STATUS_QUEUED)
        tasks.deploy_app.delay(hosted_app.pk, deployment.pk)

        return Response(
            {
                'message': 'Build queued.',
                'deployment': DeploymentSummarySerializer(deployment).data,
                'hosted_app': HostedAppSerializer(hosted_app).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    # -- endpoints ---------------------------------------------------------

    @action(detail=True, methods=['post'])
    def deploy(self, request, pk=None):
        """POST /api/deployer/apps/<pk>/deploy/"""
        application = self._application()
        return self._enqueue_build(request, self._hosted_app(application), application)

    @action(detail=True, methods=['post'])
    def redeploy(self, request, pk=None):
        """POST /api/deployer/apps/<pk>/redeploy/ — rebuild from current source."""
        application = self._application()
        return self._enqueue_build(request, self._hosted_app(application), application)

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """POST /api/deployer/apps/<pk>/stop/"""
        hosted_app = self._hosted_app(self._application())
        if hosted_app.is_busy:
            return self._conflict('Cannot stop an app mid-deployment.')
        services.stop_app(hosted_app)
        return Response(
            {'message': 'App stopped.', 'hosted_app': HostedAppSerializer(hosted_app).data}
        )

    @action(detail=True, methods=['post'])
    def restart(self, request, pk=None):
        """POST /api/deployer/apps/<pk>/restart/

        Also the resume path: a paused app is brought back up rather than
        refused.
        """
        hosted_app = self._hosted_app(self._application())
        if hosted_app.is_busy:
            return self._conflict('Cannot restart an app mid-deployment.')

        if hosted_app.status in (HostedApp.STATUS_PAUSED, HostedApp.STATUS_STOPPED):
            resumed = services.ensure_running(hosted_app)
        else:
            resumed = services.restart_app(hosted_app)

        if not resumed:
            return Response(
                {'error': 'No container exists for this app — deploy it first.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {'message': 'App running.', 'hosted_app': HostedAppSerializer(hosted_app).data}
        )

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """POST /api/deployer/apps/<pk>/publish/ — requires a live app."""
        application = self._application()
        hosted_app = self._hosted_app(application)

        if hosted_app.status != HostedApp.STATUS_LIVE:
            return self._conflict(
                f'Only a live app can be published (this one is "{hosted_app.status}").'
            )

        application.status = Application.STATUS_PUBLISHED
        application.save(update_fields=['status', 'updated_at'])
        logger.info('Published %s', application.slug)

        return Response(
            {
                'message': f'"{application.name}" is now published.',
                'application_status': application.status,
                'internal_base_url': hosted_app.internal_base_url,
            }
        )

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """GET /api/deployer/apps/<pk>/logs/ — build log plus a docker-logs tail."""
        hosted_app = self._hosted_app(self._application())
        deployment = hosted_app.deployments.order_by('-created_at').first()
        try:
            tail = int(request.query_params.get('tail', 200))
        except (TypeError, ValueError):
            tail = 200

        payload = {
            'hosted_app_status': hosted_app.status,
            'deployment': DeploymentSummarySerializer(deployment).data if deployment else None,
            'build_log': deployment.build_log if deployment else '',
            'container_logs': services.tail_container_logs(hosted_app, tail=tail),
        }
        return Response(LogsSerializer(payload).data)

    @action(detail=True, methods=['get'])
    def deployments(self, request, pk=None):
        """GET /api/deployer/apps/<pk>/deployments/ — build history."""
        hosted_app = self._hosted_app(self._application())
        queryset = hosted_app.deployments.select_related('triggered_by').order_by('-created_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(DeploymentSummarySerializer(page, many=True).data)
        return Response(DeploymentSummarySerializer(queryset, many=True).data)

    @action(detail=True, methods=['get'], url_path='deployments/(?P<deployment_id>[0-9]+)')
    def deployment_detail(self, request, pk=None, deployment_id=None):
        """GET a single build, including its full log."""
        hosted_app = self._hosted_app(self._application())
        deployment = get_object_or_404(hosted_app.deployments, pk=deployment_id)
        return Response(DeploymentDetailSerializer(deployment).data)

    @action(detail=True, methods=['patch'], url_path='env')
    def env(self, request, pk=None):
        """PATCH /api/deployer/apps/<pk>/env/ — edit env vars without re-uploading."""
        application = self._application()
        hosted_app = self._hosted_app(application)

        serializer = EnvVarsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        hosted_app.env_vars = data['env_vars']
        update_fields = ['env_vars', 'updated_at']
        if 'memory_limit_mb' in data:
            hosted_app.memory_limit_mb = data['memory_limit_mb']
            update_fields.append('memory_limit_mb')
        if 'cpu_limit' in data:
            hosted_app.cpu_limit = data['cpu_limit']
            update_fields.append('cpu_limit')
        hosted_app.save(update_fields=update_fields)

        if data.get('redeploy'):
            return self._enqueue_build(request, hosted_app, application)

        return Response(
            {
                'message': 'Environment updated. Redeploy for it to take effect.',
                'hosted_app': HostedAppSerializer(hosted_app).data,
            }
        )

    @action(detail=True, methods=['post'])
    def destroy_deployment(self, request, pk=None):
        """POST /api/deployer/apps/<pk>/destroy_deployment/ — full teardown."""
        hosted_app = self._hosted_app(self._application())
        if hosted_app.is_busy:
            return self._conflict('Cannot destroy an app mid-deployment.')

        drop_database = str(request.data.get('drop_database', '')).lower() in ('1', 'true', 'yes')
        services.destroy_app(hosted_app, drop_database=drop_database)
        return Response(
            {
                'message': 'Deployment destroyed.',
                'database_dropped': drop_database,
                'hosted_app': HostedAppSerializer(hosted_app).data,
            }
        )
