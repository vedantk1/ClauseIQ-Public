# ClauseIQ

ClauseIQ is a personal contract-review application that runs on your computer.
Upload a PDF, inspect structured clause and risk analysis, add notes, request
rewrite suggestions, and ask document-grounded questions.

The application opens directly into one local workspace. There are no accounts,
passwords, email verification, or admin roles. AI features use the OpenAI API
with your own key, entered in Settings. This is not an offline AI application
or a public, application-funded service.

> ClauseIQ is an engineering project, not legal advice. AI output can be
> incomplete or wrong and must be checked against the source.

## Technology

- Frontend: Next.js 15, React 19, TypeScript, Tailwind CSS
- Backend: FastAPI, Python 3.13
- Storage: MongoDB, GridFS and Qdrant
- Local infrastructure: Docker Compose

## Local development

Prerequisites: Node.js 24+, Python 3.13+, Docker with Docker Compose, and an
OpenAI API key if you want to run AI features.

~~~bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
npm ci
npm run setup
~~~

No application secrets or email configuration need to be generated. Check that
ports 3000, 8000, 27017, 6333 and 6334 are free or already running ClauseIQ, then:

~~~bash
docker compose -f docker-compose.dev.yml up -d
npm run dev
~~~

Open http://localhost:3000 and add your key in Settings. The backend is at
http://localhost:8000; its API documentation is at http://localhost:8000/docs.
Only local access is supported. Do not expose these services to a network or
put them behind a public tunnel.

Documents stay in the library until you delete them, unless you explicitly
enable automatic deletion in Settings. There is no document-count cap; individual
upload size and request limits still apply. Existing saved reviews, PDFs, notes
and reports remain usable without an AI key.

## Validation

~~~bash
npm run check
~~~

This runs deterministic backend/frontend tests, shared-type build, frontend
type checking, lint and production build. It does not call paid AI services.

## Documentation

- docs/DEVELOPMENT.md — setup, commands, migration and troubleshooting
- docs/ARCHITECTURE.md — components and data boundaries
- docs/API_REFERENCE.md — API groups and local access
- docs/SECURITY.md — local trust model, credentials and known limitations
- docs/REPOSITORY_POLICY.md — public/private file policy
- docs/CONTRIBUTING.md — contribution workflow
- DOCKER.md — infrastructure and container smoke runs

## Project status and licensing

Active local development is the priority. There is no supported hosted production
environment, deployment workflow or CI pipeline. Model support remains the
existing GPT-5, GPT-5 Mini and GPT-5 Nano catalog for now.

No open-source license has been selected. Until one is added, the repository is
UNLICENSED and no permission to copy, modify or redistribute the code is granted.
