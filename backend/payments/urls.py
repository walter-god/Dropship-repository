"""URL configuration for the payments app."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AdminPaymentStatsView, InitiatePaymentView, PaymentViewSet, PaymentWebhookView

router = DefaultRouter()
router.register(r'', PaymentViewSet, basename='payment')

urlpatterns = [
    path('initiate/', InitiatePaymentView.as_view(), name='payment-initiate'),
    path('webhook/', PaymentWebhookView.as_view(), name='payment-webhook'),
    path('stats/', AdminPaymentStatsView.as_view(), name='payment-stats'),
    path('', include(router.urls)),
]
