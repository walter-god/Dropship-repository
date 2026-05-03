"""Admin configuration for the payments app."""

from django.contrib import admin
from django.utils.html import format_html

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        'transaction_id', 'user', 'amount_display', 'payment_method',
        'status_badge', 'created_at', 'completed_at',
    ]
    list_filter = ['status', 'payment_method', 'currency']
    search_fields = ['transaction_id', 'user__username', 'user__email']
    ordering = ['-created_at']
    readonly_fields = ['transaction_id', 'created_at', 'completed_at']
    raw_id_fields = ['user', 'subscription']

    STATUS_COLORS = {
        'pending': '#ff9800',
        'completed': '#00c853',
        'failed': '#f44336',
        'refunded': '#2196f3',
    }

    def amount_display(self, obj):
        return f'{obj.currency} {obj.amount:,.2f}'
    amount_display.short_description = 'Amount'

    def status_badge(self, obj):
        color = self.STATUS_COLORS.get(obj.status, '#888')
        return format_html(
            '<span style="color:{};font-weight:bold;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = 'Status'
