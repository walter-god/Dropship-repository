"""Hostname allowlist for gateway proxying.

Student containers are addressed by Docker DNS name (udom-app-<slug>), which
no SSRF resolver can validate — the name has no meaning outside the daemon's
network namespace. This module is therefore the authority on which hostnames
the gateway may proxy to.

Backed by the database, not a settings list: the Celery worker registers a
hostname when a deploy goes live, while the web process is what later serves
traffic to it. They run in separate containers, so a module-level Python set
mutated in the worker would never be visible to the web process.
"""

import logging

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError

from .models import AllowedHostname

logger = logging.getLogger(__name__)

_CACHE_KEY = 'gateway:allowed_hostnames'
_CACHE_TTL = 30  # seconds


def _seed_hostnames() -> set[str]:
    return {h.strip() for h in getattr(settings, 'GATEWAY_ALLOWED_HOSTNAMES', []) if h.strip()}


def _invalidate():
    cache.delete(_CACHE_KEY)


def all_hostnames() -> set[str]:
    """Every hostname the gateway may proxy to (settings seed + database)."""
    cached = cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    hostnames = _seed_hostnames()
    hostnames.update(AllowedHostname.objects.values_list('hostname', flat=True))
    cache.set(_CACHE_KEY, hostnames, _CACHE_TTL)
    return hostnames


def is_allowed(hostname: str) -> bool:
    if not hostname:
        return False
    return hostname.strip().lower() in {h.lower() for h in all_hostnames()}


def register(hostname: str, hosted_app=None) -> None:
    """Allow the gateway to proxy to `hostname`. Idempotent."""
    hostname = (hostname or '').strip()
    if not hostname:
        return
    try:
        AllowedHostname.objects.update_or_create(
            hostname=hostname,
            defaults={'hosted_app': hosted_app},
        )
    except IntegrityError:
        # Concurrent deploys of the same app can race here; the row existing
        # is the desired end state either way.
        logger.debug('Hostname %s already registered', hostname)
    _invalidate()
    logger.info('Registered gateway hostname %s', hostname)


def unregister(hostname: str) -> None:
    """Revoke proxy access for `hostname`. Idempotent."""
    hostname = (hostname or '').strip()
    if not hostname:
        return
    AllowedHostname.objects.filter(hostname=hostname).delete()
    _invalidate()
    logger.info('Unregistered gateway hostname %s', hostname)
