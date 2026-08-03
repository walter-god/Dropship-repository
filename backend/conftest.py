"""Shared pytest fixtures for the whole backend.

Conventions: factory_boy for model construction (keeps test bodies focused on
what's being asserted, not on satisfying every required field), plain pytest
fixtures for anything cross-cutting (API clients per role, the fake Docker
service). DRF's APIClient + simplejwt's RefreshToken are used directly for
auth, matching the pattern already established in this project's own offline
verification harness (scratchpad/verify.py from the security review).
"""

import io
import zipfile

import factory
import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import CustomUser
from deployer import fakes
from deployer.docker_service import reset_docker_service
from deployer.models import Deployment, RuntimeTemplate
from gateway.models import AllowedHostname, AppSession, HostedApp
from marketplace.models import Application, Category
from subscriptions.models import SubscriptionPlan, UserSubscription


# ---------------------------------------------------------------------------
# Zip helpers
# ---------------------------------------------------------------------------

def make_zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buf.getvalue()


def make_upload(files: dict, name: str = 'project.zip'):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(name, make_zip_bytes(files), content_type='application/zip')


@pytest.fixture
def zip_upload():
    """Factory fixture: zip_upload({'app.py': '...'}) -> UploadedFile."""
    return make_upload


FLASK_SOURCE = {'app.py': 'from flask import Flask\napp = Flask(__name__)\n',
                'requirements.txt': 'flask==3.0.0\n'}
DJANGO_SOURCE = {'manage.py': '', 'requirements.txt': 'django==4.2\n'}


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CustomUser
        django_get_or_create = ('username',)
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f'user{n}')
    email = factory.LazyAttribute(lambda o: f'{o.username}@udom.ac.tz')
    first_name = 'Test'
    last_name = 'User'
    role = CustomUser.ROLE_EXTERNAL

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        obj.set_password(extracted or 'testpass123')
        if create:
            obj.save()


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category
        django_get_or_create = ('name',)

    name = factory.Sequence(lambda n: f'Category {n}')
    description = 'A test category'
    icon = 'code'
    order = 0


class ApplicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Application

    name = factory.Sequence(lambda n: f'App {n}')
    developer = factory.SubFactory(UserFactory, role=CustomUser.ROLE_INTERNAL)
    category = factory.SubFactory(CategoryFactory)
    description = 'A test application.'
    status = Application.STATUS_APPROVED
    price = 0


class RuntimeTemplateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RuntimeTemplate
        django_get_or_create = ('key',)

    key = 'python-flask'
    display_name = 'Python — Flask'
    dockerfile_template = (
        'FROM python:3.12-slim\nCOPY . .\nRUN pip install -r requirements.txt\n'
        'EXPOSE {{ port }}\nCMD ["python", "app.py"]\n'
    )
    default_health_path = '/'
    default_port = 8000
    migrate_command = None
    needs_database = False
    tmpfs_paths = []
    detection_hints = {
        'priority': 70,
        'require_files': ['requirements.txt'],
        'require_absent': ['manage.py'],
        'content_matches': [{'file': 'requirements.txt', 'pattern': r'^\s*flask'}],
    }


class HostedAppFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = HostedApp

    application = factory.SubFactory(ApplicationFactory)
    status = HostedApp.STATUS_NOT_DEPLOYED


class DeploymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Deployment

    hosted_app = factory.SubFactory(HostedAppFactory)
    status = Deployment.STATUS_QUEUED


class SubscriptionPlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SubscriptionPlan
        django_get_or_create = ('name',)

    name = 'Monthly'
    description = 'A monthly plan'
    price = '9999.00'
    duration_days = 30
    features = {}
    is_active = True


class UserSubscriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UserSubscription

    user = factory.SubFactory(UserFactory)
    plan = factory.SubFactory(SubscriptionPlanFactory)
    is_active = True

    @factory.lazy_attribute
    def end_date(self):
        from django.utils import timezone
        from datetime import timedelta
        return timezone.now() + timedelta(days=30)


# ---------------------------------------------------------------------------
# User / auth fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_user(db):
    return UserFactory(role=CustomUser.ROLE_ADMIN, is_staff=True, username='admin_user')


@pytest.fixture
def internal_user(db):
    return UserFactory(role=CustomUser.ROLE_INTERNAL, username='internal_user')


@pytest.fixture
def external_user(db):
    return UserFactory(role=CustomUser.ROLE_EXTERNAL, username='external_user')


def _authed_client(user):
    client = APIClient()
    token = str(RefreshToken.for_user(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_client(admin_user):
    return _authed_client(admin_user)


@pytest.fixture
def internal_client(internal_user):
    return _authed_client(internal_user)


@pytest.fixture
def external_client(external_user):
    return _authed_client(external_user)


@pytest.fixture
def as_user():
    """as_user(user) -> authenticated APIClient, for ad hoc users a test creates itself."""
    return _authed_client


# ---------------------------------------------------------------------------
# Domain fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def category(db):
    return CategoryFactory()


@pytest.fixture
def approved_app(db, internal_user, category):
    return ApplicationFactory(
        developer=internal_user, category=category, status=Application.STATUS_APPROVED,
        source_code=make_upload(FLASK_SOURCE),
    )


@pytest.fixture
def hosted_app(db, approved_app):
    return HostedAppFactory(application=approved_app)


@pytest.fixture
def flask_template(db):
    return RuntimeTemplateFactory()


@pytest.fixture
def django_template(db):
    return RuntimeTemplateFactory(
        key='python-django', display_name='Python — Django', default_port=8000,
        needs_database=True, migrate_command='python manage.py migrate --noinput',
        detection_hints={'priority': 90, 'require_files': ['manage.py'],
                         'any_files': ['requirements.txt']},
    )


@pytest.fixture
def subscription_plan(db):
    return SubscriptionPlanFactory()


# ---------------------------------------------------------------------------
# Docker fake
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_docker_service():
    """Every test gets a fresh FakeDockerService and a clean allowlist cache.

    autouse, because forgetting this on a single deploy test would let state
    (created containers, MODE) bleed into the next test — DockerService is a
    module-level singleton by design (see docker_service.get_docker_service).
    """
    fakes.reset_state()
    reset_docker_service()
    from django.core.cache import cache
    cache.clear()
    yield fakes
    fakes.reset_state()
    reset_docker_service()
