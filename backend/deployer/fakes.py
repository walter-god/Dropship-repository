"""A fake DockerService for tests.

Implements the full DockerService contract in memory so the deploy pipeline
can be exercised end to end without a Docker daemon — the same seam the
security review's offline harness used. `MODE` and `BREAK_LIMIT` are
module-level because `get_docker_service()` caches a singleton; tests must
call `reset_docker_service()` (a fixture does this automatically, see
conftest.py) whenever they need a fresh instance to see updated settings.
"""

from __future__ import annotations

from deployer.docker_service import (
    AppliedLimits,
    BuildResult,
    ContainerInfo,
    DockerService,
    ExecResult,
    NetworkInfo,
    _assert_no_host_access,
)

MODE = 'healthy'  # 'healthy' | 'crashloop' | 'build_fail'
BREAK_LIMIT = None  # simulate the daemon silently dropping a named limit

CRASH_LOG = (
    "Traceback (most recent call last):\n"
    '  File "/app/app.py", line 4, in <module>\n'
    "    import requests\n"
    "ModuleNotFoundError: No module named 'requests'\n"
)

HEALTHY_LOG = (
    "[INFO] Starting gunicorn 21.2.0\n"
    "[INFO] Listening at: http://0.0.0.0:8000 (1)\n"
    "[INFO] Booting worker with pid: 7\n"
)

BUILD_OUTPUT = [
    'Step 1/8 : FROM python:3.12-slim\n',
    ' ---> a1b2c3d4e5f6\n',
    'Collecting flask==3.0.0\n',
    'Successfully installed flask-3.0.0\n',
    'Successfully built deadbeef1234\n',
]


class FakeDockerService(DockerService):

    def __init__(self):
        self.containers = {
            'udom_backend': 'running',
            'udom_celery_worker': 'running',
            'udom_db': 'running',
        }
        self.images: set[str] = set()
        self.networks: dict[str, set[str]] = {}
        self.network_internal: dict[str, bool] = {}
        self.calls: list[str] = []
        self.last_run_kwargs: dict = {}
        self.last_environment: dict = {}

    # -- images --------------------------------------------------------

    def build_image(self, context_dir, tag, dockerfile='Dockerfile', timeout=600,
                    on_log=None, labels=None):
        from .docker_service import ImageBuildError

        self.calls.append(f'build:{tag}:{dockerfile}')
        if MODE == 'build_fail':
            if on_log:
                on_log('Step 1/3 : FROM python:3.12-slim\n')
                on_log('ERROR: could not find a version that satisfies flaskk\n')
            raise ImageBuildError(
                'Could not find a version that satisfies the requirement flaskk',
                log_tail='ERROR: could not find a version that satisfies flaskk\n',
            )
        for line in BUILD_OUTPUT:
            if on_log:
                on_log(line)
        self.images.add(tag)
        return BuildResult(image_tag=tag, image_id='sha256:deadbeef', size_bytes=180 * 1024 * 1024)

    def remove_image(self, tag, force=True):
        self.calls.append(f'rmi:{tag}')
        self.images.discard(tag)

    # -- networks --------------------------------------------------------

    def ensure_network(self, name, labels=None, internal=True):
        self.calls.append(f'net-create:{name}:internal={internal}')
        self.network_internal[name] = internal
        self.networks.setdefault(name, set())
        return NetworkInfo(id=f'net-{name}', name=name)

    def remove_network(self, name):
        self.calls.append(f'net-rm:{name}')
        self.networks.pop(name, None)
        self.network_internal.pop(name, None)

    def connect_container(self, network, container):
        self.calls.append(f'net-connect:{network}:{container}')
        self.networks.setdefault(network, set()).add(container)

    def disconnect_container(self, network, container):
        self.networks.get(network, set()).discard(container)

    # -- containers --------------------------------------------------------

    def run_container(self, image_tag, name, network, environment, memory_mb,
                      cpu_limit, user, pids_limit, labels=None, tmpfs=None,
                      read_only=True, ulimits=None):
        self.calls.append(f'run:{name}:net={network}')
        self.last_environment = dict(environment)
        self.last_run_kwargs = {
            'image_tag': image_tag, 'name': name, 'network': network,
            'memory_mb': memory_mb, 'cpu_limit': cpu_limit, 'user': user,
            'pids_limit': pids_limit, 'tmpfs': tmpfs or {},
            'read_only': read_only, 'ulimits': ulimits or {},
        }
        _assert_no_host_access(self.last_run_kwargs)
        self.containers[name] = 'exited' if MODE == 'crashloop' else 'running'
        self.networks.setdefault(network, set()).add(name)
        return ContainerInfo(id=f'cid-{name}', name=name, status=self.containers[name])

    def inspect_limits(self, ref):
        kwargs = self.last_run_kwargs
        values = {
            'memory_bytes': int(kwargs.get('memory_mb', 0)) * 1024 * 1024,
            'nano_cpus': int(float(kwargs.get('cpu_limit', 0)) * 1_000_000_000),
            'pids_limit': int(kwargs.get('pids_limit', 0)),
            'cap_drop': ('ALL',),
            'read_only_rootfs': bool(kwargs.get('read_only', True)),
            'user': str(kwargs.get('user', '')),
            'network_mode': str(kwargs.get('network', '')),
            'privileged': False,
            'mounts': (),
        }
        if BREAK_LIMIT:
            values[BREAK_LIMIT] = {
                'memory_bytes': 0, 'nano_cpus': 0, 'pids_limit': 0,
                'cap_drop': (), 'read_only_rootfs': False, 'user': 'root',
                'network_mode': 'bridge', 'privileged': True,
                'mounts': ('/var/run/docker.sock',),
            }[BREAK_LIMIT]
        return AppliedLimits(**values)

    def start_container(self, ref):
        self.containers[ref] = 'running'

    def stop_container(self, ref, timeout=10):
        self.calls.append(f'stop:{ref}')
        self.containers[ref] = 'exited'

    def restart_container(self, ref, timeout=10):
        self.containers[ref] = 'running'

    def remove_container(self, ref, force=True):
        self.calls.append(f'rm:{ref}')
        self.containers.pop(ref, None)

    def container_status(self, ref):
        return self.containers.get(ref, 'unknown')

    def container_logs(self, ref, tail=200):
        return CRASH_LOG if MODE == 'crashloop' else HEALTHY_LOG

    def exec_in_container(self, ref, command, timeout=300):
        self.calls.append(f'exec:{ref}:{command}')
        return ExecResult(exit_code=0, output='Migrations applied.\n')

    def container_exists(self, ref):
        return ref in self.containers


def reset_state():
    """Reset module-level fake behaviour between tests."""
    global MODE, BREAK_LIMIT
    MODE = 'healthy'
    BREAK_LIMIT = None
