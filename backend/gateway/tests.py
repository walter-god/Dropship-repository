"""Tests for the gateway app.

Two sections, deliberately kept apart:

1. Real tests for what actually exists today — HostedApp's state machine,
   AppSession lifecycle, the hostname allowlist, and Fernet-encrypted fields.

2. Explicitly SKIPPED placeholders for the proxy-gated launch behaviour a
   fuller spec asked for (subscription enforcement mid-session, SSRF
   defences, session revocation on relaunch, header rewriting). None of that
   exists: `gateway/` has no views.py, no urls.py, and is not wired into the
   URLconf — `allowlist.is_allowed()` currently has no callers anywhere in the
   codebase. This is documented as an accepted risk in SECURITY.md
   ("the gateway proxy does not exist"). These stubs encode the intended
   behaviour as executable documentation: they will start reporting real
   pass/fail the moment someone implements the proxy, and until then they
   show up as `skipped` in test output rather than silently vanishing from
   coverage or being faked against code that isn't there.
"""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from conftest import ApplicationFactory, HostedAppFactory
from gateway import allowlist
from gateway.fields import decrypt, encrypt
from gateway.models import AllowedHostname, AppSession, HostedApp

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# HostedApp state machine
# ---------------------------------------------------------------------------

class TestHostedAppStateMachine:
    def test_defaults_to_not_deployed(self, approved_app):
        hosted = HostedAppFactory(application=approved_app)
        assert hosted.status == HostedApp.STATUS_NOT_DEPLOYED
        assert hosted.is_running is False
        assert hosted.is_busy is False

    @pytest.mark.parametrize('status_value,expected', [
        (HostedApp.STATUS_QUEUED, True),
        (HostedApp.STATUS_BUILDING, True),
        (HostedApp.STATUS_STARTING, True),
        (HostedApp.STATUS_LIVE, False),
        (HostedApp.STATUS_FAILED, False),
        (HostedApp.STATUS_PAUSED, False),
    ])
    def test_is_busy_matches_busy_statuses(self, approved_app, status_value, expected):
        hosted = HostedAppFactory(application=approved_app, status=status_value)
        assert hosted.is_busy is expected

    def test_is_running_only_when_live(self, approved_app):
        hosted = HostedAppFactory(application=approved_app, status=HostedApp.STATUS_LIVE)
        assert hosted.is_running is True

    def test_mark_updates_status_and_extra_fields_together(self, approved_app):
        hosted = HostedAppFactory(application=approved_app)
        hosted.mark(HostedApp.STATUS_LIVE, container_id='abc123')
        hosted.refresh_from_db()
        assert hosted.status == HostedApp.STATUS_LIVE
        assert hosted.container_id == 'abc123'

    def test_touch_updates_last_active_at(self, approved_app):
        hosted = HostedAppFactory(application=approved_app, last_active_at=None)
        hosted.touch()
        hosted.refresh_from_db()
        assert hosted.last_active_at is not None

    def test_slug_delegates_to_application(self, approved_app):
        hosted = HostedAppFactory(application=approved_app)
        assert hosted.slug == approved_app.slug


# ---------------------------------------------------------------------------
# AppSession lifecycle
# ---------------------------------------------------------------------------

class TestAppSession:
    def test_new_session_is_active(self, hosted_app, external_user):
        session = AppSession.objects.create(hosted_app=hosted_app, user=external_user)
        assert session.is_active is True
        assert session.ended_at is None

    def test_revoke_sets_ended_at_and_deactivates(self, hosted_app, external_user):
        session = AppSession.objects.create(hosted_app=hosted_app, user=external_user)
        session.revoke()
        session.refresh_from_db()
        assert session.ended_at is not None
        assert session.is_active is False

    def test_touch_updates_last_seen_at_without_changing_started_at(self, hosted_app, external_user):
        session = AppSession.objects.create(hosted_app=hosted_app, user=external_user)
        original_started = session.started_at
        original_seen = session.last_seen_at
        session.touch()
        session.refresh_from_db()
        assert session.started_at == original_started
        assert session.last_seen_at >= original_seen

    def test_ip_address_is_optional(self, hosted_app, external_user):
        session = AppSession.objects.create(hosted_app=hosted_app, user=external_user)
        assert session.ip_address is None

    def test_ip_address_stored_when_provided(self, hosted_app, external_user):
        session = AppSession.objects.create(
            hosted_app=hosted_app, user=external_user, ip_address='10.0.0.5'
        )
        session.refresh_from_db()
        assert session.ip_address == '10.0.0.5'


# ---------------------------------------------------------------------------
# Hostname allowlist
# ---------------------------------------------------------------------------

