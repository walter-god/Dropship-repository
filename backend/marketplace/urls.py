"""URL configuration for the marketplace app."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ApplicationViewSet, CategoryViewSet, ReviewViewSet

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'apps', ApplicationViewSet, basename='application')
router.register(r'reviews', ReviewViewSet, basename='review')

urlpatterns = [
    path('', include(router.urls)),
]
