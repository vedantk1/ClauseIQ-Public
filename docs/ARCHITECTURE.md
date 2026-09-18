# Architecture

ClauseIQ is a single-person local application. It has one server-selected
workspace namespace (`local`), not a default user, membership model or account.

| Component | Responsibility |
| --- | --- |
| Next.js | Upload, review, document library, chat, analytics and Settings |
| FastAPI | Local request boundary, document processing and AI orchestration |
| MongoDB / GridFS | Documents, PDFs, interactions, chats, settings and encrypted credentials |
| Qdrant | Per-document vector data for retrieval-augmented chat |

Shared Python and TypeScript domain types live in shared/clauseiq_types.

## Document flow

1. The local browser submits a PDF with the local-request marker.
2. The backend validates the file and supplies its own workspace identifier.
3. Extraction and AI analysis use a request-scoped OpenAI client created with
   the locally configured key.
4. Documents, PDFs and embeddings retain document and workspace identifiers.
5. The frontend renders the PDF alongside the structured review.
6. Chat checks the requested document, retrieves only its workspace/document
   vectors and persists messages with that document.

Reading saved analysis does not make a new AI request. Deleting a document
must remove its files, vector chunks, interactions and embedded chat; failures
must be reported rather than claiming complete deletion.

## Settings and credentials

The workspace service separates key handling from document operations.
Settings expose key presence only, the existing main/gate model catalog,
optional retention and presentation preferences. No account, SMTP, role,
database-browser or raw-log administration routes remain.

A random encryption key is generated automatically in the backend's private
runtime directory on the first key save. Only encrypted API-key material is
stored in MongoDB. The decrypting key is owner-readable, excluded from Git and
Docker build contexts, and persisted in a separate volume in full Compose.
Missing state does not silently generate a replacement during decryption.

## Local request boundary

The application ports bind to loopback by default. The API validates loopback
Host names, exact configured browser Origins and the X-ClauseIQ-Local header.
The header is a browser preflight marker, not a password. See SECURITY.md for
the trusted-OS-user boundary and limitations.

## Migration

Startup preflights MongoDB, GridFS and Qdrant before applying an additive,
restartable migration. Zero or one legacy owner is supported automatically.
Multiple owners, ambiguous ownership or conflicting workspace data stop startup
for an explicit data-selection decision. Existing account rows, ciphertext,
legacy owner fields, document IDs and relationships are not deleted.

Inherited retention is disabled during the first migration; newly opted-in
retention is preserved on later restarts. A decryptable legacy API key is copied
into the new credential store. If its old encryption secret is unavailable, the
library remains usable and Settings requests key re-entry.

## Scope

Next.js, FastAPI, MongoDB and Qdrant are retained. This version does not introduce
a job queue, new AI models, offline inference, team support or agent orchestration.
