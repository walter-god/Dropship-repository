"""Sanity checks for a student- or admin-supplied Dockerfile.

This is best-effort, not a sandbox: a Dockerfile builds inside the same
non-root, cap-dropped, network-isolated container regime as every templated
build (see services.run_container), and that runtime posture — not this
module — is the actual security boundary. What this module catches is the
class of Dockerfile that would either defeat that posture (FROM scratch has no
shell to drop privileges in a meaningful way; a stray privileged flag baked
into a RUN line is a tell) or simply fail in a confusing way later (no EXPOSE
and no port override means the health check has nothing to poll).
"""

from __future__ import annotations

import re


class DockerfileValidationError(Exception):
    """The Dockerfile was rejected before it reached `docker build`."""


# Substrings that have no legitimate reason to appear in a Dockerfile: they
# are docker-run flags, not Dockerfile instructions, so their presence reads
# as an attempt to smuggle a privilege escalation through a RUN/ONBUILD line
# (e.g. a build step that shells out to `docker run --privileged ...` against
# the mounted socket).
DISALLOWED_SUBSTRINGS = [
    '--privileged',
    '--cap-add',
    '--security-opt',
    '--pid=host',
    '--network=host',
    '--user=root',
    '/var/run/docker.sock',
    'sys_admin',
]

EXPOSE_RE = re.compile(r'^\s*EXPOSE\s+(\d+)', re.IGNORECASE | re.MULTILINE)
FROM_SCRATCH_RE = re.compile(r'^\s*FROM\s+scratch\b', re.IGNORECASE | re.MULTILINE)


def find_exposed_port(dockerfile_text: str) -> int | None:
    match = EXPOSE_RE.search(dockerfile_text)
    return int(match.group(1)) if match else None


def validate_dockerfile(dockerfile_text: str, port_override: int | None = None) -> None:
    """Raise DockerfileValidationError if the Dockerfile is not acceptable.

    `port_override` should be the admin-supplied container_port from the
    deploy request, if any — its presence satisfies the EXPOSE requirement
    even when the Dockerfile itself declares none.
    """
    if not dockerfile_text or not dockerfile_text.strip():
        raise DockerfileValidationError('The Dockerfile is empty.')

    if FROM_SCRATCH_RE.search(dockerfile_text):
        raise DockerfileValidationError(
            "'FROM scratch' is not allowed — use a minimal base image "
            '(e.g. alpine or distroless) instead.'
        )

    lowered = dockerfile_text.lower()
    for needle in DISALLOWED_SUBSTRINGS:
        if needle in lowered:
            raise DockerfileValidationError(
                f"The Dockerfile contains '{needle}', which is not permitted. "
                'Container privileges and networking are controlled by the '
                'platform, not the Dockerfile.'
            )

    if find_exposed_port(dockerfile_text) is None and port_override is None:
        raise DockerfileValidationError(
            'No EXPOSE instruction was found, and no port was specified in the '
            'deploy request. Add `EXPOSE <port>` to the Dockerfile, or set a '
            'port override before deploying.'
        )
