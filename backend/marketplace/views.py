"""Views for the UDOM Digital Marketplace."""

from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView

from .filters import ApplicationFilter
from .models import Application, AppVersion, Category, Download, Review
from .permissions import HasActiveSubscription, IsAdminUser, IsInternalOrAdmin, IsOwnerOrAdmin
from .serializers import (
    ApplicationCreateSerializer,
    ApplicationDetailSerializer,
    ApplicationListSerializer,
    AppVersionSerializer,
    CategorySerializer,
    DownloadSerializer,
    ReviewSerializer,
)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/marketplace/categories/
    GET /api/marketplace/categories/{id}/
    """

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [AllowAny]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['order', 'name']
    ordering = ['order']


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

class ApplicationViewSet(viewsets.ModelViewSet):
    """
    Full CRUD + custom actions for marketplace applications.

    Listing & retrieval are public.  Creating / updating requires
    authentication (internal users or admins).  Download requires
    either internal/admin access, or an active subscription.
    """

    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    search_fields = ['name', 'short_description', 'description', 'tags', 'developer__username']
    ordering_fields = ['name', 'created_at', 'downloads_count', 'views_count', 'price', 'rating']
    ordering = ['-created_at']

    # Override get_queryset to apply ApplicationFilter manually (avoids DRF
    # DjangoFilterBackend needing to be in DEFAULT_FILTER_BACKENDS globally).
    filterset_class = ApplicationFilter

    def get_filterset_class(self):
        return ApplicationFilter

    def get_queryset(self):
        user = self.request.user
        # Base queryset — only show approved, active apps to the public
        qs = Application.objects.select_related('developer', 'category').prefetch_related(
            'screenshots', 'reviews', 'versions'
        )
        if user.is_authenticated and (user.is_admin or user.is_staff):
            # Admins see everything
            return qs.all()
        if user.is_authenticated and user.is_internal:
            # Internal users see approved + their own pending/rejected
            return qs.filter(
                status__in=Application.PUBLIC_STATUSES, is_active=True
            ) | qs.filter(developer=user)
        # Public / external: only approved active apps
        return qs.filter(status__in=Application.PUBLIC_STATUSES, is_active=True)

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return ApplicationCreateSerializer
        if self.action == 'retrieve':
            return ApplicationDetailSerializer
        return ApplicationListSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve', 'featured'):
            return [AllowAny()]
        if self.action == 'download':
            return [IsAuthenticated(), HasActiveSubscription()]
        if self.action in ('create',):
            return [IsAuthenticated(), IsInternalOrAdmin()]
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), IsOwnerOrAdmin()]
        if self.action in ('approve', 'reject', 'my_apps'):
            return [IsAuthenticated()]
        return [IsAuthenticated()]

    def retrieve(self, request, *args, **kwargs):
        """Increment view counter on each retrieval."""
        instance = self.get_object()
        Application.objects.filter(pk=instance.pk).update(views_count=instance.views_count + 1)
        instance.refresh_from_db(fields=['views_count'])
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # Custom actions
    # ------------------------------------------------------------------

    @action(detail=False, methods=['get'], url_path='featured')
    def featured(self, request):
        """GET /api/marketplace/apps/featured/ — list featured applications."""
        qs = self.get_queryset().filter(is_featured=True)
        # Allow filter/search/ordering to run
        qs = self.filter_queryset(qs)
        page = self.paginate_queryset(qs)
        serializer = ApplicationListSerializer(
            page if page is not None else qs,
            many=True,
            context={'request': request},
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='my-apps', permission_classes=[IsAuthenticated])
    def my_apps(self, request):
        """GET /api/marketplace/apps/my-apps/ — apps submitted by the current user."""
        qs = Application.objects.filter(developer=request.user).order_by('-created_at')
        qs = self.filter_queryset(qs)
        page = self.paginate_queryset(qs)
        serializer = ApplicationListSerializer(
            page if page is not None else qs,
            many=True,
            context={'request': request},
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(
        detail=False, methods=['post'], url_path='detect-stack',
        permission_classes=[IsAuthenticated],
    )
    def detect_stack(self, request):
        """
        POST /api/marketplace/apps/detect-stack/
        Stateless stack detection for the upload flow: takes a `source_code`
        zip in the request body and returns the detection result without
        creating or touching any Application row. Lets a student see
        "Detected: Django" before they've even picked a name for the project.
        """
        upload = request.FILES.get('source_code')
        if not upload:
            return Response(
                {'error': "A 'source_code' zip file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from deployer.detection import detect_from_archive
        return Response(detect_from_archive(upload))

    @action(detail=True, methods=['post'], url_path='download')
    def download(self, request, pk=None):
        """
        POST /api/marketplace/apps/{id}/download/
        Record a download and return the file URL.
        Permission: internal/admin users always pass; external users need a subscription.
        """
        app = self.get_object()
        if app.status not in Application.PUBLIC_STATUSES or not app.is_active:
            return Response(
                {'error': 'This application is not available for download.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # External users with no subscription blocked by HasActiveSubscription permission,
        # but double-check for paid apps even if they somehow pass.
        user = request.user
        if user.is_external and not app.is_free and not user.has_active_subscription():
            return Response(
                {'error': 'A subscription is required to download paid applications.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        ip = self._get_client_ip(request)
        with transaction.atomic():
            Download.objects.create(app=app, user=user, ip_address=ip)
            Application.objects.filter(pk=app.pk).update(
                downloads_count=app.downloads_count + 1
            )

        # Return the download URL
        file_url = request.build_absolute_uri(app.app_file.url) if app.app_file else None
        return Response(
            {
                'message': 'Download recorded successfully.',
                'app': app.name,
                'version': app.version,
                'download_url': file_url,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True, methods=['post'], url_path='approve',
        permission_classes=[IsAuthenticated, IsAdminUser],
    )
    def approve(self, request, pk=None):
        """POST /api/marketplace/apps/{id}/approve/ — admin approves an app."""
        app = self.get_object()
        app.status = Application.STATUS_APPROVED
        app.save(update_fields=['status'])
        return Response({'message': f'"{app.name}" has been approved.'})

    @action(
        detail=True, methods=['post'], url_path='reject',
        permission_classes=[IsAuthenticated, IsAdminUser],
    )
    def reject(self, request, pk=None):
        """POST /api/marketplace/apps/{id}/reject/ — admin rejects an app."""
        app = self.get_object()
        reason = request.data.get('reason', '')
        app.status = Application.STATUS_REJECTED
        app.save(update_fields=['status'])
        return Response({
            'message': f'"{app.name}" has been rejected.',
            'reason': reason,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_client_ip(request) -> str:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

class ReviewViewSet(viewsets.ModelViewSet):
    """
    CRUD for application reviews.

    list   — public
    create — authenticated users (one review per user per app)
    update / destroy — owner or admin
    """

    serializer_class = ReviewSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['created_at', 'rating']
    ordering = ['-created_at']

    def get_queryset(self):
        qs = Review.objects.select_related('user', 'app')
        app_pk = self.kwargs.get('app_pk')
        if app_pk:
            qs = qs.filter(app__pk=app_pk)
        return qs

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsAuthenticated(), IsOwnerOrAdmin()]
        return [IsAuthenticated()]
