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

from gateway.models import AppSession, HostedApp
from marketplace.models import Application
from marketplace.permissions import IsAdminUser

from . import services, tasks
from .models import Deployment, RuntimeTemplate
from .serializers import (
    AppSessionSerializer,
    DeployRequestSerializer,
    DeploymentDetailSerializer,
    DeploymentSummarySerializer,
    DockerfileUploadSerializer,
    EnvVarsSerializer,
    HostedAppSerializer,
    LogsSerializer,
    RuntimeTemplateSerializer,
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

    # -- list / retrieve -----------------------------------------------------
    # GenericViewSet adds no routes on its own; these back the admin table
    # (one row per approved/published project) and the single-app fetch the
    # deploy drawer and log modal poll.

    def list(self, request):
        """GET /api/deployer/apps/ — one row per approved/published project."""
        queryset = (
            self.queryset.filter(status__in=DEPLOYABLE_STATUSES)
            .select_related('developer', 'category')
            .order_by('-updated_at')
        )
        page = self.paginate_queryset(queryset)
        applications = list(page if page is not None else queryset)

        # Avoid an N+1 get_or_create: fetch every HostedApp that already
        # exists in one query, and only create rows for apps deployed for
        # the first time.
        existing = {
            h.application_id: h
            for h in HostedApp.objects.filter(application__in=applications)
            .select_related('runtime_template', 'application', 'application__developer')
        }
        hosted_apps = [existing.get(a.pk) or self._hosted_app(a) for a in applications]

        serializer = HostedAppSerializer(hosted_apps, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """GET /api/deployer/apps/<pk>/ — single hosted app detail."""
        hosted_app = self._hosted_app(self._application())
        return Response(HostedAppSerializer(hosted_app).data)

    def _enqueue_build(
        self, request, hosted_app: HostedApp, application: Application, overrides: dict | None = None
    ):
        """Shared by deploy, redeploy, and the env-action's redeploy shortcut.

        `overrides` holds already-validated per-run choices from the deploy
        drawer (runtime template, database checkbox, port). None means "use
        auto-detection / the app's current settings", which is what a plain
        rebuild from the env action wants.
        """
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

        overrides = overrides or {}
        deployment = Deployment.objects.create(
            hosted_app=hosted_app,
            status=Deployment.STATUS_QUEUED,
            triggered_by=request.user,
            requested_runtime_template_id=overrides.get('runtime_template_id'),
            requested_provision_database=overrides.get('provision_database'),
            requested_container_port=overrides.get('container_port'),
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

    def _deploy_or_redeploy(self, request, pk):
        """Validate the deploy-drawer payload, apply resource/env changes to
        the HostedApp immediately, and queue the build with the rest as
        per-run overrides."""
        application = self._application()
        hosted_app = self._hosted_app(application)

        serializer = DeployRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_fields = []
        if 'memory_limit_mb' in data:
            hosted_app.memory_limit_mb = data['memory_limit_mb']
            update_fields.append('memory_limit_mb')
        if 'cpu_limit' in data:
            hosted_app.cpu_limit = data['cpu_limit']
            update_fields.append('cpu_limit')
        if 'env_vars' in data:
            hosted_app.env_vars = data['env_vars']
            update_fields.append('env_vars')
        if update_fields:
            hosted_app.save(update_fields=[*update_fields, 'updated_at'])

        overrides = {
            'runtime_template_id': data.get('runtime_template_id'),
            'provision_database': data.get('provision_database'),
            'container_port': data.get('container_port'),
        }
        return self._enqueue_build(request, hosted_app, application, overrides=overrides)

    # -- endpoints ---------------------------------------------------------

    @action(detail=True, methods=['post'])
    def deploy(self, request, pk=None):
        """POST /api/deployer/apps/<pk>/deploy/"""
        return self._deploy_or_redeploy(request, pk)

    @action(detail=True, methods=['post'])
    def redeploy(self, request, pk=None):
        """POST /api/deployer/apps/<pk>/redeploy/ — rebuild from current source."""
        return self._deploy_or_redeploy(request, pk)

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

    @action(detail=True, methods=['get'])
    def sessions(self, request, pk=None):
        """GET /api/deployer/apps/<pk>/sessions/ — active AppSessions."""
        hosted_app = self._hosted_app(self._application())
        queryset = hosted_app.sessions.select_related('user').order_by('-last_seen_at')
        if str(request.query_params.get('active_only', 'true')).lower() != 'false':
            queryset = queryset.filter(ended_at__isnull=True)
        return Response(AppSessionSerializer(queryset, many=True).data)

    @action(
        detail=True, methods=['post'],
        url_path='sessions/(?P<session_id>[0-9]+)/revoke',
    )
    def revoke_session(self, request, pk=None, session_id=None):
        """POST /api/deployer/apps/<pk>/sessions/<session_id>/revoke/"""
        hosted_app = self._hosted_app(self._application())
        session = get_object_or_404(hosted_app.sessions, pk=session_id)
        session.revoke()
        return Response(
            {'message': 'Session revoked.', 'session': AppSessionSerializer(session).data}
        )

    @action(detail=True, methods=['patch'], url_path='dockerfile')
    def dockerfile(self, request, pk=None):
        """
        PATCH /api/deployer/apps/<pk>/dockerfile/
        Upload (or clear) a Dockerfile on the student's behalf — for projects
        whose author has graduated or gone unresponsive. Takes precedence over
        both a zip-supplied Dockerfile and the runtime template on the next
        deploy; does not trigger a build by itself.
        """
        hosted_app = self._hosted_app(self._application())
        serializer = DockerfileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        hosted_app.admin_dockerfile_override = serializer.validated_data['dockerfile']
        hosted_app.save(update_fields=['admin_dockerfile_override', 'updated_at'])

        cleared = not hosted_app.admin_dockerfile_override.strip()
        return Response(
            {
                'message': 'Dockerfile override cleared.' if cleared
                else 'Dockerfile override saved. It will be used on the next deploy.',
                'hosted_app': HostedAppSerializer(hosted_app).data,
            }
        )


class RuntimeTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/deployer/runtime-templates/
    Read-only listing so the deploy drawer can offer a runtime override.
    Unpaginated: this is a short, fixed catalogue meant to populate a single
    dropdown, not a browsable collection.
    """

    queryset = RuntimeTemplate.objects.all().order_by('key')
    serializer_class = RuntimeTemplateSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    pagination_class = None
