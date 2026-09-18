# Docker development

Docker provides local MongoDB and Qdrant infrastructure. It is not a production
deployment definition.

## Recommended workflow

Check for existing services, then run the application with hot reload on the host:

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

MongoDB, Qdrant, documents and logs use named volumes. The backend_credentials
volume holds the automatically generated encryption key separately from the
database. Back up credential state together with data; do not delete volumes
to troubleshoot a failed migration.

Infrastructure-only development and full Compose use separate volumes and
credential locations. Copying source or switching Compose files does not
migrate the library or its keys.

The root .dockerignore excludes secrets, runtime state and local-only material
at all relevant depths. Never copy an existing credential directory into an
image. Keep services local; there is no authentication for a shared installation.
