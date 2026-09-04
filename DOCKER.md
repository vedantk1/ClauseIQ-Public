# Docker development

Docker is used for local infrastructure and container smoke testing. It is not
a production deployment definition.

## Recommended development mode

Run MongoDB and Qdrant in containers while the application runs with hot
reload on the host:

~~~bash
docker compose -f docker-compose.dev.yml up -d
npm run dev
~~~

Stop infrastructure without deleting its named volumes:

~~~bash
docker compose -f docker-compose.dev.yml down
~~~

## Containerized smoke run

After creating backend/.env and frontend/.env.local:

~~~bash
docker compose up --build
docker compose ps
docker compose logs -f backend frontend
~~~

The full Compose file builds the frontend and backend images and runs MongoDB
and Qdrant. It is useful for checking container compatibility, but the
infrastructure-only mode is the normal development path.

## Data

MongoDB, Qdrant, uploaded documents, and application logs use local Docker
volumes. Published MongoDB and Qdrant ports bind to 127.0.0.1 so those
unauthenticated development services are not exposed to the local network. Do
not commit exports, uploads, logs, or volume data.

The tracked root .dockerignore applies to both application image builds because
their build context is the repository root. Keep secret and local-only patterns
there whenever the build context changes.
