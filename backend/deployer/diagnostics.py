"""Turn build and container output into one sentence an admin can act on.

A failed deploy leaves behind hundreds of lines of pip/npm/Docker noise. This
module extracts the one line that actually explains the failure and phrases it
as an instruction, so the admin does not have to read the log to know what to
tell the student.

Both sources matter, and for different reasons: a missing dependency in
requirements.txt often builds cleanly and only fails at startup, so the
ModuleNotFoundError exists solely in the *container* log, never the build log.
"""

from __future__ import annotations

import re

# (pattern, template) — first match wins, so order from specific to general.
BUILD_PATTERNS: list[tuple[str, str]] = [
    (
        r'Could not find a version that satisfies the requirement ([^\s(]+)',
        "Build failed: no installable version of '{0}' was found. Check the "
        "spelling and version pin in requirements.txt.",
    ),
    (
        r'No matching distribution found for ([^\s]+)',
        "Build failed: package '{0}' does not exist on PyPI. Check requirements.txt.",
    ),
    (
        r'ERROR: Could not open requirements file: .*?No such file or directory: '
        r"'?([^'\s]+)'?",
        "Build failed: '{0}' is missing from the uploaded archive.",
    ),
    (
        r'npm ERR! notarget No matching version found for ([^\s.]+)',
        "Build failed: npm package '{0}' has no matching version. Check package.json.",
    ),
    (
        r'npm ERR! code E404[\s\S]{0,200}?npm ERR! 404\s+\'?([^\'\s]+)',
        "Build failed: npm package '{0}' was not found in the registry.",
    ),
    (
        r'npm ERR! `npm ci` can only install packages when your package\.json and '
        r'package-lock\.json',
        'Build failed: package-lock.json is missing or out of sync with '
        'package.json. Run `npm install` locally and re-upload with the lockfile.',
    ),
    (
        r'failed to compute cache key: .*?"?/?([^"\s]+)"?: not found',
        "Build failed: the Dockerfile copies '{0}', which is not in the archive.",
    ),
    (
        r'COPY failed: .*?no such file or directory.*?([^\s/]+)$',
        "Build failed: the Dockerfile copies '{0}', which is not in the archive.",
    ),
    (
        r'executor failed running \[(.+?)\]: exit code: (\d+)',
        "Build failed: the step `{0}` exited with code {1}.",
    ),
    (
        r'The command .*?returned a non-zero code: (\d+)',
        'Build failed: a Dockerfile step exited with code {0}.',
    ),
    (
        r'(?:manifest for |pull access denied for )([^\s,]+).*?not found',
        "Build failed: base image '{0}' could not be pulled. Check the FROM line.",
    ),
    (
        r'composer\b.*?(Your requirements could not be resolved[^\n]*)',
        'Build failed: Composer could not resolve dependencies. {0}',
    ),
]

RUNTIME_PATTERNS: list[tuple[str, str]] = [
    (
        r"ModuleNotFoundError: No module named '([^']+)'",
        "App crashed on startup: Python module '{0}' is not installed. Add it "
        "to requirements.txt and redeploy.",
    ),
    (
        r"ImportError: cannot import name '([^']+)'",
        "App crashed on startup: could not import '{0}' — likely a version "
        "mismatch between pinned dependencies.",
    ),
    (
        r"Error: Cannot find module '([^']+)'",
        "App crashed on startup: Node module '{0}' is not installed. Add it to "
        "package.json and redeploy.",
    ),
    (
        r'exec: "([^"]+)": executable file not found',
        "App crashed on startup: the start command '{0}' does not exist in the image.",
    ),
    (
        r'(?:Address already in use|EADDRINUSE).*?(\d{2,5})',
        'App crashed on startup: port {0} is already bound inside the container.',
    ),
    (
        r'Permission denied.*?bind.*?:(\d{1,5})',
        'App crashed on startup: cannot bind port {0}. Containers run as a '
        'non-root user, so the app must listen on a port above 1024.',
    ),
    (
        r'(django\.db\.utils\.OperationalError: [^\n]+)',
        'App crashed on startup: {0}',
    ),
    (
        r'(psycopg2\.OperationalError: [^\n]+)',
        'App crashed on startup: database connection failed — {0}',
    ),
    (
        r'(SyntaxError: [^\n]+)',
        'App crashed on startup: {0}',
    ),
    (
        r'gunicorn.*?Worker failed to boot',
        'App crashed on startup: the Gunicorn worker failed to boot. Check that '
        'the module path in the start command matches the project layout.',
    ),
]

STAGE_FALLBACKS = {
    'extract': 'The uploaded archive could not be extracted.',
    'validate': 'The supplied Dockerfile was rejected before the build started.',
    'detect': 'No runtime template matched this project, and it contains no Dockerfile.',
    'database': 'The dedicated Postgres database could not be provisioned.',
    'build': 'The Docker build failed. See the build log for the full output.',
    'network': 'The per-app Docker network could not be created.',
    'run': 'The container could not be started.',
    'migrate': 'Database migrations failed.',
    'health': 'The app started but never returned HTTP 200 on its health path.',
}


def tail(text: str, lines: int = 40) -> str:
    if not text:
        return ''
    return '\n'.join(text.strip().splitlines()[-lines:])


def _scan(text: str, patterns: list[tuple[str, str]]) -> str | None:
    if not text:
        return None
    for pattern, template in patterns:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            groups = [g.strip() if g else '' for g in match.groups()]
            try:
                return template.format(*groups)
            except (IndexError, KeyError):
                return template
    return None


def summarize_failure(
    stage: str,
    build_log: str = '',
    container_log: str = '',
    error: str = '',
) -> str:
    """Produce a one-line, human-readable explanation of a failed deploy."""
    # Runtime output is checked first: when a container crash-loops, its log
    # holds the real cause while the build log looks perfectly healthy.
    summary = _scan(container_log, RUNTIME_PATTERNS)
    if summary:
        return summary

    summary = _scan(build_log, BUILD_PATTERNS)
    if summary:
        return summary

    # Runtime-shaped errors also surface during a build — `npm run build` or a
    # Django collectstatic step can raise the same missing-module error — so
    # the runtime patterns get a second pass against build output.
    summary = _scan(build_log, RUNTIME_PATTERNS)
    if summary:
        return summary

    # Docker's own error text is usually clearer than a generic fallback.
    if error:
        cleaned = ' '.join(error.strip().split())
        if cleaned:
            return f'{STAGE_FALLBACKS.get(stage, "Deployment failed.")} {cleaned}'[:1000]

    return STAGE_FALLBACKS.get(stage, 'Deployment failed for an unknown reason.')
