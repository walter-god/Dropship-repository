"""Tests for the marketplace app: visibility, download permissions, and the
data-exposure fixes from the security review."""

import pytest

from accounts.models import CustomUser
from conftest import ApplicationFactory, FLASK_SOURCE
from marketplace.models import Application, Download

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Public visibility
# ---------------------------------------------------------------------------

class TestPublicVisibility:
    @pytest.mark.parametrize('status_value,visible', [
        (Application.STATUS_APPROVED, True),
        (Application.STATUS_PUBLISHED, True),
        (Application.STATUS_PENDING, False),
        (Application.STATUS_REJECTED, False),
    ])
    def test_list_visibility_by_status(self, api_client, internal_user, category,
                                       status_value, visible):
        app = ApplicationFactory(developer=internal_user, category=category, status=status_value)
        resp = api_client.get('/api/marketplace/apps/')
        assert resp.status_code == 200
        slugs = [a['slug'] for a in resp.data.get('results', resp.data)]
        assert (app.slug in slugs) == visible

    @pytest.mark.parametrize('status_value,expected_status', [
        (Application.STATUS_APPROVED, 200),
        (Application.STATUS_PUBLISHED, 200),
        # get_queryset() filters retrieve to PUBLIC_STATUSES for anonymous
        # users, so a non-public app 404s at the object level — stronger than
        # merely hiding fields on an otherwise-200 response.
        (Application.STATUS_PENDING, 404),
        (Application.STATUS_REJECTED, 404),
    ])
    def test_retrieve_status_code(self, api_client, internal_user, category,
                                  status_value, expected_status):
        app = ApplicationFactory(developer=internal_user, category=category, status=status_value)
        resp = api_client.get(f'/api/marketplace/apps/{app.pk}/')
        assert resp.status_code == expected_status

    def test_owner_sees_their_own_pending_app_in_my_apps(self, internal_user, category, as_user):
        app = ApplicationFactory(
            developer=internal_user, category=category, status=Application.STATUS_PENDING
        )
        client = as_user(internal_user)
        resp = client.get('/api/marketplace/apps/my-apps/')
        slugs = [a['slug'] for a in resp.data.get('results', resp.data)]
        assert app.slug in slugs


# ---------------------------------------------------------------------------
# Public payload must never carry source_code / notes / credentials (C2)
# ---------------------------------------------------------------------------

class TestPrivilegedFieldExposure:
    SENSITIVE_FIELDS = ('source_code', 'deployment_notes', 'demo_credentials')

    @pytest.fixture
    def app_with_secrets(self, internal_user, category, zip_upload):
        return ApplicationFactory(
            developer=internal_user, category=category, status=Application.STATUS_PUBLISHED,
            source_code=zip_upload(FLASK_SOURCE),
            deployment_notes='Run migrations before first boot.',
            demo_credentials='demo@udom.ac.tz / hunter2',
        )

    def test_anonymous_retrieve_excludes_sensitive_fields(self, api_client, app_with_secrets):
        resp = api_client.get(f'/api/marketplace/apps/{app_with_secrets.pk}/')
        assert resp.status_code == 200
        for field in self.SENSITIVE_FIELDS:
            assert field not in resp.data

    def test_anonymous_list_excludes_sensitive_fields(self, api_client, app_with_secrets):
        resp = api_client.get('/api/marketplace/apps/')
        rows = resp.data.get('results', resp.data)
        assert all(f not in row for row in rows for f in self.SENSITIVE_FIELDS)

    def test_unrelated_authenticated_user_excluded_too(
        self, external_client, app_with_secrets
    ):
        resp = external_client.get(f'/api/marketplace/apps/{app_with_secrets.pk}/')
        assert resp.status_code == 200
        assert 'demo_credentials' not in resp.data

    def test_owner_sees_sensitive_fields(self, app_with_secrets, as_user):
        client = as_user(app_with_secrets.developer)
        resp = client.get(f'/api/marketplace/apps/{app_with_secrets.pk}/')
        for field in self.SENSITIVE_FIELDS:
            assert field in resp.data

    def test_admin_sees_sensitive_fields(self, admin_client, app_with_secrets):
        resp = admin_client.get(f'/api/marketplace/apps/{app_with_secrets.pk}/')
        for field in self.SENSITIVE_FIELDS:
            assert field in resp.data

    def test_source_code_never_appears_as_a_media_url_publicly(self, api_client, app_with_secrets):
        resp = api_client.get(f'/api/marketplace/apps/{app_with_secrets.pk}/')
        assert 'projects/source' not in str(resp.data)


# ---------------------------------------------------------------------------
# Self-promotion (M1)
# ---------------------------------------------------------------------------

class TestSelfPromotionBlocked:
    def test_internal_user_cannot_set_is_featured(self, internal_client, category, zip_upload):
        resp = internal_client.post('/api/marketplace/apps/', {
            'name': 'Self Promoted', 'category': category.id, 'description': 'x',
            'is_featured': True,
            'source_code': zip_upload(FLASK_SOURCE),
        }, format='multipart')
        assert resp.status_code == 201
        app = Application.objects.get(pk=resp.data['id'])
        assert app.is_featured is False

    def test_admin_can_set_is_featured(self, admin_client, category, zip_upload):
        resp = admin_client.post('/api/marketplace/apps/', {
            'name': 'Admin Featured', 'category': category.id, 'description': 'x',
            'is_featured': True,
            'source_code': zip_upload(FLASK_SOURCE),
        }, format='multipart')
        assert resp.status_code == 201
        assert Application.objects.get(pk=resp.data['id']).is_featured is True

    def test_internal_user_cannot_self_approve(self, internal_client, category, zip_upload):
        resp = internal_client.post('/api/marketplace/apps/', {
            'name': 'Self Approved', 'category': category.id, 'description': 'x',
            'status': Application.STATUS_APPROVED,
            'source_code': zip_upload(FLASK_SOURCE),
        }, format='multipart')
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# download action permission matrix
# ---------------------------------------------------------------------------

