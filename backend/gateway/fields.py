"""Model fields that encrypt their contents at rest.

HostedApp stores admin-supplied environment variables and a generated database
password. Both are credentials, so they are Fernet-encrypted in the column
rather than sitting in plaintext in Postgres and in every database backup.
"""

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

_fernet_cache: dict[str, Fernet] = {}


def _resolve_key() -> bytes:
    """Return the Fernet key, deriving one from SECRET_KEY if unset.

    Deriving keeps development working with no configuration, but it ties the
    ciphertext to SECRET_KEY — rotating that would orphan stored values, which
    is why DEPLOYER_ENV_ENCRYPTION_KEY should be set explicitly in production.
    """
    configured = getattr(settings, 'DEPLOYER_ENV_ENCRYPTION_KEY', '') or ''
    if configured:
        return configured.encode()
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    key = _resolve_key()
    cache_key = key.decode()
    if cache_key not in _fernet_cache:
        _fernet_cache[cache_key] = Fernet(key)
    return _fernet_cache[cache_key]


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str | None:
    """Decrypt, returning None when the value is not valid ciphertext.

    A None return means the row predates encryption or the key changed; callers
    decide whether to fall back or treat it as empty. We never raise here,
    because an undecryptable env var must not make the admin page 500.
    """
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return None


class EncryptedTextField(models.TextField):
    """TextField whose value is encrypted on the way to the database."""

    description = 'Text encrypted at rest'

    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        decrypted = decrypt(value)
        # Fall back to the raw value so pre-encryption rows stay readable.
        return value if decrypted is None else decrypted

    def to_python(self, value):
        if value is None or value == '':
            return value
        decrypted = decrypt(value)
        return value if decrypted is None else decrypted

    def get_prep_value(self, value):
        if value is None or value == '':
            return value
        return encrypt(str(value))


class EncryptedJSONField(models.TextField):
    """JSON stored as Fernet ciphertext.

    A TextField rather than a JSONField because the column holds opaque
    ciphertext — Postgres must not try to parse or index it as JSON.
    """

    description = 'JSON encrypted at rest'

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('default', dict)
        super().__init__(*args, **kwargs)

    def _load(self, value):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if value == '':
            return {}
        decrypted = decrypt(value)
        payload = value if decrypted is None else decrypted
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return {}

    def from_db_value(self, value, expression, connection):
        return self._load(value)

    def to_python(self, value):
        return self._load(value)

    def get_prep_value(self, value):
        if value is None:
            return None
        if value == '':
            value = {}
        return encrypt(json.dumps(value, sort_keys=True, default=str))

    def value_to_string(self, obj):
        """Serialize for dumpdata as readable JSON, not ciphertext."""
        return json.dumps(self.value_from_object(obj) or {}, sort_keys=True, default=str)
