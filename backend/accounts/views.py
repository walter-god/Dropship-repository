"""Views for the accounts app."""

from django.contrib.auth import logout
from rest_framework import status, viewsets, filters
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView  # re-exported
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from .models import CustomUser
from .serializers import (
    AdminUserSerializer,
    ChangePasswordSerializer,
    UserLoginSerializer,
    UserProfileSerializer,
    UserRegistrationSerializer,
)
from marketplace.permissions import IsAdminUser


class RegisterView(APIView):
    """
    POST /api/auth/register/
    Create a new user account. Returns JWT tokens on success.
    """

    permission_classes = [AllowAny]
    # Unauthenticated and account-creating: needs a tighter bucket than the
    # global 100/hour anon default.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'register'

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'message': 'Account created successfully.',
                'user': UserProfileSerializer(user).data,
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                },
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    """
    POST /api/auth/login/
    Authenticate user and return JWT access + refresh tokens.
    """

    permission_classes = [AllowAny]
    # Credential-guessing surface: the global anon bucket allows 100 attempts
    # an hour, which is far too generous for a login endpoint.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        serializer = UserLoginSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(
            {
                'message': 'Login successful.',
                'user': UserProfileSerializer(data['user']).data,
                'tokens': {
                    'access': data['access'],
                    'refresh': data['refresh'],
                },
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """
    POST /api/auth/logout/
    Blacklist the supplied refresh token, effectively logging the user out.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'error': 'Refresh token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except (TokenError, InvalidToken) as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        logout(request)
        return Response({'message': 'Logged out successfully.'}, status=status.HTTP_200_OK)


class UserProfileView(APIView):
    """
    GET  /api/auth/profile/  — retrieve current user's profile
    PUT  /api/auth/profile/  — update current user's profile (full)
    PATCH /api/auth/profile/ — partial update
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

    def put(self, request):
        serializer = UserProfileSerializer(
            request.user, data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserProfileSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ChangePasswordView(APIView):
    """
    POST /api/auth/change-password/
    Change the authenticated user's password.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {'message': 'Password changed successfully. Please log in again.'},
            status=status.HTTP_200_OK,
        )


class UserManagementViewSet(viewsets.ModelViewSet):
    """
    Admin-only CRUD for all user accounts.
    /api/auth/users/
    """

    queryset = CustomUser.objects.all().order_by('-date_joined')
    serializer_class = AdminUserSerializer
    permission_classes = [IsAuthenticated, IsAdminUser]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['username', 'email', 'first_name', 'last_name', 'university_id']
    ordering_fields = ['date_joined', 'username', 'role']
    ordering = ['-date_joined']

    def get_queryset(self):
        queryset = super().get_queryset()
        role = self.request.query_params.get('role')
        is_active = self.request.query_params.get('is_active')
        is_verified = self.request.query_params.get('is_verified')

        if role:
            queryset = queryset.filter(role=role)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        if is_verified is not None:
            queryset = queryset.filter(is_verified=is_verified.lower() == 'true')

        return queryset

    @action(detail=True, methods=['post'], url_path='verify')
    def verify_user(self, request, pk=None):
        """Mark a user account as verified."""
        user = self.get_object()
        user.is_verified = True
        user.save(update_fields=['is_verified'])
        return Response({'message': f'User {user.username} has been verified.'})

    @action(detail=True, methods=['post'], url_path='deactivate')
    def deactivate_user(self, request, pk=None):
        """Deactivate a user account."""
        user = self.get_object()
        if user == request.user:
            return Response(
                {'error': 'You cannot deactivate your own account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.is_active = False
        user.save(update_fields=['is_active'])
        return Response({'message': f'User {user.username} has been deactivated.'})

    @action(detail=True, methods=['post'], url_path='activate')
    def activate_user(self, request, pk=None):
        """Reactivate a previously deactivated user account."""
        user = self.get_object()
        user.is_active = True
        user.save(update_fields=['is_active'])
        return Response({'message': f'User {user.username} has been activated.'})


# Re-export simplejwt's TokenRefreshView so it can be wired in urls.py
__all__ = [
    'RegisterView',
    'LoginView',
    'LogoutView',
    'UserProfileView',
    'ChangePasswordView',
    'UserManagementViewSet',
    'TokenRefreshView',
]
