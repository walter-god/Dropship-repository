"""Runtime auto-detection.

Two entry points share one matching engine via a small `_FileView`
abstraction:

* `detect_runtime(project_root)` — disk-backed, used by the deploy pipeline
  against an already-extracted project. This is the original, tested
  function; its signature and return value (a RuntimeTemplate or None) are
  unchanged.
* `detect_from_archive(zip_path)` — zip-backed, used for the instant
  upload-time preview. It never writes anything to disk: it inspects the
  central directory and reads a handful of small manifest files (package.json,
  requirements.txt, ...) straight out of the archive.

Keeping these as two thin wrappers around one `_matches()` function is
deliberate — two independent reimplementations of "what does a Flask project
look like" would drift apart the first time either one is edited.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath

from .extraction import IGNORED_NAMES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File views — the seam between "detection logic" and "where the files live"
# ---------------------------------------------------------------------------

class _FileView(ABC):
    """A read-only, minimal view over a project tree."""

    @abstractmethod
    def exists(self, name: str) -> bool: ...

    @abstractmethod
    def read_text(self, name: str, limit: int = 200_000) -> str: ...

    @abstractmethod
    def glob_exists(self, pattern: str) -> bool:
        """True if any file, at any depth, matches `pattern` by basename."""


class _DiskView(_FileView):
    def __init__(self, root: Path):
        self._root = root

    def exists(self, name: str) -> bool:
        return (self._root / name).exists()

    def read_text(self, name: str, limit: int = 200_000) -> str:
        try:
            return (self._root / name).read_text(encoding='utf-8', errors='replace')[:limit]
        except OSError:
            return ''

    def glob_exists(self, pattern: str) -> bool:
        try:
            return next(self._root.glob(f'**/{pattern}'), None) is not None
        except OSError:
            return False


class _ZipView(_FileView):
    """Peeks at a zip's central directory without extracting anything.

    `source` may be a path or any seekable file-like object (Django's
    UploadedFile subclasses all qualify), so this can inspect a zip that only
    exists in memory — the common case for the student-facing upload preview,
    where nothing has hit disk yet.

    Applies the same "single wrapper directory" convention as
    extraction.safe_extract (zipping a folder rather than its contents is the
    common case), so detection results match what extraction will actually
    produce.
    """

    def __init__(self, source):
        with zipfile.ZipFile(source) as archive:
            entries = [
                n for n in archive.namelist()
                if not n.endswith('/') and not self._is_ignored(n)
            ]
            prefix = self._wrapper_prefix(entries)
            self._by_logical_name: dict[str, str] = {}
            for entry in entries:
                logical = entry[len(prefix):].lstrip('/') if prefix else entry
                self._by_logical_name[logical] = entry
            self._source = source

    def _reopen(self):
        """Re-seek a file-like source so repeated reads don't need a fresh open.

        zipfile itself seeks freely on a real path, but a Django UploadedFile
        is a single shared stream — resetting position 0 before each open call
        keeps concurrent reads (e.g. glob check followed by a content read)
        from stepping on each other.
        """
        if hasattr(self._source, 'seek'):
            try:
                self._source.seek(0)
            except (AttributeError, ValueError, OSError):
                pass

    @staticmethod
    def _is_ignored(name: str) -> bool:
        return any(part in IGNORED_NAMES for part in PurePosixPath(name).parts)

    @staticmethod
    def _wrapper_prefix(entries: list[str]) -> str:
        top_level_parts = set()
        has_bare_file = False
        for entry in entries:
            parts = PurePosixPath(entry).parts
            if len(parts) == 1:
                has_bare_file = True
            else:
                top_level_parts.add(parts[0])
        if len(top_level_parts) == 1 and not has_bare_file:
            return next(iter(top_level_parts)) + '/'
        return ''

    def exists(self, name: str) -> bool:
        return name in self._by_logical_name

    def read_text(self, name: str, limit: int = 200_000) -> str:
        entry = self._by_logical_name.get(name)
        if not entry:
            return ''
        self._reopen()
        try:
            with zipfile.ZipFile(self._source) as archive, archive.open(entry) as fh:
                return fh.read(limit).decode('utf-8', errors='replace')
        except (KeyError, OSError, zipfile.BadZipFile):
            return ''

    def glob_exists(self, pattern: str) -> bool:
        return any(
            fnmatch.fnmatch(PurePosixPath(name).name, pattern)
            for name in self._by_logical_name
        )


# ---------------------------------------------------------------------------
# Tier-A matching (backed by RuntimeTemplate.detection_hints)
# ---------------------------------------------------------------------------

def _package_json_deps(view: _FileView) -> set[str]:
    raw = view.read_text('package.json')
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


def _matches(view: _FileView, hints: dict) -> bool:
    """True when every declared hint is satisfied."""
    for name in hints.get('require_files', []):
        if not view.exists(name):
            return False

    for name in hints.get('require_absent', []):
        if view.exists(name):
            return False

    any_files = hints.get('any_files', [])
    if any_files and not any(view.exists(name) for name in any_files):
        return False

    wanted_deps = set(hints.get('package_json_deps', []))
    if wanted_deps and not (wanted_deps & _package_json_deps(view)):
        return False

    for probe in hints.get('content_matches', []):
        target = probe.get('file', '')
        pattern = probe.get('pattern', '')
        if not pattern:
            continue
        text = view.read_text(target)
        if not text:
            return False
        if not re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
            return False

    return True


def _sorted_templates():
    from .models import RuntimeTemplate
    templates = list(RuntimeTemplate.objects.all())
    # Highest priority first; ties broken by key for determinism.
    templates.sort(key=lambda t: (-(t.detection_hints or {}).get('priority', 0), t.key))
    return templates


def detect_runtime(project_root: str | Path):
    """Return the best-matching RuntimeTemplate for an extracted project, or None.

    Used by the deploy pipeline once the archive is already on disk.
    """
    view = _DiskView(Path(project_root))
    for template in _sorted_templates():
        hints = template.detection_hints or {}
        if hints and _matches(view, hints):
            logger.info('Detected runtime %s for %s', template.key, project_root)
            return template
    logger.warning('No runtime template matched %s', project_root)
    return None


# ---------------------------------------------------------------------------
# Tier B — recognized-but-unsupported stacks (no auto-buildable template)
# ---------------------------------------------------------------------------

OTHER_STACK_HINTS = [
    {'key': 'java-maven', 'language': 'Java (Maven)', 'files': ['pom.xml']},
    {'key': 'java-gradle', 'language': 'Java (Gradle)',
     'files': ['build.gradle', 'build.gradle.kts']},
    {'key': 'dotnet', 'language': '.NET', 'globs': ['*.csproj']},
    {'key': 'go', 'language': 'Go', 'files': ['go.mod']},
    {'key': 'ruby-rails', 'language': 'Ruby (Rails)', 'files': ['Gemfile']},
    {'key': 'rust', 'language': 'Rust', 'files': ['Cargo.toml']},
]


def describe_detection(view: _FileView) -> dict:
    """Return {runtime_key, confidence, reason, needs_dockerfile} for `view`.

    Shared by both public entry points below, so the student-facing preview
    and the persisted Application fields are always computed the same way.
    """
    if view.exists('Dockerfile'):
        return {
            'runtime_key': 'custom',
            'confidence': 'high',
            'reason': 'A Dockerfile was found at the project root — it will be used as-is.',
            'needs_dockerfile': False,
        }

    for template in _sorted_templates():
        hints = template.detection_hints or {}
        if hints and _matches(view, hints):
            return {
                'runtime_key': template.key,
                'confidence': 'high',
                'reason': f'Recognized as {template.display_name}. This can be '
                          'deployed automatically.',
                'needs_dockerfile': False,
            }

    for spec in OTHER_STACK_HINTS:
        found = any(view.exists(f) for f in spec.get('files', [])) or \
            any(view.glob_exists(g) for g in spec.get('globs', []))
        if found:
            return {
                'runtime_key': spec['key'],
                'confidence': 'low',
                'reason': f"Detected {spec['language']}, which has no automatic build "
                          'template. Add a Dockerfile to your project root.',
                'needs_dockerfile': True,
            }

    return {
        'runtime_key': '',
        'confidence': 'none',
        'reason': "Could not recognize this project's structure.",
        'needs_dockerfile': True,
    }


def detect_from_archive(zip_source) -> dict:
    """Stateless detection straight from a zip — no extraction.

    `zip_source` may be a path or a seekable file-like object (a Django
    UploadedFile, most commonly). Used for the instant "Detected: Django"
    feedback on upload, and for persisting detection results whenever an
    Application's source_code changes.
    """
    try:
        view = _ZipView(zip_source)
    except (OSError, zipfile.BadZipFile):
        return {
            'runtime_key': '',
            'confidence': 'none',
            'reason': 'The uploaded file is not a valid zip archive.',
            'needs_dockerfile': True,
        }
    return describe_detection(view)


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
