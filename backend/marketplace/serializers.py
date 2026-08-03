"""Serializers for the marketplace app."""

from django.db.models import Avg
from rest_framework import serializers

from accounts.models import CustomUser
from .models import Application, AppVersion, Category, Download, Review, Screenshot


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

class CategorySerializer(serializers.ModelSerializer):
    app_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Category
        fields = ['id', 'name', 'description', 'icon', 'slug', 'order', 'app_count']
        read_only_fields = ['slug']

    def get_app_count(self, obj) -> int:
        return obj.applications.filter(
            status__in=Application.PUBLIC_STATUSES, is_active=True
        ).count()


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

class ScreenshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Screenshot
        fields = ['id', 'image', 'caption', 'order']


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

class ReviewUserSerializer(serializers.ModelSerializer):
    """Minimal user info embedded in review responses."""

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'full_name', 'profile_picture']

    def get_full_name(self, obj) -> str:
        return obj.get_full_name()


class ReviewSerializer(serializers.ModelSerializer):
    user = ReviewUserSerializer(read_only=True)
    app_name = serializers.CharField(source='app.name', read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'app', 'app_name', 'user', 'rating',
            'comment', 'is_verified_purchase', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user', 'is_verified_purchase', 'created_at', 'updated_at']

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError('Rating must be between 1 and 5.')
        return value

    def validate(self, attrs):
        request = self.context.get('request')
        app = attrs.get('app')
        if request and app:
            # On create only, check for duplicate
            if self.instance is None:
                if Review.objects.filter(app=app, user=request.user).exists():
                    raise serializers.ValidationError(
                        'You have already reviewed this application.'
                    )
        return attrs

    def create(self, validated_data):
        request = self.context['request']
        user = request.user
        # Mark as verified purchase if user has downloaded the app
        app = validated_data['app']
        is_verified = Download.objects.filter(app=app, user=user).exists()
        return Review.objects.create(
            user=user,
            is_verified_purchase=is_verified,
            **validated_data,
        )


# ---------------------------------------------------------------------------
# Application — list (lightweight)
# ---------------------------------------------------------------------------

class DeveloperMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'first_name', 'last_name']


