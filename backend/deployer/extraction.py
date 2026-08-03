"""Safe extraction of student-supplied source archives.

The zip is untrusted input uploaded by a student, so this module assumes it is
hostile: path traversal (zip-slip), absolute paths, symlinks pointing outside
the build directory, and decompression bombs are all rejected before a single
byte is written to disk.
"""

from __future__ import annotations

import logging
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# Archive noise that should never influence project-root detection.
IGNORED_NAMES = {'__MACOSX', '.DS_Store', 'Thumbs.db'}

S_IFLNK = 0o120000
S_IFMT = 0o170000


class UnsafeArchive(Exception):
    """The archive was rejected before extraction."""


@dataclass
class ExtractionResult:
    root: Path
    file_count: int
    total_bytes: int

    @property
    def has_dockerfile(self) -> bool:
        return (self.root / 'Dockerfile').is_file()


def _is_ignored(name: str) -> bool:
    parts = Path(name).parts
    return any(part in IGNORED_NAMES for part in parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & S_IFMT == S_IFLNK


def _validate(info: zipfile.ZipInfo, dest: Path) -> Path:
    """Return the safe destination path, or raise UnsafeArchive."""
    name = info.filename

    if name.startswith('/') or os.path.isabs(name) or (len(name) > 1 and name[1] == ':'):
        raise UnsafeArchive(f'Archive contains an absolute path: {name!r}')

    parts = Path(name).parts
    if '..' in parts:
        raise UnsafeArchive(f'Archive contains a parent-directory reference: {name!r}')

    if _is_symlink(info):
        raise UnsafeArchive(f'Archive contains a symlink, which is not allowed: {name!r}')

    target = (dest / name).resolve()
    # The decisive check: resolved target must stay inside the build directory.
    if not str(target).startswith(str(dest.resolve()) + os.sep) and target != dest.resolve():
        raise UnsafeArchive(f'Archive entry escapes the build directory: {name!r}')

    return target


def _find_project_root(dest: Path) -> Path:
    """Descend through a single wrapper directory if the zip has one.

    Zipping a folder (rather than its contents) is the common case, and it
    would otherwise hide requirements.txt one level down from every detector.
    """
    entries = [e for e in dest.iterdir() if not _is_ignored(e.name)]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return dest


def safe_extract(
    zip_path: str | Path,
    dest_dir: str | Path,
    max_bytes: int | None = None,
    max_files: int | None = None,
    max_ratio: int | None = None,
) -> ExtractionResult:
    """Extract `zip_path` into `dest_dir`, enforcing safety and size limits."""
    zip_path = Path(zip_path)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    if max_bytes is None:
        max_bytes = settings.DEPLOYER_MAX_EXTRACTED_MB * 1024 * 1024
    if max_files is None:
        max_files = settings.DEPLOYER_MAX_EXTRACTED_FILES
    if max_ratio is None:
        max_ratio = settings.DEPLOYER_MAX_COMPRESSION_RATIO

    if not zip_path.is_file():
        raise UnsafeArchive(f'Source archive not found at {zip_path}')

    if not zipfile.is_zipfile(zip_path):
        raise UnsafeArchive(
            'The uploaded source file is not a valid zip archive.'
        )

    total = 0
    count = 0

    with zipfile.ZipFile(zip_path) as archive:
        infos = [i for i in archive.infolist() if not _is_ignored(i.filename)]

        # Cheap pre-flight from the manifest, so an obvious bomb is rejected
        # without writing anything.
        declared = sum(i.file_size for i in infos)
        if declared > max_bytes:
            raise UnsafeArchive(
                f'Archive expands to {declared // (1024 * 1024)} MB, over the '
                f'{max_bytes // (1024 * 1024)} MB limit.'
            )
        if len(infos) > max_files:
            raise UnsafeArchive(
                f'Archive contains {len(infos)} entries, over the {max_files} limit.'
            )

        # Compression ratio, checked separately from absolute size: a 500 KB
        # archive that expands to just under the size cap still costs real CPU
        # and I/O, and no honest source tree compresses anywhere near this
        # hard. Per-entry as well as aggregate, so one pathological member
        # cannot hide inside an otherwise normal archive.
        compressed = sum(i.compress_size for i in infos)
        if compressed > 0 and (declared / compressed) > max_ratio:
            raise UnsafeArchive(
                f'Archive compression ratio is {declared // max(compressed, 1)}:1, over '
                f'the {max_ratio}:1 limit — this looks like a decompression bomb.'
            )
        for info in infos:
            if info.compress_size > 0 and (info.file_size / info.compress_size) > max_ratio:
                raise UnsafeArchive(
                    f'Entry {info.filename!r} has a compression ratio of '
                    f'{info.file_size // max(info.compress_size, 1)}:1, over the '
                    f'{max_ratio}:1 limit.'
                )

        for info in infos:
            target = _validate(info, dest)

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)

            # Stream, enforcing the limit again — the manifest is attacker
            # controlled and can understate the real size.
            with archive.open(info) as src, open(target, 'wb') as dst:
                while chunk := src.read(64 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise UnsafeArchive(
                            f'Archive exceeded the {max_bytes // (1024 * 1024)} MB '
                            'limit during extraction.'
                        )
                    dst.write(chunk)
            count += 1

    root = _find_project_root(dest)
    logger.info('Extracted %s files (%s bytes) to %s', count, total, root)
    return ExtractionResult(root=root, file_count=count, total_bytes=total)


def cleanup_build_dir(path: str | Path) -> None:
    """Remove a build directory, never raising."""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning('Could not clean build dir %s: %s', path, exc)
