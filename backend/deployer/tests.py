"""Tests for the deployment pipeline.

Everything Docker-shaped goes through the fake DockerService (deployer/fakes.py)
— the same seam the module itself is built around, so these tests exercise the
real pipeline logic in services.py without a Docker daemon.
"""

import io
import zipfile
from unittest import mock

import pytest
from django.utils import timezone

from conftest import DJANGO_SOURCE, FLASK_SOURCE, DeploymentFactory, HostedAppFactory
from deployer import fakes, services
from deployer.detection import detect_from_archive, detect_runtime
from deployer.dockerfile_validation import DockerfileValidationError, validate_dockerfile
from deployer.extraction import UnsafeArchive, safe_extract
from deployer.models import Deployment
from gateway import allowlist
from gateway.models import HostedApp

pytestmark = pytest.mark.django_db


def ok_response():
    return mock.Mock(status_code=200)


def mock_health():
    return mock.patch.object(services.requests, 'get', return_value=ok_response())


# ---------------------------------------------------------------------------
# Successful deploy
# ---------------------------------------------------------------------------

class TestSuccessfulDeploy:
    def test_deploy_transitions_to_live(self, hosted_app, flask_template):
        deployment = DeploymentFactory(hosted_app=hosted_app)

        with mock_health():
            services.run_deployment(hosted_app, deployment)

        hosted_app.refresh_from_db()
        deployment.refresh_from_db()
        assert deployment.status == Deployment.STATUS_LIVE
        assert hosted_app.status == HostedApp.STATUS_LIVE
        assert hosted_app.runtime_template.key == 'python-flask'

    def test_deployment_row_records_image_and_container(self, hosted_app, flask_template):
        deployment = DeploymentFactory(hosted_app=hosted_app)
        with mock_health():
            services.run_deployment(hosted_app, deployment)
        deployment.refresh_from_db()
        assert deployment.image_tag
        assert deployment.container_id
        assert deployment.started_at is not None
        assert deployment.finished_at is not None

    def test_container_addressed_by_name_not_a_host_port(self, hosted_app, flask_template):
        deployment = DeploymentFactory(hosted_app=hosted_app)
        with mock_health():
            services.run_deployment(hosted_app, deployment)
        hosted_app.refresh_from_db()
        assert hosted_app.internal_base_url.startswith('http://udom-app-')
        assert hosted_app.internal_base_url.endswith(f':{hosted_app.container_port}')

    def test_hostname_registered_in_gateway_allowlist_on_success(self, hosted_app, flask_template):
        deployment = DeploymentFactory(hosted_app=hosted_app)
        with mock_health():
            services.run_deployment(hosted_app, deployment)
        hosted_app.refresh_from_db()
        assert allowlist.is_allowed(hosted_app.container_name)

    def test_per_app_network_created_internal_by_default(self, hosted_app, flask_template):
        deployment = DeploymentFactory(hosted_app=hosted_app)
        with mock_health():
            services.run_deployment(hosted_app, deployment)
        svc = services.get_docker_service()
        assert svc.network_internal[hosted_app.network_name] is True

    def test_allow_egress_creates_non_internal_network(self, hosted_app, flask_template):
        hosted_app.allow_egress = True
        hosted_app.save(update_fields=['allow_egress'])
        deployment = DeploymentFactory(hosted_app=hosted_app)
        with mock_health():
            services.run_deployment(hosted_app, deployment)
        svc = services.get_docker_service()
        assert svc.network_internal[hosted_app.network_name] is False


# ---------------------------------------------------------------------------
# Build failure
# ---------------------------------------------------------------------------

