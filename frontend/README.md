# ClauseIQ frontend

The frontend is a Next.js application for a single-person local workspace:
document management, contract review, document-grounded chat, and analytics.
There is no registration, login, or administrator setup. OpenAI credentials,
model choices, optional document retention, and notifications live in Settings.

## Setup

From the repository root:

~~~bash
cp frontend/.env.example frontend/.env.local
npm --prefix frontend ci
npm --prefix shared ci
npm --prefix shared run build
npm --prefix frontend run dev
~~~

The application runs at http://localhost:3000 and expects the backend at the
NEXT_PUBLIC_API_URL configured in frontend/.env.local.

The development server binds to the loopback interface. Requests to the local
backend include the `X-ClauseIQ-Local: 1` header and must pass its origin and host
checks. Do not expose this account-free workspace publicly. PDF downloads and
the viewer use the same request boundary as other document operations.

## Checks

~~~bash
npm --prefix frontend exec -- tsc --noEmit
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
~~~

The small deterministic test suite checks the local API request boundary,
file-upload handling, and uncapped library responses without credentials or
provider calls. Browser state,
screenshots, Playwright captures, build output, and local environment files are
not tracked.
