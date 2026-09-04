# Repository Guidance

This file contains stable project instructions for coding assistants and human
contributors. Transient handovers, session notes, screenshots, and local tool
state belong in .local-only or another ignored path.

## Project shape

- frontend — Next.js, React, and TypeScript
- backend — FastAPI and Python
- shared — TypeScript and Python domain types
- docs — maintained architecture, API, security, and development documentation
- docker-compose.dev.yml — MongoDB and Qdrant for local development

The API is versioned under /api/v1. Authenticated AI operations use the
signed-in user's OpenAI key through request-scoped client handling.

## Working rules

- Never add secrets, real credentials, private documents, personal data, or
  machine-specific paths to tracked files.
- Never add an application-owner OpenAI key or an anonymous AI-spend path.
- Keep user-document ownership checks intact across storage, analysis, chat,
  reports, and vector data.
- Prefer modular services and configurable values over hard-coded behavior.
- Use in-app modals, not browser-native alert or confirm dialogs.
- Check whether local services are already running before starting them.
- Run application servers in development mode during local development.
- Update relevant documentation whenever behavior or setup changes.
- Run migrations and smoke checks when a change introduces or affects them.
- Do not reset passwords, create branches, commit, push, deploy, or change
  remote resources unless the user explicitly asks.

## Local commands

~~~bash
npm run dev
npm run test
npm run typecheck
npm run lint
npm run build
npm run check
~~~

See docs/DEVELOPMENT.md for setup and service-level commands.

## Git workflow

Use short-lived feature branches and pull requests into main. There is no
permanent dev branch and no deployment workflow at this stage.
