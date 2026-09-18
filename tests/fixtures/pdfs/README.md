# Synthetic PDF fixtures

These four deliberately small, invented documents are safe public test inputs,
not real contracts, legal templates or legal advice. All names, dates, charges
and terms are fictional. The PDFs contain no author name, personal information,
credentials or machine-specific paths.

| PDF | Pages | Purpose |
| --- | --- | --- |
| `mutual-nda.pdf` | 1 | Text extraction, reciprocal obligations, exceptions and survival period |
| `service-terms-conflict.pdf` | 2 | Page boundaries, a table, cross-references and conflicting payment deadlines |
| `embedded-instructions.pdf` | 1 | Untrusted instruction-like source content for future AI evaluations |
| `image-only-scan.pdf` | 1 | Raster-only input with no text layer; currently rejected by extraction |

`manifest.json` is the human-readable source and expectation manifest.
`generate.py` creates the PDFs deterministically using ReportLab and Pillow from
the backend environment. It uses bundled fonts, fixed PDF metadata and explicit
page boundaries. The checked-in PDFs are an intentional test-fixture exception
to the policy against committing generated runtime documents. Generated page
previews do not belong in this folder.

From the repository root:

```bash
# Read-only verification against the current dependency environment.
backend/venv/bin/python tests/fixtures/pdfs/generate.py --check

# Regenerate only these four known fixture files after an intentional edit.
backend/venv/bin/python tests/fixtures/pdfs/generate.py

# Focused offline extraction and fixture tests.
cd backend && venv/bin/python -m pytest tests/test_pdf_fixtures.py
```

Exact-byte checks were established with ReportLab 5.0.1 and Pillow 12.3.0.
A renderer/dependency change may require deliberate regeneration and review;
do not silently replace fixtures to make a failing check pass. Inspect the
rendered pages when changing fixture content or generation. Other ordinary
application changes do not require regenerating or visually reviewing them.

The automated tests cover reproducibility, page counts, text anchors, metadata
and the actual text-extraction service, including its current image-only error.
They do not call AI, a database or the network. They do not assert a legally
correct risk score, test OCR, or demonstrate prompt-injection resistance. The
embedded instruction passage must be treated as document data, never as a
directive to an assistant, tool or reviewer. Contract types here are coverage
examples, not a decision about ClauseIQ's eventual target audience.
