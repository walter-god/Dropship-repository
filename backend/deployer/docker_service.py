"""The only module in the project that talks to Docker.

Everything above this line — views, tasks, services — works against the
`DockerService` interface and the plain dataclasses below. No `docker.*` object
and no `docker.errors.*` exception is allowed to escape, so this can later be
swapped for a client of a remote deployer daemon by pointing the
DEPLOYER_DOCKER_SERVICE setting at a different class.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

# Applied to everything the deployer creates, so orphans are identifiable.
MANAGED_LABEL = 'udom.managed'
SLUG_LABEL = 'udom.app_slug'


# ---------------------------------------------------------------------------
# Errors — the public failure vocabulary
# ---------------------------------------------------------------------------

class DockerServiceError(Exception):
    """Base class for every failure this module reports."""


class DockerUnavailable(DockerServiceError):
    """The Docker daemon could not be reached at all."""


class ImageBuildError(DockerServiceError):
    """The build itself failed. `log_tail` carries the last output seen."""

    def __init__(self, message: str, log_tail: str = ''):
        super().__init__(message)
        self.log_tail = log_tail


class BuildTimeout(ImageBuildError):
    """The build exceeded its deadline and was abandoned."""


class ImageTooLarge(DockerServiceError):
    def __init__(self, message: str, size_bytes: int, limit_bytes: int):
        super().__init__(message)
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes


class ContainerFailure(DockerServiceError):
    """A container could not be created, started, or inspected."""


class ResourceNotFound(DockerServiceError):
    """A named container, image, or network does not exist."""


# ---------------------------------------------------------------------------
# Value objects — never leak SDK types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BuildResult:
    image_tag: str
    image_id: str
    size_bytes: int


@dataclass(frozen=True)
class ContainerInfo:
    id: str
    name: str
    status: str


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class NetworkInfo:
    id: str
    name: str


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class DockerService(ABC):
    """Narrow contract the deployment pipeline depends on."""

    # -- images ------------------------------------------------------------
    @abstractmethod
    def build_image(
        self,
        context_dir: str,
        tag: str,
        dockerfile: str = 'Dockerfile',
        timeout: int = 600,
        on_log: Callable[[str], None] | None = None,
        labels: dict | None = None,
    ) -> BuildResult: ...

    @abstractmethod
    def remove_image(self, tag: str, force: bool = True) -> None: ...

    # -- networks ----------------------------------------------------------
    @abstractmethod
    def ensure_network(self, name: str, labels: dict | None = None) -> NetworkInfo: ...

    @abstractmethod
    def remove_network(self, name: str) -> None: ...

    @abstractmethod
    def connect_container(self, network: str, container: str) -> None: ...

    @abstractmethod
    def disconnect_container(self, network: str, container: str) -> None: ...

    # -- containers --------------------------------------------------------
    @abstractmethod
    def run_container(
        self,
        image_tag: str,
        name: str,
        network: str,
        environment: dict,
        memory_mb: int,
        cpu_limit: float,
        user: str,
        pids_limit: int,
        labels: dict | None = None,
    ) -> ContainerInfo: ...

    @abstractmethod
    def start_container(self, ref: str) -> None: ...

    @abstractmethod
    def stop_container(self, ref: str, timeout: int = 10) -> None: ...

    @abstractmethod
    def restart_container(self, ref: str, timeout: int = 10) -> None: ...

    @abstractmethod
    def remove_container(self, ref: str, force: bool = True) -> None: ...

    @abstractmethod
    def container_status(self, ref: str) -> str: ...

    @abstractmethod
    def container_logs(self, ref: str, tail: int = 200) -> str: ...

    @abstractmethod
    def exec_in_container(self, ref: str, command: str, timeout: int = 300) -> ExecResult: ...

    @abstractmethod
    def container_exists(self, ref: str) -> bool: ...


# ---------------------------------------------------------------------------
# Local implementation — talks to the mounted /var/run/docker.sock
# ---------------------------------------------------------------------------

class LocalDockerService(DockerService):

    def __init__(self):
        self._client = None

    @property
    def client(self):
        """Connect lazily so importing this module never requires a daemon."""
        if self._client is None:
            import docker
            from docker.errors import DockerException
            try:
                self._client = docker.from_env()
                self._client.ping()
            except DockerException as exc:
                raise DockerUnavailable(
                    'Cannot reach the Docker daemon. Is /var/run/docker.sock '
                    f'mounted into this container? ({exc})'
                ) from exc
        return self._client

    @staticmethod
    def _labels(extra: dict | None = None) -> dict:
        labels = {MANAGED_LABEL: 'true'}
        if extra:
            labels.update({k: str(v) for k, v in extra.items()})
        return labels

    # -- images ------------------------------------------------------------

    def build_image(
        self,
        context_dir: str,
        tag: str,
        dockerfile: str = 'Dockerfile',
        timeout: int = 600,
        on_log: Callable[[str], None] | None = None,
        labels: dict | None = None,
    ) -> BuildResult:
        from docker.errors import APIError, BuildError

        deadline = time.monotonic() + timeout
        recent: list[str] = []

        def emit(text: str):
            recent.append(text)
            del recent[:-80]  # keep only a tail for error reporting
            if on_log:
                on_log(text)

        try:
            stream = self.client.api.build(
                path=context_dir,
                dockerfile=dockerfile,
                tag=tag,
                rm=True,
                forcerm=True,
                decode=True,
                pull=False,
                labels=self._labels(labels),
            )
        except (APIError, BuildError) as exc:
            raise ImageBuildError(f'Could not start build: {exc}') from exc

        try:
            for chunk in stream:
                # A build can hang for a very long time on a bad network or a
                # pathological Dockerfile; the SDK offers no native timeout, so
                # the deadline is enforced here between chunks.
                if time.monotonic() > deadline:
                    self._close_quietly(stream)
                    raise BuildTimeout(
                        f'Build exceeded the {timeout}s limit and was aborted.',
                        log_tail=''.join(recent),
                    )

                if 'stream' in chunk:
                    emit(chunk['stream'])
                elif 'status' in chunk:
                    progress = chunk.get('progress', '')
                    emit(f"{chunk['status']} {progress}\n")

                if 'error' in chunk:
                    detail = chunk.get('errorDetail', {}) or {}
                    message = detail.get('message') or chunk['error']
                    emit(f'\nERROR: {message}\n')
                    raise ImageBuildError(message, log_tail=''.join(recent))
        except ImageBuildError:
            raise
        except APIError as exc:
            raise ImageBuildError(f'Build failed: {exc}', log_tail=''.join(recent)) from exc
        finally:
            self._close_quietly(stream)

        try:
            image = self.client.images.get(tag)
        except Exception as exc:
            raise ImageBuildError(
                'Build reported success but the image is missing.',
                log_tail=''.join(recent),
            ) from exc

        return BuildResult(
            image_tag=tag,
            image_id=image.id,
            size_bytes=int(image.attrs.get('Size') or 0),
        )

    @staticmethod
    def _close_quietly(stream):
        try:
            stream.close()
        except Exception:  # noqa: BLE001 - closing must never mask the real error
            pass

    def remove_image(self, tag: str, force: bool = True) -> None:
        from docker.errors import APIError, ImageNotFound
        try:
            self.client.images.remove(image=tag, force=force)
        except ImageNotFound:
            logger.debug('Image %s already gone', tag)
        except APIError as exc:
            # A dangling image is untidy but not fatal — never fail cleanup on it.
            logger.warning('Could not remove image %s: %s', tag, exc)

    # -- networks ----------------------------------------------------------

    def ensure_network(self, name: str, labels: dict | None = None) -> NetworkInfo:
        from docker.errors import APIError, NotFound
        try:
            net = self.client.networks.get(name)
            return NetworkInfo(id=net.id, name=net.name)
        except NotFound:
            pass
        except APIError as exc:
            raise DockerServiceError(f'Could not inspect network {name}: {exc}') from exc

        try:
            net = self.client.networks.create(
                name, driver='bridge', labels=self._labels(labels)
            )
        except APIError as exc:
            # Lost a race with a concurrent deploy — re-fetch rather than fail.
            try:
                net = self.client.networks.get(name)
            except Exception:
                raise DockerServiceError(f'Could not create network {name}: {exc}') from exc
        return NetworkInfo(id=net.id, name=net.name)

    def remove_network(self, name: str) -> None:
        from docker.errors import APIError, NotFound
        try:
            self.client.networks.get(name).remove()
        except NotFound:
            logger.debug('Network %s already gone', name)
        except APIError as exc:
            logger.warning('Could not remove network %s: %s', name, exc)

    def connect_container(self, network: str, container: str) -> None:
        from docker.errors import APIError, NotFound
        try:
            net = self.client.networks.get(network)
        except NotFound as exc:
            raise ResourceNotFound(f'Network {network} does not exist.') from exc
        try:
            net.connect(container)
        except APIError as exc:
            if 'already exists in network' in str(exc) or 'already connected' in str(exc):
                return
            raise DockerServiceError(
                f'Could not connect {container} to {network}: {exc}'
            ) from exc

    def disconnect_container(self, network: str, container: str) -> None:
        from docker.errors import APIError, NotFound
        try:
            self.client.networks.get(network).disconnect(container, force=True)
        except NotFound:
            pass
        except APIError as exc:
            logger.warning('Could not disconnect %s from %s: %s', container, network, exc)

    # -- containers --------------------------------------------------------

    def run_container(
        self,
        image_tag: str,
        name: str,
        network: str,
        environment: dict,
        memory_mb: int,
        cpu_limit: float,
        user: str,
        pids_limit: int,
        labels: dict | None = None,
    ) -> ContainerInfo:
        from docker.errors import APIError, ImageNotFound
        try:
            container = self.client.containers.run(
                image=image_tag,
                name=name,
                detach=True,
                environment={k: str(v) for k, v in environment.items()},
                # Exactly one network, and no `ports` argument anywhere: the
                # app must be unreachable except through the gateway, or the
                # subscription check is trivially bypassed.
                network=network,
                mem_limit=f'{memory_mb}m',
                nano_cpus=int(cpu_limit * 1_000_000_000),
                pids_limit=pids_limit,
                user=user,
                restart_policy={'Name': 'unless-stopped'},
                cap_drop=['ALL'],
                security_opt=['no-new-privileges'],
                labels=self._labels(labels),
            )
        except ImageNotFound as exc:
            raise ResourceNotFound(f'Image {image_tag} not found.') from exc
        except APIError as exc:
            raise ContainerFailure(f'Could not start container {name}: {exc}') from exc

        container.reload()
        return ContainerInfo(id=container.id, name=container.name, status=container.status)

    def _get(self, ref: str):
        from docker.errors import APIError, NotFound
        try:
            return self.client.containers.get(ref)
        except NotFound as exc:
            raise ResourceNotFound(f'Container {ref} does not exist.') from exc
        except APIError as exc:
            raise ContainerFailure(f'Could not inspect container {ref}: {exc}') from exc

    def container_exists(self, ref: str) -> bool:
        try:
            self._get(ref)
            return True
        except ResourceNotFound:
            return False

    def start_container(self, ref: str) -> None:
        from docker.errors import APIError
        try:
            self._get(ref).start()
        except APIError as exc:
            raise ContainerFailure(f'Could not start {ref}: {exc}') from exc

    def stop_container(self, ref: str, timeout: int = 10) -> None:
        from docker.errors import APIError
        try:
            self._get(ref).stop(timeout=timeout)
        except ResourceNotFound:
            pass
        except APIError as exc:
            raise ContainerFailure(f'Could not stop {ref}: {exc}') from exc

    def restart_container(self, ref: str, timeout: int = 10) -> None:
        from docker.errors import APIError
        try:
            self._get(ref).restart(timeout=timeout)
        except APIError as exc:
            raise ContainerFailure(f'Could not restart {ref}: {exc}') from exc

    def remove_container(self, ref: str, force: bool = True) -> None:
        from docker.errors import APIError
        try:
            self._get(ref).remove(force=force, v=True)
        except ResourceNotFound:
            pass
        except APIError as exc:
            logger.warning('Could not remove container %s: %s', ref, exc)

    def container_status(self, ref: str) -> str:
        container = self._get(ref)
        container.reload()
        return container.status

    def container_logs(self, ref: str, tail: int = 200) -> str:
        try:
            raw = self._get(ref).logs(tail=tail, timestamps=False)
        except ResourceNotFound:
            return ''
        except Exception as exc:  # noqa: BLE001 - logs are diagnostic, never fatal
            logger.warning('Could not read logs for %s: %s', ref, exc)
            return ''
        return raw.decode('utf-8', errors='replace')

    def exec_in_container(self, ref: str, command: str, timeout: int = 300) -> ExecResult:
        from docker.errors import APIError
        try:
            exit_code, output = self._get(ref).exec_run(
                cmd=['sh', '-c', command], demux=False
            )
        except APIError as exc:
            raise ContainerFailure(f'Could not exec in {ref}: {exc}') from exc
        text = (output or b'').decode('utf-8', errors='replace')
        return ExecResult(exit_code=exit_code if exit_code is not None else -1, output=text)


# ---------------------------------------------------------------------------
# Accessor
# ---------------------------------------------------------------------------

_service: DockerService | None = None


def get_docker_service() -> DockerService:
    """Return the configured DockerService singleton."""
    global _service
    if _service is None:
        _service = import_string(settings.DEPLOYER_DOCKER_SERVICE)()
    return _service


def reset_docker_service() -> None:
    """Drop the cached instance (used by tests)."""
    global _service
    _service = None
