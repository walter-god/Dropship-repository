"""Upload validators.

Enforced in the serializer rather than only on the model field, because
`nginx`'s `client_max_body_size` is bypassed entirely by anything talking to
`backend:8000` directly — which includes every student container, since they
share a Docker network with the backend.

The extension allowlists are also an anti-XSS control: uploads are served from
`/media/` on the same origin as the SPA, so an uploaded `.html` or `.svg` would
otherwise be stored XSS against a logged-in admin.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

SOURCE_ARCHIVE_EXTENSIONS = {'.zip'}

# Deliberately excludes anything a browser will render in-origin
# (.html, .htm, .svg, .xml, .js, .pdf).
DISTRIBUTABLE_EXTENSIONS = {
    '.zip', '.apk', '.ipa', '.jar', '.exe', '.msi', '.dmg', '.deb', '.rpm',
    '.tar', '.gz', '.tgz', '.bz2', '.xz', '.7z', '.appimage',
}


def _extension(filename: str) -> str:
    name = (filename or '').lower()
    return name[name.rfind('.'):] if '.' in name else ''


def _check(uploaded, allowed: set[str], max_mb: int, label: str):
    if not uploaded:
        return uploaded

    extension = _extension(getattr(uploaded, 'name', ''))
    if extension not in allowed:
        raise ValidationError(
            _('%(label)s must be one of: %(allowed)s (got "%(got)s").') % {
                'label': label,
                'allowed': ', '.join(sorted(allowed)),
                'got': extension or 'no extension',
            }
        )

    size = getattr(uploaded, 'size', None)
    if size is not None and size > max_mb * 1024 * 1024:
        raise ValidationError(
            _('%(label)s is %(size)s MB, over the %(max)s MB limit.') % {
                'label': label,
                'size': size // (1024 * 1024),
                'max': max_mb,
            }
        )
    return uploaded


def validate_source_archive(uploaded):
    """A buildable project archive. Zip only — the extractor only reads zips."""
    return _check(
        uploaded,
        SOURCE_ARCHIVE_EXTENSIONS,
        getattr(settings, 'MARKETPLACE_MAX_SOURCE_UPLOAD_MB', 100),
        'Source archive',
    )


def validate_distributable(uploaded):
    """A downloadable package listed in the marketplace."""
    return _check(
        uploaded,
        DISTRIBUTABLE_EXTENSIONS,
        getattr(settings, 'MARKETPLACE_MAX_APP_FILE_MB', 500),
        'Application package',
    )