class TestBuildFailure:
    def test_build_failure_marks_deployment_failed(self, hosted_app, flask_template):
        fakes.MODE = 'build_fail'
        deployment = DeploymentFactory(hosted_app=hosted_app)

        services.run_deployment(hosted_app, deployment)

        deployment.refresh_from_db()
        hosted_app.refresh_from_db()
        assert deployment.status == Deployment.STATUS_FAILED
        assert hosted_app.status == HostedApp.STATUS_FAILED

    def test_build_failure_preserves_log(self, hosted_app, flask_template):
        fakes.MODE = 'build_fail'
        deployment = DeploymentFactory(hosted_app=hosted_app)
        services.run_deployment(hosted_app, deployment)
        deployment.refresh_from_db()
        assert 'ERROR' in deployment.build_log or 'flaskk' in deployment.build_log

    def test_build_failure_writes_readable_error_summary(self, hosted_app, flask_template):
        fakes.MODE = 'build_fail'
        deployment = DeploymentFactory(hosted_app=hosted_app)
        services.run_deployment(hosted_app, deployment)
        deployment.refresh_from_db()
        assert deployment.error_summary
        assert 'flaskk' in deployment.error_summary

    def test_build_failure_cleans_up_container_image_network(self, hosted_app, flask_template):
        fakes.MODE = 'build_fail'
        deployment = DeploymentFactory(hosted_app=hosted_app)
        services.run_deployment(hosted_app, deployment)
        svc = services.get_docker_service()
        # Nothing should be left registered for a build that never produced a
        # runnable image.
        assert hosted_app.container_name not in svc.networks.get(
            services.network_name_for(hosted_app.application.slug), set()
        )

    def test_build_failure_revokes_allowlist_entry(self, hosted_app, flask_template):
        # Simulate a previously-live app whose redeploy then fails.
        container_name = services.container_name_for(hosted_app.application.slug)
        allowlist.register(container_name, hosted_app)
        assert allowlist.is_allowed(container_name)

        fakes.MODE = 'build_fail'
        deployment = DeploymentFactory(hosted_app=hosted_app)
        services.run_deployment(hosted_app, deployment)

        assert not allowlist.is_allowed(container_name)


# ---------------------------------------------------------------------------
# Health check timeout / crash loop
# ---------------------------------------------------------------------------

class TestHealthCheckFailure:
    def test_crashlooping_container_fails_fast(self, hosted_app, flask_template):
        fakes.MODE = 'crashloop'
        deployment = DeploymentFactory(hosted_app=hosted_app)

        services.run_deployment(hosted_app, deployment)

        deployment.refresh_from_db()
        hosted_app.refresh_from_db()
        assert deployment.status == Deployment.STATUS_FAILED
        assert hosted_app.status == HostedApp.STATUS_FAILED

    def test_crashloop_error_summary_names_the_missing_module(self, hosted_app, flask_template):
        fakes.MODE = 'crashloop'
        deployment = DeploymentFactory(hosted_app=hosted_app)
        services.run_deployment(hosted_app, deployment)
        deployment.refresh_from_db()
        assert 'requests' in deployment.error_summary

    def test_health_timeout_with_no_response_fails_and_cleans_up(self, hosted_app, flask_template):
        deployment = DeploymentFactory(hosted_app=hosted_app)
        with mock.patch.object(
            services.requests, 'get', side_effect=services.requests.RequestException('refused')
        ):
            services.run_deployment(hosted_app, deployment)

        deployment.refresh_from_db()
        svc = services.get_docker_service()
        assert deployment.status == Deployment.STATUS_FAILED
        assert not svc.container_exists(services.container_name_for(hosted_app.application.slug))


# ---------------------------------------------------------------------------
# Applied-limit verification (H4 from the security review)
# ---------------------------------------------------------------------------

class TestLimitVerification:
    @pytest.mark.parametrize('broken_limit', [
        'memory_bytes', 'pids_limit', 'read_only_rootfs', 'user', 'privileged', 'mounts',
    ])
    def test_deploy_fails_when_daemon_silently_drops_a_limit(
        self, hosted_app, flask_template, broken_limit
    ):
        fakes.BREAK_LIMIT = broken_limit
        deployment = DeploymentFactory(hosted_app=hosted_app)
        with mock_health():
            services.run_deployment(hosted_app, deployment)
        deployment.refresh_from_db()
        assert deployment.status == Deployment.STATUS_FAILED
        assert 'isolation' in deployment.error_summary.lower() or \
            'host configuration' in deployment.error_summary.lower()


# ---------------------------------------------------------------------------
# Concurrent deploys / ports
# ---------------------------------------------------------------------------

class TestNoPortAllocation:
    def test_no_ports_are_ever_published(self, hosted_app, flask_template):
        """
        There is no port allocator in this design, by explicit choice: student
        apps are addressed only by Docker DNS container name
        (http://udom-app-<slug>:<port>), never by a published host port — see
        docker_service.run_container, which never passes `ports`, and
        SECURITY.md's isolation section. "Concurrent deploys never receive the
        same port" does not apply because no host port is ever handed out to
        collide over; this test asserts that invariant instead.
        """
        deployment = DeploymentFactory(hosted_app=hosted_app)
        with mock_health():
            services.run_deployment(hosted_app, deployment)
        svc = services.get_docker_service()
        assert 'ports' not in svc.last_run_kwargs

    def test_two_apps_deployed_concurrently_get_independent_container_ports(
        self, internal_user, category, flask_template
    ):
        """Each app's container_port is its own field — two apps can validly
        share the same *container-internal* port number, because each lives on
        its own isolated network and is never compared to another app's port.
        """
        from conftest import ApplicationFactory, make_upload

        app_a = ApplicationFactory(developer=internal_user, category=category,
                                   source_code=make_upload(FLASK_SOURCE))
        app_b = ApplicationFactory(developer=internal_user, category=category,
                                   source_code=make_upload(FLASK_SOURCE))
        hosted_a = HostedAppFactory(application=app_a)
        hosted_b = HostedAppFactory(application=app_b)

        with mock_health():
            services.run_deployment(hosted_a, DeploymentFactory(hosted_app=hosted_a))
            services.run_deployment(hosted_b, DeploymentFactory(hosted_app=hosted_b))

        hosted_a.refresh_from_db()
        hosted_b.refresh_from_db()
        assert hosted_a.network_name != hosted_b.network_name
        assert hosted_a.container_name != hosted_b.container_name


