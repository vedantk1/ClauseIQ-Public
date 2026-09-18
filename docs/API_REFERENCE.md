# API reference

Application routes use /api/v1. The generated schema at
http://localhost:8000/docs is authoritative while the API evolves.

## Local access

Workspace calls require:

~~~http
X-ClauseIQ-Local: 1
~~~

There are no bearer tokens or account sessions. This marker triggers browser
CORS preflight; it is not a secret. Requests also require a loopback Host and,
when present, an allowed local Origin. In Swagger, select Authorize and enter
1 for the local marker. CLI clients may omit Origin but must include the marker.

| Prefix | Purpose |
| --- | --- |
| /api/v1/workspace | Key status, key save/removal and ordinary Settings |
| /api/v1/documents | List, fetch, PDF access and delete |
| /api/v1/analysis | Upload/analysis, stored clauses, notes, flags and rewrites |
| /api/v1/chat | Document sessions, messages, history and status |
| /api/v1/analytics | Workspace dashboard |
| /api/v1/reports | Document PDF reports |
| /api/v1/health | Local health checks |
| /api/v1/app-config | Non-sensitive presentation settings |

Account, admin and AI-debug routes are removed. The server supplies workspace_id;
request data cannot change the workspace. Document IDs remain required for
document-specific operations.

## Workspace settings

GET /api/v1/workspace returns:

- has_api_key and api_key_needs_reentry (booleans, never credential material)
- model_id and query_gate_model_id
- available_models (id, name, description)
- retention_days (0 means keep until manually deleted)
- toast_notifications_enabled

PUT /api/v1/workspace/settings accepts any subset of model_id,
query_gate_model_id, retention_days and toast_notifications_enabled. Models
must be in the advertised catalog. Retention is 0..36500 days; enabling it can
delete already-old documents on the next cleanup run.

PUT /api/v1/workspace/api-key accepts a JSON api_key field.
DELETE /api/v1/workspace/api-key removes the active credential.
Both return has_api_key only. Saving checks format and local persistence, not
OpenAI account access or balance; it makes no paid provider call.

## AI and saved data

Analysis, new chat answers and new rewrites need the configured key.
Reading saved documents, PDFs, clauses, chats and cached rewrites, managing
notes/flags, generating reports and deletion do not require an AI call.
File type/size and request-rate limits still apply; there is no library count cap.

## Responses

Application endpoints generally use:

~~~json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": {}
}
~~~

PDF responses and framework documentation are exceptions. Errors must not
include key material, request bodies, document content or raw provider errors.
