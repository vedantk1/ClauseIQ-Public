# Security

ClauseIQ processes confidential documents and user-supplied AI credentials.
Security and privacy changes are release requirements, not optional polish.

## Current model

- Document and AI routes require authentication and enforce per-user document
  ownership.
- OpenAI access is BYOK; there is no anonymous or application-funded AI path.
- User API keys are encrypted before database persistence.
- JWT signing and API-key encryption use separate configurable secrets.
- Administrative endpoints require an account listed in ADMIN_EMAILS.
- Email verification can be disabled only in development/testing. Staging and
  production always require it.
- Uploaded documents, secrets, logs, local databases, and tool artifacts are
  excluded from Git and Docker build contexts.
- API documentation is disabled when the backend runs in production mode.

## Operator requirements

- Generate unique high-entropy values for JWT_SECRET_KEY and
  API_KEY_ENCRYPTION_SECRET.
- Never reuse development values in staging or production.
- Configure working SMTP before enabling email verification in development or
  running in staging/production.
- Restrict MongoDB and Qdrant to trusted networks outside local development.
- Configure explicit CORS origins and TLS before any hosted use.
- Treat logs, backups, uploaded documents, and vector data as sensitive.
- Rotate a credential immediately if it may have been exposed; deleting a file
  or commit is not sufficient.

## Known limitations

- The repository does not yet define CI security gates.
- Development Compose publishes MongoDB and Qdrant only on 127.0.0.1; do not
  broaden those bindings without adding authentication and a network boundary.
- Browser token storage and centralized session revocation require further
  hardening before a public production deployment.
- The current @react-pdf-viewer release constrains PDF.js to major versions 2 or
  3. ClauseIQ sets `isEvalSupported: false`, the published mitigation for
  GHSA-wgrm-67xf-hhpq, but the advisory remains until the viewer can be replaced
  or upgraded. Resolve this before hosted production use.
- No threat model or security review currently covers future agentic tools.

Agentic features must be designed with explicit tool allowlists, durable
per-user quotas, token and output limits, audit trails, human confirmation for
side effects, and infrastructure-level spend caps before public access.

## Reporting

Do not disclose a suspected vulnerability in a public issue. Once the public
repository exists, enable GitHub private vulnerability reporting and use that
channel. Until then, report concerns privately to the repository owner.
