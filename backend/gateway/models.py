"""Substrate models for hosting student applications.

A HostedApp is the running counterpart of a marketplace Application: where the
Application row is the catalogue listing, HostedApp is the container actually
serving it. AppSession records that somebody is using it, which is what keeps
the idle auto-stop sweep from killing an app somebody is mid-way through.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .fields import EncryptedJSONField, EncryptedTextField


class HostedApp(models.Model):
    """A deployable, runnable instance of a marketplace Application."""

    STATUS_NOT_DEPLOYED = 'not_deployed'
    STATUS_QUEUED = 'queued'
    STATUS_BUILDING = 'building'
    STATUS_STARTING = 'starting'
    STATUS_LIVE = 'live'
    STATUS_PAUSED = 'paused'
    STATUS_STOPPED = 'stopped'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_NOT_DEPLOYED, _('Not deployed')),
        (STATUS_QUEUED, _('Queued')),
        (STATUS_BUILDING, _('Building')),
        (STATUS_STARTING, _('Starting')),
        (STATUS_LIVE, _('Live')),
        (STATUS_PAUSED, _('Paused (idle)')),
        (STATUS_STOPPED, _('Stopped')),
        (STATUS_FAILED, _('Failed')),
    ]

    # Statuses where a deploy is already in flight; a second one must not start.
    BUSY_STATUSES = (STATUS_QUEUED, STATUS_BUILDING, STATUS_STARTING)

    application = models.OneToOneField(
        'marketplace.Application',
        on_delete=models.CASCADE,
        related_name='hosted_app',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NOT_DEPLOYED,
        db_index=True,
    )
    internal_base_url = models.URLField(
        blank=True,
        default='',
        help_text=_('http://udom-app-<slug>:<port> — resolvable only inside Docker DNS.'),
    )

    # String reference: deployer imports gateway, so a direct import here would
    # close the loop.
    runtime_template = models.ForeignKey(
        'deployer.RuntimeTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hosted_apps',
    )

    container_id = models.CharField(max_length=128, blank=True, default='')
    container_name = models.CharField(max_length=128, blank=True, default='', db_index=True)
    network_name = models.CharField(max_length=128, blank=True, default='')
    container_port = models.PositiveIntegerField(
        default=8000,
        help_text=_('Port the app listens on inside its container. Must be >1024 (non-root).'),
    )

    needs_database = models.BooleanField(default=False)
    db_name = models.CharField(max_length=63, blank=True, default='')
    db_user = models.CharField(max_length=63, blank=True, default='')
    # Persisted so DATABASE_URL can be rebuilt on restart without re-provisioning.
    db_password = EncryptedTextField(blank=True, default='')

    env_vars = EncryptedJSONField(
        blank=True,
        default=dict,
        help_text=_('Admin-supplied environment variables, encrypted at rest.'),
    )

    admin_dockerfile_override = models.TextField(
        blank=True,
        default='',
        help_text=_(
            'A Dockerfile supplied by an admin on the student’s behalf — takes '
            'precedence over both a zip-supplied Dockerfile and the runtime template. '
            'Cleared by setting to an empty string.'
        ),
    )

    memory_limit_mb = models.PositiveIntegerField(default=512)
    cpu_limit = models.FloatField(default=0.5)

    last_active_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Hosted App')
        verbose_name_plural = _('Hosted Apps')
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['status', 'last_active_at']),
        ]

    def __str__(self):
        return f'{self.application.name} [{self.get_status_display()}]'

    @property
    def slug(self) -> str:
        return self.application.slug

    @property
    def is_busy(self) -> bool:
        return self.status in self.BUSY_STATUSES

    @property
    def is_running(self) -> bool:
        return self.status == self.STATUS_LIVE

    def touch(self):
        """Record user activity so the idle sweep leaves this app alone."""
        self.last_active_at = timezone.now()
        self.save(update_fields=['last_active_at', 'updated_at'])

    def mark(self, status: str, **fields):
        """Set status plus any extra fields in a single targeted UPDATE."""
        self.status = status
        fields['status'] = status
        for key, value in fields.items():
            setattr(self, key, value)
        self.save(update_fields=[*fields.keys(), 'updated_at'])


class AppSession(models.Model):
    """A user's active session against a running app.

    `last_seen_at` is the signal the idle auto-stop sweep reads; the gateway
    proxy will bump it on each proxied request once it lands.
    """

    hosted_app = models.ForeignKey(
        HostedApp,
        on_delete=models.CASCADE,
        related_name='sessions',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='app_sessions',
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text=_('Populated by the gateway proxy once it exists; empty until then.'),
    )

    class Meta:
        verbose_name = _('App Session')
        verbose_name_plural = _('App Sessions')
        ordering = ['-last_seen_at']
        indexes = [
            models.Index(fields=['hosted_app', 'last_seen_at']),
        ]

    def __str__(self):
        return f'{self.user} on {self.hosted_app.application.name}'

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    def touch(self):
        self.last_seen_at = timezone.now()
        self.save(update_fields=['last_seen_at'])

    def revoke(self):
        self.ended_at = timezone.now()
        self.save(update_fields=['ended_at'])


class AllowedHostname(models.Model):
    """Container hostnames the gateway is permitted to proxy to.

    Container names resolve only inside Docker DNS, so an SSRF resolver cannot
    validate them by IP — this table is the authority instead. It lives in the
    database rather than in settings because the Celery worker registers
    hostnames while the web process reads them, and they are separate
    containers: an in-process set would never propagate.
    """

    hostname = models.CharField(max_length=255, unique=True, db_index=True)
    hosted_app = models.ForeignKey(
        HostedApp,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='allowed_hostnames',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Allowed Hostname')
        verbose_name_plural = _('Allowed Hostnames')
        ordering = ['hostname']

    def __str__(self):
        return self.hostname
