# Architecture

ClauseIQ is a local-first full-stack application with four runtime components:

| Component | Responsibility |
| --- | --- |
| Next.js frontend | Authentication UI, upload, review, chat, analytics, and administration |
| FastAPI backend | Authorization, document processing, AI orchestration, and API responses |
| MongoDB | Users, encrypted BYOK credentials, documents, interactions, and configuration |
| Qdrant | Per-document vector data used by retrieval-augmented chat |

Shared domain types live in shared/clauseiq_types for Python and TypeScript.

## Request flow

### Document analysis

1. An authenticated user submits a PDF.
2. The backend validates the file and ownership context.
3. Text is extracted and sent through the analysis pipeline using that user's
   request-scoped OpenAI client.
4. Structured document and clause data is stored in MongoDB.
5. Embeddings are stored in Qdrant under document and user ownership context.
6. The frontend renders the source PDF beside the structured review.

### Document chat

1. The backend verifies the user owns the requested document.
2. The query is embedded using the user's request-scoped OpenAI client.
3. Relevant chunks are retrieved from Qdrant.
4. The model receives the query, retrieved context, and bounded conversation
   history.
5. Messages are returned through the API and persisted for that user.

## Key boundaries

- All document, PDF, interaction, report, and chat operations must preserve
  authenticated ownership checks.
- OpenAI access is BYOK. User keys are encrypted before persistence and are
  installed only in request-local client context for AI operations.
- API-key encryption should use API_KEY_ENCRYPTION_SECRET, distinct from
  JWT_SECRET_KEY.
- Administrative access is controlled separately through ADMIN_EMAILS.
- Public runtime configuration may expose presentation settings only, never
  secrets or user-specific data.
- Uploaded documents, database data, vector data, and logs are runtime data and
  are excluded from version control and Docker build contexts.

## API organization

The backend mounts versioned routes below /api/v1. Routers call services, which
coordinate database adapters, file storage, AI clients, and vector search.
Middleware provides response standardization, request logging, rate limiting,
monitoring, CORS, and security checks.

## Current scope

This clean snapshot intentionally has no anonymous sample document, no
application-funded AI key, no cloud deployment definition, and no continuous
delivery workflow. The architecture will continue to evolve before any hosted
or agentic capabilities are introduced.
