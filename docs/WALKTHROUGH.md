# Try the review workspace

This tour uses the repository's authored synthetic example. It needs a running
local application but no API key, model access or provider calls. It demonstrates
the workflow, not the quality of an AI-generated review.

## Agreement → finding → evidence → saved question

1. Open **Library → Import agreement** and choose
   [managed-services-25p.pdf](../tests/fixtures/pdfs/managed-services-25p.pdf).
   Confirm the import. The application stores the original and extracts its text
   locally; importing does not start an AI review.
2. In setup, expand **Try the synthetic example** and choose
   **Load synthetic customer-perspective example**. Only the unchanged sample PDF
   is eligible. The fixed example is labelled and does not use your editable
   review instructions.
3. Read **Overview**, then open **Findings**. Select
   **Plan for the conditional Archive exit extension**. The finding separates
   what the agreement says, why it matters, what remains unknown and a possible
   next step.
4. Preview its references in the evidence pane, then use **View page 22** or
   **View page 25** to inspect the original. Use the return action to go back to
   the finding. The quote is preserved verbatim; surrounding extraction is a
   separate aid, not a reconstructed clause.
5. Choose **Keep question**, enter a question and **Save question**. For example:
   “Who will request the Archive extension, and which assistance charges need
   approval?” Mark the finding **Revisit** if useful.
6. Open **My review**. Confirm your saved wording and marker, then **Copy brief**
   or **Download Markdown**. Filters change the visible list, not the selected
   run's complete confirmed export.
7. Return to Library and use **Continue reviewing**. Saved personal work and the
   document's browser-local reading position can be resumed without another
   review request.

Importing this file creates a local library record; saving the question changes
that record. For a demonstration, use synthetic wording only and keep any existing
records intact. Do not clear an existing installation to prepare a clean screen.

## Explore Ask without sending

Within a finding, switch from **Review** to **Ask**. **Use review question** copies
your current question wording into a separate Ask draft; it does not send it.
Replacing an existing different draft requires confirmation. Return to Review to
see that the saved question and Ask draft remain separate.

The authored example does not include provider answers. To demonstrate a real
answer, deliberately enter your own key in Settings and use the explicit paid
send control. Label the result as AI output and inspect its evidence; do not
present the authored findings as proof of generation quality.

## Optional live review

Settings offers the application model catalog and reasoning effort. Saving a key
or choosing a model makes no provider call and does not validate account access.
To generate a fresh review, set your instructions and explicitly choose
**Start review**. Sending a question or starting a review transmits source content
to OpenAI and can incur API charges. Older runs keep their original context.

For repeatable quality assessment rather than a product tour, use the separately
approved, cost-capped process in [Development](DEVELOPMENT.md#model-defaults-and-bounded-requests).
Deterministic tests and authored examples do not establish legal correctness or
review completeness.
