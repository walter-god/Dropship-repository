"""Django admin configuration for the marketplace app."""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import AppVersion, Application, Category, Download, Review, Screenshot


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon', 'order', 'app_count')
    list_editable = ('order',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('order', 'name')

    @admin.display(description='# Apps')
    def app_count(self, obj):
        return obj.applications.filter(
            status=Application.STATUS_APPROVED, is_active=True
        ).count()


# ---------------------------------------------------------------------------
# Screenshot inline
# ---------------------------------------------------------------------------

class ScreenshotInline(admin.TabularInline):
    model = Screenshot
    extra = 1
    fields = ('image', 'caption', 'order')
    ordering = ('order',)


# ---------------------------------------------------------------------------
# AppVersion inline
# ---------------------------------------------------------------------------

class AppVersionInline(admin.TabularInline):
    model = AppVersion
    extra = 1
    fields = ('version_number', 'changelog', 'app_file', 'is_current', 'created_at')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'developer', 'category', 'version',
        'status', 'is_active', 'is_featured',
        'downloads_count', 'views_count', 'price_display', 'created_at',
    )
    list_filter = ('status', 'is_active', 'is_featured', 'category', 'created_at')
    search_fields = ('name', 'developer__username', 'developer__email', 'tags', 'description')
    ordering = ('-created_at',)
    readonly_fields = ('slug', 'downloads_count', 'views_count', 'created_at', 'updated_at')
    prepopulated_fields = {}  # slug auto-generated in model.save()
    inlines = [ScreenshotInline, AppVersionInline]
    list_select_related = ('developer', 'category')

    fieldsets = (
        (_('Basic info'), {
            'fields': ('name', 'slug', 'category', 'developer', 'status', 'is_active', 'is_featured'),
        }),
        (_('Content'), {
            'fields': ('description', 'short_description', 'tags'),
        }),
        (_('Files'), {
            'fields': ('app_file', 'icon', 'version', 'min_os_version', 'size_bytes'),
        }),
        (_('Pricing'), {
            'fields': ('price',),
        }),
        (_('Stats'), {
            'fields': ('downloads_count', 'views_count', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['approve_apps', 'reject_apps', 'feature_apps', 'unfeature_apps']

    @admin.display(description='Price', ordering='price')
    def price_display(self, obj):
        if obj.price == 0:
            return 'Free'
        return f'TZS {obj.price:,.2f}'

    @admin.action(description='Approve selected applications')
    def approve_apps(self, request, queryset):
        updated = queryset.update(status=Application.STATUS_APPROVED)
        self.message_user(request, f'{updated} application(s) approved.')

    @admin.action(description='Reject selected applications')
    def reject_apps(self, request, queryset):
        updated = queryset.update(status=Application.STATUS_REJECTED)
        self.message_user(request, f'{updated} application(s) rejected.')

    @admin.action(description='Mark selected applications as featured')
    def feature_apps(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f'{updated} application(s) marked as featured.')

    @admin.action(description='Remove featured status from selected applications')
    def unfeature_apps(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(request, f'{updated} application(s) unfeatured.')


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('app', 'user', 'rating', 'is_verified_purchase', 'created_at')
    list_filter = ('rating', 'is_verified_purchase', 'created_at')
    search_fields = ('app__name', 'user__username', 'comment')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')


# ---------------------------------------------------------------------------
# AppVersion
# ---------------------------------------------------------------------------

@admin.register(AppVersion)
class AppVersionAdmin(admin.ModelAdmin):
    list_display = ('app', 'version_number', 'is_current', 'created_at')
    list_filter = ('is_current', 'created_at')
    search_fields = ('app__name', 'version_number', 'changelog')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

@admin.register(Screenshot)
class ScreenshotAdmin(admin.ModelAdmin):
    list_display = ('app', 'order', 'caption', 'thumbnail')
    list_filter = ('app',)
    search_fields = ('app__name', 'caption')
    ordering = ('app', 'order')

    @admin.display(description='Preview')
    def thumbnail(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height:60px; max-width:80px;" />',
                obj.image.url,
            )
        return '-'


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

@admin.register(Download)
class DownloadAdmin(admin.ModelAdmin):
    list_display = ('app', 'user', 'downloaded_at', 'ip_address')
    list_filter = ('downloaded_at',)
    search_fields = ('app__name', 'user__username', 'ip_address')
    ordering = ('-downloaded_at',)
    readonly_fields = ('downloaded_at',)
