"""Deployment orchestration.

The pipeline lives here rather than in tasks.py so it can be exercised without
a broker, and so views never reach past this layer into Docker. Everything
Docker-shaped goes through `docker_service`.
"""

from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from gateway import allowlist
from gateway.models import HostedApp

from . import db_provision, diagnostics
from .detection import describe_tree, detect_runtime
from .docker_service import (
    SLUG_LABEL,
    DockerServiceError,
    get_docker_service,
)
from .dockerfile_validation import DockerfileValidationError, find_exposed_port, validate_dockerfile
from .extraction import UnsafeArchive, cleanup_build_dir, safe_extract
from .models import Deployment
from .redaction import redact, secrets_from_environment

logger = logging.getLogger(__name__)

# Container states that mean the app is not coming up on its own.
DEAD_STATES = {'exited', 'dead', 'removing'}


class DeploymentError(Exception):
    """A pipeline stage failed. Carries enough context to explain itself."""

    def __init__(self, stage: str, message: str, container_log: str = ''):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.container_log = container_log


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

def container_name_for(slug: str) -> str:
    return f'{settings.DEPLOYER_CONTAINER_PREFIX}{slug}'


def network_name_for(slug: str) -> str:
    return f'{settings.DEPLOYER_NETWORK_PREFIX}{slug}'


def image_tag_for(slug: str, deployment_id: int) -> str:
    return f'{settings.DEPLOYER_IMAGE_PREFIX}/{slug}:{deployment_id}'


# ---------------------------------------------------------------------------
# Build-log streaming
# ---------------------------------------------------------------------------

class _LogSink:
    """Batches build output and flushes it to the database on an interval.

    Writing every chunk straight through would mean one UPDATE per line of
    Docker output; batching keeps the admin's log live without hammering
    Postgres for the length of a build.

    Everything is redacted on the way out. Build output and migrate output are
    both student-controlled, and the migrate step in particular runs the
    student's own code with the database credentials in its environment.
    """

    def __init__(self, deployment: Deployment, interval: float):
        self._deployment = deployment
        self._interval = interval
        self._buffer: list[str] = []
        self._last_flush = time.monotonic()
        self._secrets: list[str] = []

    def add_secrets(self, secrets_: list[str]) -> None:
        """Register literal values to strip from all subsequent output."""
        self._secrets = sorted(set(self._secrets) | set(secrets_), key=len, reverse=True)

    @property
    def secrets(self) -> list[str]:
        """Literals registered so far, for redacting sinks other than the log."""
        return list(self._secrets)

    def write(self, text: str) -> None:
        if not text:
            return
        self._buffer.append(redact(text, self._secrets))
        if time.monotonic() - self._last_flush >= self._interval:
            self.flush()

    def flush(self) -> None:
        if self._buffer:
            self._deployment.append_log(''.join(self._buffer))
            self._buffer.clear()
        self._last_flush = time.monotonic()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_environment(hosted_app: HostedApp, database_url: str, container_name: str) -> dict:
    """Environment injected into the student container."""
    env_vars = dict(hosted_app.env_vars or {})

    # Persist a stable per-app SECRET_KEY so sessions survive a redeploy.
    if not env_vars.get('SECRET_KEY'):
        env_vars['SECRET_KEY'] = secrets.token_urlsafe(50)
        hosted_app.env_vars = env_vars
        hosted_app.save(update_fields=['env_vars', 'updated_at'])

    env = {
        'PORT': hosted_app.container_port,
        'SECRET_KEY': env_vars['SECRET_KEY'],
        # The gateway proxies with Host set to the container name, so a Django
        # app would reject every request without this.
        'ALLOWED_HOSTS': f'{container_name},localhost,127.0.0.1',
        'PYTHONUNBUFFERED': '1',
    }
    if database_url:
        env['DATABASE_URL'] = database_url

    # Admin-supplied values win, so an admin can override anything above.
    env.update({k: v for k, v in env_vars.items() if k != 'SECRET_KEY'})
    env['SECRET_KEY'] = env_vars['SECRET_KEY']
    return env


