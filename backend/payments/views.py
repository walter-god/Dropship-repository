"""Views for the payments app."""

import hashlib
import hmac
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from marketplace.permissions import IsAdminUser

from .models import Payment
from .serializers import InitiatePaymentSerializer, PaymentSerializer, PaymentWebhookSerializer

logger = logging.getLogger(__name__)


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/payments/          — list payments (own; admin sees all)
    GET /api/payments/{id}/     — retrieve single payment
    """

    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['created_at', 'amount', 'status']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        qs = Payment.objects.select_related('user', 'subscription')
        if user.is_admin or user.is_staff:
            uid = self.request.query_params.get('user')
            if uid:
                qs = qs.filter(user__id=uid)
            status_filter = self.request.query_params.get('status')
            if status_filter:
                qs = qs.filter(status=status_filter)
            return qs
        return qs.filter(user=user)


class InitiatePaymentView(APIView):
    """
    POST /api/payments/initiate/
    Create (or retrieve existing pending) payment for a subscription.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InitiatePaymentSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        subscription = serializer.context['subscription']
        payment_method = serializer.validated_data['payment_method']

        # Reuse any existing pending payment for this subscription
        existing = Payment.objects.filter(
            subscription=subscription,
            status=Payment.STATUS_PENDING,
        ).first()

        if existing:
            return Response(PaymentSerializer(existing).data, status=status.HTTP_200_OK)

        import uuid
        payment = Payment.objects.create(
            user=request.user,
            subscription=subscription,
            amount=subscription.plan.price,
            currency='TZS',
            status=Payment.STATUS_PENDING,
            transaction_id=f'TXN-{uuid.uuid4().hex[:16].upper()}',
            payment_method=payment_method,
            metadata={
                'plan_name': subscription.plan.name,
                'phone_number': serializer.validated_data.get('phone_number', ''),
            },
        )
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


SIGNATURE_HEADER = 'HTTP_X_UDOM_SIGNATURE'


class PaymentWebhookView(APIView):
    """
    POST /api/payments/webhook/
    Called by a payment gateway to update payment status.
    On completion, the linked subscription is activated.

    This endpoint is necessarily unauthenticated — a payment provider has no
    session — so the signature IS the authentication. Every request must carry
    X-UDOM-Signature: sha256=<hex>, an HMAC-SHA256 of the exact raw request
    body keyed with PAYMENTS_WEBHOOK_SECRET.

    Without that check this endpoint grants free subscriptions to anyone who
    knows a transaction_id, and transaction_ids are handed back to the user who
    initiated the payment. It is also reachable from every student container,
    which shares a Docker network with this backend.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payment_webhook'

    @staticmethod
    def _signature_valid(raw_body: bytes, provided: str) -> bool:
        secret = getattr(settings, 'PAYMENTS_WEBHOOK_SECRET', '') or ''
        if not secret:
            # Fail closed. An unset secret means the deployment has not been
            # configured for webhooks, not that anyone may call this.
            logger.error(
                'PAYMENTS_WEBHOOK_SECRET is not set — rejecting webhook. '
                'Set it to the shared secret issued by the payment provider.'
            )
            return False
        if not provided:
            return False

        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        candidate = provided.strip()
        if candidate.startswith('sha256='):
            candidate = candidate[len('sha256='):]
        # Constant-time: a naive == leaks the correct prefix byte by byte.
        return hmac.compare_digest(expected, candidate)

    def post(self, request):
        # Read the raw body BEFORE request.data, which consumes the stream.
        raw_body = request.body

        if not self._signature_valid(raw_body, request.META.get(SIGNATURE_HEADER, '')):
            logger.warning('Rejected payment webhook with a bad or missing signature.')
            return Response(
                {'error': 'Invalid signature.'}, status=status.HTTP_401_UNAUTHORIZED
            )

        serializer = PaymentWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        new_status = data['status']

        with transaction.atomic():
            try:
                payment = (
                    Payment.objects.select_for_update()
                    .select_related('subscription')
                    .get(transaction_id=data['transaction_id'])
                )
            except Payment.DoesNotExist:
                return Response(
                    {'error': 'Transaction not found.'}, status=status.HTTP_404_NOT_FOUND
                )

            # Idempotency / replay guard: a captured-and-replayed webhook must
            # not be able to re-activate a subscription that was since revoked.
            if payment.status == new_status:
                return Response(
                    {'message': f'Payment {payment.transaction_id} already {new_status}.'}
                )
            if payment.status == Payment.STATUS_REFUNDED:
                return Response(
                    {'error': 'Refunded payments cannot change status.'},
                    status=status.HTTP_409_CONFLICT,
                )

            payment.status = new_status
            if new_status == Payment.STATUS_COMPLETED:
                payment.completed_at = timezone.now()
                if payment.subscription:
                    payment.subscription.is_active = True
                    payment.subscription.save(update_fields=['is_active'])
            payment.save(update_fields=['status', 'completed_at'])

        logger.info('Payment %s updated to %s via webhook.', payment.transaction_id, new_status)
        return Response({'message': f'Payment {payment.transaction_id} updated to {new_status}.'})


class AdminPaymentStatsView(APIView):
    """
    GET /api/payments/stats/
    Summary statistics for the admin dashboard.
    """

    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request):
        from django.db.models import Sum, Count
        stats = Payment.objects.aggregate(
            total_payments=Count('id'),
            completed_payments=Count('id', filter=__import__('django.db.models', fromlist=['Q']).Q(status=Payment.STATUS_COMPLETED)),
            total_revenue=Sum('amount', filter=__import__('django.db.models', fromlist=['Q']).Q(status=Payment.STATUS_COMPLETED)),
        )
        return Response({
            'total_payments': stats['total_payments'],
            'completed_payments': stats['completed_payments'],
            'total_revenue': str(stats['total_revenue'] or 0),
            'currency': 'TZS',
        })
