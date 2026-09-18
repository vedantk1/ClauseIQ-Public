# Backend tests

The default Pytest suite covers configuration, domain models, local access,
credential privacy, migration, storage scoping and mocked review workflows.
It is deterministic and must not call live AI services.

Run it from the repository root:

~~~bash
npm run test:backend
~~~

Or run it directly:

~~~bash
cd backend
venv/bin/python -m pytest tests -v
~~~

Add focused tests when changing local request boundaries, workspace and document
scoping, BYOK handling, deletion, or API response contracts. Do not hard-code a test
count in this file because it becomes stale as the suite evolves.

## Optional live storage smoke

With the development MongoDB and Qdrant services already running, this manual
check creates uniquely named, isolated fixture stores, exercises the real
migration and deletion services, and removes only those fixture stores afterward:

~~~bash
cd backend
venv/bin/python tests/manual_workspace_smoke.py --run-isolated-live
~~~

It does not modify the application's library, settings, credentials, or .env
files, and makes no OpenAI calls. It is excluded from normal Pytest discovery.
Review the final cleanup report; a failed cleanup names any remaining fixture.
