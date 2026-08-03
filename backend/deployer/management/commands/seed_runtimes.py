"""Seed the Tier-A runtime templates. Idempotent — safe to re-run."""

from django.core.management.base import BaseCommand

from deployer.models import RuntimeTemplate
from deployer.runtime_definitions import RUNTIME_TEMPLATES


class Command(BaseCommand):
    help = 'Create or update the built-in runtime templates.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Overwrite existing templates even if they were edited by hand.',
        )

    def handle(self, *args, **options):
        created_count = updated_count = skipped_count = 0

        for definition in RUNTIME_TEMPLATES:
            key = definition['key']
            existing = RuntimeTemplate.objects.filter(key=key).first()

            if existing and not options['reset']:
                # Refresh detection rules and the Dockerfile, but leave any
                # admin-tuned limits alone.
                existing.dockerfile_template = definition['dockerfile_template']
                existing.detection_hints = definition['detection_hints']
                existing.save(update_fields=['dockerfile_template', 'detection_hints', 'updated_at'])
                updated_count += 1
                continue

            RuntimeTemplate.objects.update_or_create(key=key, defaults=definition)
            if existing:
                updated_count += 1
            else:
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Runtime templates: {created_count} created, '
                f'{updated_count} updated, {skipped_count} skipped.'
            )
        )
        for template in RuntimeTemplate.objects.order_by('-id'):
            self.stdout.write(
                f'  {template.key:<16} port={template.default_port:<5} '
                f'db={"yes" if template.needs_database else "no":<3} '
                f'priority={template.priority}'
            )
