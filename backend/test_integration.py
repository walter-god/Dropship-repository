"""End-to-end lifecycle test across marketplace, deployer, subscriptions and
payments.

The original ask was upload -> approve -> deploy -> publish -> subscribe ->
launch -> proxy -> expire -> blocked. There is no launch/proxy step to walk
through: the gateway proxy does not exist in this codebase (see SECURITY.md,
"the gateway proxy does not exist" and gateway/tests.py's skipped stubs). The
adapted walk below covers the same shape with what actually exists — a
paid app's real access gate is HasActiveSubscription on the marketplace
download action, so the walk ends there: subscribe -> download -> expire ->
blocked.
"""

import json
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from conftest import CategoryFactory, FLASK_SOURCE, UserFactory
from deployer import services
from deployer.models import Deployment
from gateway import allowlist
from gateway.models import HostedApp
from marketplace.models import Application

pytestmark = pytest.mark.django_db


def ok_response():
    return mock.Mock(status_code=200)


@pytest.mark.integration
class TestFullProjectLifecycle:
    def test_upload_approve_deploy_publish_subscribe_download_expire_blocked(
        self, admin_client, as_user, zip_upload, flask_template
    ):
        developer = UserFactory(role='internal', username='lifecycle_dev')
        student_client = as_user(developer)
        category = CategoryFactory()

        # --- 1. upload -----------------------------------------------------
        resp = student_client.post('/api/marketplace/apps/', {
            'name': 'Lifecycle Demo', 'category': category.id,
            'description': 'Full lifecycle smoke test.',
            'price': '500.00',
            'source_code': zip_upload(FLASK_SOURCE),
        }, format='multipart')
        assert resp.status_code == 201, resp.data
        app_id = resp.data['id']

        application = Application.objects.get(pk=app_id)
        assert application.status == Application.STATUS_PENDING
        assert application.detected_runtime_key == 'python-flask'

        # A stranger cannot see it yet — it isn't public until approved.
        stranger = UserFactory(role='external', username='lifecycle_stranger')
        stranger_client = as_user(stranger)
        resp = stranger_client.get(f'/api/marketplace/apps/{app_id}/')
        assert resp.status_code == 404

        # --- 2. approve ------------------------------------------------------
        resp = admin_client.post(f'/api/marketplace/apps/{app_id}/approve/')
        assert resp.status_code == 200
        application.refresh_from_db()
        assert application.status == Application.STATUS_APPROVED

        # Now visible to the public.
        resp = stranger_client.get(f'/api/marketplace/apps/{app_id}/')
        assert resp.status_code == 200
        # ...but without the source archive or developer notes.
        assert 'source_code' not in resp.data

        # --- 3. deploy -------------------------------------------------------
        with mock.patch.object(services.requests, 'get', return_value=ok_response()):
            resp = admin_client.post(f'/api/deployer/apps/{app_id}/deploy/', {})
            assert resp.status_code == 202, resp.data

        hosted = HostedApp.objects.get(application_id=app_id)
        assert hosted.status == HostedApp.STATUS_LIVE
        deployment = Deployment.objects.get(hosted_app=hosted)
        assert deployment.status == Deployment.STATUS_LIVE
        assert allowlist.is_allowed(hosted.container_name)

        # --- 4. publish --------------------------------------------------
        resp = admin_client.post(f'/api/deployer/apps/{app_id}/publish/')
        assert resp.status_code == 200
        application.refresh_from_db()
        assert application.status == Application.STATUS_PUBLISHED

        # Published apps stay publicly visible, per PUBLIC_STATUSES.
        resp = stranger_client.get('/api/marketplace/apps/')
        assert app_id in [a['id'] for a in resp.data.get('results', resp.data)]

        # --- 5. an external user cannot download the paid app yet ----------
        resp = stranger_client.post(f'/api/marketplace/apps/{app_id}/download/')
        assert resp.status_code == 403

        # --- 6. subscribe ----------------------------------------------------
        resp = admin_client.post('/api/subscriptions/plans/', {
            'name': 'Lifecycle Plan', 'description': 'x', 'price': '2000.00',
            'duration_days': 30, 'features': {}, 'is_active': True,
        }, format='json')
        assert resp.status_code == 201, resp.data
        plan_id = resp.data['id']

        resp = stranger_client.post('/api/subscriptions/subscribe/', {
            'plan_id': plan_id, 'payment_method': 'card',
        })
        assert resp.status_code == 201, resp.data
        transaction_id = resp.data['payment']['transaction_id']

        # Payment provider confirms via the signed webhook.
        import hashlib
        import hmac
        from django.conf import settings as django_settings
        body = json.dumps({'transaction_id': transaction_id, 'status': 'completed'})
        signature = 'sha256=' + hmac.new(
            django_settings.PAYMENTS_WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        from rest_framework.test import APIClient
        anon = APIClient()
        resp = anon.post('/api/payments/webhook/', data=body, content_type='application/json',
                         HTTP_X_UDOM_SIGNATURE=signature)
        assert resp.status_code == 200

        # --- 7. download now succeeds ----------------------------------------
        resp = stranger_client.post(f'/api/marketplace/apps/{app_id}/download/')
        assert resp.status_code == 200, resp.data

        # --- 8. expire ---------------------------------------------------
        from subscriptions.models import UserSubscription
        subscription = UserSubscription.objects.get(user=stranger, plan_id=plan_id)
        subscription.end_date = timezone.now() - timedelta(days=1)
        subscription.save(update_fields=['end_date'])
        assert subscription.is_valid is False

        # --- 9. blocked again after expiry -----------------------------------
        resp = stranger_client.post(f'/api/marketplace/apps/{app_id}/download/')
        assert resp.status_code == 403, resp.data

    def test_internal_developer_and_admin_never_needed_a_subscription(
        self, admin_client, as_user, zip_upload, flask_template
    ):
        """The same lifecycle, but for the two roles the platform grants free
        access to throughout — no subscribe step should ever be necessary."""
        developer = UserFactory(role='internal', username='lifecycle_dev2')
        student_client = as_user(developer)
        category = CategoryFactory()

        resp = student_client.post('/api/marketplace/apps/', {
            'name': 'Free Access Demo', 'category': category.id,
            'description': 'x', 'price': '500.00',
            'source_code': zip_upload(FLASK_SOURCE),
        }, format='multipart')
        app_id = resp.data['id']
        admin_client.post(f'/api/marketplace/apps/{app_id}/approve/')

        with mock.patch.object(services.requests, 'get', return_value=ok_response()):
            admin_client.post(f'/api/deployer/apps/{app_id}/deploy/', {})
        admin_client.post(f'/api/deployer/apps/{app_id}/publish/')

        # The developer who built it, and the admin, both download the paid
        # app without ever subscribing.
        assert student_client.post(f'/api/marketplace/apps/{app_id}/download/').status_code == 200
        assert admin_client.post(f'/api/marketplace/apps/{app_id}/download/').status_code == 200
