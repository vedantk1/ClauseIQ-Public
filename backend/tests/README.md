# Backend tests

The default Pytest suite covers configuration, domain models, local access,
credential privacy, migration, storage scoping and mocked review workflows.
It is deterministic and must not call live AI services.

Model tests also cover the canonical catalog, token-budget overrides, selected
models across all generation operations, safe output/error handling, generation
attribution and the installed SDK's request serialization through a mock HTTP
transport. They do not validate live account access, pricing invoices or AI quality.

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

tests/test_pdf_fixtures.py checks the public synthetic PDFs in
../tests/fixtures/pdfs (relative to the backend directory): deterministic bytes,
metadata, page/text expectations and the real local extractor, including image-only
rejection. These are ingestion fixtures, not evidence of legal or AI-review quality.
See the fixture README for regeneration. Use focused tests during routine work;
broader manual UI runs and full builds are checkpoint work (see the repository's
docs/DEVELOPMENT.md).

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

## Source-foundation checks

test_source_extraction.py exercises page inventories, exact line spans, stable
versioned identities and partial/unavailable/malformed cases using the existing
synthetic corpus. test_source_import.py checks local-only import, original-first
persistence, extraction retry, source identity and stale-result fencing.
test_source_storage.py covers actual adapter contracts and uncertain GridFS pointer
writes. test_source_analysis.py checks source-before-generation, partial-input
refusal and preservation after provider/save failures. test_source_error_responses.py
checks that the application's error standardization retains recovery references.

A smaller real MongoDB/GridFS check is available without Qdrant:

~~~bash
cd backend
venv/bin/python tests/manual_source_smoke.py --run-isolated-live
~~~

It verifies persistence through new connections, exact PDF bytes/page data,
same-record retries, concurrent/stale claims and unrelated fixture preservation.
It creates only its own verified-absent fixture database and removes that database
in finally. Application library/settings/credentials are not read; no provider or
vector client may be requested. Inspect the cleanup report for leftovers.
