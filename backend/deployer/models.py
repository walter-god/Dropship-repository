"""Deployment pipeline models."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Value
from django.db.models.functions import Concat
from django.template import Context, Template
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class RuntimeTemplate(models.Model):
    """A recipe for containerising one class of project.

    Seeded from deployer/fixtures/runtime_templates.json rather than created by
    hand, so the six Tier-A runtimes are reproducible across environments.
    """

    key = models.SlugField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    dockerfile_template = models.TextField(
        help_text=_('Django template string rendered when the project has no Dockerfile.'),
    )
    default_health_path = models.CharField(max_length=200, default='/')
    default_port = models.PositiveIntegerField(
        default=8000,
        help_text=_('Must be >1024: containers run as a non-root user.'),
    )
    migrate_command = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text=_('Optional shell command run inside the container after start.'),
    )
    needs_database = models.BooleanField(default=False)
    tmpfs_paths = models.JSONField(
        default=list,
        blank=True,
        help_text=_(
            'Paths this runtime must be able to write to at runtime, mounted as '
            'tmpfs because the root filesystem is read-only (e.g. Next.js writes '
            '.next, Laravel writes storage/). /tmp is always mounted.'
        ),
    )
    detection_hints = models.JSONField(
        default=dict,
        blank=True,
        help_text=_(
            'Auto-detection rules. Supports priority, require_files, any_files, '
            'require_absent, package_json_deps, content_matches.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Runtime Template')
        verbose_name_plural = _('Runtime Templates')
        ordering = ['key']

    def __str__(self):
        return self.display_name

    @property
    def priority(self) -> int:
        return (self.detection_hints or {}).get('priority', 0)

    def tmpfs_mounts(self, size_mb: int = 64) -> dict:
        """Docker tmpfs spec for this runtime's writable paths.

        Sized explicitly — an unbounded tmpfs is RAM the container can consume
        past its own memory limit.
        """
        opts = f'rw,noexec,nosuid,nodev,size={size_mb}m'
        paths = ['/tmp', *(self.tmpfs_paths or [])]
        return {path: opts for path in paths}

    def render_dockerfile(self, **context) -> str:
        """Render the Dockerfile for a concrete app.

        The template text is admin-authored (a fixture) and the context is
        derived from platform settings, so no student-controlled string is
        interpolated as template source.
        """
        context.setdefault('port', self.default_port)
        context.setdefault('health_path', self.default_health_path)
        return Template(self.dockerfile_template).render(Context(context))


class Deployment(models.Model):
    """One build attempt. Kept forever, so failures stay auditable."""

    STATUS_QUEUED = 'queued'
    STATUS_BUILDING = 'building'
    STATUS_STARTING = 'starting'
    STATUS_LIVE = 'live'
    STATUS_FAILED = 'failed'

    STATUS_CHOICES = [
        (STATUS_QUEUED, _('Queued')),
        (STATUS_BUILDING, _('Building')),
        (STATUS_STARTING, _('Starting')),
        (STATUS_LIVE, _('Live')),
        (STATUS_FAILED, _('Failed')),
    ]

    TERMINAL_STATUSES = (STATUS_LIVE, STATUS_FAILED)

    hosted_app = models.ForeignKey(
        'gateway.HostedApp',
        on_delete=models.CASCADE,
        related_name='deployments',
    )

    # Per-run overrides captured from the deploy request, so a single build can
    # honour an admin's choices (drawer override, DB checkbox, custom port)
    # without mutating HostedApp until the build actually succeeds.
    requested_runtime_template = models.ForeignKey(
        'RuntimeTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        help_text=_('Explicit override from the deploy drawer; null means auto-detect.'),
    )
    requested_provision_database = models.BooleanField(
        null=True,
        blank=True,
        help_text=_('Null defers to the runtime template / current HostedApp setting.'),
    )
    requested_container_port = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_('Explicit port override — required when a custom Dockerfile has no '
                     'EXPOSE instruction.'),
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_QUEUED,
        db_index=True,
    )
    build_log = models.TextField(blank=True, default='')
    image_tag = models.CharField(max_length=255, blank=True, default='')
    container_id = models.CharField(max_length=128, blank=True, default='')
    error_summary = models.TextField(blank=True, default='')
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='triggered_deployments',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Deployment')
        verbose_name_plural = _('Deployments')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['hosted_app', '-created_at']),
        ]

    def __str__(self):
        return f'{self.hosted_app.application.name} #{self.pk} ({self.status})'

    @property
    def is_finished(self) -> bool:
        return self.status in self.TERMINAL_STATUSES

    @property
    def duration_seconds(self) -> float | None:
        if not self.started_at:
            return None
        end = self.finished_at or timezone.now()
        return (end - self.started_at).total_seconds()

    def append_log(self, text: str) -> None:
        """Append to build_log atomically in the database.

        A read-modify-write would drop output: the worker writes chunks while
        the admin polls, and two concurrent flushes would clobber each other.
        Concat pushes the append into Postgres so nothing is lost.
        """
        if not text:
            return
        Deployment.objects.filter(pk=self.pk).update(
            build_log=Concat(F('build_log'), Value(text))
        )

    def mark(self, status: str, **fields) -> None:
        self.status = status
        fields['status'] = status
        if status in self.TERMINAL_STATUSES and 'finished_at' not in fields:
            fields['finished_at'] = timezone.now()
        for key, value in fields.items():
            setattr(self, key, value)
        self.save(update_fields=list(fields.keys()))
