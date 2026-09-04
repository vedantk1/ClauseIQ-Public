# Development

## Prerequisites

- Node.js 24 or newer
- npm with lockfile version 3 support
- Python 3.13 or newer
- Docker with Docker Compose

## First setup

~~~bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
npm ci
npm run setup
~~~

Generate unique local values for JWT_SECRET_KEY and
API_KEY_ENCRYPTION_SECRET. Do not put an OpenAI key in backend/.env.

EMAIL_VERIFICATION_REQUIRED defaults to false for development and testing.
Fresh local accounts are therefore treated as verified and can add a BYOK key
without SMTP. Set it to true and configure SMTP only when testing email
verification. Staging and production always require verification, regardless
of an attempted false override.

## Start development

Check whether ports 3000, 8000, 27017, 6333, and 6334 are already in use.
Then start local infrastructure and the hot-reloading application servers:

~~~bash
docker compose -f docker-compose.dev.yml up -d
npm run dev
~~~

Users configure their own OpenAI API key after signing in. MongoDB and Qdrant
are published on the host loopback interface only; they are not intentionally
available to other devices on the local network.

## Root commands

| Command | Purpose |
| --- | --- |
| npm run setup | Create the backend venv, install locked Node dependencies, and build shared types |
| npm run dev | Run frontend and backend development servers |
| npm run test | Run deterministic backend tests |
| npm run typecheck | Type-check the frontend without emitting files |
| npm run lint | Run frontend lint |
| npm run build | Build shared types and the frontend |
| npm run check | Run the complete local validation sequence |

## Focused commands

~~~bash
docker compose -f docker-compose.dev.yml ps
docker compose -f docker-compose.dev.yml logs -f
cd backend && venv/bin/python -m pytest tests -v
npm --prefix shared run build
npm --prefix frontend run dev
~~~

## Troubleshooting

- Backend startup failure: confirm backend/.env exists and both local secrets
  are at least 32 characters.
- Database failure: confirm the development Compose services are healthy and
  MongoDB uses localhost:27017.
- Vector-search failure: confirm Qdrant is available at localhost:6333.
- AI feature unavailable: sign in and add a valid user OpenAI key in settings.
- Email verification unavailable: in development, leave
  EMAIL_VERIFICATION_REQUIRED=false; to test the verification flow, configure
  SMTP before setting it to true.
- Frontend API failure: confirm NEXT_PUBLIC_API_URL is
  http://localhost:8000 and restart the frontend after changing it.

The full container smoke workflow is documented in ../DOCKER.md.
