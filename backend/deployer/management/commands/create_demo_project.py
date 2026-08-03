"""Create a deployable demo project, optionally a deliberately broken one.

Used to exercise the pipeline end to end without hand-building a zip:

    python manage.py create_demo_project              # a working Flask app
    python manage.py create_demo_project --broken     # crashes on startup

The broken variant drops `requests` from requirements.txt while leaving `flask`
in place. That is deliberate: the project still detects as Flask and still
builds cleanly, then crash-loops with ModuleNotFoundError at startup — which is
the interesting failure, because the cause appears only in the container log
and never in the build log.
"""

import io
import zipfile

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from marketplace.models import Application, Category

APP_PY = '''\
import os

from flask import Flask, jsonify
import requests  # noqa: F401 - present so --broken has something to remove

app = Flask(__name__)


@app.get("/")
def index():
    return jsonify(
        app="UDOM demo app",
        status="ok",
        port=os.environ.get("PORT", "8000"),
    )


@app.get("/health")
def health():
    return jsonify(status="healthy"), 200
'''

WORKING_REQUIREMENTS = 'flask==3.0.0\nrequests==2.31.0\n'

# `flask` stays so the project still auto-detects and still builds; only the
# import that runs at startup is missing.
BROKEN_REQUIREMENTS = (
    'flask==3.0.0\n'
    '# requests==2.31.0  <- deliberately removed to exercise failure reporting\n'
)

README = '''\
# UDOM demo app

A minimal Flask service used to verify the deployment pipeline.

* `/`        returns a JSON payload and HTTP 200 (the health path)
* `/health`  returns {"status": "healthy"}
'''


def build_zip(broken: bool) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('demo-app/app.py', APP_PY)
        archive.writestr(
            'demo-app/requirements.txt',
            BROKEN_REQUIREMENTS if broken else WORKING_REQUIREMENTS,
        )
        archive.writestr('demo-app/README.md', README)
    return buffer.getvalue()


class Command(BaseCommand):
    help = 'Create (or refresh) a demo Flask project ready to deploy.'

    def add_arguments(self, parser):
        parser.add_argument('--slug', default='udom-demo-flask', help='Application slug.')
        parser.add_argument('--name', default='UDOM Demo (Flask)', help='Application name.')
        parser.add_argument(
            '--broken',
            action='store_true',
            help='Omit a runtime dependency so the container crashes on startup.',
        )

    def handle(self, *args, **options):
        User = get_user_model()
        developer = (
            User.objects.filter(role='admin').first()
            or User.objects.filter(is_superuser=True).first()
            or User.objects.first()
        )
        if developer is None:
            raise CommandError(
                'No users exist. Run `python manage.py createsuperuser` first.'
            )

        category, _ = Category.objects.get_or_create(
            name='Developer Tools',
            defaults={'description': 'Tools for software developers', 'icon': 'code', 'order': 10},
        )

        slug = options['slug']
        broken = options['broken']

        application, created = Application.objects.get_or_create(
            slug=slug,
            defaults={
                'name': options['name'],
                'developer': developer,
                'category': category,
                'description': (
                    'A minimal Flask service used to verify the one-click '
                    'deployment pipeline end to end.'
                ),
                'short_description': 'Deployment pipeline smoke test.',
                'version': '1.0.0',
                'price': 0,
            },
        )

        # app_file is required on the model but irrelevant to deployment; the
        # pipeline builds from source_code.
        if not application.app_file:
            application.app_file.save(
                f'{slug}-placeholder.txt',
                ContentFile(b'This project is deployed from source, not downloaded.'),
                save=False,
            )

        payload = build_zip(broken=broken)
        application.source_code.save(f'{slug}-source.zip', ContentFile(payload), save=False)
        application.status = Application.STATUS_APPROVED
        application.is_active = True
        application.save()

        variant = 'BROKEN (missing runtime dependency)' if broken else 'working'
        self.stdout.write(
            self.style.SUCCESS(
                f'{"Created" if created else "Updated"} demo project "{application.name}" '
                f'[{variant}]'
            )
        )
        self.stdout.write(f'  Application id : {application.pk}')
        self.stdout.write(f'  Slug           : {application.slug}')
        self.stdout.write(f'  Status         : {application.status}')
        self.stdout.write(f'  Source archive : {application.source_code.name}')
        self.stdout.write('')
        self.stdout.write('Deploy it with:')
        self.stdout.write(
            f'  POST /api/deployer/apps/{application.pk}/deploy/   (admin token required)'
        )
