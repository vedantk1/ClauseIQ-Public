# ClauseIQ

ClauseIQ is a full-stack legal-document analysis application. It extracts text
from PDF contracts, produces structured clause and risk analysis, and supports
document-grounded chat through a retrieval-augmented generation pipeline.

The project is in active redevelopment. It is currently intended to run
locally, has no supported public deployment, and does not provide an
application-funded AI service.

> ClauseIQ is an engineering project, not legal advice. AI output can be
> incomplete or wrong and must be reviewed by a qualified person.

## Capabilities

- Account registration, authentication, and document ownership
- PDF upload, extraction, structured analysis, and review
- Clause-level notes, rewrite suggestions, and risk summaries
- Document-grounded chat backed by Qdrant
- Document management, analytics, and administrative controls
- Bring-your-own-key (BYOK) OpenAI access for authenticated users

## Technology

- Frontend: Next.js 15, React 19, TypeScript, Tailwind CSS
- Backend: FastAPI, Python 3.13
- Data: MongoDB
- Vector search: Qdrant
- Local infrastructure: Docker Compose

## Local development

Prerequisites:

- Node.js 24 or newer
- Python 3.13 or newer
- Docker with Docker Compose
- An OpenAI API key for the signed-in user who runs AI features

Prepare the environment:

~~~bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
npm ci
npm run setup
~~~

Replace the two development-only secret placeholders in backend/.env. The
default development policy sets EMAIL_VERIFICATION_REQUIRED=false, so local
accounts are treated as verified and BYOK works without SMTP. Staging and
production always require verification. To exercise verification locally, set
the flag to true and configure SMTP.

Start MongoDB and Qdrant, then run both application servers in development mode:

~~~bash
docker compose -f docker-compose.dev.yml up -d
npm run dev
~~~

Open:

- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- API documentation: http://localhost:8000/docs
- Qdrant dashboard: http://localhost:6333/dashboard

Create an account and add your OpenAI API key in application settings. With
the default development policy, no email step is required. The backend
environment does not accept an application-owner OpenAI key.

For a containerized smoke run instead, use:

~~~bash
docker compose up --build
~~~

## Validation

Run the deterministic local checks with:

~~~bash
npm run check
~~~

Individual commands are documented in docs/DEVELOPMENT.md.

## Documentation

- docs/DEVELOPMENT.md — setup, commands, and troubleshooting
- docs/ARCHITECTURE.md — components, data flow, and trust boundaries
- docs/API_REFERENCE.md — API groups and access rules
- docs/SECURITY.md — security model and disclosure guidance
- docs/REPOSITORY_POLICY.md — public/private file policy and Git workflow
- docs/CONTRIBUTING.md — contribution workflow

## Deployment and licensing

There is no deployment workflow in this repository. Hosting and continuous
delivery will be designed separately if the project later needs them.

No open-source license has been selected yet. Until a license is added, the
repository is UNLICENSED and no permission to copy, modify, or redistribute the
code is granted.
