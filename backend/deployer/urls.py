"""URL configuration for the deployer admin API."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DeployerViewSet

router = DefaultRouter()
router.register(r'apps', DeployerViewSet, basename='deployer-app')

urlpatterns = [
    path('', include(router.urls)),
]