def _verify_limits(svc, ref: str, sink, *, memory_mb: int, cpu_limit: float,
                   network_name: str) -> None:
    """Assert the container is running under the isolation we asked for.

    Fails the deploy rather than logging a warning: a container running
    without its memory cap, without a read-only rootfs, as root, or with a
    host mount is a containment failure, and hostile code is inside it.
    """
    applied = svc.inspect_limits(ref)
    expected_memory = memory_mb * 1024 * 1024
    expected_cpus = int(cpu_limit * 1_000_000_000)

    problems = []
    if applied.memory_bytes != expected_memory:
        problems.append(f'memory {applied.memory_bytes} != {expected_memory}')
    if applied.nano_cpus != expected_cpus:
        problems.append(f'nano_cpus {applied.nano_cpus} != {expected_cpus}')
    if applied.pids_limit != settings.DEPLOYER_PIDS_LIMIT:
        problems.append(f'pids_limit {applied.pids_limit} != {settings.DEPLOYER_PIDS_LIMIT}')
    if 'ALL' not in {c.upper() for c in applied.cap_drop}:
        problems.append(f'capabilities not dropped (cap_drop={applied.cap_drop})')
    if not applied.read_only_rootfs:
        problems.append('root filesystem is writable')
    if applied.privileged:
        problems.append('container is privileged')
    if applied.user != settings.DEPLOYER_CONTAINER_USER:
        problems.append(f'user {applied.user!r} != {settings.DEPLOYER_CONTAINER_USER!r}')
    if applied.network_mode != network_name:
        problems.append(f'network {applied.network_mode!r} != {network_name!r}')
    if applied.mounts:
        problems.append(f'unexpected host mounts: {applied.mounts}')

    if problems:
        raise DeploymentError(
            'verify',
            'The container did not start under the required isolation: '
            + '; '.join(problems)
            + '. This usually means the host kernel or cgroup driver does not '
              'support a limit the platform depends on.',
        )
    sink.write('    isolation verified (memory, cpu, pids, caps, read-only, network)\n')


