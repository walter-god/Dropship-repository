"""Per-app Postgres provisioning.

Each database-backed student app gets its own database and its own login role
that owns only that database. The role is NOSUPERUSER / NOCREATEDB /
NOCREATEROLE, so the credentials injected into a student container cannot be
used to reach the platform's own data.

PostgreSQL's defaults work against this: `template1` carries CONNECT for
PUBLIC, which every new database inherits, so a student role could otherwise
open a session to the platform's own database. `_harden_cluster()` revokes
that, revokes PUBLIC's CREATE on the app's schema, and applies a per-role
connection limit.

Residual risk, documented in SECURITY.md rather than hidden here: DB-backed
apps still have a TCP route to the shared Postgres instance, because the
container needs to reach *a* database and this deployment shares one. The
boundary is therefore authentication and privilege, not the network. A
per-app Postgres sidecar would remove the route entirely, at roughly double
the container count.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import string

import psycopg2
from psycopg2 import sql
from django.conf import settings

logger = logging.getLogger(__name__)

# Postgres truncates identifiers at 63 bytes.
MAX_IDENTIFIER = 63


class ProvisioningError(Exception):
    """A database or role could not be created or removed."""


def _sanitize(slug: str) -> str:
    return re.sub(r'[^a-z0-9_]', '_', slug.lower()).strip('_') or 'app'


def make_identifiers(slug: str) -> tuple[str, str]:
    """Return (db_name, db_user) for an app slug, collision-resistant."""
    base = _sanitize(slug)
    # Long slugs would collide after truncation, so fold in a short digest.
    digest = hashlib.sha256(slug.encode()).hexdigest()[:8]
    stem = base[: MAX_IDENTIFIER - len('udom_app_') - len(digest) - 2]
    return f'udom_app_{stem}_{digest}', f'udomu_{stem}_{digest}'[:MAX_IDENTIFIER]


def generate_password(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _connect():
    try:
        conn = psycopg2.connect(
            host=settings.DEPLOYER_APP_DB_HOST,
            port=settings.DEPLOYER_APP_DB_PORT,
            user=settings.DEPLOYER_APP_DB_SUPERUSER,
            password=settings.DEPLOYER_APP_DB_PASSWORD,
            dbname='postgres',
            connect_timeout=10,
        )
    except psycopg2.Error as exc:
        raise ProvisioningError(f'Cannot reach Postgres to provision: {exc}') from exc
    # CREATE DATABASE cannot run inside a transaction block.
    conn.autocommit = True
    return conn


def provision(db_name: str, db_user: str, password: str) -> None:
    """Create the role and database, idempotently."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (db_user,))
            if cur.fetchone():
                cur.execute(
                    sql.SQL('ALTER ROLE {} WITH LOGIN PASSWORD %s').format(
                        sql.Identifier(db_user)
                    ),
                    (password,),
                )
            else:
                cur.execute(
                    sql.SQL(
                        'CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB '
                        'NOCREATEROLE NOINHERIT PASSWORD %s'
                    ).format(sql.Identifier(db_user)),
                    (password,),
                )

            cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (db_name,))
            if not cur.fetchone():
                cur.execute(
                    sql.SQL('CREATE DATABASE {} OWNER {}').format(
                        sql.Identifier(db_name), sql.Identifier(db_user)
                    )
                )

            # Scope privileges to this database only.
            cur.execute(
                sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(
                    sql.Identifier(db_name)
                )
            )
            cur.execute(
                sql.SQL('GRANT ALL PRIVILEGES ON DATABASE {} TO {}').format(
                    sql.Identifier(db_name), sql.Identifier(db_user)
                )
            )

            # Bound concurrent connections so one app cannot exhaust the
            # shared instance's connection slots and take the platform with it.
            cur.execute(
                sql.SQL('ALTER ROLE {} CONNECTION LIMIT %s').format(
                    sql.Identifier(db_user)
                ),
                (settings.DEPLOYER_APP_DB_CONNECTION_LIMIT,),
            )

            _harden_cluster(cur, db_name, db_user)
    except psycopg2.Error as exc:
        raise ProvisioningError(f'Could not provision {db_name}: {exc}') from exc
    finally:
        conn.close()

    logger.info('Provisioned database %s owned by %s', db_name, db_user)