class ApplicationListSerializer(serializers.ModelSerializer):
    """Compact representation used in list endpoints."""

    category_name = serializers.CharField(source='category.name', read_only=True)
    developer = DeveloperMinimalSerializer(read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    is_free = serializers.BooleanField(read_only=True)

    class Meta:
        model = Application
        fields = [
            'id', 'name', 'slug', 'developer', 'category', 'category_name',
            'short_description', 'version', 'icon', 'price', 'is_free',
            'is_featured', 'status', 'downloads_count', 'views_count',
            'average_rating', 'review_count', 'created_at',
        ]
        read_only_fields = fields

    def get_average_rating(self, obj):
        result = obj.reviews.aggregate(avg=Avg('rating'))
        avg = result.get('avg')
        return round(avg, 1) if avg is not None else None

    def get_review_count(self, obj) -> int:
        return obj.reviews.count()


# ---------------------------------------------------------------------------
# Application — full detail
# ---------------------------------------------------------------------------

class AppVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppVersion
        fields = ['id', 'version_number', 'changelog', 'is_current', 'created_at']
        read_only_fields = fields


class ApplicationDetailSerializer(serializers.ModelSerializer):
    """Full detail including screenshots, reviews, and version history."""

    category = CategorySerializer(read_only=True)
    developer = DeveloperMinimalSerializer(read_only=True)
    screenshots = ScreenshotSerializer(many=True, read_only=True)
    reviews = ReviewSerializer(many=True, read_only=True)
    versions = AppVersionSerializer(many=True, read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    is_free = serializers.BooleanField(read_only=True)
    tag_list = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = Application
        fields = [
            'id', 'name', 'slug', 'developer', 'category',
            'description', 'short_description', 'version', 'app_file',
            'source_code', 'icon', 'price', 'is_free', 'is_featured', 'is_active',
            'status', 'downloads_count', 'views_count',
            'min_os_version', 'size_bytes', 'tags', 'tag_list',
            'average_rating', 'review_count',
            'screenshots', 'reviews', 'versions',
            'detected_runtime_key', 'detection_confidence', 'detection_reason',
            'needs_dockerfile', 'deployment_notes', 'demo_credentials',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'slug', 'downloads_count', 'views_count',
            'detected_runtime_key', 'detection_confidence', 'detection_reason',
            'needs_dockerfile', 'created_at', 'updated_at',
        ]

    def get_average_rating(self, obj):
        result = obj.reviews.aggregate(avg=Avg('rating'))
        avg = result.get('avg')
        return round(avg, 1) if avg is not None else None

    def get_review_count(self, obj) -> int:
        return obj.reviews.count()


# ---------------------------------------------------------------------------
# Application — create / update (write)
# ---------------------------------------------------------------------------

class ApplicationCreateSerializer(serializers.ModelSerializer):
    """
    Used when a developer or admin submits a new application or updates
    an existing one.  The developer is set from the authenticated user.
    """

    screenshots = ScreenshotSerializer(many=True, read_only=True)
    uploaded_screenshots = serializers.ListField(
        child=serializers.ImageField(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Application
        fields = [
            'id', 'name', 'category', 'description', 'short_description',
            'version', 'app_file', 'source_code', 'icon', 'price',
            'min_os_version', 'size_bytes', 'tags',
            'is_featured', 'is_active', 'status',
            'deployment_notes', 'demo_credentials',
            'detected_runtime_key', 'detection_confidence', 'detection_reason',
            'needs_dockerfile',
            'screenshots', 'uploaded_screenshots',
        ]
        read_only_fields = [
            'id', 'detected_runtime_key', 'detection_confidence',
            'detection_reason', 'needs_dockerfile',
        ]
        extra_kwargs = {
            'status': {'required': False},
        }

    def validate_status(self, value):
        request = self.context.get('request')
        # Only admins may directly approve / reject an app
        if value in (Application.STATUS_APPROVED, Application.STATUS_REJECTED):
            if not (request and (request.user.is_admin or request.user.is_staff)):
                raise serializers.ValidationError(
                    'Only administrators may set approved or rejected status.'
                )
        return value

    @staticmethod
    def _apply_detection(instance, source_file):
        """Run stack detection against a freshly uploaded source archive.

        Runs whenever source_code is set or replaced, so the result is
        visible to both the student and the admin without a separate step —
        detection here always agrees with the stateless preview endpoint,
        because both call the same detect_from_archive().
        """
        if not source_file:
            return
        from deployer.detection import detect_from_archive

        try:
            source_file.seek(0)
        except (AttributeError, ValueError):
            pass
        result = detect_from_archive(source_file)
        try:
            source_file.seek(0)
        except (AttributeError, ValueError):
            pass

        instance.detected_runtime_key = result['runtime_key']
        instance.detection_confidence = result['confidence']
        instance.detection_reason = result['reason']
        instance.needs_dockerfile = result['needs_dockerfile']

    def create(self, validated_data):
        uploaded_screenshots = validated_data.pop('uploaded_screenshots', [])
        request = self.context['request']
        source_file = validated_data.get('source_code')

        application = Application(developer=request.user, **validated_data)
        self._apply_detection(application, source_file)
        application.save()

        for idx, image in enumerate(uploaded_screenshots):
            Screenshot.objects.create(app=application, image=image, order=idx)
        return application

    def update(self, instance, validated_data):
        uploaded_screenshots = validated_data.pop('uploaded_screenshots', None)
        source_file = validated_data.get('source_code')
        source_changed = 'source_code' in validated_data

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if source_changed:
            self._apply_detection(instance, source_file)
        instance.save()

        if uploaded_screenshots is not None:
            # Replace existing screenshots with the new set
            instance.screenshots.all().delete()
            for idx, image in enumerate(uploaded_screenshots):
                Screenshot.objects.create(app=instance, image=image, order=idx)
        return instance


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

class DownloadSerializer(serializers.ModelSerializer):
    app_name = serializers.CharField(source='app.name', read_only=True)

    class Meta:
        model = Download
        fields = ['id', 'app', 'app_name', 'downloaded_at', 'ip_address']
        read_only_fields = fields
