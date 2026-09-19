import type { DocumentSourceResponse, ReviewPersonalState, ReviewRun } from "@clauseiq/shared-types";
import { evidenceMatches, runStatus } from "./workspaceState";

export interface ReviewBriefExport {
  markdown: string;
  filename: string;
  itemCount: number;
}

/** Literal blocks preserve saved wording, including newlines, without executable markup. */
function literal(value: string): string {
  const longestFence = Math.max(0, ...(value.match(/`+/g) || []).map(match => match.length));
  const fence = "`".repeat(Math.max(3, longestFence + 1));
  return `${fence}text\n${value}\n${fence}`;
}

function exportFilename(filename: string): string {
  const basename = filename.split(/[\\/]/).at(-1) || "agreement";
  const stem = Array.from(basename.replace(/\.pdf$/i, "").normalize("NFC")
    .replace(/[^\p{L}\p{N} _-]/gu, "-").replace(/[\s-]+/g, "-").replace(/^-+|-+$/g, ""))
    .slice(0, 80).join("").replace(/-+$/g, "");
  // Prefix also avoids reserved device filenames on Windows.
  return `review-brief-${stem || "agreement"}.md`;
}

const perspectives = { neutral: "Neutral", customer: "Customer", provider: "Provider", other: "Other role" };
const statuses = { ready: "Ready", processing: "Processing", incomplete: "Incomplete", failed: "Failed", interrupted: "Interrupted" };

/** Export only confirmed personal work for the selected immutable run, without side effects. */
export function buildReviewBrief({ filename, run, personal, source }: {
  filename: string;
  run: ReviewRun | null;
  personal: ReviewPersonalState;
  source: DocumentSourceResponse | null;
}): ReviewBriefExport | null {
  if (!run) return null;
  const selected = run.findings.filter(finding =>
    Object.hasOwn(personal.saved_questions, finding.id) ||
    personal.markers[finding.id] === "revisit" || personal.markers[finding.id] === "reviewed_by_me");
  if (!selected.length) return null;

  const status = runStatus(run);
  const matchingSource = source?.source_revision_id === run.source_revision_id ? source : null;
  const blocks = [
    "# My review brief",
    "## Agreement",
    literal(filename.split(/[\\/]/).at(-1) || "Agreement"),
    `Review: ${run.kind === "fixture" ? "Authored synthetic example (not an AI-generated review)" : "AI-generated review"}.`,
    `Saved run status: ${statuses[status]}.`,
    `Original review perspective: ${perspectives[run.context.perspective]}.`,
  ];
  const field = (label: string, value: string) => { if (value) blocks.push(`**${label}**`, literal(value)); };
  field("Role recorded with this run", run.context.role);
  field("Priorities recorded with this run", run.context.priorities);
  if (run.generation?.model_id) field("Recorded model", run.generation.model_id);
  if (run.generation?.reasoning_effort) field("Recorded reasoning effort", run.generation.reasoning_effort);
  if (status !== "ready") blocks.push("This run did not reach a ready state. Its saved items must be read with the recorded status and limitations below.");
  if (run.failure) field("Recorded review problem", run.failure.message);

  blocks.push("## Scope and limitations",
    `${selected.length} selected ${selected.length === 1 ? "finding" : "findings"}: confirmed saved questions and explicit personal markers from this run only. Drafts, Ask AI answers and other runs are not included.`,
    "Personal markers record your activity, not legal safety, agreement acceptance or review completeness. This brief is not legal advice or a complete review of the agreement.");
  if (run.kind === "fixture") blocks.push("This is an authored synthetic example for demonstration; its example findings are not exhaustive.");
  if (run.coverage) {
    blocks.push(`Recorded review input: ${run.coverage.extracted_pages.length} of ${run.coverage.page_count} physical PDF pages.`,
      `Pages supplied: ${run.coverage.extracted_pages.join(", ") || "None"}.`,
      `Pages omitted: ${run.coverage.omitted_pages.join(", ") || "None recorded"}.`);
    for (const limitation of run.coverage.limitations) field("Recorded limitation", limitation);
    blocks.push("Text supplied to the model is not proof that every provision was understood.");
  } else blocks.push("No page-coverage record is available for this run. Coverage and completeness cannot be inferred.");
  if (!source?.source_extraction) blocks.push("Source text is unavailable for reference matching in this export.");
  else if (!matchingSource) blocks.push("The available source revision differs from this run. Its references are not matched in this export.");
  blocks.push("References below accompany the recorded finding; they do not verify your saved question or its interpretation. A quote match confirms wording and physical page location only, not correctness or legal effect. Page numbers refer to the original PDF, not printed clause or schedule numbering.");

  selected.forEach((finding, index) => {
    blocks.push(`## Finding ${index + 1}`, literal(finding.title));
    const question = Object.hasOwn(personal.saved_questions, finding.id) ? personal.saved_questions[finding.id] : null;
    if (question) field("Saved question", question.text);
    else blocks.push("No question saved for this finding.");
    const marker = personal.markers[finding.id];
    blocks.push(`Personal marker: ${marker === "revisit" ? "Revisit" : marker === "reviewed_by_me" ? "Reviewed by me" : "Not marked"}.`);
    field("What the agreement says (recorded finding)", finding.facts);
    field("Why it matters (recorded interpretation)", finding.interpretation);
    field("Still unknown (recorded uncertainty)", finding.uncertainty);
    if (finding.basis === "not_found") {
      blocks.push("Finding basis: not found within the recorded review scope; this is not proof of absence from the agreement.");
      field("Recorded coverage basis", finding.coverage_basis || "");
    }
    blocks.push("### Finding references");
    if (!finding.evidence.length) blocks.push("No source reference accompanies this finding.");
    finding.evidence.forEach(evidence => {
      const matched = evidence.source_revision_id === run.source_revision_id && evidenceMatches(evidence, matchingSource);
      const unavailable = !source?.source_extraction;
      blocks.push(`Physical PDF page ${evidence.page_number} — ${matched ? "quote matched to source" : unavailable ? "source unavailable; quote not matched" : "quote not matched to this run's source"}.`,
        literal(evidence.label));
    });
  });
  return { markdown: `${blocks.join("\n\n")}\n`, filename: exportFilename(filename), itemCount: selected.length };
}
