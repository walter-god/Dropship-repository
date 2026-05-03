"""Serializers for the subscriptions app."""

from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from .models import SubscriptionPlan, UserSubscription


# ---------------------------------------------------------------------------
# Subscription Plan
# ---------------------------------------------------------------------------

class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """Public-facing plan serializer (read)."""

    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'name', 'description', 'price', 'duration_days',
            'features', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class SubscriptionPlanAdminSerializer(serializers.ModelSerializer):
    """Full plan serializer for admin create/update."""

    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'name', 'description', 'price', 'duration_days',
            'features', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_duration_days(self, value):
        if value < 1:
            raise serializers.ValidationError('Duration must be at least 1 day.')
        return value

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError('Price cannot be negative.')
        return value


# ---------------------------------------------------------------------------
# User Subscription
# ---------------------------------------------------------------------------

class SubscriptionPlanMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = ['id', 'name', 'price', 'duration_days']


class UserSubscriptionSerializer(serializers.ModelSerializer):
    """Serializer for listing / viewing a user's subscriptions."""

    plan = SubscriptionPlanMinimalSerializer(read_only=True)
    is_valid = serializers.BooleanField(read_only=True)
    days_remaining = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = UserSubscription
        fields = [
            'id', 'plan', 'start_date', 'end_date',
            'is_active', 'auto_renew', 'is_valid', 'days_remaining',
            'created_at',
        ]
        read_only_fields = [
            'id', 'start_date', 'end_date', 'is_valid', 'days_remaining', 'created_at',
        ]

    def get_days_remaining(self, obj) -> int:
        if not obj.is_valid:
            return 0
        delta = obj.end_date - timezone.now()
        return max(0, delta.days)


class SubscribeSerializer(serializers.Serializer):
    """
    Input serializer for POST /api/subscriptions/subscribe/.
    The caller provides a plan ID; the view creates the UserSubscription
    and a pending Payment record.
    """

    plan_id = serializers.IntegerField()
    auto_renew = serializers.BooleanField(default=False)
    payment_method = serializers.ChoiceField(
        choices=['card', 'mobile_money', 'bank_transfer'],
        default='mobile_money',
    )

    def validate_plan_id(self, value):
        try:
            plan = SubscriptionPlan.objects.get(pk=value, is_active=True)
        except SubscriptionPlan.DoesNotExist:
            raise serializers.ValidationError('Subscription plan not found or is inactive.')
        self.context['plan'] = plan
        return value
