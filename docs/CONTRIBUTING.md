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

For routine changes, run focused tests and affected type/lint checks:

~~~bash
npm run test:backend
npm run test:frontend
npm run typecheck
npm run lint
~~~

Narrow the test selection further when appropriate. Batch broader manual UI
testing and production builds after several related changes or at a substantial
milestone. Run the complete checkpoint when due:

~~~bash
npm run check
~~~

Build sooner for build-specific risks; still run targeted safety checks when
migration, persistence, access or credential handling changes. See DEVELOPMENT.md
for the cadence and synthetic PDF fixtures. Report deferred checks clearly.

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
