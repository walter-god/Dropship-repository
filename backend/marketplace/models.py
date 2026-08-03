"""Models for the UDOM Digital Marketplace."""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class Category(models.Model):
    """Top-level grouping for marketplace applications."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default='')
    icon = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text=_('Icon identifier (e.g. Material icon name or Font-Awesome class).'),
    )
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    order = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('Category')
        verbose_name_plural = _('Categories')
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Application(models.Model):
    """A software application listed in the marketplace."""

    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_PUBLISHED = 'published'

    STATUS_CHOICES = [
        (STATUS_PENDING, _('Pending')),
        (STATUS_APPROVED, _('Approved')),
        (STATUS_REJECTED, _('Rejected')),
        (STATUS_PUBLISHED, _('Published')),
    ]

    # Statuses visible to the public: approved apps are browsable, published
    # apps are approved AND running behind the gateway.
    PUBLIC_STATUSES = (STATUS_APPROVED, STATUS_PUBLISHED)

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    developer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='developed_apps',
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        related_name='applications',
    )
    description = models.TextField()
    short_description = models.CharField(max_length=300, blank=True, default='')
    version = models.CharField(max_length=50, default='1.0.0')
    app_file = models.FileField(
        upload_to='apps/files/',
        help_text=_('Uploadable package (APK, IPA, ZIP, etc.).'),
    )
    source_code = models.FileField(
        upload_to='projects/source/',
        blank=True,
        null=True,
        help_text=_(
            'Zipped project source. This is the build input for the deployment '
            'pipeline, distinct from app_file which is the distributable package.'
        ),
    )
    icon = models.ImageField(
        upload_to='apps/icons/',
        blank=True,
        null=True,
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(0)],
        help_text=_('Set to 0 for a free application.'),
    )
    is_featured = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    downloads_count = models.PositiveIntegerField(default=0)
    views_count = models.PositiveIntegerField(default=0)
    min_os_version = models.CharField(max_length=50, blank=True, default='')
    size_bytes = models.PositiveBigIntegerField(
        default=0,
        help_text=_('File size in bytes.'),
    )
    tags = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text=_('Comma-separated list of tags.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Application')
        verbose_name_plural = _('Applications')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'is_active']),
            models.Index(fields=['is_featured', 'status']),
        ]

    def __str__(self):
        return f'{self.name} v{self.version}'

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Application.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_free(self) -> bool:
        return self.price == 0

    @property
    def average_rating(self):
        result = self.reviews.aggregate(avg=models.Avg('rating'))
        return round(result['avg'], 1) if result['avg'] else None

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]


class Screenshot(models.Model):
    """Screenshot image attached to an Application."""

    app = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name='screenshots',
    )
    image = models.ImageField(upload_to='apps/screenshots/')
    caption = models.CharField(max_length=200, blank=True, default='')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _('Screenshot')
        verbose_name_plural = _('Screenshots')
        ordering = ['order']

    def __str__(self):
        return f'Screenshot {self.order} for {self.app.name}'


class Review(models.Model):
    """User review and rating for an Application."""

    app = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name='reviews',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reviews',
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.TextField(blank=True, default='')
    is_verified_purchase = models.BooleanField(
        default=False,
        help_text=_('True when the reviewer has downloaded the app.'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Review')
        verbose_name_plural = _('Reviews')
        ordering = ['-created_at']
        unique_together = [('app', 'user')]

    def __str__(self):
        return f'{self.user.username} rated {self.app.name} {self.rating}/5'


class AppVersion(models.Model):
    """Historical version record for an Application."""

    app = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name='versions',
    )
    version_number = models.CharField(max_length=50)
    changelog = models.TextField(blank=True, default='')
    app_file = models.FileField(upload_to='apps/versions/')
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('App Version')
        verbose_name_plural = _('App Versions')
        ordering = ['-created_at']
        unique_together = [('app', 'version_number')]

    def __str__(self):
        return f'{self.app.name} v{self.version_number}'

    def save(self, *args, **kwargs):
        # Ensure only one version is marked current at a time
        if self.is_current:
            AppVersion.objects.filter(app=self.app, is_current=True).exclude(
                pk=self.pk
            ).update(is_current=False)
        super().save(*args, **kwargs)


class Download(models.Model):
    """Record of each time a user downloads an Application."""

    app = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name='downloads',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='downloads',
    )
    downloaded_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)

    class Meta:
        verbose_name = _('Download')
        verbose_name_plural = _('Downloads')
        ordering = ['-downloaded_at']
        indexes = [
            models.Index(fields=['app', 'user']),
        ]

    def __str__(self):
        return f'{self.user.username} downloaded {self.app.name}'