class TestDownloadPermissions:
    @pytest.fixture
    def free_app(self, internal_user, category):
        return ApplicationFactory(
            developer=internal_user, category=category,
            status=Application.STATUS_APPROVED, price=0,
        )

    @pytest.fixture
    def paid_app(self, internal_user, category):
        return ApplicationFactory(
            developer=internal_user, category=category,
            status=Application.STATUS_APPROVED, price='999.00',
        )

    def test_admin_can_download_free_app(self, admin_client, free_app):
        resp = admin_client.post(f'/api/marketplace/apps/{free_app.pk}/download/')
        assert resp.status_code == 200

    def test_internal_user_can_download_free_app(self, internal_client, free_app):
        resp = internal_client.post(f'/api/marketplace/apps/{free_app.pk}/download/')
        assert resp.status_code == 200

    def test_internal_user_can_download_paid_app_without_subscribing(
        self, internal_client, paid_app
    ):
        # Internal (campus) users have free access to everything, per the
        # platform's core access model — no subscription required.
        resp = internal_client.post(f'/api/marketplace/apps/{paid_app.pk}/download/')
        assert resp.status_code == 200

    def test_external_user_can_download_free_app_without_subscribing(
        self, external_client, free_app
    ):
        resp = external_client.post(f'/api/marketplace/apps/{free_app.pk}/download/')
        assert resp.status_code == 200

    def test_external_user_without_subscription_blocked_on_paid_app(
        self, external_client, paid_app
    ):
        resp = external_client.post(f'/api/marketplace/apps/{paid_app.pk}/download/')
        assert resp.status_code == 403

    def test_external_user_with_active_subscription_can_download_paid_app(
        self, external_user, paid_app, as_user
    ):
        from conftest import UserSubscriptionFactory
        UserSubscriptionFactory(user=external_user, is_active=True)
        client = as_user(external_user)
        resp = client.post(f'/api/marketplace/apps/{paid_app.pk}/download/')
        assert resp.status_code == 200

    def test_external_user_with_expired_subscription_blocked(
        self, external_user, paid_app, as_user
    ):
        from conftest import UserSubscriptionFactory
        from django.utils import timezone
        from datetime import timedelta
        UserSubscriptionFactory(
            user=external_user, is_active=True,
            end_date=timezone.now() - timedelta(days=1),
        )
        client = as_user(external_user)
        resp = client.post(f'/api/marketplace/apps/{paid_app.pk}/download/')
        assert resp.status_code == 403

    def test_anonymous_cannot_download_anything(self, api_client, free_app):
        resp = api_client.post(f'/api/marketplace/apps/{free_app.pk}/download/')
        assert resp.status_code == 401

    def test_download_recorded_and_count_incremented(self, internal_client, free_app):
        internal_client.post(f'/api/marketplace/apps/{free_app.pk}/download/')
        free_app.refresh_from_db()
        assert free_app.downloads_count == 1
        assert Download.objects.filter(app=free_app).exists()

    def test_pending_app_not_downloadable_by_anyone(self, admin_client, internal_user, category):
        app = ApplicationFactory(
            developer=internal_user, category=category, status=Application.STATUS_PENDING
        )
        resp = admin_client.post(f'/api/marketplace/apps/{app.pk}/download/')
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# detect-stack endpoint
# ---------------------------------------------------------------------------

class TestDetectStackEndpoint:
    def test_requires_authentication(self, api_client, zip_upload):
        resp = api_client.post(
            '/api/marketplace/apps/detect-stack/',
            {'source_code': zip_upload(FLASK_SOURCE)}, format='multipart',
        )
        assert resp.status_code == 401

    def test_identifies_flask(self, internal_client, zip_upload, flask_template):
        resp = internal_client.post(
            '/api/marketplace/apps/detect-stack/',
            {'source_code': zip_upload(FLASK_SOURCE)}, format='multipart',
        )
        assert resp.status_code == 200
        assert resp.data['runtime_key'] == 'python-flask'

    def test_requires_a_file(self, internal_client):
        resp = internal_client.post('/api/marketplace/apps/detect-stack/', {}, format='multipart')
        assert resp.status_code == 400

    def test_rejects_non_zip_upload(self, internal_client, tmp_path):
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = internal_client.post(
            '/api/marketplace/apps/detect-stack/',
            {'source_code': SimpleUploadedFile('evil.html', b'<script>1</script>')},
            format='multipart',
        )
        assert resp.status_code == 400

    def test_stateless_no_application_created(self, internal_client, zip_upload):
        count_before = Application.objects.count()
        internal_client.post(
            '/api/marketplace/apps/detect-stack/',
            {'source_code': zip_upload(FLASK_SOURCE)}, format='multipart',
        )
        assert Application.objects.count() == count_before
