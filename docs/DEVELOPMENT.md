# Development

## Setup

Use Node.js 24+, Python 3.13+ and Docker with Docker Compose.

~~~bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
npm ci
npm run setup
~~~

No JWT, SMTP or admin-email setup is needed. Do not put an OpenAI key in an
environment file; enter it in the application's Settings when needed.

Check ports 3000, 8000, 27017, 6333 and 6334 before starting another service:

~~~bash
docker compose -f docker-compose.dev.yml up -d
npm run dev
~~~

Open http://localhost:3000. Servers use development mode and loopback bindings.
MongoDB and Qdrant must both be available for workspace migration preflight.
Use matching compatible Qdrant server/client versions; an existing older Docker
image may need a separately reviewed upgrade before updating stored vectors.

## Commands

| Command | Purpose |
| --- | --- |
| npm run setup | Install dependencies and build shared types |
| npm run dev | Hot-reloading frontend and backend |
| npm test | Deterministic backend and frontend tests, no paid AI calls |
| npm run test:backend | Backend tests only |
| npm run test:frontend | Local API client contract tests |
| npm run typecheck | Frontend types |
| npm run lint | Frontend lint |
| npm run build | Shared types and frontend production build |
| npm run check | Complete deterministic validation sequence |

Focused commands:

~~~bash
docker compose -f docker-compose.dev.yml ps
cd backend && venv/bin/python -m pytest tests -v
npm --prefix shared run build
~~~

Optional isolated live storage checks (no OpenAI calls) are documented in
../backend/tests/README.md. They create and clean up only their own fixture stores.

## Existing local installations

Back up MongoDB, GridFS and Qdrant before the first workspace-mode startup.
Do not clear volumes or replace an existing .env file to fix a startup issue.

Startup checks ownership across all stores, then adds workspace metadata
without deleting accounts, legacy ownership fields, original ciphertext or
document relationships. A migration marker makes interrupted runs restartable.
Inherited automatic deletion is disabled; re-enable it only deliberately in
Settings. Legacy document-count settings are no longer enforced.

Multiple old accounts, missing ownership or conflicting data stop startup
rather than silently merging libraries. Select/import the intended data into
a separate local installation with an explicit migration plan; there is no
automatic account-selection or destructive reset command.

A single legacy key can be re-encrypted if the old API_KEY_ENCRYPTION_SECRET
(or its old JWT_SECRET_KEY fallback) remains available in the backend environment
or its existing .env. These values are used only for legacy decryption, not
new account functionality. If unavailable, Settings shows that key re-entry is
needed; document access is unaffected and the original ciphertext is preserved.

## Credential state and backups

The first key save creates backend/.local-only/workspace/credential.key with
owner-only permissions. WORKSPACE_STATE_DIR overrides the directory, relative
to backend unless absolute. This is ignored runtime data, not source.

Back up the database and credential directory together. Full Compose uses the
backend_credentials volume instead. Host development and full Compose use
different data/credential volumes; switching workflows is not a data migration.
A missing key file requires restoration or explicit key re-entry, never a reset
of the document library.

## Troubleshooting

- Database/vector startup failure: check Docker and both development services.
- Migration refusal: preserve data, read the ownership error and plan an explicit
  import. Repeated restarts cannot resolve ambiguous ownership.
- Key not usable: re-enter it in Settings, or restore the matching credential
  state. Saving does not validate OpenAI balance/model access.
- Local-access denial: use localhost, the configured frontend port and the
  X-ClauseIQ-Local: 1 request header; do not broaden CORS to external origins.
- Frontend API failure: NEXT_PUBLIC_API_URL defaults to http://localhost:8000.
  Restart frontend development after changing public environment values.
- Type-check errors referring to removed routes after switching revisions:
  regenerate Next.js types with a fresh frontend build.

See ../DOCKER.md for container smoke testing. Hosted deployment is unsupported.
