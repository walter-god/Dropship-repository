"""Custom DRF permission classes for the marketplace app."""

from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsAdminUser(BasePermission):
    """
    Grants access only to users whose role is 'admin' or who have
    Django staff / superuser status.
    """

    message = 'You do not have administrator privileges.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_admin or request.user.is_staff or request.user.is_superuser)
        )


class IsInternalOrAdmin(BasePermission):
    """
    Read-write access for internal campus users and admins.
    External users get read-only access.
    """

    message = 'Only internal campus users or administrators may perform this action.'

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_admin or request.user.is_internal


class IsOwnerOrAdmin(BasePermission):
    """
    Object-level permission: the requesting user must be the owner of
    the object or an administrator.
    """

    message = 'You do not have permission to modify this resource.'

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_admin or request.user.is_staff or request.user.is_superuser:
            return True
        # Support objects with a 'developer' FK (Application) or 'user' FK (Review, Download)
        if hasattr(obj, 'developer'):
            return obj.developer == request.user
        if hasattr(obj, 'user'):
            return obj.user == request.user
        return False


class HasActiveSubscription(BasePermission):
    """
    Grants access when the requesting user has an active subscription.

    Admin and internal users are always allowed (they have inherent
    access to all content). External users must hold a valid subscription.
    """

    message = 'An active subscription is required to access this content.'

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        # Admins and internal users pass unconditionally
        if request.user.is_admin or request.user.is_internal:
            return True
        # External users need a valid subscription
        return request.user.has_active_subscription()
