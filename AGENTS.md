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

The API is versioned under /api/v1. ClauseIQ is one local workspace with no
accounts or admin roles. AI operations use the person's OpenAI key from
Settings through request-scoped client handling.

## Working rules

- Never add secrets, real credentials, private documents, personal data, or
  machine-specific paths to tracked files.
- Never add an application-owner OpenAI key or a publicly accessible AI-spend path.
- Preserve loopback bindings, browser Origin/Host checks and the local-request
  marker. No hosted or shared installation is supported.
- Keep document/workspace scoping intact across storage, analysis, chat,
  reports and vectors. Do not reintroduce synthetic users or admin assignment.
- Preserve existing local data during migrations; never silently merge legacy
  accounts or discard credential state. Retention is opt-in, not a default.
- Prefer modular services and configurable values over hard-coded behavior.
- Use in-app modals, not browser-native alert or confirm dialogs.
- Check whether local services are already running before starting them.
- Run application servers in development mode during local development.
- Update relevant documentation whenever behavior or setup changes.
- Use focused automated tests for routine changes, plus affected type/lint checks.
  Batch broader manual UI testing and full production builds at meaningful
  milestones or after several related changes; do not repeat them for every edit.
  Build earlier only when bundling, dependencies, shared output or another
  build-specific risk requires it. Keep development servers hot-reloading.
- Run targeted migration/storage smoke checks when those paths change. These
  safety checks are not deferred just because general UI testing is batched.
- Use the reviewed synthetic PDFs in tests/fixtures/pdfs for repeatable checks.
  Never substitute private contracts or run paid AI evaluations without approval.
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
