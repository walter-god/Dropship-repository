"""Runtime auto-detection from an extracted project tree.

Each RuntimeTemplate carries a `detection_hints` JSON blob describing what its
projects look like. Templates are evaluated highest-priority first and the
first full match wins, which is what keeps node-next from being mistaken for
node-express (both have package.json) and python-django for python-flask (both
have requirements.txt).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def _read(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='replace')[:limit]
    except OSError:
        return ''


def _package_json_deps(root: Path) -> set[str]:
    raw = _read(root / 'package.json')
    if not raw:
        return set()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    deps: set[str] = set()
    for key in ('dependencies', 'devDependencies', 'peerDependencies'):
        section = data.get(key)
        if isinstance(section, dict):
            deps.update(section.keys())
    return deps


def _matches(root: Path, hints: dict) -> bool:
    """True when every declared hint is satisfied."""
    # All of these files must exist.
    for name in hints.get('require_files', []):
        if not (root / name).exists():
            return False

    # None of these may exist.
    for name in hints.get('require_absent', []):
        if (root / name).exists():
            return False

    # At least one of these must exist.
    any_files = hints.get('any_files', [])
    if any_files and not any((root / name).exists() for name in any_files):
        return False

    # At least one of these packages must appear in package.json.
    wanted_deps = set(hints.get('package_json_deps', []))
    if wanted_deps and not (wanted_deps & _package_json_deps(root)):
        return False

    # Regex probes against file contents, e.g. "^flask" in requirements.txt.
    for probe in hints.get('content_matches', []):
        target = root / probe.get('file', '')
        pattern = probe.get('pattern', '')
        if not pattern:
            continue
        if not target.is_file():
            return False
        if not re.search(pattern, _read(target), re.IGNORECASE | re.MULTILINE):
            return False

    return True


def detect_runtime(project_root: str | Path):
    """Return the best-matching RuntimeTemplate, or None."""
    from .models import RuntimeTemplate

    root = Path(project_root)
    templates = list(RuntimeTemplate.objects.all())
    # Highest priority first; ties broken by key for determinism.
    templates.sort(
        key=lambda t: (-(t.detection_hints or {}).get('priority', 0), t.key)
    )

    for template in templates:
        hints = template.detection_hints or {}
        if not hints:
            continue
        if _matches(root, hints):
            logger.info('Detected runtime %s for %s', template.key, root)
            return template

    logger.warning('No runtime template matched %s', root)
    return None


def describe_tree(project_root: str | Path, limit: int = 40) -> str:
    """A short listing of the project root, for failure messages."""
    root = Path(project_root)
    try:
        names = sorted(p.name + ('/' if p.is_dir() else '') for p in root.iterdir())
    except OSError:
        return '(unreadable)'
    shown = names[:limit]
    suffix = f' … (+{len(names) - limit} more)' if len(names) > limit else ''
    return ', '.join(shown) + suffix
