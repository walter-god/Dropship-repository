"""Models for the payments app."""

import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Payment(models.Model):
    """Records a financial transaction for a subscription purchase."""

    STATUS_PENDING = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_REFUNDED = 'refunded'

    STATUS_CHOICES = [
        (STATUS_PENDING, _('Pending')),
        (STATUS_COMPLETED, _('Completed')),
        (STATUS_FAILED, _('Failed')),
        (STATUS_REFUNDED, _('Refunded')),
    ]

    METHOD_CARD = 'card'
    METHOD_MOBILE_MONEY = 'mobile_money'
    METHOD_BANK_TRANSFER = 'bank_transfer'

    METHOD_CHOICES = [
        (METHOD_CARD, _('Card')),
        (METHOD_MOBILE_MONEY, _('Mobile Money')),
        (METHOD_BANK_TRANSFER, _('Bank Transfer')),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payments',
    )
    subscription = models.ForeignKey(
        'subscriptions.UserSubscription',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='TZS')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    transaction_id = models.CharField(
        max_length=100,
        unique=True,
        default=uuid.uuid4,
        help_text=_('Unique transaction reference.'),
    )
    payment_method = models.CharField(
        max_length=30,
        choices=METHOD_CHOICES,
        default=METHOD_MOBILE_MONEY,
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_('Extra data from payment gateway or internal notes.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('Payment')
        verbose_name_plural = _('Payments')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['transaction_id']),
        ]

    def __str__(self):
        return f'{self.transaction_id} — {self.user.username} — {self.get_status_display()}'

    @property
    def is_successful(self) -> bool:
        return self.status == self.STATUS_COMPLETED