class TestAllowlist:
    def test_unregistered_hostname_is_not_allowed(self):
        assert allowlist.is_allowed('udom-app-nonexistent') is False

    def test_register_then_is_allowed(self, hosted_app):
        allowlist.register('udom-app-test-slug', hosted_app)
        assert allowlist.is_allowed('udom-app-test-slug') is True

    def test_unregister_revokes_access(self, hosted_app):
        allowlist.register('udom-app-test-slug', hosted_app)
        allowlist.unregister('udom-app-test-slug')
        assert allowlist.is_allowed('udom-app-test-slug') is False

    def test_register_is_idempotent(self, hosted_app):
        allowlist.register('udom-app-test-slug', hosted_app)
        allowlist.register('udom-app-test-slug', hosted_app)
        assert AllowedHostname.objects.filter(hostname='udom-app-test-slug').count() == 1

    def test_matching_is_case_insensitive(self, hosted_app):
        allowlist.register('udom-app-test-slug', hosted_app)
        assert allowlist.is_allowed('UDOM-APP-TEST-SLUG') is True

    def test_unregistering_unknown_hostname_does_not_raise(self):
        allowlist.unregister('never-registered')  # must not raise

    def test_settings_seeded_hostnames_are_always_allowed(self, settings):
        settings.GATEWAY_ALLOWED_HOSTNAMES = ['udom_backend', 'udom_celery_worker']
        cache.clear()
        assert allowlist.is_allowed('udom_backend') is True

    def test_cache_invalidated_on_register(self, hosted_app):
        # Prime the cache with an empty result, then register — the entry
        # must become visible immediately, not after the TTL.
        assert allowlist.is_allowed('udom-app-fresh') is False
        allowlist.register('udom-app-fresh', hosted_app)
        assert allowlist.is_allowed('udom-app-fresh') is True


# ---------------------------------------------------------------------------
# Encrypted fields
# ---------------------------------------------------------------------------

class TestEncryptedFields:
    def test_env_vars_round_trip(self, hosted_app):
        hosted_app.env_vars = {'API_KEY': 'super-secret-value'}
        hosted_app.save(update_fields=['env_vars'])
        hosted_app.refresh_from_db()
        assert hosted_app.env_vars == {'API_KEY': 'super-secret-value'}

    def test_ciphertext_in_column_not_plaintext(self, hosted_app):
        hosted_app.env_vars = {'API_KEY': 'super-secret-value'}
        hosted_app.save(update_fields=['env_vars'])

        from django.db import connection
        with connection.cursor() as cur:
            cur.execute(
                'SELECT env_vars FROM gateway_hostedapp WHERE id = %s', [hosted_app.pk]
            )
            raw = cur.fetchone()[0]
        assert 'super-secret-value' not in raw

    def test_db_password_round_trips(self, hosted_app):
        hosted_app.db_password = 'a-generated-db-password'
        hosted_app.save(update_fields=['db_password'])
        hosted_app.refresh_from_db()
        assert hosted_app.db_password == 'a-generated-db-password'

    def test_encrypt_decrypt_helpers(self):
        ciphertext = encrypt('hello world')
        assert ciphertext != 'hello world'
        assert decrypt(ciphertext) == 'hello world'

    def test_decrypt_returns_none_for_garbage_input(self):
        assert decrypt('not-valid-fernet-ciphertext') is None

    def test_empty_env_vars_default(self, approved_app):
        hosted = HostedAppFactory(application=approved_app)
        assert hosted.env_vars == {}


# ---------------------------------------------------------------------------
# NOT YET IMPLEMENTED: the gateway proxy itself
#
# Skipped rather than omitted, so the intended behaviour stays visible in test
# output as a to-do rather than silently disappearing. See SECURITY.md,
# "Accepted risks #1 — the gateway proxy does not exist".
# ---------------------------------------------------------------------------

NO_PROXY_REASON = (
    'gateway/ has no views.py, no urls.py, and is not wired into the URLconf. '
    'There is no request path to a running student app to test. '
    'See SECURITY.md accepted risk #1.'
)


class TestGatewayProxyNotYetImplemented:
    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_active_subscription_allows_proxying(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_expired_subscription_returns_402_mid_session(self):
        """The subscription check must be re-evaluated on every proxied
        request, not just at launch time, or an expiry mid-session is
        silently ignored until the user relaunches."""

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_revoked_session_rejected(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_expired_session_rejected(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_launching_twice_as_same_user_revokes_first_session(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_free_project_launches_without_subscription(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_admin_lecturer_and_owning_developer_launch_without_subscribing(self):
        """Note: there is no 'lecturer' role in this codebase — roles are
        admin/internal/external (accounts.models.CustomUser.ROLE_CHOICES).
        Internal users (which include staff) already bypass the subscription
        check in HasActiveSubscription; this stub should be rewritten against
        the roles that actually exist once the proxy is built."""

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_ssrf_private_ip_rejected(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_ssrf_cloud_metadata_address_rejected(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_ssrf_encoded_ip_literal_rejected(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_ssrf_redirect_to_internal_rejected(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_path_traversal_rejected(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_x_frame_options_stripped_from_upstream_response(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_location_header_rewritten(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_set_cookie_path_rewritten(self):
        ...

    @pytest.mark.skip(reason=NO_PROXY_REASON)
    def test_internal_base_url_absent_from_every_non_admin_serializer(self):
        """Partially covered today: HostedAppSerializer (which does carry
        internal_base_url) is already admin-only end to end — see
        deployer.tests.TestDeployerPermissions. What's untested is a future
        gateway-facing serializer that might expose launch info to a regular
        user; this stub is the reminder to check it when that's built."""
