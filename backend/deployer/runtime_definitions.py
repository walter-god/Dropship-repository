"""Tier-A runtime definitions, seeded by `manage.py seed_runtimes`.

Kept as Python rather than a JSON fixture on purpose: these are six multi-line
Dockerfiles, and hand-escaping them into JSON string literals is a reliable
source of subtle breakage. The seeder upserts by `key`, so it is safe to re-run.

Two constraints shape every template here:

* Containers run as a non-root user (DEPLOYER_CONTAINER_USER), so no image may
  bind a port below 1024 and every writable path must be world-writable.
* The app must honour the PORT environment variable, because the gateway
  addresses it by container name and port.
"""

DJANGO_DOCKERFILE = """\
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \\
 && apt-get install -y --no-install-recommends libpq-dev gcc \\
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \\
 && pip install --no-cache-dir gunicorn

COPY . .
RUN mkdir -p /app/staticfiles /app/media && chmod -R a+rwX /app/staticfiles /app/media \\
 && chmod -R a+rX /app

EXPOSE {{ port }}
# Locate the settings package rather than guessing the project name.
CMD sh -c 'PKG=$(ls -d */settings.py 2>/dev/null | head -1 | cut -d/ -f1); \\
  if [ -z "$PKG" ]; then echo "ERROR: could not find a Django settings package (*/settings.py)"; exit 1; fi; \\
  exec gunicorn "$PKG.wsgi:application" --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 60'
"""

FLASK_DOCKERFILE = """\
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \\
 && pip install --no-cache-dir gunicorn

COPY . .
RUN chmod -R a+rX /app

EXPOSE {{ port }}
# Try the conventional entrypoints in order, and say so clearly if none match.
CMD sh -c 'for m in app main wsgi application server; do \\
    if [ -f "$m.py" ]; then exec gunicorn "$m:app" --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 60; fi; \\
  done; \\
  echo "ERROR: no Flask entrypoint found (looked for app.py, main.py, wsgi.py, application.py, server.py)"; exit 1'
"""

EXPRESS_DOCKERFILE = """\
FROM node:20-slim
ENV NODE_ENV=production
WORKDIR /app

COPY package*.json ./
RUN npm ci --omit=dev || npm install --omit=dev

COPY . .
RUN chmod -R a+rX /app

EXPOSE {{ port }}
CMD sh -c 'exec npm start'
"""

NEXT_DOCKERFILE = """\
FROM node:20-slim
WORKDIR /app

COPY package*.json ./
RUN npm ci || npm install

COPY . .
RUN npm run build

# Next writes to .next at runtime, and the container is not root.
RUN chmod -R a+rwX /app/.next 2>/dev/null || true
RUN chmod -R a+rX /app

ENV NODE_ENV=production
EXPOSE {{ port }}
# Next.js reads PORT from the environment.
CMD sh -c 'exec npm start'
"""

STATIC_SPA_DOCKERFILE = """\
FROM node:20-slim AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci || npm install

COPY . .
# Normalise the output directory: Vite emits dist/, CRA emits build/.
RUN npm run build \\
 && if [ -d dist ]; then mv dist /out; \\
    elif [ -d build ]; then mv build /out; \\
    else echo "ERROR: build produced neither dist/ nor build/"; exit 1; fi

# nginx-unprivileged listens on 8080 and keeps its cache paths writable, which
# stock nginx:alpine cannot do as a non-root user.
FROM nginxinc/nginx-unprivileged:alpine
COPY --from=build /out /usr/share/nginx/html
EXPOSE {{ port }}
"""

LARAVEL_DOCKERFILE = """\
FROM php:8.3-cli
WORKDIR /app

RUN apt-get update \\
 && apt-get install -y --no-install-recommends git unzip libpq-dev libzip-dev \\
 && docker-php-ext-install pdo pdo_pgsql zip \\
 && rm -rf /var/lib/apt/lists/*

COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

COPY . .
RUN composer install --no-dev --no-interaction --prefer-dist --optimize-autoloader \\
 || composer install --no-interaction

RUN mkdir -p storage/framework/sessions storage/framework/views storage/framework/cache \\
      storage/logs bootstrap/cache \\
 && chmod -R a+rwX storage bootstrap/cache \\
 && chmod -R a+rX /app

EXPOSE {{ port }}
CMD sh -c 'exec php artisan serve --host=0.0.0.0 --port=${PORT:-8080}'
"""


