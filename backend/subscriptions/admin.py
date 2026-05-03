"""Admin configuration for the subscriptions app."""

from django.contrib import admin
from django.utils.html import format_html

from .models import SubscriptionPlan, UserSubscription


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'price_display', 'duration_days', 'subscriber_count', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'description']
    ordering = ['price']
    readonly_fields = ['created_at', 'updated_at']

    def price_display(self, obj):
        return f'TZS {obj.price:,.2f}'
    price_display.short_description = 'Price'

    def subscriber_count(self, obj):
        return obj.subscriptions.filter(is_active=True).count()
    subscriber_count.short_description = 'Active Subscribers'


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ['user', 'plan', 'start_date', 'end_date', 'is_valid_display', 'is_active', 'auto_renew']
    list_filter = ['is_active', 'auto_renew', 'plan']
    search_fields = ['user__username', 'user__email', 'plan__name']
    ordering = ['-start_date']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['user']

    def is_valid_display(self, obj):
        if obj.is_valid:
            return format_html('<span style="color:green;">&#10003; Valid</span>')
        return format_html('<span style="color:red;">&#10007; Expired</span>')
    is_valid_display.short_description = 'Status'
