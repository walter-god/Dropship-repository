"""Models for the subscriptions app."""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class SubscriptionPlan(models.Model):
    """
    A reusable subscription plan that users may subscribe to.

    Plans are created and managed by administrators.  External users
    must hold at least one active UserSubscription tied to a plan in
    order to access premium marketplace content.
    """

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True, default='')
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text=_('Price in TZS.'),
    )
    duration_days = models.PositiveIntegerField(
        help_text=_('Subscription validity period in days.'),
    )
    features = models.JSONField(
        default=list,
        blank=True,
        help_text=_('List of feature strings shown to users, e.g. ["Unlimited downloads"].'),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_('Inactive plans are hidden from public listings and cannot be subscribed to.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Subscription Plan')
        verbose_name_plural = _('Subscription Plans')
        ordering = ['price']

    def __str__(self):
        return f'{self.name} ({self.duration_days}d @ TZS {self.price})'


class UserSubscription(models.Model):
    """
    Tracks a single user's subscription to a SubscriptionPlan.

    A user may have multiple historical subscriptions but should only
    have one *active* subscription at a time.  is_valid checks that
    the subscription has not expired.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions',
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name='subscriptions',
    )
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True, db_index=True)
    auto_renew = models.BooleanField(
        default=False,
        help_text=_('Whether the subscription should automatically renew on expiry.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('User Subscription')
        verbose_name_plural = _('User Subscriptions')
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        status = 'active' if self.is_valid else 'expired'
        return f'{self.user.username} — {self.plan.name} ({status})'

    @property
    def is_valid(self) -> bool:
        """Returns True when the subscription is both active and not yet expired."""
        return self.is_active and timezone.now() <= self.end_date

    def cancel(self):
        """Deactivate the subscription immediately."""
        self.is_active = False
        self.auto_renew = False
        self.save(update_fields=['is_active', 'auto_renew', 'updated_at'])

    def renew(self):
        """Extend the subscription by one plan period from the current end_date."""
        from datetime import timedelta
        self.end_date = self.end_date + timedelta(days=self.plan.duration_days)
        self.is_active = True
        self.save(update_fields=['end_date', 'is_active', 'updated_at'])