# Detection runs highest-priority-first and stops at the first full match.
# The ordering is what keeps Next from being read as plain Express, a React SPA
# from being read as an Express server, and Django from being read as Flask.
RUNTIME_TEMPLATES = [
    {
        'key': 'python-django',
        'display_name': 'Python — Django',
        'dockerfile_template': DJANGO_DOCKERFILE,
        'default_health_path': '/',
        'default_port': 8000,
        'migrate_command': 'python manage.py migrate --noinput',
        'needs_database': True,
        # Gunicorn worker heartbeats, collectstatic output, uploads.
        'tmpfs_paths': ['/app/staticfiles', '/app/media'],
        'detection_hints': {
            'priority': 90,
            'require_files': ['manage.py'],
            'any_files': ['requirements.txt'],
        },
    },
    {
        'key': 'node-next',
        'display_name': 'Node — Next.js',
        'dockerfile_template': NEXT_DOCKERFILE,
        'default_health_path': '/',
        'default_port': 3000,
        'migrate_command': None,
        'needs_database': False,
        # Next.js writes its incremental cache under .next at runtime.
        'tmpfs_paths': ['/app/.next/cache', '/app/.npm'],
        'detection_hints': {
            'priority': 85,
            'require_files': ['package.json'],
            'package_json_deps': ['next'],
        },
    },
    {
        'key': 'php-laravel',
        'display_name': 'PHP — Laravel',
        'dockerfile_template': LARAVEL_DOCKERFILE,
        'default_health_path': '/',
        'default_port': 8080,
        'migrate_command': 'php artisan migrate --force',
        'needs_database': True,
        # Laravel compiles views, writes sessions and logs on every request.
        'tmpfs_paths': [
            '/app/storage/framework/sessions',
            '/app/storage/framework/views',
            '/app/storage/framework/cache',
            '/app/storage/logs',
            '/app/bootstrap/cache',
        ],
        'detection_hints': {
            'priority': 80,
            'require_files': ['artisan', 'composer.json'],
        },
    },
    {
        'key': 'python-flask',
        'display_name': 'Python — Flask',
        'dockerfile_template': FLASK_DOCKERFILE,
        'default_health_path': '/',
        'default_port': 8000,
        'migrate_command': None,
        'needs_database': False,
        'tmpfs_paths': [],
        'detection_hints': {
            'priority': 70,
            'require_files': ['requirements.txt'],
            'require_absent': ['manage.py'],
            'content_matches': [
                {'file': 'requirements.txt', 'pattern': r'^\s*flask'},
            ],
        },
    },
    {
        'key': 'static-spa',
        'display_name': 'Static SPA (Vite / CRA / Vue)',
        'dockerfile_template': STATIC_SPA_DOCKERFILE,
        'default_health_path': '/',
        'default_port': 8080,
        'migrate_command': None,
        'needs_database': False,
        # nginx-unprivileged keeps its cache and pid under these paths.
        'tmpfs_paths': ['/var/cache/nginx', '/var/run', '/tmp/nginx'],
        'detection_hints': {
            'priority': 65,
            'require_files': ['package.json'],
            'package_json_deps': [
                'vite', 'react-scripts', '@angular/core', 'vue', 'svelte', 'parcel',
            ],
        },
    },
    {
        'key': 'node-express',
        'display_name': 'Node — Express',
        'dockerfile_template': EXPRESS_DOCKERFILE,
        'default_health_path': '/',
        'default_port': 3000,
        'migrate_command': None,
        'needs_database': False,
        'tmpfs_paths': ['/app/.npm'],
        'detection_hints': {
            'priority': 60,
            'require_files': ['package.json'],
        },
    },
]
