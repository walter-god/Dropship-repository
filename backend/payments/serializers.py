"""Serializers for the payments app."""

from rest_framework import serializers

from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    method_display = serializers.CharField(source='get_payment_method_display', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'id', 'username', 'subscription', 'amount', 'currency',
            'status', 'status_display', 'transaction_id',
            'payment_method', 'method_display', 'metadata',
            'created_at', 'completed_at',
        ]
        read_only_fields = [
            'id', 'username', 'status_display', 'method_display',
            'created_at', 'completed_at',
        ]


class InitiatePaymentSerializer(serializers.Serializer):
    subscription_id = serializers.IntegerField()
    payment_method = serializers.ChoiceField(
        choices=['card', 'mobile_money', 'bank_transfer'],
        default='mobile_money',
    )
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)

    def validate_subscription_id(self, value):
        from subscriptions.models import UserSubscription
        request = self.context.get('request')
        try:
            sub = UserSubscription.objects.get(pk=value, user=request.user)
        except UserSubscription.DoesNotExist:
            raise serializers.ValidationError('Subscription not found.')
        self.context['subscription'] = sub
        return value


class PaymentWebhookSerializer(serializers.Serializer):
    transaction_id = serializers.CharField()
    status = serializers.ChoiceField(choices=['completed', 'failed', 'refunded'])
    gateway_reference = serializers.CharField(required=False, allow_blank=True)
