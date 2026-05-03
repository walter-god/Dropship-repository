"""Django admin configuration for the accounts app."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _

from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """
    Extended admin for CustomUser.  Adds the custom fields (role,
    is_verified, university_id, etc.) to the built-in UserAdmin.
    """

    list_display = (
        'username', 'email', 'first_name', 'last_name',
        'role', 'is_verified', 'is_active', 'date_joined',
    )
    list_filter = ('role', 'is_verified', 'is_active', 'is_staff', 'date_joined')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'university_id')
    ordering = ('-date_joined',)
    readonly_fields = ('date_joined', 'last_login')

    # Fields shown when *viewing / editing* an existing user
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {
            'fields': ('first_name', 'last_name', 'email', 'bio', 'profile_picture'),
        }),
        (_('Role & access'), {
            'fields': ('role', 'is_verified', 'university_id'),
        }),
        (_('Permissions'), {
            'fields': (
                'is_active', 'is_staff', 'is_superuser',
                'groups', 'user_permissions',
            ),
        }),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )

    # Fields shown when *creating* a new user via admin
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username', 'email', 'first_name', 'last_name',
                'password1', 'password2',
                'role', 'university_id', 'is_verified',
            ),
        }),
    )

    actions = ['verify_users', 'deactivate_users', 'activate_users']

    @admin.action(description='Mark selected users as verified')
    def verify_users(self, request, queryset):
        updated = queryset.update(is_verified=True)
        self.message_user(request, f'{updated} user(s) marked as verified.')

    @admin.action(description='Deactivate selected users')
    def deactivate_users(self, request, queryset):
        updated = queryset.exclude(pk=request.user.pk).update(is_active=False)
        self.message_user(request, f'{updated} user(s) deactivated.')

    @admin.action(description='Activate selected users')
    def activate_users(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} user(s) activated.')
