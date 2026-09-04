# API reference

The backend exposes versioned application routes under /api/v1. When running
locally, use http://localhost:8000/docs for the generated, current OpenAPI
schema.

## Route groups

| Prefix | Purpose | Access |
| --- | --- | --- |
| /api/v1/auth | Registration, sessions, profile, preferences, and BYOK settings | Mixed public and authenticated |
| /api/v1/documents | Upload, list, fetch, view, delete, and PDF access | Authenticated owner |
| /api/v1/analysis | Analysis results, interactions, notes, and clause rewrites | Authenticated owner |
| /api/v1/chat | Document chat sessions, messages, history, and status | Authenticated owner |
| /api/v1/analytics | User dashboard data | Authenticated |
| /api/v1/reports | Generated document reports | Authenticated owner |
| /api/v1/health | Readiness, liveness, and diagnostics | Varies by endpoint |
| /api/v1/app-config | Non-sensitive presentation settings used before sign-in | Public |
| /api/v1/admin | User, document, model, retention, and UI administration | Administrator |
| /api/v1/ai-debug | AI and RAG diagnostics | Administrator |

There is no unauthenticated sample-document API and no endpoint backed by an
application-owner OpenAI key.

## Authentication

Protected routes expect:

~~~http
Authorization: Bearer <access-token>
~~~

Access and refresh tokens have distinct token types. Registration and login
responses include the public user profile but never password hashes or stored
API-key material. PDF content also uses the Authorization header; bearer tokens
must not be placed in query strings.

Email verification is disabled by default only in development/testing, where a
new account is immediately eligible for BYOK. Staging and production always
require verification; registration fails clearly if the verification email
cannot be delivered.

## BYOK lifecycle

Authenticated users manage their key through:

- PUT /api/v1/auth/api-key
- GET /api/v1/auth/api-key/status
- DELETE /api/v1/auth/api-key

The status endpoint reports presence only. It must never return the stored key.
When email verification is required, PUT rejects an unverified account.

## Responses

Application endpoints generally use a standard envelope:

~~~json
{
  "success": true,
  "data": {},
  "error": null,
  "metadata": {}
}
~~~

Binary PDF responses and framework-generated documentation are exceptions.
Treat the generated OpenAPI schema and router code as authoritative if this
summary falls behind during active development.
