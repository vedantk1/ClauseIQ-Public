# ClauseIQ shared types

This local package holds domain types used by the frontend and backend.

- clauseiq_types/common.py — Python Pydantic models and enums
- clauseiq_types/common.ts — manually maintained TypeScript equivalents
- index.ts — TypeScript export surface

Build the TypeScript package with:

~~~bash
npm --prefix shared ci
npm --prefix shared run build
~~~

The generated dist directory is intentionally ignored. Python installs the
package in editable mode through backend/requirements.txt.

The Python and TypeScript definitions are currently maintained together by
review. Do not claim generated synchronization unless a tested generator and
drift check are added.