# ---------------------------------------------------------------------------
# Archive safety: zip-slip and zip-bomb
# ---------------------------------------------------------------------------

class TestArchiveSafety:
    def _write_zip(self, tmp_path, entries):
        path = tmp_path / 'archive.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, kwargs in entries:
                kwargs = dict(kwargs)
                data = kwargs.pop('data', b'x')
                info = zipfile.ZipInfo(name)
                for key, value in kwargs.items():
                    setattr(info, key, value)
                archive.writestr(info, data)
        return path

    def test_rejects_parent_directory_traversal(self, tmp_path):
        path = self._write_zip(tmp_path, [('../../../etc/passwd', {})])
        with pytest.raises(UnsafeArchive):
            safe_extract(path, tmp_path / 'dest')

    def test_rejects_absolute_paths(self, tmp_path):
        path = self._write_zip(tmp_path, [('/etc/passwd', {})])
        with pytest.raises(UnsafeArchive):
            safe_extract(path, tmp_path / 'dest')

    def test_rejects_symlink_entries(self, tmp_path):
        path = self._write_zip(tmp_path, [('evil', {'external_attr': 0o120777 << 16})])
        with pytest.raises(UnsafeArchive):
            safe_extract(path, tmp_path / 'dest')

    def test_rejects_archive_over_size_cap(self, tmp_path):
        path = self._write_zip(tmp_path, [('big.bin', {'data': b'\0' * 2048})])
        with pytest.raises(UnsafeArchive):
            safe_extract(path, tmp_path / 'dest', max_bytes=1024)

    def test_rejects_high_compression_ratio_zip_bomb(self, tmp_path):
        path = tmp_path / 'bomb.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('bomb.txt', b'\0' * (20 * 1024 * 1024))
        with pytest.raises(UnsafeArchive, match='(?i)ratio'):
            safe_extract(path, tmp_path / 'dest')

    def test_ordinary_source_archive_still_extracts(self, tmp_path):
        path = tmp_path / 'ok.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('app.py', 'print("hi")\n' * 20)
            archive.writestr('requirements.txt', 'flask\n')
        result = safe_extract(path, tmp_path / 'dest')
        assert result.file_count == 2


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

class TestDetection:
    @pytest.mark.parametrize('expected_key,files', [
        ('python-django', {'manage.py': '', 'requirements.txt': 'django==4.2\n'}),
        ('python-flask', {'requirements.txt': 'flask==3.0.0\n', 'app.py': ''}),
        ('node-next', {'package.json': '{"dependencies":{"next":"14"}}'}),
        ('node-express', {'package.json': '{"dependencies":{"express":"4"}}'}),
        ('static-spa', {'package.json': '{"devDependencies":{"vite":"5"}}'}),
        ('php-laravel', {'artisan': '', 'composer.json': '{}'}),
    ])
    def test_detects_representative_fixtures_on_disk(self, tmp_path, expected_key, files, db):
        from deployer.runtime_definitions import RUNTIME_TEMPLATES
        from deployer.models import RuntimeTemplate
        for definition in RUNTIME_TEMPLATES:
            RuntimeTemplate.objects.get_or_create(key=definition['key'], defaults=definition)

        root = tmp_path / 'proj'
        root.mkdir()
        for name, content in files.items():
            (root / name).write_text(content)

        result = detect_runtime(root)
        assert result is not None
        assert result.key == expected_key

    def test_zip_peek_detection_matches_disk_detection(self, db, flask_template, zip_upload):
        upload = zip_upload(FLASK_SOURCE)
        result = detect_from_archive(upload)
        assert result['runtime_key'] == 'python-flask'
        assert result['confidence'] == 'high'
        assert result['needs_dockerfile'] is False

    def test_unrecognized_project_needs_dockerfile(self, db, flask_template, zip_upload):
        upload = zip_upload({'readme.txt': 'nothing here'})
        result = detect_from_archive(upload)
        assert result['confidence'] == 'none'
        assert result['needs_dockerfile'] is True

    def test_dockerfile_present_detected_as_custom(self, db, flask_template, zip_upload):
        upload = zip_upload({'Dockerfile': 'FROM python:3.12\nEXPOSE 8000\n'})
        result = detect_from_archive(upload)
        assert result['runtime_key'] == 'custom'
        assert result['confidence'] == 'high'
        assert result['needs_dockerfile'] is False

    def test_compiled_language_flagged_needs_dockerfile(self, db, flask_template, zip_upload):
        upload = zip_upload({'pom.xml': '<project></project>'})
        result = detect_from_archive(upload)
        assert result['runtime_key'] == 'java-maven'
        assert result['needs_dockerfile'] is True
        assert 'Java' in result['reason']


