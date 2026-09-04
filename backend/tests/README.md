# Backend tests

The default Pytest suite covers configuration, domain models, and utilities.
It is deterministic and must not call live AI services.

Run it from the repository root:

~~~bash
npm run test
~~~

Or run it directly:

~~~bash
cd backend
venv/bin/python -m pytest tests -v
~~~

Add focused tests when changing authentication, ownership boundaries, BYOK
handling, document cleanup, or API response contracts. Do not hard-code a test
count in this file because it becomes stale as the suite evolves.
