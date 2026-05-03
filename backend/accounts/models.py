"""Custom user model for UDOM Digital Marketplace."""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class CustomUser(AbstractUser):
    """
    Extended user model with role-based access control.

    Roles:
        admin    — full platform access, manages marketplace
        internal — campus users (students/staff), free access to all apps
        external — off-campus users, must subscribe and pay for premium content
    """

    ROLE_ADMIN = 'admin'
    ROLE_INTERNAL = 'internal'
    ROLE_EXTERNAL = 'external'

    ROLE_CHOICES = [
        (ROLE_ADMIN, _('Admin')),
        (ROLE_INTERNAL, _('Internal')),
        (ROLE_EXTERNAL, _('External')),
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_EXTERNAL,
        db_index=True,
    )
    is_verified = models.BooleanField(
        default=False,
        help_text=_('Designates whether the user has verified their email address.'),
    )
    university_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        unique=True,
        help_text=_('University ID number — required for internal (campus) users.'),
    )
    profile_picture = models.ImageField(
        upload_to='profiles/',
        blank=True,
        null=True,
    )
    bio = models.TextField(
        blank=True,
        default='',
        help_text=_('Short biography shown on user profile.'),
    )

    class Meta:
        verbose_name = _('User')
        verbose_name_plural = _('Users')
        ordering = ['-date_joined']

    def __str__(self):
        return f'{self.username} ({self.get_role_display()})'

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_admin(self) -> bool:
        return self.role == self.ROLE_ADMIN or self.is_staff or self.is_superuser

    @property
    def is_internal(self) -> bool:
        return self.role == self.ROLE_INTERNAL

    @property
    def is_external(self) -> bool:
        return self.role == self.ROLE_EXTERNAL

    def has_active_subscription(self) -> bool:
        """Return True if user currently holds a valid subscription."""
        return self.subscriptions.filter(is_active=True).exists() and any(
            sub.is_valid for sub in self.subscriptions.filter(is_active=True)
        )
