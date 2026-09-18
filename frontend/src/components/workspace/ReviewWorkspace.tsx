"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReviewEvidence, ReviewMarker, ReviewPosition } from "@clauseiq/shared-types";
import Modal from "@/components/ui/Modal";
import { useReviewWorkspace } from "@/hooks/useReviewWorkspace";
import { draftKey, emptyPersonal, hasUnconfirmedChanges, sameBrief, runLabel, safeReviewPosition } from "./workspaceState";
import { Action, BriefForm, fieldClass, markerLabels, Panel, SaveFeedback } from "./WorkspaceControls";
import { DocumentSourceView, EvidenceSourcePane, EvidenceList } from "./EvidenceSourcePane";
import { ReviewGenerationControls, ReviewRunSummary } from "./ReviewGenerationControls";

const viewNames: Record<ReviewPosition["view"], string> = {
  overview: "Overview", findings: "Findings", document: "Document", my_review: "My review",
};

export default function ReviewWorkspace({ documentId }: { documentId: string }) {
  const { controller, state, source, filename, sourceError } = useReviewWorkspace(documentId);
  const router = useRouter();
  const [view, setView] = useState<ReviewPosition["view"]>("overview");
  const [selectedRun, setSelectedRun] = useState("");
  const [selectionRunId, setSelectionRunId] = useState("");
  const [selectedFinding, setSelectedFinding] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<string | null>(null);
  const [overviewSource, setOverviewSource] = useState<{ runId: string; text: string; evidence: ReviewEvidence } | null>(null);
  const [navigationRequest, setNavigationRequest] = useState<{ runId: string; requestId: number; pageNumber: number }>();
  const [leaveWarning, setLeaveWarning] = useState(false);
  const [leaveDestination, setLeaveDestination] = useState("/documents");
  const workspace = state?.workspace;

  if (!state || !controller) return <p className="p-8" role="status">Loading review workspace…</p>;
  if (!workspace) return <div className="mx-auto max-w-3xl space-y-4 p-6">
    <h1 className="text-2xl font-semibold">Review workspace</h1>
    <SaveFeedback state={state} onReload={() => void controller.reloadSaved()} onRetry={() => void controller.load()} />
    <p className="text-sm text-text-secondary">This workspace needs a stored source revision. Existing analyses remain available in the earlier review screen.</p>
    <div className="flex gap-4"><Link className="underline" href="/documents">Document library</Link><Link className="underline" href={`/review?documentId=${encodeURIComponent(documentId)}`}>Earlier review</Link></div>
  </div>;

  const run = workspace.runs.find(item => item.id === selectedRun) || workspace.runs.at(-1) || null;
  const personal = run ? workspace.personal[run.id] || emptyPersonal() : emptyPersonal();
  const selectionBelongsToRun = run?.id === selectionRunId;
  const finding = (selectionBelongsToRun ? run?.findings.find(item => item.id === selectedFinding) : null) ||
    run?.findings.find(item => item.id === personal.position.finding_id) || run?.findings[0] || null;
  const evidence = (selectionBelongsToRun ? finding?.evidence.find(item => item.span_id === selectedEvidence) : null) || null;
  const activeOverviewSource = overviewSource?.runId === run?.id ? overviewSource : null;
  const brief = state.briefDraft || workspace.brief;
  const briefDirty = !!state.briefDraft && !sameBrief(state.briefDraft, workspace.brief);
  const blocked = ["loading", "failed", "conflict", "review"].includes(state.status);
  const sourcePages = source?.source_extraction?.pages || [];
  const extractedPages = sourcePages.filter(page => page.status === "extracted").length;
  const limitations = sourcePages.filter(page => page.status !== "extracted");
  const saved = Object.entries(personal.saved_questions);
  const revisits = run?.findings.filter(item => personal.markers[item.id] === "revisit") || [];
  const reviewed = run?.findings.filter(item => personal.markers[item.id] === "reviewed_by_me") || [];
  const draft = finding && run ? state.localDrafts[draftKey(run.id, finding.id)] ?? personal.drafts[finding.id] ?? personal.saved_questions[finding.id]?.text ?? "" : "";
  const savedQuestion = finding ? personal.saved_questions[finding.id] : undefined;

  function navigate(nextView: ReviewPosition["view"], findingId = finding?.id || null, evidenceId = evidence?.span_id || null) {
    setOverviewSource(null);
    setView(nextView);
    const position = run ? safeReviewPosition(run, nextView, findingId, evidenceId) : null;
    setSelectionRunId(run?.id || "");
    setSelectedFinding(position?.finding_id || null);
    setSelectedEvidence(position?.evidence_span_id || null);
    if (run && position) controller!.enqueue({ type: "set_position", run_id: run.id, position });
  }

  function openEvidence(item: ReviewEvidence) {
    setNavigationRequest(previous => ({ runId: run?.id || "", requestId: (previous?.requestId || 0) + 1, pageNumber: item.page_number }));
    navigate("document", finding?.id || null, item.span_id);
  }

  function openOverviewEvidence(text: string, item: ReviewEvidence) {
    setOverviewSource({ runId: run?.id || "", text, evidence: item });
    setNavigationRequest(previous => ({ runId: run?.id || "", requestId: (previous?.requestId || 0) + 1, pageNumber: item.page_number }));
    setView("document");
    // Overview references are not finding-scoped resume positions.
  }

  function resume() {
    const position = personal.position;
    const previousFinding = run?.findings.find(item => item.id === position.finding_id);
    const previousEvidence = previousFinding?.evidence.find(item => item.span_id === position.evidence_span_id);
    if (previousEvidence) setNavigationRequest(previous => ({ runId: run?.id || "", requestId: (previous?.requestId || 0) + 1, pageNumber: previousEvidence.page_number }));
    navigate(position.view, position.finding_id, position.evidence_span_id);
  }

  const openFinding = (findingId: string) => navigate("findings", findingId, null);
  const findTitle = (findingId: string) => run?.findings.find(item => item.id === findingId)?.title || "Finding";
  function leave(destination: string) {
    if (hasUnconfirmedChanges(state!)) {
      controller!.flushDrafts(); setLeaveDestination(destination); setLeaveWarning(true);
    } else router.push(destination);
  }

  return <div className="mx-auto max-w-[1600px] space-y-4 px-4 py-6 sm:px-6">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-widest text-text-secondary">Agreement workspace</p>
        <h1 className="mt-1 break-words text-2xl font-semibold">{filename}</h1>
        <p className="mt-1 text-sm text-text-secondary">Local source · {extractedPages}/{sourcePages.length || "?"} pages with extractable text · reviews start only on your request</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Action onClick={() => leave(`/review?documentId=${encodeURIComponent(documentId)}`)}>Earlier review</Action>
        <Action onClick={() => leave("/documents")}>Document library</Action>
      </div>
    </header>

    <SaveFeedback state={state} onReload={() => void controller.reloadSaved()} onRetry={() => controller.retryPending()} />
    {sourceError && <p role="alert" className="rounded-lg border border-border-muted p-3 text-sm">{sourceError}</p>}
    {run && <ReviewRunSummary run={run} contextChanged={!sameBrief(run.context, workspace.brief)} />}

    <nav aria-label="Agreement workspace views" className="flex flex-wrap gap-2 border-b border-border-muted pb-3">
      {(Object.keys(viewNames) as ReviewPosition["view"][]).map(item => <Action key={item} aria-current={view === item ? "page" : undefined}
        className={view === item ? "border-accent-purple bg-accent-purple/10" : ""} onClick={() => navigate(item)}>{viewNames[item]}</Action>)}
      {workspace.runs.length > 1 && <label className="ml-auto text-sm">Review run <select className="ml-2 rounded border border-border-muted bg-bg-surface p-2" value={run?.id || ""} onChange={event => {
        setSelectedRun(event.target.value); setSelectionRunId(event.target.value); setSelectedFinding(null); setSelectedEvidence(null); setOverviewSource(null); setView("overview");
      }}>{workspace.runs.map((item, index) => <option key={item.id} value={item.id}>{index + 1}. {runLabel(item)}{item.generation ? ` · ${item.generation.model_id}` : ""}</option>)}</select></label>}
    </nav>

    {view === "overview" && <div className="grid items-start gap-4 lg:grid-cols-[1.2fr_1fr]">
      <div className="space-y-4">
        {run && <Panel>
          <h2 className="text-lg font-semibold">Pick up where you left off</h2>
          <p className="mt-2 text-sm">Last saved position: {viewNames[personal.position.view]}{personal.position.finding_id ? ` — ${findTitle(personal.position.finding_id)}` : ""}.</p>
          <p className="my-3 text-sm text-text-secondary">{personal.opened_finding_ids.length} opened · {revisits.length} to revisit · {saved.length} saved questions. These are personal activity counts, not review completeness.</p>
          <Action onClick={resume}>Continue from saved position</Action>
          {!!revisits.length && <div className="mt-4"><h3 className="text-sm font-semibold">Left for later</h3><ul className="mt-2 space-y-2">{revisits.map(item => <li key={item.id}><button className="text-left text-sm underline" onClick={() => openFinding(item.id)}>{item.title}</button></li>)}</ul></div>}
          {!!saved.length && <div className="mt-4"><h3 className="text-sm font-semibold">Saved questions</h3><ul className="mt-2 space-y-2">{saved.map(([id, item]) => <li key={item.id}><button className="text-left text-sm underline" onClick={() => openFinding(id)}>{item.text}</button></li>)}</ul></div>}
        </Panel>}
        <Panel>
          <h2 className="text-lg font-semibold">{run ? `${run.kind === "fixture" ? "Example agreement" : "Agreement"} overview` : "Source saved. Review not started."}</h2>
          {run?.overview_items?.length ? <div className="mt-3 space-y-5">{run.overview_items.map((item, index) => <article key={index}>
            <p className="whitespace-pre-wrap text-sm leading-relaxed">{item.text}</p>
            <details className="mt-2 text-sm"><summary className="cursor-pointer">Supporting source ({item.evidence.length})</summary><EvidenceList evidence={item.evidence} source={source} onOpen={evidence => openOverviewEvidence(item.text, evidence)} /></details>
          </article>)}</div> : <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{run?.overview || (run ? "No usable overview is available for this run. Check its status and limitations above." : "You can inspect the original and save a review brief without a key. Start a review explicitly when ready.")}</p>}
          {run && <Action className="mt-4" onClick={() => navigate("findings")}>Explore {run.findings.length} {run.kind === "fixture" ? "example " : ""}findings</Action>}
          {!workspace.runs.some(item => item.kind === "fixture") && workspace.fixture_available && <div className="mt-4 border-t border-border-muted pt-4"><p className="mb-3 text-sm text-text-secondary">This source matches the supported synthetic fixture. Load the labelled customer-perspective example to exercise saved work. Your brief is not used to generate it.</p><Action disabled={blocked || state.pending > 0 || state.reviewAction?.status !== "idle"} onClick={() => controller.createFixture()}>Load synthetic customer-perspective example</Action></div>}
        </Panel>
        <Panel>
          <h2 className="text-lg font-semibold">Source and coverage</h2>
          <p className="mt-2 text-sm">{extractedPages} of {sourcePages.length || "unknown"} pages have extracted text. Extraction does not mean every provision has been reviewed.</p>
          {!!limitations.length && <p className="mt-2 text-sm">Extraction limitations on pages {limitations.map(page => `${page.page_number} (${page.status === "empty" ? "no extractable text" : "extraction failed"})`).join(", ")}. No OCR is performed.</p>}
          {run?.coverage && <div className="mt-3 space-y-2 text-sm">
            <p>Selected run input: all successfully extracted text from pages {run.coverage.extracted_pages.join(", ") || "none"} of {run.coverage.page_count}. Text supplied is not proof that every provision was understood.</p>
            {!!run.coverage.omitted_pages.length && <p>Pages omitted from review input: {run.coverage.omitted_pages.join(", ")}.</p>}
            {!!run.coverage.limitations.length && <ul className="list-disc space-y-1 pl-5">{run.coverage.limitations.map((text, index) => <li key={index}>{text}</li>)}</ul>}
          </div>}
          {!source?.source_extraction && <p className="mt-2 text-sm">No page-aware source snapshot is available. Evidence cannot be checked yet.</p>}
          <details className="mt-3 break-all text-xs text-text-secondary"><summary className="cursor-pointer">Source identity</summary><p className="mt-2">Revision: {workspace.source_revision_id}</p><p>SHA-256: {source?.source_sha256 || "Unavailable"}</p><p>Extractor: {source?.source_extraction?.extraction_version || "Unavailable"}</p></details>
          <Action className="mt-3" onClick={() => navigate("document")}>Open original document</Action>
        </Panel>
      </div>
      <div className="space-y-4"><BriefForm brief={brief} dirty={briefDirty} pending={blocked || state.pending > 0} onChange={value => controller.setBriefDraft(value)} onSave={() => controller.saveBrief()} />
        <ReviewGenerationControls state={state} controller={controller} sourceReady={!!source && extractedPages > 0 && !sourceError} onSettings={() => leave("/settings")} />
        {state.status === "review" && briefDirty && <Panel><h2 className="font-semibold">Latest saved brief</h2><p className="mt-2 text-sm">{workspace.brief.role || workspace.brief.perspective}</p><p className="mt-2 whitespace-pre-wrap text-sm">{workspace.brief.priorities || "No priorities supplied."}</p><p className="mt-2 text-xs text-text-secondary">Your different local edits remain in the form. Applying pending changes may replace these saved values.</p></Panel>}
      </div>
    </div>}

    {view === "findings" && (run && finding ? <div className="grid items-start gap-4 xl:grid-cols-[230px_minmax(0,1fr)_minmax(0,1fr)]">
      <Panel><h2 className="font-semibold">{run.kind === "fixture" ? "Example findings" : "Review findings"}</h2><div className="mt-3 space-y-2">{run.findings.map(item => <button key={item.id} onClick={() => openFinding(item.id)} aria-current={finding.id === item.id ? "true" : undefined}
        className={`w-full rounded-md border p-3 text-left text-sm ${finding.id === item.id ? "border-accent-purple bg-accent-purple/10" : "border-border-muted"}`}>
        <span className="block font-medium">{item.title}</span><span className="mt-1 block text-xs text-text-secondary">{markerLabels[personal.markers[item.id] || "not_marked"]} · {personal.opened_finding_ids.includes(item.id) ? "Opened" : "Not opened"}</span>
        {personal.saved_questions[item.id] && <span className="mt-1 block text-xs">Question saved</span>}
      </button>)}</div></Panel>
      <div className="space-y-4">
        <Panel>
          <p className="text-xs uppercase tracking-wider text-text-secondary">{run.kind === "fixture" ? "Example finding" : "AI finding"}</p><h2 className="mt-1 text-xl font-semibold">{finding.title}</h2>
          <div className="mt-4 space-y-4 text-sm leading-relaxed">
            <div><h3 className="font-semibold">What the agreement says</h3><p className="mt-1">{finding.facts}</p></div>
            <div><h3 className="font-semibold">Why this matters for this review perspective</h3><p className="mt-1">{finding.interpretation}</p></div>
            <div><h3 className="font-semibold">What remains uncertain</h3><p className="mt-1">{finding.uncertainty}</p></div>
            <div><h3 className="font-semibold">Possible next step</h3><p className="mt-1">{finding.next_step}</p></div>
            {finding.basis === "not_found" && <div><h3 className="font-semibold">Not found within the reviewed scope</h3><p className="mt-1">{finding.coverage_basis || "No reviewed-scope explanation was supplied."}</p><p className="mt-1 text-text-secondary">This is not proof of absence from the original, missing schedules or related documents.</p></div>}
            {finding.basis !== "not_found" && finding.coverage_basis && <div><h3 className="font-semibold">Reviewed scope</h3><p className="mt-1">{finding.coverage_basis}</p></div>}
          </div>
          <label className="mt-5 block text-sm font-medium">My review marker
            <select disabled={blocked} className={`${fieldClass} mt-1`} value={personal.markers[finding.id] || "not_marked"} onChange={event => controller.enqueue({ type: "set_marker", run_id: run.id, finding_id: finding.id, marker: event.target.value as ReviewMarker })}>
              {Object.entries(markerLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <p className="mt-2 text-xs text-text-secondary">Your marker is not legal acceptance, a resolved issue or an AI judgement. Opening or saving does not set it.</p>
        </Panel>
        <Panel>
          <h2 className="text-lg font-semibold">Keep a question</h2>
          <p className="my-2 text-sm text-text-secondary">Drafts save locally as you type. Add useful wording to My review explicitly; nothing is sent.</p>
          <label className="sr-only" htmlFor="question-draft">Question draft for {finding.title}</label>
          <textarea id="question-draft" className={fieldClass} rows={5} maxLength={5000} value={draft} onChange={event => controller.setDraft(run.id, finding.id, event.target.value)} onBlur={() => controller.flushDrafts()} placeholder="Write a question you want to keep…" />
          <div className="mt-3 flex flex-wrap gap-2"><Action onClick={() => controller.setDraft(run.id, finding.id, finding.suggested_question)}>{draft && draft !== finding.suggested_question ? "Replace draft with suggested wording" : "Use suggested wording"}</Action><Action disabled={blocked || !draft.trim() || draft === savedQuestion?.text} onClick={() => controller.saveQuestion(run.id, finding.id, draft)}>{savedQuestion ? "Update saved question" : "Save question to My review"}</Action></div>
          <p className="mt-2 text-xs text-text-secondary">{savedQuestion ? draft === savedQuestion.text ? "This wording is saved in My review." : "Your draft differs from the saved question. The last saved wording remains below until an update is confirmed." : "No question has been added to My review for this finding."}</p>
          {savedQuestion && <blockquote className="mt-3 whitespace-pre-wrap border-l-2 border-border-muted pl-3 text-sm">{savedQuestion.text}</blockquote>}
          {state.status === "review" && personal.drafts[finding.id] !== undefined && personal.drafts[finding.id] !== draft && <div className="mt-4 rounded-md border border-border-muted p-3"><h3 className="text-sm font-semibold">Latest saved draft from the workspace</h3><p className="mt-2 whitespace-pre-wrap text-sm">{personal.drafts[finding.id] || "Empty draft"}</p><p className="mt-2 text-xs text-text-secondary">Your local wording remains above. Apply pending changes only after comparing both.</p></div>}
          <details className="mt-4 text-sm"><summary className="cursor-pointer">{run.kind === "fixture" ? "Authored example suggestion" : "AI-suggested wording"}</summary><p className="mt-2">{finding.suggested_question}</p></details>
        </Panel>
        <Panel><h2 className="font-semibold">Ask about this finding</h2><p className="my-2 text-sm text-text-secondary">Contextual AI follow-ups are a later increment. No answer will be generated here.</p><Action disabled>Ask — not available yet</Action></Panel>
      </div>
      <EvidenceSourcePane finding={finding} source={source} onOpen={openEvidence} />
    </div> : <Panel><h2 className="text-lg font-semibold">{run ? "No usable findings in this run" : "No review run yet"}</h2><p className="mt-2 text-sm">An empty finding list is not proof that the agreement has no issues. Check the run status and coverage on Overview.</p><Action className="mt-3" onClick={() => navigate("overview")}>Return to overview</Action></Panel>)}

    {view === "document" && <DocumentSourceView documentId={documentId} filename={filename} source={source} finding={activeOverviewSource ? null : finding} evidence={activeOverviewSource?.evidence || evidence}
      overviewText={activeOverviewSource?.text} navigationRequest={navigationRequest?.runId === run?.id ? navigationRequest : undefined} onReturn={() => navigate(activeOverviewSource ? "overview" : "findings")} />}

    {view === "my_review" && <div className="grid items-start gap-4 lg:grid-cols-2">
      <Panel><h2 className="text-lg font-semibold">Saved questions</h2><p className="mt-2 text-sm text-text-secondary">Deliberately saved wording only. Saving does not send a message, change a term or resolve a finding.</p>
        {saved.length ? <ul className="mt-4 space-y-4">{saved.map(([id, item]) => <li className="rounded-lg border border-border-muted p-4" key={item.id}><h3 className="font-medium">{findTitle(id)}</h3><p className="my-3 whitespace-pre-wrap text-sm">{item.text}</p><Action onClick={() => openFinding(id)}>Return to finding and edit</Action></li>)}</ul> : <p className="mt-4 text-sm">No saved questions yet. Recoverable drafts stay separate.</p>}
      </Panel>
      <div className="space-y-4">{([['Revisit', revisits], ['Reviewed by me', reviewed]] as const).map(([title, findings]) => <Panel key={title}><h2 className="text-lg font-semibold">{title}</h2><p className="mt-2 text-sm text-text-secondary">Explicit personal markers, not resolved or accepted terms.</p>{findings.length ? <ul className="mt-3 space-y-3">{findings.map(item => <li key={item.id}><button className="text-left text-sm underline" onClick={() => openFinding(item.id)}>{item.title}</button></li>)}</ul> : <p className="mt-3 text-sm">Nothing marked here yet.</p>}</Panel>)}</div>
    </div>}

    <Modal isOpen={leaveWarning} onClose={() => setLeaveWarning(false)} title="Some changes are not confirmed saved" footer={<><Action onClick={() => setLeaveWarning(false)}>Stay and finish saving</Action><Action onClick={() => router.push(leaveDestination)}>Leave without confirmed changes</Action></>}>
      <p>Confirmed saved work will remain. Local drafts, brief edits or pending changes may be lost when you leave. Return to the workspace to retry or resolve a conflict first.</p>
      {["generating", "uncertain"].includes(state.reviewAction?.status) && <p className="mt-3">Leaving does not cancel an accepted review request. Provider charges may still apply. Reopen this document to check its saved status; it will not automatically rerun.</p>}
    </Modal>
  </div>;
}
