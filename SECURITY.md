# Security Model — UDOM e-Store

This platform **builds and runs arbitrary code written by students, on your server**. That single
fact drives everything below. This document states what we defend against, what we actually do
about it, and — the section worth your attention — **what we do not defend against**.

Last reviewed: Stage 7 hardening pass. Read the [Accepted risks](#accepted-risks) section end to
end before going live. If anything there surprises you, do not deploy yet.

---

## Threat model

**Primary adversary: a malicious student submission.** Someone submits a project intending to
attack the platform, other students, or third parties. They fully control the source archive, the
`Dockerfile` (if they supply one), everything the container executes at build and run time, and
anything the app prints to stdout. They can also hold a normal user account.

**Secondary adversaries:** an external user trying to obtain a subscription without paying; an
unauthenticated internet user; a legitimate subscriber trying to exfiltrate a hosted app.

**Assets, roughly in order of value:** the platform database (all users, payments,
subscriptions); the Docker socket, which is equivalent to host root; students' unpublished source
code and demo credentials; other tenants' databases; the server's reputation and IP address;
subscription revenue.

**Explicitly out of scope:** a malicious platform administrator (admins legitimately hold Docker
socket access and can read everything), and physical/host compromise.

---

## Trust boundaries

```
internet ──▶ nginx ──▶ Django (backend)         ── holds the Docker socket = host root
                          │
                          ├──▶ Postgres, Redis        on udom_internal
                          │
                          └──▶ udom_app_<slug>        one internal network per student app
                                    │                  no route off the host
                                    └──▶ student container   read-only, non-root, caps dropped
```

A student container is attached to exactly one network. The backend and the Celery worker are
also attached to it (the worker runs the health check; without it every deploy would fail). For
apps that need a database, the shared Postgres container is attached too — see
[Accepted risks](#accepted-risks).

---

## What is mitigated

### Container isolation

| Control | Implementation |
|---|---|
| No published ports | `run_container` never passes `ports`; asserted in code |
| No host mounts, no Docker socket | `_assert_no_host_access()` rejects `volumes`, `mounts`, `binds`, `devices`, `privileged`, `pid_mode`, `ipc_mode`, `userns_mode`, `cap_add`, `ports`, `network_mode`, `sysctls` before every container start, and refuses any config mentioning `docker.sock` |
| Non-root | `user=1000:1000` at run time |
| All capabilities dropped | `cap_drop=['ALL']`, `security_opt=['no-new-privileges:true']` |
| Read-only root filesystem | `read_only=True`, with size-bounded tmpfs for the paths each runtime declares in `RuntimeTemplate.tmpfs_paths` |
| Memory / CPU / PID caps | `mem_limit`, `memswap_limit` (so it cannot swap past its ceiling), `nano_cpus`, `pids_limit` |
| FD / process / file-size caps | `ulimits` for `nofile`, `nproc`, `fsize` |
| **Limits verified, not assumed** | Docker only *warns* when a cgroup feature is unavailable — the container still starts. `_verify_limits()` reads back the applied `HostConfig` and **fails the deploy** if memory, CPU, pids, caps, read-only, user, network or mounts differ from what was requested |
| No egress | Per-app networks are created `internal=True`. No outbound internet, no host LAN, no cloud metadata endpoint (`169.254.169.254`), no reaching host-published ports. Opt-in per app via `HostedApp.allow_egress`, which logs a warning when used |
| No sibling reachability | Each app has its own bridge network; Docker's inter-bridge isolation blocks cross-network traffic, and no student container shares a network with another |
| Redis and frontend unreachable | Neither joins any per-app network |

### Database isolation

- Each app gets a dedicated database and a dedicated role, created `NOSUPERUSER NOCREATEDB
  NOCREATEROLE NOINHERIT`.
- `REVOKE ALL ON DATABASE <app_db> FROM PUBLIC`, then `GRANT` only to the owning role.
- `REVOKE CONNECT ON DATABASE <platform_db> FROM PUBLIC` and the same on `template1`, so student
  roles cannot open a session against the platform's own database — PostgreSQL grants this by
  default and it is not closed unless you do it explicitly.
- `REVOKE ALL ON SCHEMA public FROM PUBLIC` in the app database, with rights re-granted to the
  app's own role (required, or migrations break on PostgreSQL < 15 where `public` is owned by the
  bootstrap superuser).
- Per-role `CONNECTION LIMIT`, so one app cannot exhaust the shared instance's connection slots.
- Passwords are generated with `secrets.choice` (CSPRNG, ~190 bits) and stored Fernet-encrypted.
- Postgres is published on `127.0.0.1` only, never `0.0.0.0`.

### Build safety

Archive extraction (`deployer/extraction.py`) rejects absolute paths, `..` traversal, symlink
entries, and any entry whose resolved target escapes the build directory. Size is capped both
from the manifest and again while streaming (the manifest is attacker-controlled). Compression
ratio is capped in aggregate **and** per entry, so a small archive that expands enormously is
rejected before it costs I/O. Entry count is capped.

Builds have a hard timeout and a post-hoc image size cap. The build context is the extraction
directory only; because symlinks are rejected, a student cannot plant one to pull in a host path.

Student-supplied Dockerfiles are validated before use: `FROM scratch` is rejected, as is any
content referencing `--privileged`, `--cap-add`, `--security-opt`, host namespaces, or the Docker
socket. An `EXPOSE` (or an explicit admin port override) is required. **This validation is
best-effort defence in depth, not a sandbox** — the runtime posture above is the real control.

### Secrets

- `HostedApp.env_vars` and `db_password` are Fernet-encrypted at rest.
- **All log sinks are redacted** (`deployer/redaction.py`). This matters because the migrate step
  executes the student's own code with the database credentials in its environment; a
  `print(os.environ)` would otherwise write a live password into `build_log`, into every database
  backup, into the admin UI, into a notification email, and into the application log. Redaction
  combines literal removal of this deployment's actual secrets with pattern matching for
  credential shapes (DSNs, `*_PASSWORD=`, `*_TOKEN=`, JWTs, AWS keys, PEM blocks).
- `error_summary` and notification emails are redacted on the same path.

### Application security

- The payment webhook requires an HMAC-SHA256 signature over the raw body, compared in constant
  time, and **fails closed when the secret is unset**. Completion is idempotent, so a captured
  request cannot be replayed to re-activate a revoked subscription.
- Source archives, deployment notes and demo credentials are served **only** to the app's own
  developer or an admin; the public detail endpoint excludes them, and nginx denies
  `/media/projects/source/` outright.
- Uploads are extension- and size-validated in the serializer (so requests that bypass nginx are
  still covered). `/media/` is served with `nosniff`, `Content-Disposition: attachment` and a
  sandboxing CSP, closing stored-XSS via uploaded HTML/SVG.
- `is_featured` / `is_active` are admin-only; `status` transitions to approved/rejected are
  admin-only.
- Scoped rate limits on login (10/min), registration (5/hr), the webhook (60/min) and stack
  detection (20/hr). `NUM_PROXIES` is set so the throttle keys on the real client IP rather than
  a client-supplied `X-Forwarded-For`. Counters live in Redis, so they are shared across workers
  rather than per-process.
- The OpenAPI schema and docs require admin.
- `DEBUG=False` by default, with HSTS, secure cookies, `nosniff`, and `X-Frame-Options: DENY`
  outside development.

---

## Accepted risks

**These are real. Read them.**

### 1. The gateway proxy does not exist — the subscription gate is unimplemented

`gateway/` contains models, a hostname allowlist, and an encryption layer, but **no proxy view
and no URLs**. `allowlist.is_allowed()` has no callers. Consequently:

- There is no request path from a user to a running student app at all.
- The subscription check that is supposed to gate access **is not enforced anywhere**, because
  there is nothing to enforce it in.
- The SSRF defences, proxy rate limiting, and upstream-header-injection handling described in the
  original design do not exist yet.

Today this is safe by accident: student apps are unreachable except from the backend and worker
containers. But the product does not function until this is built, and when it is built, all of
the above needs implementing and reviewing — DNS rebinding, redirect chains, IPv6-mapped private
addresses, and octal/decimal IP literals included. **Do not assume any of it is handled.**

### 2. The Django backend holds the Docker socket — this is effectively host root

`backend` and `celery_worker` mount `/var/run/docker.sock` and run as root. Anyone who achieves
remote code execution in Django, or who obtains admin credentials, can start a privileged
container and own the host. This is inherent to orchestrating Docker from the application, and it
is the single largest concentration of risk in the design.

Partial mitigations: the socket is never exposed to student containers (asserted in code), and
`DEBUG=False` prevents the settings dump that would otherwise hand over `SECRET_KEY`. Moving the
deployer behind a separate, minimally-privileged daemon is the real fix — the `DockerService`
abstraction exists specifically so that can be swapped in without touching views or tasks.

### 3. DB-backed apps retain a network route to the shared Postgres

Django and Laravel apps need a database, and this deployment shares one Postgres instance, so the
`udom_db` container is attached to those apps' networks. The student container therefore has a TCP
route to it. **The boundary is authentication and privilege, not the network:** the role cannot
connect to the platform database or to any other tenant's database, holds no rights outside its
own, and is connection-limited.

Residual: exposure to Postgres protocol-level vulnerabilities, and catalog enumeration within its
own session. A per-app Postgres sidecar removes the route entirely at roughly double the container
count; this was consciously deferred for laptop-scale deployments.

### 4. Build-time egress is unrestricted

`docker build` runs on Docker's default network, so a student's `RUN` instruction has full
outbound access — it can download payloads or exfiltrate the build context. This is largely
inherent: `pip install` and `npm ci` need the network. Bounded by the build timeout and image size
cap, but not prevented. A build-time egress proxy with a package-registry allowlist would close it.

### 5. Screen recording by a legitimate subscriber cannot be prevented

A paying user with legitimate access to a hosted app can record, screenshot, or scrape whatever it
displays. There is no technical control for this and there cannot be one. If content is
commercially sensitive, the mitigation is contractual and legal, not technical.

### 6. WebSocket applications are unsupported

The stack is WSGI (gunicorn). Student apps that depend on WebSockets will fail once proxying
exists. Supporting them requires Django Channels and an ASGI server.

### 7. Encryption-at-rest caveats

- `DEPLOYER_ENV_ENCRYPTION_KEY` defaults to an unsalted `sha256(SECRET_KEY)` with no KDF. **Set it
  explicitly** (`.env.example` shows how) — otherwise leaking `SECRET_KEY` decrypts every stored
  credential, and rotating `SECRET_KEY` silently orphans them.
- On `InvalidToken`, the encrypted fields return the raw stored value rather than failing, so a
  key change degrades to handing back ciphertext instead of erroring loudly.
- `EncryptedJSONField.value_to_string` emits plaintext, so `manage.py dumpdata` on
  `gateway.HostedApp` writes all environment variables in cleartext. Treat such fixtures as
  secrets.

### 8. Smaller known gaps

- No cap on image **layer** count (total size is capped).
- The Dockerfile validator is substring-based and trivially evaded by an attacker who cares; it
  catches mistakes and casual attempts, not determined ones.
- `detect_from_archive` reads a zip's entry list into memory; a pathological archive with millions
  of entries could pressure memory before the deploy-time caps apply.
- Container images are not scanned for known-vulnerable base layers.
- No egress restriction exists on the platform's *own* containers.

---

## Configuration checklist before going live

1. Generate and set `SECRET_KEY`, `POSTGRES_PASSWORD` and `DEPLOYER_ENV_ENCRYPTION_KEY` in `.env`
   (never commit it). Commands are in `.env.example`.
2. Set `PAYMENTS_WEBHOOK_SECRET` to the provider's shared secret. Until then the webhook rejects
   everything, which is the correct default.
3. Keep `DEBUG=False`. Set `SECURE_SSL_REDIRECT=True` once TLS terminates at nginx.
4. Confirm Postgres is not published beyond `127.0.0.1`.
5. Confirm the host kernel supports memory and pids cgroup limits — a deploy will now fail loudly
   rather than run unconstrained, so verify this before your first real deploy.
6. Restrict `/admin/` by source IP at nginx if the platform is internet-facing.

## Reporting

Report suspected vulnerabilities privately to the platform administrators. Do not open a public
issue.
