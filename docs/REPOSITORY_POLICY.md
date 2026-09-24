# Repository policy

This repository is a clean public-facing snapshot. The deprecated private
repository is historical reference only; its Git history must never be merged,
grafted, or pushed into this repository.

## Tracked

- Application and test source
- Dependency manifests and lockfiles
- Reviewed environment examples containing placeholders only
- Dockerfiles, local Compose definitions, and the root .dockerignore
- Stable architecture, API, security, development, and contributor documents
- Stable AGENTS.md guidance that applies to the project
- Reviewed synthetic PDF test fixtures under tests/fixtures/pdfs, together with
  their readable source, manifest and deterministic generator
- Reviewed product screenshots under docs/images that show only synthetic
  fixture content and explicitly authored demonstration state

## Local only

- Every real .env file and credential
- Private keys, certificates, service-account files, and database exports
- Uploaded contracts, generated reports, logs, backups, and runtime data
- Dependency folders, virtual environments, caches, and build output
- Browser automation captures, screenshots, and test artifacts, except the narrow
  reviewed product-image allowance below
- Agent session state, scratch work, handovers, and temporary checklists

Use .local-only for transient project notes. Do not create broad ignore rules
for every file containing the word agent: stable repository guidance may be
tracked, but session-specific material may not.

Synthetic fixtures are a narrow exception to the exclusion of document artifacts:
invent all content, label it synthetic, keep personal/credential metadata out,
and review rendered pages and extraction expectations. Do not commit uploaded
agreements or generated review reports. Regeneration must not require live AI,
credentials or private source documents.

Product screenshots are a separate, narrow publishing exception, not permission to
track test-output folders. Review each selected image under docs/images before
staging it. It must show only repository synthetic fixtures and authored demo
state, with no real saved questions, account/key state, personal paths, browser
chrome, identifiers from the user's installation or private application data.
Keep its origin and scope in docs/images/README.md. Do not retouch a screenshot to
invent application behavior or present an authored example as AI-generated output.
All other captures remain ignored local artifacts.

## Before publishing changes

1. Inspect every staged path.
2. Scan staged content and reachable Git history for secrets.
3. Review binary files and generated artifacts explicitly.
4. Confirm environment examples contain placeholders only.
5. Confirm no unapproved deployment workflow or cloud identifier is present.
6. Confirm the intended public Git author identity.
7. Confirm LICENSE and package license metadata consistently identify MIT.

## Licensing

ClauseIQ is licensed under the root MIT LICENSE. Keep its copyright and permission
notice when redistributing the project. Third-party dependencies retain their own
licenses; the project license does not replace those terms.

PDF rendering uses `pdfjs-dist` under Apache-2.0; the previous commercial viewer
packages have been removed. Its worker and support assets are copied from the
locked installation into ignored frontend/public/pdfjs for local serving and
builds, with the upstream LICENSE and resource notices retained. Do not commit
those generated files or dependency trees. Bundled distributions must preserve
applicable dependency licenses and notices.

## Git workflow

- main is the only permanent branch.
- Use short-lived feature branches and pull requests.
- Deterministic CI and a history secret scan run on pull requests and main pushes;
  making checks required is a separate repository-settings decision.
- Add deployment automation only after a hosting design is approved.
- Do not commit, push, create branches, or change remotes without explicit
  authorization.

If a secret is committed, revoke or rotate it first, stop publication, and
remove it from every reachable ref before continuing.
