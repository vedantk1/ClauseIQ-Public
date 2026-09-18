# Contributing

## Workflow

1. Branch from main using a short-lived feature branch.
2. Keep the change focused and update affected documentation.
3. Run the relevant local checks.
4. Open a pull request with behavior, risk, and verification notes.
5. Merge only after review and passing required checks.

There is no permanent dev branch. Direct pushes to main should be avoided once
branch protection and continuous integration are configured.

## Validation

Run the full deterministic check:

~~~bash
npm run check
~~~

Or run focused checks:

~~~bash
npm run test
npm run typecheck
npm run lint
npm run build
~~~

Tests that call live AI services must not run in the default suite. Use mocks
for deterministic behavior; keep paid, live-model evaluations manual,
explicit, and cost-capped.

## Code expectations

- Keep business logic in services rather than route handlers.
- Preserve local-access and document/workspace data boundaries.
- Use typed interfaces at frontend/backend boundaries.
- Prefer small modules and configurable policy values.
- Do not introduce browser-native alert or confirm dialogs.
- Never include credentials, private documents, local tool state, or personal
  metadata in a contribution.

## Documentation

Update API_REFERENCE.md for route changes, ARCHITECTURE.md for structural
changes, SECURITY.md for trust-boundary changes, and DEVELOPMENT.md for command
or setup changes.
