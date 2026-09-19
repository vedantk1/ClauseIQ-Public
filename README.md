# ClauseIQ

ClauseIQ is a personal contract-review application that runs on your computer.
Import a PDF, understand it through an evidence-linked review, inspect the source,
keep questions and personal markers, and ask finding-grounded follow-ups.

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

Appearance offers Black and Graphite dark themes through the navigation theme
switch. The choice is saved in this browser; light mode is no longer offered.

The app opens into the Library at /documents, which combines an agreement list, selected-agreement details
and Continue reviewing for the latest eligible saved review activity. Review
status is separate from source extraction and earlier analysis; examples remain
labelled. Resume restores the latest run's saved view without starting AI. Search,
sorting, contract-type filters and confirmed deletion remain available. About is
accessible through More; saved earlier analyses retain document-specific review
links. Library, Import, Settings and the workspace share the same navigation.
The retired /analytics and /legacy-analysis URLs redirect to Library and Import.
Settings groups personal AI access, model choices, document retention and notifications.

The Library offers Import agreement without AI: choose or drop one PDF, confirm
the import, then open review setup. Setup shows source readiness and missing-text
limitations beside a short, optional review brief. Read the original or save the
brief and return later without a key. Starting an AI review is a separate explicit
action using the model and key configured in Settings. Existing runs keep their
overview and original review context. Their Overview leads with the saved agreement
summary and source coverage; editing the brief and starting another run are secondary,
explicit actions. Recovery controls and consequential warnings remain available.
New work uses Import and the review workspace; the earlier analysis uploader has
been retired. Existing earlier results, notes, chat and reports remain accessible.
Extraction or AI failures do not discard an already stored PDF.
Imported/not-ready records are labelled separately from completed analysis.

The review workspace connects Overview, Findings, Document and My review to
local persistence. Save a brief, then explicitly Start review using the model
selected in Settings. One bounded generation request produces an evidence-linked
overview and findings; changing the brief never reruns AI or changes older runs.
Source quotes are checked against stored extraction, not proof of legal accuracy.
Findings show all navigation items and put the selected quote first. Saved excerpts
are labelled as potentially partial; separately disclosed surrounding source text
helps inspect context without changing the quotation or claiming a complete clause.
Incomplete extraction, invalid output and interrupted requests remain visible.
Draft recovery, explicit saved questions, personal markers and resume position
remain separate. My review collects only confirmed questions from the selected run,
with finding context, source links and reversible personal markers; drafts and AI
answers are not promoted into it. Copy brief and Download Markdown take confirmed
questions and markers out of My review, with finding context, source-page references
and the selected run's limitations. Export is local and makes no AI call.
Finding-scoped Ask uses the selected review's original perspective
and extracted source, with its own recoverable draft and saved answer history.
Sending is an explicit paid action; opening answers or saving drafts is not.
Answers include source links, model attribution and any input limitations.
Quote matching establishes location, not correctness. Importing, reading and
saving personal work make no provider calls. Source and filename reads recover
independently: explicit read retries preserve drafts and do not re-extract or run AI.
An optional authored synthetic
example remains available only for the unchanged
tests/fixtures/pdfs/managed-services-25p.pdf and is labelled separately from AI output.
See docs/API_REFERENCE.md for source and review-workspace APIs.

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

Experimental project under active development. There is no supported hosted production
environment, deployment workflow or CI pipeline. Settings offers GPT-5.6 Luna,
Terra and Sol, with GPT-5 retained for legacy selections. Terra is the
default for review and query preparation. Old Mini/Nano selections resolve to
Terra; other explicit choices and historical run attribution are preserved.
Choose models deliberately; there is no automatic provider fallback.

ClauseIQ is licensed under the [MIT License](LICENSE). Third-party dependencies
remain subject to their own licenses.

PDF rendering uses Mozilla PDF.js (Apache-2.0). The worker and supporting assets
are generated from the locked dependency before development/build and served
locally; opening a saved PDF does not contact a viewer CDN.
