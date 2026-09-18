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

The backend also supports key-free PDF import with page-level source extraction.
The current upload screen still starts analysis, but it now preserves the original
before generation; extraction or AI failures do not discard an already stored PDF.
Imported/not-ready records are labelled separately from completed analysis.
See docs/API_REFERENCE.md for the source API. The redesigned review workflow is
not yet implemented.

## Validation

For routine development, run the tests and type/lint checks affected by the change.
Batch broader manual UI testing and production builds at meaningful checkpoints;
neither is required after every small implementation. The complete checkpoint is:

~~~bash
npm run check
~~~

This runs deterministic backend/frontend tests, shared-type build, frontend
type checking, lint and production build. It does not call paid AI services.
See docs/DEVELOPMENT.md for the incremental workflow. Reviewed synthetic PDFs
and their reproducible sources are in tests/fixtures/pdfs.

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
environment, deployment workflow or CI pipeline. Settings offers GPT-5.6 Luna,
Terra and Sol, plus GPT-5 Mini and Nano for development/testing. Luna is the
default when no model selection is saved; existing explicit selections are
preserved. Choose more expensive models deliberately; there is no model fallback.

No open-source license has been selected. Until one is added, the repository is
UNLICENSED and no permission to copy, modify or redistribute the code is granted.
