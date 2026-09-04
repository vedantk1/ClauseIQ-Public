# ClauseIQ frontend

The frontend is a Next.js application for authentication, document management,
contract review, document-grounded chat, analytics, and administration.

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

## Checks

~~~bash
npm --prefix frontend exec -- tsc --noEmit
npm --prefix frontend run lint
npm --prefix frontend run build
~~~

There is no standalone frontend test suite yet. Browser state, screenshots,
Playwright captures, build output, and local environment files are not tracked.
