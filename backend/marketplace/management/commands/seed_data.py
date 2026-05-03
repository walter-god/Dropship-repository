from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from marketplace.models import Category
from subscriptions.models import SubscriptionPlan

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed initial data: categories, subscription plans, and demo admin'

    def handle(self, *args, **kwargs):
        self._seed_categories()
        self._seed_subscription_plans()
        self._seed_admin()
        self.stdout.write(self.style.SUCCESS('Data seeded successfully.'))

    def _seed_categories(self):
        categories = [
            {'name': 'Education', 'description': 'Learning and academic tools', 'icon': 'school', 'order': 1},
            {'name': 'Productivity', 'description': 'Tools to boost your workflow', 'icon': 'work', 'order': 2},
            {'name': 'Research', 'description': 'Research and data analysis tools', 'icon': 'science', 'order': 3},
            {'name': 'Communication', 'description': 'Messaging and collaboration', 'icon': 'chat', 'order': 4},
            {'name': 'Finance', 'description': 'Financial management tools', 'icon': 'account_balance', 'order': 5},
            {'name': 'Health', 'description': 'Health and wellness applications', 'icon': 'health_and_safety', 'order': 6},
            {'name': 'Entertainment', 'description': 'Games and media applications', 'icon': 'sports_esports', 'order': 7},
            {'name': 'Utilities', 'description': 'System and utility tools', 'icon': 'build', 'order': 8},
            {'name': 'PaaS', 'description': 'Platform-as-a-Service solutions', 'icon': 'cloud', 'order': 9},
            {'name': 'Developer Tools', 'description': 'Tools for software developers', 'icon': 'code', 'order': 10},
        ]
        for cat_data in categories:
            Category.objects.get_or_create(name=cat_data['name'], defaults=cat_data)
        self.stdout.write(f'  Created {len(categories)} categories')

    def _seed_subscription_plans(self):
        plans = [
            {
                'name': 'Monthly',
                'description': 'Full access for one month',
                'price': '9999.00',
                'duration_days': 30,
                'features': {
                    'unlimited_downloads': True,
                    'priority_support': False,
                    'early_access': False,
                    'api_access': False,
                },
                'is_active': True,
            },
            {
                'name': 'Quarterly',
                'description': 'Full access for three months — save 20%',
                'price': '23999.00',
                'duration_days': 90,
                'features': {
                    'unlimited_downloads': True,
                    'priority_support': True,
                    'early_access': False,
                    'api_access': False,
                },
                'is_active': True,
            },
            {
                'name': 'Annual',
                'description': 'Full access for one year — save 40%',
                'price': '71999.00',
                'duration_days': 365,
                'features': {
                    'unlimited_downloads': True,
                    'priority_support': True,
                    'early_access': True,
                    'api_access': True,
                },
                'is_active': True,
            },
        ]
        for plan_data in plans:
            SubscriptionPlan.objects.get_or_create(name=plan_data['name'], defaults=plan_data)
        self.stdout.write(f'  Created {len(plans)} subscription plans')

    def _seed_admin(self):
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser(
                username='admin',
                email='admin@udom.ac.tz',
                password='Admin@1234',
                first_name='UDOM',
                last_name='Administrator',
                role='admin',
            )
            self.stdout.write('  Created admin user: admin@udom.ac.tz / Admin@1234')
        else:
            self.stdout.write('  Admin user already exists')
