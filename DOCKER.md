# Docker development

Docker provides local MongoDB and Qdrant infrastructure. It is not a production
deployment definition.

## Recommended workflow

Check for existing services before starting the application.

For an existing installation, read the version and data guidance below before
recreating Qdrant. Changing an image tag does not migrate or back up its volume.

Run the application with hot reload on the host:

~~~bash
docker compose -f docker-compose.dev.yml up -d
npm run dev
~~~

Stop infrastructure without deleting its named volumes:

~~~bash
docker compose -f docker-compose.dev.yml down
~~~

## Container smoke run

After creating backend/.env and frontend/.env.local from their examples:

~~~bash
docker compose up --build
docker compose ps
docker compose logs -f backend frontend
~~~

This builds the application images; normal development uses the host workflow.
Published frontend/backend and database ports bind to 127.0.0.1. Container
applications listen on their internal interfaces for container networking;
that does not authorize exposing host ports externally.

## Persistence

The backend loads `MONGODB_DATABASE` from `backend/.env` when present, otherwise
using the same `clauseiq` default as native development. Keep an existing
installation's database name; changing it does not rename or migrate data.
The local database-binding marker refuses name/prefix changes within the same
workspace state. See [workspace continuity](docs/DEVELOPMENT.md#existing-workspace-continuity).

MongoDB, Qdrant, documents and logs use named volumes. The backend_credentials
volume holds the automatically generated encryption key separately from the
database. Back up credential state together with data; do not delete volumes
to troubleshoot a failed migration.

Infrastructure-only development and full Compose use separate volumes and
credential locations. Copying source or switching Compose files does not
migrate the library or its keys.

## Qdrant versions and existing stores

Both Compose definitions pin `qdrant/qdrant:v1.16.3`; backend requirements pin
`qdrant-client==1.16.2`. This intentionally keeps the existing 1.16 storage line
and replaces the floating `latest` tag with a tested pair. The server patch includes
[upstream storage fixes](https://github.com/qdrant/qdrant/releases/tag/v1.16.3).
Review client and server pins together; changing one is not a routine independent
dependency bump. Updating repository declarations does not update an already
running container or installed Python environment.

Before applying a different server image to an existing volume, inspect its
actual running version and back up the vector data using Qdrant's supported
snapshot/restore procedure. Preserve the MongoDB/GridFS and credential backups
alongside it. Recreating a server, upgrading its data or changing its Python
client is a separate maintenance action; never downgrade a server against data
written by a newer version or use `down -v` to resolve a compatibility warning.
Do not disable the SDK compatibility check to hide a mismatched pair.

The opt-in compatibility smoke documented in backend/tests/README.md uses its
own temporary Qdrant container and synthetic vectors. It checks client behavior
without reading, migrating or certifying the contents of an existing store.

The root .dockerignore excludes secrets, runtime state and local-only material
at all relevant depths. Never copy an existing credential directory into an
image. Keep services local; there is no authentication for a shared installation.
