"""Views for the payments app."""

from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from marketplace.permissions import IsAdminUser

from .models import Payment
from .serializers import InitiatePaymentSerializer, PaymentSerializer, PaymentWebhookSerializer


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


class PaymentWebhookView(APIView):
    """
    POST /api/payments/webhook/
    Called by a payment gateway to update payment status.
    On completion, the linked subscription is activated.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PaymentWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            payment = Payment.objects.select_related('subscription').get(
                transaction_id=data['transaction_id']
            )
        except Payment.DoesNotExist:
            return Response({'error': 'Transaction not found.'}, status=status.HTTP_404_NOT_FOUND)

        new_status = data['status']
        payment.status = new_status
        if new_status == Payment.STATUS_COMPLETED:
            payment.completed_at = timezone.now()
            if payment.subscription:
                payment.subscription.is_active = True
                payment.subscription.save(update_fields=['is_active'])
        payment.save(update_fields=['status', 'completed_at'])

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
