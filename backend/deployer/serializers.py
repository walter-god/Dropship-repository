"""Serializers for the deployer admin API."""

from rest_framework import serializers

from gateway.models import AppSession, HostedApp

from .models import Deployment, RuntimeTemplate


class RuntimeTemplateSerializer(serializers.ModelSerializer):
    priority = serializers.IntegerField(read_only=True)

    class Meta:
        model = RuntimeTemplate
        fields = [
            'id', 'key', 'display_name', 'default_health_path', 'default_port',
            'migrate_command', 'needs_database', 'detection_hints', 'priority',
        ]
        read_only_fields = fields


class DeploymentSummarySerializer(serializers.ModelSerializer):
    """Build history — deliberately omits build_log, which can be megabytes."""

    triggered_by_username = serializers.CharField(
        source='triggered_by.username', read_only=True, default=None
    )
    duration_seconds = serializers.FloatField(read_only=True)

    class Meta:
        model = Deployment
        fields = [
            'id', 'status', 'image_tag', 'container_id', 'error_summary',
            'triggered_by_username', 'started_at', 'finished_at',
            'duration_seconds', 'created_at',
        ]
        read_only_fields = fields


class DeploymentDetailSerializer(DeploymentSummarySerializer):
    class Meta(DeploymentSummarySerializer.Meta):
        fields = DeploymentSummarySerializer.Meta.fields + ['build_log']
        read_only_fields = fields


class HostedAppSerializer(serializers.ModelSerializer):
    application_name = serializers.CharField(source='application.name', read_only=True)
    application_slug = serializers.CharField(source='application.slug', read_only=True)
    application_status = serializers.CharField(source='application.status', read_only=True)
    developer_username = serializers.CharField(
        source='application.developer.username', read_only=True
    )
    deployment_notes = serializers.CharField(
        source='application.deployment_notes', read_only=True
    )
    demo_credentials = serializers.CharField(
        source='application.demo_credentials', read_only=True
    )
    detected_runtime_key = serializers.CharField(
        source='application.detected_runtime_key', read_only=True
    )
    detection_confidence = serializers.CharField(
        source='application.detection_confidence', read_only=True
    )
    detection_reason = serializers.CharField(
        source='application.detection_reason', read_only=True
    )
    needs_dockerfile = serializers.BooleanField(
        source='application.needs_dockerfile', read_only=True
    )
    runtime_template = RuntimeTemplateSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    active_session_count = serializers.SerializerMethodField()
    has_admin_dockerfile_override = serializers.SerializerMethodField()
    last_deployment = serializers.SerializerMethodField()

    class Meta:
        model = HostedApp
        fields = [
            'id', 'application', 'application_name', 'application_slug',
            'application_status', 'developer_username', 'status', 'status_display',
            'internal_base_url', 'runtime_template', 'container_name', 'container_port',
            'network_name', 'needs_database', 'db_name', 'db_user', 'env_vars',
            'memory_limit_mb', 'cpu_limit', 'last_active_at', 'updated_at',
            'deployment_notes', 'demo_credentials', 'detected_runtime_key',
            'detection_confidence', 'detection_reason', 'needs_dockerfile',
            'has_admin_dockerfile_override', 'active_session_count', 'last_deployment',
        ]
        read_only_fields = [
            'id', 'application', 'status', 'internal_base_url', 'runtime_template',
            'container_name', 'network_name', 'db_name', 'db_user', 'last_active_at',
            'updated_at',
        ]

    def get_active_session_count(self, obj) -> int:
        return obj.sessions.filter(ended_at__isnull=True).count()

    def get_has_admin_dockerfile_override(self, obj) -> bool:
        return bool(obj.admin_dockerfile_override.strip())

    def get_last_deployment(self, obj):
        last = obj.deployments.order_by('-created_at').first()
        return DeploymentSummarySerializer(last).data if last else None


class DeployRequestSerializer(serializers.Serializer):
    """POST body for /deploy/ and /redeploy/ — every field optional.

    Lets the deploy drawer send a runtime override, the database checkbox,
    resource sliders, an env var set, and a port override in one call, so the
    admin only has to click a single Deploy button.
    """

    runtime_template_id = serializers.IntegerField(required=False, allow_null=True)
    provision_database = serializers.BooleanField(required=False, allow_null=True)
    memory_limit_mb = serializers.IntegerField(required=False, min_value=64, max_value=8192)
    cpu_limit = serializers.FloatField(required=False, min_value=0.1, max_value=8.0)
    env_vars = serializers.DictField(
        child=serializers.CharField(allow_blank=True), required=False
    )
    container_port = serializers.IntegerField(required=False, min_value=1025, max_value=65535)

    def validate_runtime_template_id(self, value):
        if value is None:
            return value
        if not RuntimeTemplate.objects.filter(pk=value).exists():
            raise serializers.ValidationError('No such runtime template.')
        return value

    def validate_env_vars(self, value):
        for key in value:
            if not key or not key.replace('_', '').isalnum():
                raise serializers.ValidationError(
                    f"'{key}' is not a valid environment variable name."
                )
        return value


class AppSessionSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = AppSession
        fields = [
            'id', 'username', 'started_at', 'last_seen_at', 'ended_at',
            'ip_address', 'is_active',
        ]
        read_only_fields = fields


class DockerfileUploadSerializer(serializers.Serializer):
    """PATCH payload for uploading a Dockerfile on a student's behalf."""

    dockerfile = serializers.CharField(
        allow_blank=True,
        help_text='Full Dockerfile text. An empty string clears the override.',
    )


class EnvVarsSerializer(serializers.Serializer):
    """PATCH payload for editing environment variables."""

    env_vars = serializers.DictField(child=serializers.CharField(allow_blank=True))
    redeploy = serializers.BooleanField(
        default=False,
        help_text='Rebuild immediately so the new values take effect.',
    )
    memory_limit_mb = serializers.IntegerField(required=False, min_value=64, max_value=8192)
    cpu_limit = serializers.FloatField(required=False, min_value=0.1, max_value=8.0)

    def validate_env_vars(self, value):
        for key in value:
            if not key or not key.replace('_', '').isalnum():
                raise serializers.ValidationError(
                    f"'{key}' is not a valid environment variable name."
                )
        return value


class LogsSerializer(serializers.Serializer):
    """Response shape for the logs endpoint."""

    hosted_app_status = serializers.CharField()
    deployment = DeploymentSummarySerializer(allow_null=True)
    build_log = serializers.CharField(allow_blank=True)
    container_logs = serializers.CharField(allow_blank=True)
