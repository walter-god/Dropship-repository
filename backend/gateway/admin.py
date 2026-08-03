from django.contrib import admin
from django.utils.html import format_html

from .models import AllowedHostname, AppSession, HostedApp

STATUS_COLORS = {
    'not_deployed': '#6b6b80',
    'queued': '#2196f3',
    'building': '#ff9800',
    'starting': '#ff9800',
    'live': '#00c853',
    'paused': '#9c27b0',
    'stopped': '#6b6b80',
    'failed': '#f44336',
}


@admin.register(HostedApp)
class HostedAppAdmin(admin.ModelAdmin):
    list_display = (
        'application', 'status_badge', 'container_name', 'container_port',
        'runtime_template', 'needs_database', 'egress_badge', 'last_active_at',
    )
    list_filter = ('status', 'needs_database', 'allow_egress', 'runtime_template')
    search_fields = ('application__name', 'container_name', 'db_name')
    readonly_fields = (
        'container_id', 'container_name', 'network_name',
        'internal_base_url', 'created_at', 'updated_at',
    )
    raw_id_fields = ('application',)

    @admin.display(description='Status', ordering='status')
    def status_badge(self, obj):
        return format_html(
            '<span style="color:{};font-weight:bold;">&#9679; {}</span>',
            STATUS_COLORS.get(obj.status, '#888'),
            obj.get_status_display(),
        )

    @admin.display(description='Egress', ordering='allow_egress', boolean=False)
    def egress_badge(self, obj):
        """Surfaced in the list because granting egress is a security decision."""
        if obj.allow_egress:
            return format_html('<span style="color:#f44336;font-weight:bold;">⚠ ALLOWED</span>')
        return format_html('<span style="color:#00c853;">blocked</span>')


@admin.register(AppSession)
class AppSessionAdmin(admin.ModelAdmin):
    list_display = ('hosted_app', 'user', 'started_at', 'last_seen_at', 'ended_at')
    list_filter = ('started_at', 'last_seen_at')
    search_fields = ('hosted_app__application__name', 'user__username')
    raw_id_fields = ('hosted_app', 'user')
    readonly_fields = ('started_at',)


@admin.register(AllowedHostname)
class AllowedHostnameAdmin(admin.ModelAdmin):
    list_display = ('hostname', 'hosted_app', 'created_at')
    search_fields = ('hostname',)
    raw_id_fields = ('hosted_app',)
    readonly_fields = ('created_at',)
