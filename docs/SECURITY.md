# Security

ClauseIQ handles confidential documents and personal AI credentials. It supports
one person on their own computer, not a shared or hosted installation.

## Trust boundary

- There are no accounts or passwords. Access to the local OS session is access
  to this workspace.
- Application and database ports bind to loopback in the provided workflows.
  Do not expose them through LAN bindings, reverse proxies or public tunnels.
- The API accepts only loopback Host names and exact permitted browser Origins.
  Every workspace request requires X-ClauseIQ-Local: 1, forcing cross-origin
  browser requests through an allowlisted CORS preflight.
- This header is not a secret and does not authenticate a native process.
  Other programs running on the computer are trusted. These safeguards do not
  protect against malware, a compromised local frontend, browser extensions,
  or another person with access to the same OS session.
- CORS configuration permits only exact loopback origins. Staging and production
  backend modes are rejected; they are not an authentication bypass.
- Document, file, note, chat, report and vector operations preserve document and
  workspace scoping. A caller cannot select a different workspace.

Minimal liveness and generated API documentation do not expose workspace content.
Application API responses are not browser-cacheable. Admin database/log and AI
debug routes have been removed.

## Credentials

Enter an OpenAI key in Settings. The browser sends it only to the local backend
for storage; it is not retained in browser storage or returned by the API.
AI calls use request-scoped clients, which are closed after each request.
There is no fallback to an application-owner OPENAI_API_KEY environment value.

API keys are encrypted in MongoDB using a randomly generated local Fernet key.
The key file defaults to backend/.local-only/workspace/credential.key and uses
owner-only file permissions. WORKSPACE_STATE_DIR can change its directory;
relative paths resolve from the backend directory. Full Compose persists it in
the backend_credentials volume.

Protect both the database and credential directory. Encryption protects a
database-only copy, not someone who can read both stores. Back up them together;
if the key file is lost, restore it or explicitly re-enter the OpenAI key.
Deleting the key in Settings disables future requests but does not revoke it
at OpenAI or cancel a request already in progress.

Legacy encrypted keys are imported only for an unambiguous single-owner
installation. Old account rows and ciphertext remain local for recovery and
are not reachable through account APIs. Removing a workspace key never
automatically reimports it on restart. See DEVELOPMENT.md for migration.

## Data and retention

Documents do not expire by default. Automatic deletion is an explicit Settings
choice and can permanently remove documents already older than the selected
period on the next cleanup run. Treat MongoDB, GridFS, vectors, logs and backups
as sensitive. AI requests send relevant document content to OpenAI; local
storage does not imply offline processing.

Never commit credentials, real contracts, exports, local state or logs. The only
tracked PDF exception is the reviewed synthetic test corpus described in
REPOSITORY_POLICY.md; it contains no private source documents. Rotate a
credential if exposed; removing a file or Git commit is not enough.

## Known limitations

- The repository has no CI security gates or supported production environment.
- The current React PDF Viewer dependency still has the PDF.js advisory
  GHSA-wgrm-67xf-hhpq. The application keeps isEvalSupported: false; replacing
  or upgrading the viewer is still needed to remove the advisory. Upstream React
  PDF Viewer is archived; its 3.12 peer range does not support forcing a current
  PDF.js version under it. The new page-navigation adapter does not remediate the
  dependency audit. See the [Mozilla advisory](https://github.com/mozilla/pdf.js/security/advisories/GHSA-wgrm-67xf-hhpq)
  and [viewer package](https://github.com/react-pdf-viewer/react-pdf-viewer/blob/v3.12.0/packages/core/package.json).
- Review workspace fixtures are authored synthetic examples, restricted to the
  exact reviewed PDF hash. They are not generated results or evidence of model
  quality. Source content and editable personal work are rendered as text, never
  trusted HTML. All new persistence routes retain the local boundary and scoped
  conditional writes; stale requests cannot silently overwrite newer work.
- Multi-store migration/deletion is restartable but not a distributed transaction.
  Back up legacy data before migration and investigate reported cleanup errors.
- Future agent tools require their own threat model, allowlists, resource limits
  and human confirmation for external side effects.

## Reporting

Do not disclose vulnerabilities in public issues. Until a public repository
with private vulnerability reporting is established, contact the repository
owner privately.
