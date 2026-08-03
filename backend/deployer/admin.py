from django.contrib import admin
from django.utils.html import format_html

from .models import Deployment, RuntimeTemplate

STATUS_COLORS = {
    'queued': '#2196f3',
    'building': '#ff9800',
    'starting': '#ff9800',
    'live': '#00c853',
    'failed': '#f44336',
}


@admin.register(RuntimeTemplate)
class RuntimeTemplateAdmin(admin.ModelAdmin):
    list_display = (
        'key', 'display_name', 'default_port', 'default_health_path',
        'needs_database', 'priority',
    )
    list_filter = ('needs_database',)
    search_fields = ('key', 'display_name')
    readonly_fields = ('created_at', 'updated_at')

    @admin.display(description='Detection priority')
    def priority(self, obj):
        return obj.priority


@admin.register(Deployment)
class DeploymentAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'hosted_app', 'status_badge', 'image_tag',
        'triggered_by', 'started_at', 'finished_at', 'duration',
    )
    list_filter = ('status', 'created_at')
    search_fields = (
        'hosted_app__application__name', 'image_tag', 'container_id', 'error_summary',
    )
    raw_id_fields = ('hosted_app', 'triggered_by')
    readonly_fields = (
        'hosted_app', 'status', 'image_tag', 'container_id', 'error_summary',
        'build_log', 'triggered_by', 'started_at', 'finished_at', 'created_at',
    )

    @admin.display(description='Status', ordering='status')
    def status_badge(self, obj):
        return format_html(
            '<span style="color:{};font-weight:bold;">&#9679; {}</span>',
            STATUS_COLORS.get(obj.status, '#888'),
            obj.get_status_display(),
        )

    @admin.display(description='Duration')
    def duration(self, obj):
        seconds = obj.duration_seconds
        return f'{seconds:.0f}s' if seconds is not None else '—'

    def has_add_permission(self, request):
        # Deployments are created by the pipeline, never by hand.
        return False
