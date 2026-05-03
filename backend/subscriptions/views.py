"""Views for the subscriptions app."""

import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from marketplace.permissions import IsAdminUser

from .models import SubscriptionPlan, UserSubscription
from .serializers import (
    SubscribeSerializer,
    SubscriptionPlanAdminSerializer,
    SubscriptionPlanSerializer,
    UserSubscriptionSerializer,
)


# ---------------------------------------------------------------------------
# Subscription Plans
# ---------------------------------------------------------------------------

class SubscriptionPlanViewSet(viewsets.ModelViewSet):
    """
    GET    /api/subscriptions/plans/         — list active plans (public)
    GET    /api/subscriptions/plans/{id}/    — retrieve single plan (public)
    POST   /api/subscriptions/plans/         — create plan (admin only)
    PUT    /api/subscriptions/plans/{id}/    — update plan (admin only)
    PATCH  /api/subscriptions/plans/{id}/    — partial update (admin only)
    DELETE /api/subscriptions/plans/{id}/    — delete plan (admin only)
    """

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['price', 'duration_days', 'name']
    ordering = ['price']

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and (user.is_admin or user.is_staff):
            return SubscriptionPlan.objects.all()
        return SubscriptionPlan.objects.filter(is_active=True)

    def get_serializer_class(self):
        user = self.request.user
        if user.is_authenticated and (user.is_admin or user.is_staff):
            return SubscriptionPlanAdminSerializer
        return SubscriptionPlanSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            from rest_framework.permissions import AllowAny
            return [AllowAny()]
        return [IsAuthenticated(), IsAdminUser()]


# ---------------------------------------------------------------------------
# User Subscriptions
# ---------------------------------------------------------------------------

class UserSubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/subscriptions/my-subscriptions/         — list own subscriptions
    GET /api/subscriptions/my-subscriptions/{id}/    — retrieve single subscription
    """

    serializer_class = UserSubscriptionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['start_date', 'end_date', 'is_active']
    ordering = ['-start_date']

    def get_queryset(self):
        user = self.request.user
        if user.is_admin or user.is_staff:
            # Admins can query any user's subscriptions via ?user=<id>
            qs = UserSubscription.objects.select_related('user', 'plan')
            user_id = self.request.query_params.get('user')
            if user_id:
                qs = qs.filter(user__id=user_id)
            return qs
        return UserSubscription.objects.filter(user=user).select_related('plan')


# ---------------------------------------------------------------------------
# Subscribe
# ---------------------------------------------------------------------------

class SubscribeView(APIView):
    """
    POST /api/subscriptions/subscribe/

    Creates a UserSubscription and an associated pending Payment.
    The caller receives the subscription details and a payment initiation
    reference to complete the transaction.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SubscribeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        plan: SubscriptionPlan = serializer.context['plan']
        user = request.user

        with transaction.atomic():
            # Deactivate any currently active subscriptions so there is
            # only one active subscription per user at a time.
            UserSubscription.objects.filter(user=user, is_active=True).update(is_active=False)

            now = timezone.now()
            subscription = UserSubscription.objects.create(
                user=user,
                plan=plan,
                start_date=now,
                end_date=now + timedelta(days=plan.duration_days),
                is_active=False,   # activated after payment succeeds
                auto_renew=data.get('auto_renew', False),
            )

            # Create a pending payment record (import here to avoid circular import)
            from payments.models import Payment
            transaction_id = f'TXN-{uuid.uuid4().hex[:16].upper()}'
            payment = Payment.objects.create(
                user=user,
                subscription=subscription,
                amount=plan.price,
                currency='TZS',
                status=Payment.STATUS_PENDING,
                transaction_id=transaction_id,
                payment_method=data.get('payment_method', 'mobile_money'),
                metadata={
                    'plan_name': plan.name,
                    'duration_days': plan.duration_days,
                },
            )

        return Response(
            {
                'message': 'Subscription initiated. Complete the payment to activate.',
                'subscription': UserSubscriptionSerializer(subscription).data,
                'payment': {
                    'transaction_id': payment.transaction_id,
                    'amount': str(payment.amount),
                    'currency': payment.currency,
                    'payment_method': payment.payment_method,
                    'status': payment.status,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class CancelSubscriptionView(APIView):
    """
    POST /api/subscriptions/cancel/{id}/
    Cancel an active subscription.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            subscription = UserSubscription.objects.get(pk=pk)
        except UserSubscription.DoesNotExist:
            return Response({'error': 'Subscription not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Only the owner or an admin may cancel
        if subscription.user != request.user and not request.user.is_admin:
            return Response(
                {'error': 'You do not have permission to cancel this subscription.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not subscription.is_active:
            return Response({'error': 'This subscription is already inactive.'}, status=status.HTTP_400_BAD_REQUEST)

        subscription.cancel()
        return Response(
            {
                'message': 'Subscription cancelled successfully.',
                'subscription': UserSubscriptionSerializer(subscription).data,
            }
        )
