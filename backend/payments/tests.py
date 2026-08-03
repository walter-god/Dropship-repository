"""Tests for the payment webhook — the C1 fix from the security review.

The webhook is necessarily unauthenticated (a payment provider has no
session), so the HMAC signature IS the authentication. These tests exist
because before this fix, any known transaction_id could be marked completed
by anyone, and transaction_ids are handed back to the user who initiates the
payment.
"""

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from conftest import SubscriptionPlanFactory, UserSubscriptionFactory
from payments.models import Payment

pytestmark = pytest.mark.django_db

WEBHOOK_URL = '/api/payments/webhook/'
SECRET = 'test-webhook-secret'  # matches settings_test.PAYMENTS_WEBHOOK_SECRET


def sign(payload: str, secret: str = SECRET) -> str:
    return 'sha256=' + hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def pending_payment(external_user):
    plan = SubscriptionPlanFactory()
    sub = UserSubscriptionFactory(user=external_user, plan=plan, is_active=False)
    return Payment.objects.create(
        user=external_user, subscription=sub, amount='1000.00',
        transaction_id='TXN-TEST0001', status=Payment.STATUS_PENDING,
    )


class TestWebhookSignature:
    def test_unsigned_request_rejected(self, api_client, pending_payment):
        body = json.dumps({'transaction_id': pending_payment.transaction_id, 'status': 'completed'})
        resp = api_client.post(WEBHOOK_URL, data=body, content_type='application/json')
        assert resp.status_code == 401
        pending_payment.subscription.refresh_from_db()
        assert pending_payment.subscription.is_active is False

    def test_wrong_secret_rejected(self, api_client, pending_payment):
        body = json.dumps({'transaction_id': pending_payment.transaction_id, 'status': 'completed'})
        resp = api_client.post(
            WEBHOOK_URL, data=body, content_type='application/json',
            HTTP_X_UDOM_SIGNATURE=sign(body, secret='wrong-secret'),
        )
        assert resp.status_code == 401

    def test_signature_over_different_body_rejected(self, api_client, pending_payment):
        real_body = json.dumps({'transaction_id': pending_payment.transaction_id, 'status': 'completed'})
        other_signature = sign(json.dumps({'transaction_id': 'other', 'status': 'completed'}))
        resp = api_client.post(
            WEBHOOK_URL, data=real_body, content_type='application/json',
            HTTP_X_UDOM_SIGNATURE=other_signature,
        )
        assert resp.status_code == 401

    def test_correctly_signed_request_succeeds(self, api_client, pending_payment):
        body = json.dumps({'transaction_id': pending_payment.transaction_id, 'status': 'completed'})
        resp = api_client.post(
            WEBHOOK_URL, data=body, content_type='application/json',
            HTTP_X_UDOM_SIGNATURE=sign(body),
        )
        assert resp.status_code == 200
        pending_payment.refresh_from_db()
        pending_payment.subscription.refresh_from_db()
        assert pending_payment.status == Payment.STATUS_COMPLETED
        assert pending_payment.subscription.is_active is True

    def test_unset_secret_fails_closed(self, api_client, pending_payment):
        body = json.dumps({'transaction_id': pending_payment.transaction_id, 'status': 'completed'})
        with override_settings(PAYMENTS_WEBHOOK_SECRET=''):
            resp = api_client.post(
                WEBHOOK_URL, data=body, content_type='application/json',
                HTTP_X_UDOM_SIGNATURE=sign(body),
            )
        assert resp.status_code == 401

    def test_unknown_transaction_id_404s_even_when_signed(self, api_client):
        body = json.dumps({'transaction_id': 'TXN-DOES-NOT-EXIST', 'status': 'completed'})
        resp = api_client.post(
            WEBHOOK_URL, data=body, content_type='application/json',
            HTTP_X_UDOM_SIGNATURE=sign(body),
        )
        assert resp.status_code == 404


class TestWebhookIdempotency:
    def test_replaying_a_completed_webhook_does_not_reactivate_a_revoked_subscription(
        self, api_client, pending_payment
    ):
        body = json.dumps({'transaction_id': pending_payment.transaction_id, 'status': 'completed'})
        signature = sign(body)

        resp = api_client.post(WEBHOOK_URL, data=body, content_type='application/json',
                               HTTP_X_UDOM_SIGNATURE=signature)
        assert resp.status_code == 200

        # Admin (or the subscription's own expiry) revokes it afterwards.
        pending_payment.subscription.is_active = False
        pending_payment.subscription.save(update_fields=['is_active'])

        # The same signed body, replayed.
        resp = api_client.post(WEBHOOK_URL, data=body, content_type='application/json',
                               HTTP_X_UDOM_SIGNATURE=signature)
        assert resp.status_code == 200
        pending_payment.subscription.refresh_from_db()
        assert pending_payment.subscription.is_active is False

    def test_refunded_payment_cannot_change_status(self, api_client, pending_payment):
        pending_payment.status = Payment.STATUS_REFUNDED
        pending_payment.save(update_fields=['status'])
        body = json.dumps({'transaction_id': pending_payment.transaction_id, 'status': 'completed'})
        resp = api_client.post(WEBHOOK_URL, data=body, content_type='application/json',
                               HTTP_X_UDOM_SIGNATURE=sign(body))
        assert resp.status_code == 409
        pending_payment.refresh_from_db()
        assert pending_payment.status == Payment.STATUS_REFUNDED


class TestWebhookThrottle:
    def test_scoped_throttle_applies(self, api_client, pending_payment):
        # DRF's ScopedRateThrottle reads a class attribute snapshotted from
        # api_settings at import time, which does not observe a later
        # `settings` fixture override — so the rate is patched directly here
        # rather than through Django settings.
        from rest_framework.throttling import ScopedRateThrottle
        original = ScopedRateThrottle.THROTTLE_RATES
        ScopedRateThrottle.THROTTLE_RATES = {**original, 'payment_webhook': '2/min'}
        try:
            body = json.dumps({'transaction_id': 'nope', 'status': 'completed'})
            signature = sign(body)
            statuses = [
                api_client.post(WEBHOOK_URL, data=body, content_type='application/json',
                                HTTP_X_UDOM_SIGNATURE=signature).status_code
                for _ in range(4)
            ]
            assert 429 in statuses
        finally:
            ScopedRateThrottle.THROTTLE_RATES = original