def _wait_until_running(svc, ref: str, timeout: int = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if svc.container_status(ref) == 'running':
            return
        time.sleep(0.5)


def _wait_for_health(svc, container_name: str, port: int, health_path: str, sink: _LogSink) -> None:
    """Poll the app by container name until it answers 200.

    Runs from inside the Celery worker, which is why the worker is attached to
    the per-app network alongside the backend.
    """
    path = health_path if health_path.startswith('/') else f'/{health_path}'
    url = f'http://{container_name}:{port}{path}'
    timeout = settings.DEPLOYER_HEALTH_TIMEOUT_SECONDS
    interval = settings.DEPLOYER_HEALTH_POLL_INTERVAL_SECONDS
    deadline = time.monotonic() + timeout

    sink.write(f'==> Waiting for {url} to return 200 (up to {timeout}s)\n')
    last_error = ''

    while time.monotonic() < deadline:
        # Fail fast on a crash-loop instead of burning the full 90 seconds.
        try:
            state = svc.container_status(container_name)
        except DockerServiceError:
            state = 'unknown'
        if state in DEAD_STATES:
            raise DeploymentError(
                'health',
                f'The container exited immediately (state: {state}).',
                container_log=svc.container_logs(container_name, tail=200),
            )

        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                sink.write(f'==> Healthy after {int(time.monotonic() - (deadline - timeout))}s\n')
                return
            last_error = f'HTTP {response.status_code}'
        except requests.RequestException as exc:
            last_error = type(exc).__name__

        time.sleep(interval)

    raise DeploymentError(
        'health',
        f'No HTTP 200 from {path} within {timeout}s (last: {last_error}).',
        container_log=svc.container_logs(container_name, tail=200),
    )


def _notify(hosted_app: HostedApp, subject: str, body: str, secrets_: list[str] | None = None) -> None:
    """Best-effort notification to the developer. Never fails a deploy.

    Redacts again rather than trusting the caller: this body reaches two sinks
    outside the database (SMTP and the application log), and both persist
    beyond anything the admin UI shows.
    """
    body = redact(body, secrets_ or [])
    recipient = getattr(hosted_app.application.developer, 'email', '')
    logger.info('%s — %s', subject, body)
    if not recipient:
        return
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@udom.ac.tz'),
            recipient_list=[recipient],
            fail_silently=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('Notification failed: %s', exc)


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

def run_deployment(hosted_app: HostedApp, deployment: Deployment) -> None:
    """Build, run, and health-check an app. Cleans up after itself on failure."""
    svc = get_docker_service()
    slug = hosted_app.application.slug
    container_name = container_name_for(slug)
    network_name = network_name_for(slug)
    image_tag = image_tag_for(slug, deployment.pk)
    build_dir = Path(settings.DEPLOYER_BUILD_ROOT) / f'{slug}-{deployment.pk}'
    sink = _LogSink(deployment, settings.DEPLOYER_LOG_FLUSH_INTERVAL_SECONDS)
    labels = {SLUG_LABEL: slug}

    previous_image = _current_image_tag(hosted_app)
    made_image = made_network = made_container = False
    stage = 'init'
    container_log = ''

    try:
        deployment.mark(
            Deployment.STATUS_BUILDING, started_at=timezone.now(), image_tag=image_tag
        )
        hosted_app.mark(HostedApp.STATUS_BUILDING)

        # -- 2. extract ---------------------------------------------------
        stage = 'extract'
        source = hosted_app.application.source_code
        if not source:
            raise DeploymentError('extract', 'This project has no source archive uploaded.')
        sink.write(f'==> Extracting source archive for {slug}\n')
        extracted = safe_extract(source.path, build_dir)
        sink.write(f'    {extracted.file_count} files, {extracted.total_bytes} bytes\n')

        # -- 3. Dockerfile ------------------------------------------------
        stage = 'detect'
        port_override = deployment.requested_container_port
        # Precedence: admin-supplied override > zip-supplied Dockerfile >
        # explicit template override from the deploy request > auto-detect.
        template = deployment.requested_runtime_template or hosted_app.runtime_template

        custom_dockerfile = (
            hosted_app.admin_dockerfile_override.strip() or extracted.has_dockerfile
        )
        if hosted_app.admin_dockerfile_override.strip():
            sink.write('==> Using the Dockerfile uploaded by an admin\n')
            dockerfile_text = hosted_app.admin_dockerfile_override
            dockerfile = 'Dockerfile.udom-admin'
            (extracted.root / dockerfile).write_text(dockerfile_text, encoding='utf-8')
        elif extracted.has_dockerfile:
            sink.write('==> Using the Dockerfile supplied in the archive\n')
            dockerfile = 'Dockerfile'
            dockerfile_text = (extracted.root / dockerfile).read_text(
                encoding='utf-8', errors='replace'
            )

        if custom_dockerfile:
            stage = 'validate'
            validate_dockerfile(dockerfile_text, port_override=port_override)
            stage = 'detect'
            # A supplied Dockerfile means no template applies. Its own EXPOSE
            # is the port of record unless the admin explicitly overrode it —
            # validate_dockerfile already guaranteed one of the two exists.
            template = None
            port_override = port_override or find_exposed_port(dockerfile_text)
        else:
            if template is None:
                template = detect_runtime(extracted.root)
            if template is None:
                raise DeploymentError(
                    'detect',
                    'No runtime matched and the archive has no Dockerfile. '
                    f'Project root contains: {describe_tree(extracted.root)}',
                )
            sink.write(f'==> Detected runtime: {template.display_name}\n')
            dockerfile = 'Dockerfile.udom'
            (extracted.root / dockerfile).write_text(
                template.render_dockerfile(slug=slug, port=template.default_port),
                encoding='utf-8',
            )

        if template is not None:
            hosted_app.runtime_template = template
            hosted_app.container_port = port_override or template.default_port
            hosted_app.needs_database = (
                template.needs_database
                if deployment.requested_provision_database is None
                else deployment.requested_provision_database
            )
            hosted_app.save(
                update_fields=[
                    'runtime_template', 'container_port', 'needs_database', 'updated_at'
                ]
            )
        else:
            # A Dockerfile was supplied directly — no template to source
            # defaults from, so the deploy request (or the current HostedApp
            # settings) is the only source of truth.
            hosted_app.runtime_template = None
            if port_override:
                hosted_app.container_port = port_override
            if deployment.requested_provision_database is not None:
                hosted_app.needs_database = deployment.requested_provision_database
            hosted_app.save(
                update_fields=['runtime_template', 'container_port', 'needs_database', 'updated_at']
            )

        # -- 4. database --------------------------------------------------
        stage = 'database'
        database_url = ''
        if hosted_app.needs_database:
            db_name = hosted_app.db_name or db_provision.make_identifiers(slug)[0]
            db_user = hosted_app.db_user or db_provision.make_identifiers(slug)[1]
            password = db_provision.generate_password()
            sink.write(f'==> Provisioning database {db_name}\n')
            db_provision.provision(db_name, db_user, password)
            database_url = db_provision.build_database_url(db_name, db_user, password)
            hosted_app.db_name = db_name
            hosted_app.db_user = db_user
            hosted_app.db_password = password
            hosted_app.save(
                update_fields=['db_name', 'db_user', 'db_password', 'updated_at']
            )

        # -- 5. build -----------------------------------------------------
        stage = 'build'
        sink.write(f'==> Building image {image_tag}\n')
        result = svc.build_image(
            context_dir=str(extracted.root),
            tag=image_tag,
            dockerfile=dockerfile,
            timeout=settings.DEPLOYER_BUILD_TIMEOUT_SECONDS,
            on_log=sink.write,
            labels=labels,
        )
        made_image = True
        sink.flush()

        # Post-hoc: the SDK cannot abort a build partway on size, so an
        # oversized image is built, rejected, then removed.
        cap = settings.DEPLOYER_MAX_IMAGE_SIZE_MB * 1024 * 1024
        if result.size_bytes > cap:
            raise DeploymentError(
                'build',
                f'Image is {result.size_bytes // (1024 * 1024)} MB, over the '
                f'{settings.DEPLOYER_MAX_IMAGE_SIZE_MB} MB limit.',
            )

        # -- 6. network ---------------------------------------------------
        stage = 'network'
        internal = not hosted_app.allow_egress
        sink.write(
            f'==> Creating network {network_name} '
            f'({"no outbound internet" if internal else "EGRESS ALLOWED"})\n'
        )
        svc.ensure_network(network_name, labels=labels, internal=internal)
        made_network = True
        if not internal:
            logger.warning(
                'App %s is running WITH outbound egress (allow_egress=True).', slug
            )

        # Platform containers join before the app starts, so the health check
        # and any database traffic work from the first moment it boots.
        for platform in settings.DEPLOYER_ATTACH_CONTAINERS:
            if svc.container_exists(platform):
                svc.connect_container(network_name, platform)
                sink.write(f'    attached {platform}\n')
            else:
                logger.warning('Platform container %s not found; skipping', platform)

        if hosted_app.needs_database:
            db_container = settings.DEPLOYER_DB_CONTAINER_NAME
            if svc.container_exists(db_container):
                svc.connect_container(network_name, db_container)
                sink.write(f'    attached {db_container}\n')
            else:
                raise DeploymentError(
                    'network',
                    f'This app needs a database but the Postgres container '
                    f'({db_container}) was not found.',
                )

        # -- 7. run -------------------------------------------------------
        stage = 'run'
        deployment.mark(Deployment.STATUS_STARTING)
        hosted_app.mark(HostedApp.STATUS_STARTING)

        if svc.container_exists(container_name):
            svc.remove_container(container_name)

        sink.write(f'==> Starting container {container_name}\n')
        memory_mb = hosted_app.memory_limit_mb or settings.DEPLOYER_DEFAULT_MEMORY_MB
        cpu_limit = hosted_app.cpu_limit or settings.DEPLOYER_DEFAULT_CPU
        # A read-only root filesystem needs explicit writable paths. With no
        # template (a custom Dockerfile) only /tmp is granted, since we cannot
        # know what that image expects to write.
        tmpfs = (
            template.tmpfs_mounts(settings.DEPLOYER_TMPFS_SIZE_MB)
            if template is not None
            else {'/tmp': f'rw,noexec,nosuid,nodev,size={settings.DEPLOYER_TMPFS_SIZE_MB}m'}
        )
        container_env = _build_environment(hosted_app, database_url, container_name)
        # Register the live credentials before anything student-controlled can
        # be logged — the migrate step below runs the student's own code with
        # exactly these values in its environment.
        sink.add_secrets(secrets_from_environment(container_env))

        info = svc.run_container(
            image_tag=image_tag,
            name=container_name,
            network=network_name,
            environment=container_env,
            memory_mb=memory_mb,
            cpu_limit=cpu_limit,
            user=settings.DEPLOYER_CONTAINER_USER,
            pids_limit=settings.DEPLOYER_PIDS_LIMIT,
            labels=labels,
            tmpfs=tmpfs,
            read_only=True,
            ulimits=settings.DEPLOYER_ULIMITS,
        )
        made_container = True

        # Verify the daemon actually applied the limits. Docker only *warns*
        # when a cgroup feature is unavailable, so without this a deploy could
        # report success while running with no memory or pids cap at all.
        _verify_limits(
            svc, container_name, sink,
            memory_mb=memory_mb, cpu_limit=cpu_limit, network_name=network_name,
        )

        # -- 8. migrate ---------------------------------------------------
        stage = 'migrate'
        if template is not None and template.migrate_command:
            _wait_until_running(svc, container_name)
            sink.write(f'==> Running migrations: {template.migrate_command}\n')
            exec_result = svc.exec_in_container(container_name, template.migrate_command)
            sink.write(exec_result.output + '\n')
            if not exec_result.ok:
                raise DeploymentError(
                    'migrate',
                    f'`{template.migrate_command}` exited with code {exec_result.exit_code}.',
                    container_log=exec_result.output,
                )

        # -- 9. health ----------------------------------------------------
        stage = 'health'
        health_path = template.default_health_path if template else '/'
        _wait_for_health(svc, container_name, hosted_app.container_port, health_path, sink)

        # -- 10. live -----------------------------------------------------
        stage = 'finalize'
        base_url = f'http://{container_name}:{hosted_app.container_port}'
        hosted_app.mark(
            HostedApp.STATUS_LIVE,
            internal_base_url=base_url,
            container_id=info.id,
            container_name=container_name,
            network_name=network_name,
            last_active_at=timezone.now(),
        )
        allowlist.register(container_name, hosted_app)
        deployment.mark(Deployment.STATUS_LIVE, container_id=info.id)
        sink.write(f'==> Live at {base_url}\n')
        sink.flush()

        # Prune the image the previous deployment was running.
        if previous_image and previous_image != image_tag:
            svc.remove_image(previous_image)

        _notify(
            hosted_app,
            f'{hosted_app.application.name} is live',
            f'Your app was deployed successfully and is now running at {base_url}.',
        )

    except (DeploymentError, DockerServiceError, UnsafeArchive, Exception) as exc:
        sink.flush()
        if isinstance(exc, DeploymentError):
            stage = exc.stage
            container_log = exc.container_log
            message = exc.message
        else:
            message = str(exc)
            container_log = getattr(exc, 'log_tail', '')

        # Reload the log we streamed so the summariser sees the whole build.
        deployment.refresh_from_db(fields=['build_log'])
        if made_container and not container_log:
            container_log = svc.container_logs(container_name, tail=200)

        # container_log and `message` are student-controlled, and the exception
        # text from a failed DB connection can embed the DSN. Redact before
        # anything is persisted, summarised, or emailed.
        known_secrets = sink.secrets
        container_log = redact(container_log, known_secrets)
        message = redact(message, known_secrets)

        summary = redact(
            diagnostics.summarize_failure(
                stage=stage,
                build_log=deployment.build_log,
                container_log=container_log,
                error=message,
            ),
            known_secrets,
        )

        if container_log:
            deployment.append_log(
                '\n===== container logs =====\n' + diagnostics.tail(container_log, 100) + '\n'
            )
        deployment.append_log(f'\n==> FAILED during {stage}: {message}\n')

        logger.exception('Deployment %s failed at %s', deployment.pk, stage)
        deployment.mark(Deployment.STATUS_FAILED, error_summary=summary)
        hosted_app.mark(HostedApp.STATUS_FAILED)

        # Unconditional, not just when this run created a container: an earlier
        # deployment may have authorised this hostname, and the container it
        # pointed at is being torn down below. Leaving the entry behind would
        # keep a dead name proxyable.
        allowlist.unregister(container_name)

        _cleanup_failed(
            svc,
            container_name if made_container else None,
            image_tag if made_image else None,
            network_name if made_network else None,
        )
        _notify(
            hosted_app,
            f'{hosted_app.application.name} failed to deploy',
            summary,
            secrets_=known_secrets,
        )

    finally:
        sink.flush()
        cleanup_build_dir(build_dir)


def _current_image_tag(hosted_app: HostedApp) -> str:
    latest = (
        hosted_app.deployments.filter(status=Deployment.STATUS_LIVE)
        .order_by('-created_at')
        .values_list('image_tag', flat=True)
        .first()
    )
    return latest or ''


def _cleanup_failed(svc, container: str | None, image: str | None, network: str | None) -> None:
    """Best-effort teardown. Each step is independent so one failure does not
    strand the rest."""
    if container:
        try:
            svc.remove_container(container, force=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning('Cleanup: container %s: %s', container, exc)
    if image:
        try:
            svc.remove_image(image, force=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning('Cleanup: image %s: %s', image, exc)
    if network:
        try:
            _detach_platform(svc, network)
            svc.remove_network(network)
        except Exception as exc:  # noqa: BLE001
            logger.warning('Cleanup: network %s: %s', network, exc)


def _detach_platform(svc, network: str) -> None:
    """A network with containers still attached refuses to be removed."""
    names = list(settings.DEPLOYER_ATTACH_CONTAINERS) + [settings.DEPLOYER_DB_CONTAINER_NAME]
    for name in names:
        try:
            svc.disconnect_container(network, name)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Lifecycle operations
# ---------------------------------------------------------------------------

def tail_container_logs(hosted_app: HostedApp, tail: int = 200) -> str:
    """Docker logs for an app's container; empty string when there is none.

    Views call this rather than importing docker_service directly, so the swap
    seam stays intact.
    """
    svc = get_docker_service()
    name = hosted_app.container_name or container_name_for(hosted_app.application.slug)
    try:
        if not svc.container_exists(name):
            return ''
        return svc.container_logs(name, tail=tail)
    except DockerServiceError as exc:
        logger.warning('Could not read logs for %s: %s', name, exc)
        return ''


def stop_app(hosted_app: HostedApp, status: str = HostedApp.STATUS_STOPPED) -> None:
    svc = get_docker_service()
    name = hosted_app.container_name or container_name_for(hosted_app.application.slug)
    if svc.container_exists(name):
        svc.stop_container(name)
    allowlist.unregister(name)
    hosted_app.mark(status)
    logger.info('Stopped %s (%s)', name, status)


def start_app(hosted_app: HostedApp) -> bool:
    """Start an existing stopped container. False if there is nothing to start."""
    svc = get_docker_service()
    name = hosted_app.container_name or container_name_for(hosted_app.application.slug)
    if not svc.container_exists(name):
        return False
    svc.start_container(name)
    allowlist.register(name, hosted_app)
    hosted_app.mark(HostedApp.STATUS_LIVE, last_active_at=timezone.now())
    return True


def restart_app(hosted_app: HostedApp) -> bool:
    svc = get_docker_service()
    name = hosted_app.container_name or container_name_for(hosted_app.application.slug)
    if not svc.container_exists(name):
        return False
    svc.restart_container(name)
    allowlist.register(name, hosted_app)
    hosted_app.mark(HostedApp.STATUS_LIVE, last_active_at=timezone.now())
    return True


def ensure_running(hosted_app: HostedApp) -> bool:
    """Bring a paused or stopped app back up on demand.

    This is the seam the gateway's launch endpoint will call: an app parked by
    the idle sweep should resume rather than refuse.
    """
    if hosted_app.status == HostedApp.STATUS_LIVE:
        hosted_app.touch()
        return True
    if hosted_app.status in (HostedApp.STATUS_PAUSED, HostedApp.STATUS_STOPPED):
        return start_app(hosted_app)
    return False


def destroy_app(hosted_app: HostedApp, drop_database: bool = False) -> None:
    """Remove every trace of a deployment."""
    svc = get_docker_service()
    slug = hosted_app.application.slug
    name = hosted_app.container_name or container_name_for(slug)
    network = hosted_app.network_name or network_name_for(slug)

    allowlist.unregister(name)

    if svc.container_exists(name):
        svc.remove_container(name, force=True)

    for tag in hosted_app.deployments.exclude(image_tag='').values_list('image_tag', flat=True):
        svc.remove_image(tag)

    _detach_platform(svc, network)
    svc.remove_network(network)

    if drop_database and hosted_app.db_name:
        db_provision.drop(hosted_app.db_name, hosted_app.db_user)
        hosted_app.db_name = ''
        hosted_app.db_user = ''
        hosted_app.db_password = ''

    hosted_app.mark(
        HostedApp.STATUS_NOT_DEPLOYED,
        container_id='',
        container_name='',
        network_name='',
        internal_base_url='',
        db_name=hosted_app.db_name,
        db_user=hosted_app.db_user,
        db_password=hosted_app.db_password,
    )
    logger.info('Destroyed deployment for %s', slug)
