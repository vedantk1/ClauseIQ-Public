# Product images

`review-workspace.png` shows the actual ClauseIQ Findings workspace in the Black
theme at a 1440×1000 browser viewport. It is a browser capture, not a generated
mockup or a retouched representation of application behavior.

The capture uses the isolated Playwright showcase case in
`frontend/e2e/workspace.spec.mjs`, with test-owned API responses derived from
`tests/fixtures/pdfs/managed-services-25p.pdf` and the authored review fixture under
`backend/fixtures/reviews`. The visible finding is **Clarify how service credits
are earned**. Synthetic/example labels remain visible. Test source spans are
derived from the exact PDF through PDF.js; the capture does not run the backend
extractor.

No real installation, account, credential, private agreement or saved personal
work is used. Browser chrome is excluded. The mocked API state demonstrates the
frontend's presentation; the image does not demonstrate database persistence,
live AI generation, citation support for every claim or legal accuracy.

## Regeneration

With the dependencies and Playwright Chromium installed, run from the repository
root:

~~~bash
npm --prefix frontend run test:e2e:screenshots
~~~

The Black capture is written to
`output/playwright/showcase/review-workspace-black.png`; the Graphite capture stays
beside it as a local artifact. Review the selected Black image before copying it
to `docs/images/review-workspace.png`. Do not copy the whole generated output
directory. See [Development](../DEVELOPMENT.md#browser-smoke) for setup and
[repository policy](../REPOSITORY_POLICY.md) for the publishing boundary.
