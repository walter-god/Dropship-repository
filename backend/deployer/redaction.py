"""Strip credentials out of anything we persist or send.

The migrate step runs *student code* (`python manage.py migrate` is the
student's own `manage.py`) and its stdout is written verbatim into
`Deployment.build_log`. A single `print(os.environ)` — hostile or accidental —
would otherwise put a live database password into that column, into every
database backup, into the admin UI, into an email, and into the application
log. That also silently defeats encrypting `HostedApp.db_password` at rest.

Two layers, because neither is sufficient alone:

* **Literal redaction** of the exact secrets in play for this deployment.
  Precise, and immune to formatting — it catches the password whether it is
  printed inside a DSN, a dict repr, a stack frame, or split across a log
  prefix.
* **Pattern redaction** for credential shapes we can recognise generically,
  which covers secrets we were never told about (a student's own API key in
  their app's crash output, for instance).
"""

from __future__ import annotations

import re

PLACEHOLDER = '[REDACTED]'

# Ordered most-specific first. Each pattern must keep the surrounding context
# intact so the log stays diagnostically useful — the goal is a readable log
# with the secret removed, not an unreadable one.
PATTERNS: list[re.Pattern] = [
    # postgres://user:secret@host/db  (also mysql://, redis://, amqp://, ...)
    re.compile(r'(?P<pre>[a-zA-Z][a-zA-Z0-9+.\-]*://[^:/\s]+:)(?P<secret>[^@\s]+)(?P<post>@)'),
    # KEY=value / KEY: value for anything that smells like a credential
    re.compile(
        r'(?P<pre>\b(?:[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|APIKEY|API_KEY|'
        r'PRIVATE_KEY|ACCESS_KEY|CREDENTIALS?)[A-Z0-9_]*)\s*[=:]\s*)'
        r'(?P<secret>[^\s,;"\'\)\}]+)',
        re.IGNORECASE,
    ),
    # Quoted dict/JSON form: 'PASSWORD': 'secret'
    re.compile(
        r'(?P<pre>["\'][A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_KEY)[A-Z0-9_]*["\']\s*:\s*["\'])'
        r'(?P<secret>[^"\']+)(?P<post>["\'])',
        re.IGNORECASE,
    ),
    # Authorization: Bearer <jwt|opaque>
    re.compile(r'(?P<pre>[Aa]uthorization:\s*(?:Bearer|Basic)\s+)(?P<secret>[\w\-._~+/=]+)'),
    # Bare JWTs
    re.compile(r'(?P<secret>\beyJ[\w\-]{6,}\.[\w\-]{6,}\.[\w\-]{6,})'),
    # AWS access key IDs
    re.compile(r'(?P<secret>\b(?:AKIA|ASIA)[0-9A-Z]{16}\b)'),
    # PEM private key blocks
    re.compile(
        r'(?P<secret>-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----)'
    ),
]

# Below this length a "secret" is too generic to blind-replace without
# shredding ordinary log text (e.g. a password of "x" would blank every x).
MIN_LITERAL_LENGTH = 8


def _replace(match: re.Match) -> str:
    groups = match.groupdict()
    return f"{groups.get('pre') or ''}{PLACEHOLDER}{groups.get('post') or ''}"


def redact(text: str, extra_secrets: list[str] | None = None) -> str:
    """Return `text` with credentials replaced by a placeholder."""
    if not text:
        return text

    # Literals first: an exact match is unambiguous, and doing it before the
    # patterns means a DSN password is caught even if the DSN form is unusual.
    for secret in extra_secrets or []:
        if secret and len(secret) >= MIN_LITERAL_LENGTH:
            text = text.replace(secret, PLACEHOLDER)

    for pattern in PATTERNS:
        text = pattern.sub(_replace, text)

    return text


def secrets_from_environment(environment: dict) -> list[str]:
    """Pick the values worth redacting literally out of a container env.

    Returns values rather than keys: it is the value that will show up in a
    traceback or a `print(os.environ)`, in whatever formatting the app chose.
    """
    interesting = ('PASSWORD', 'SECRET', 'TOKEN', 'API_KEY', 'DATABASE_URL', 'DSN', 'CREDENTIAL')
    found: list[str] = []
    for key, value in (environment or {}).items():
        text = str(value)
        if len(text) < MIN_LITERAL_LENGTH:
            continue
        if any(needle in key.upper() for needle in interesting):
            found.append(text)
            # A DSN also embeds the raw password; redact that on its own so a
            # log line printing only the password is still caught.
            match = re.search(r'://[^:/\s]+:([^@\s]+)@', text)
            if match:
                found.append(match.group(1))
    # Longest first, so a DSN is replaced before its substring password is.
    return sorted(set(found), key=len, reverse=True)