def _harden_cluster(cur, app_db_name: str, app_db_user: str) -> None:
    """Close the cross-database holes PostgreSQL leaves open by default.

    Two defaults matter here. First, `template1` carries CONNECT for PUBLIC,
    so every database — including the platform's own — is connectable by every
    role unless explicitly revoked; provisioning only revoked on the app's own
    database, leaving `udom_estore` reachable by every student role. Second, on
    PostgreSQL < 15 PUBLIC holds CREATE on schema `public`, so a connected role
    can create objects and consume disk even with no table grants.

    Idempotent: REVOKE on an already-revoked privilege is a no-op.
    """
    platform_db = settings.DATABASES['default']['NAME']

    # Stop student roles connecting to the platform database at all.
    cur.execute(
        sql.SQL('REVOKE CONNECT ON DATABASE {} FROM PUBLIC').format(
            sql.Identifier(platform_db)
        )
    )
    # Django connects as the owner/superuser, so it is unaffected by the above;
    # re-grant explicitly in case the configured app user is not the owner.
    cur.execute(
        sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
            sql.Identifier(platform_db),
            sql.Identifier(settings.DATABASES['default']['USER']),
        )
    )
    # New databases inherit template1's ACL, so fix the source too.
    cur.execute('REVOKE CONNECT ON DATABASE template1 FROM PUBLIC')

    # Deny PUBLIC object creation inside the app's own database, then hand the
    # rights back to the app's own role. The re-grant is essential: on
    # PostgreSQL < 15 schema `public` is owned by the bootstrap superuser, not
    # by the database owner, so revoking from PUBLIC without this would strip
    # the app's ability to create its own tables and break every migration.
    try:
        app_conn = psycopg2.connect(
            host=settings.DEPLOYER_APP_DB_HOST,
            port=settings.DEPLOYER_APP_DB_PORT,
            user=settings.DEPLOYER_APP_DB_SUPERUSER,
            password=settings.DEPLOYER_APP_DB_PASSWORD,
            dbname=app_db_name,
            connect_timeout=10,
        )
        app_conn.autocommit = True
        try:
            with app_conn.cursor() as app_cur:
                app_cur.execute('REVOKE ALL ON SCHEMA public FROM PUBLIC')
                app_cur.execute(
                    sql.SQL('GRANT ALL ON SCHEMA public TO {}').format(
                        sql.Identifier(app_db_user)
                    )
                )
                app_cur.execute(
                    sql.SQL('ALTER SCHEMA public OWNER TO {}').format(
                        sql.Identifier(app_db_user)
                    )
                )
        finally:
            app_conn.close()
    except psycopg2.Error as exc:
        # Not fatal: the database is still isolated at the CONNECT layer.
        logger.warning('Could not revoke PUBLIC on schema public in %s: %s', app_db_name, exc)


def drop(db_name: str, db_user: str) -> None:
    """Remove the database and role. Never raises — used during cleanup."""
    try:
        conn = _connect()
    except ProvisioningError as exc:
        logger.warning('Skipping DB teardown: %s', exc)
        return

    try:
        with conn.cursor() as cur:
            # Terminate stragglers, or DROP DATABASE fails.
            cur.execute(
                'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
                'WHERE datname = %s AND pid <> pg_backend_pid()',
                (db_name,),
            )
            cur.execute(
                sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(db_name))
            )
            cur.execute(
                sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(db_user))
            )
    except psycopg2.Error as exc:
        logger.warning('Could not fully drop %s/%s: %s', db_name, db_user, exc)
    finally:
        conn.close()


def build_database_url(db_name: str, db_user: str, password: str) -> str:
    """DATABASE_URL as seen from inside a student container.

    Uses the Docker DNS name for Postgres, not localhost — the app is in its
    own network namespace.
    """
    from urllib.parse import quote

    host = settings.DEPLOYER_APP_DB_INTERNAL_HOST
    port = settings.DEPLOYER_APP_DB_PORT
    return f'postgresql://{quote(db_user)}:{quote(password)}@{host}:{port}/{db_name}'
