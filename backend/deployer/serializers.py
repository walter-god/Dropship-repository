"""Serializers for the deployer admin API."""

from rest_framework import serializers

from gateway.models import HostedApp

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
    runtime_template = RuntimeTemplateSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = HostedApp
        fields = [
            'id', 'application', 'application_name', 'application_slug',
            'application_status', 'status', 'status_display', 'internal_base_url',
            'runtime_template', 'container_name', 'container_port', 'network_name',
            'needs_database', 'db_name', 'db_user', 'env_vars',
            'memory_limit_mb', 'cpu_limit', 'last_active_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'application', 'status', 'internal_base_url', 'runtime_template',
            'container_name', 'network_name', 'db_name', 'db_user', 'last_active_at',
            'updated_at',
        ]


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