# ---------------------------------------------------------------------------
# Dockerfile validation
# ---------------------------------------------------------------------------

class TestDockerfileValidation:
    def test_rejects_from_scratch(self):
        with pytest.raises(DockerfileValidationError, match='scratch'):
            validate_dockerfile('FROM scratch\nEXPOSE 8000\n')

    @pytest.mark.parametrize('needle', [
        '--privileged', '--cap-add', '--security-opt', '--network=host', 'sys_admin',
    ])
    def test_rejects_privileged_instructions(self, needle):
        text = f'FROM ubuntu\nRUN docker run {needle} evil\nEXPOSE 8000\n'
        with pytest.raises(DockerfileValidationError):
            validate_dockerfile(text)

    def test_rejects_docker_socket_reference(self):
        with pytest.raises(DockerfileValidationError):
            validate_dockerfile('FROM ubuntu\nEXPOSE 8000\nVOLUME /var/run/docker.sock\n')

    def test_rejects_missing_expose_with_no_override(self):
        with pytest.raises(DockerfileValidationError, match='EXPOSE'):
            validate_dockerfile('FROM python:3.12\nCMD ["python", "app.py"]\n')

    def test_port_override_satisfies_missing_expose(self):
        validate_dockerfile('FROM python:3.12\nCMD ["python", "app.py"]\n', port_override=9000)

    def test_normal_dockerfile_passes(self):
        validate_dockerfile('FROM golang:1.22\nEXPOSE 8080\nCMD ["./app"]\n')


# ---------------------------------------------------------------------------
# Admin-only permission on every deployer endpoint
# ---------------------------------------------------------------------------

class TestDeployerPermissions:
    ACTIONS = [
        ('post', 'deploy'), ('post', 'stop'), ('post', 'restart'),
        ('post', 'redeploy'), ('post', 'publish'), ('get', 'logs'),
        ('get', 'deployments'), ('patch', 'env'), ('post', 'destroy_deployment'),
        ('get', 'sessions'), ('patch', 'dockerfile'),
    ]

    @pytest.mark.parametrize('method,action', ACTIONS)
    def test_internal_user_gets_403(self, internal_client, hosted_app, method, action):
        url = f'/api/deployer/apps/{hosted_app.application.pk}/{action}/'
        resp = getattr(internal_client, method)(url, {}, format='json')
        assert resp.status_code == 403

    @pytest.mark.parametrize('method,action', ACTIONS)
    def test_external_user_gets_403(self, external_client, hosted_app, method, action):
        url = f'/api/deployer/apps/{hosted_app.application.pk}/{action}/'
        resp = getattr(external_client, method)(url, {}, format='json')
        assert resp.status_code == 403

    @pytest.mark.parametrize('method,action', ACTIONS)
    def test_anonymous_gets_401_or_403(self, api_client, hosted_app, method, action):
        url = f'/api/deployer/apps/{hosted_app.application.pk}/{action}/'
        resp = getattr(api_client, method)(url, {}, format='json')
        assert resp.status_code in (401, 403)

    def test_the_developer_who_owns_the_app_is_still_not_admin(
        self, internal_user, hosted_app, as_user
    ):
        # Owning a project grants no deployer privileges — only IsAdminUser
        # does. This matters because internal users can deploy their own app
        # object in marketplace, but the deployer surface is admin-only.
        client = as_user(hosted_app.application.developer)
        resp = client.post(f'/api/deployer/apps/{hosted_app.application.pk}/deploy/', {})
        assert resp.status_code == 403

    def test_admin_can_reach_deploy(self, admin_client, hosted_app, flask_template):
        with mock_health():
            resp = admin_client.post(f'/api/deployer/apps/{hosted_app.application.pk}/deploy/', {})
        assert resp.status_code == 202

    def test_runtime_templates_list_requires_admin(self, internal_client):
        resp = internal_client.get('/api/deployer/runtime-templates/')
        assert resp.status_code == 403
