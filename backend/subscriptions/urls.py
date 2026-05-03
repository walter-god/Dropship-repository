"""URL configuration for the subscriptions app."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CancelSubscriptionView, SubscribeView, SubscriptionPlanViewSet, UserSubscriptionViewSet

router = DefaultRouter()
router.register(r'plans', SubscriptionPlanViewSet, basename='subscription-plan')
router.register(r'my-subscriptions', UserSubscriptionViewSet, basename='user-subscription')

urlpatterns = [
    path('subscribe/', SubscribeView.as_view(), name='subscribe'),
    path('cancel/<int:pk>/', CancelSubscriptionView.as_view(), name='cancel-subscription'),
    path('', include(router.urls)),
]
