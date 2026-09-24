import type {
  DocumentSourceResponse, ReviewBrief, ReviewEvidence, ReviewPersonalState, ReviewPosition,
  ReviewAskTurn, ReviewRun, ReviewWorkspaceOperation, ReviewWorkspaceResponse,
} from "@clauseiq/shared-types";
import type { ReviewWorkspaceTransport } from "@/lib/reviewWorkspaceApi";

export const emptyPersonal = (): ReviewPersonalState => ({
  drafts: {}, ask_drafts: {}, saved_questions: {}, markers: {}, opened_finding_ids: [],
  position: { view: "overview", finding_id: null, evidence_span_id: null },
});
export const draftKey = (runId: string, findingId: string) => JSON.stringify([runId, findingId]);
export const sameBrief = (a: ReviewBrief, b: ReviewBrief) =>
  a.perspective === b.perspective && a.role === b.role && a.priorities === b.priorities;

export const runStatus = (run: ReviewRun) => run.status || "ready";
export const runLabel = (run: ReviewRun) => `${run.kind === "fixture" ? "Synthetic example" : "AI review"} — ${
  { ready: "available", processing: "processing", incomplete: "incomplete", failed: "failed", interrupted: "interrupted" }[runStatus(run)]
}`;

/** UI tabs remain available for empty runs without creating invalid saved positions. */
export function safeReviewPosition(run: ReviewRun, view: ReviewPosition["view"], findingId: string | null, evidenceId: string | null): ReviewPosition | null {
  const finding = run.findings.find(item => item.id === findingId);
  if (view === "findings" && !finding) return null;
  return { view, finding_id: finding?.id || null,
    evidence_span_id: finding?.evidence.some(item => item.span_id === evidenceId) ? evidenceId : null };
}

/** Same latest-run rule as the Library; never silently fall back to older output. */
export function libraryResumePosition(workspace: ReviewWorkspaceResponse) {
  const run = workspace.runs.at(-1);
  if (!run || run.source_revision_id !== workspace.source_revision_id || !["ready", "incomplete"].includes(runStatus(run))) return null;
  const saved = workspace.personal[run.id]?.position || emptyPersonal().position;
  const position = safeReviewPosition(run, saved.view, saved.finding_id, saved.evidence_span_id) || emptyPersonal().position;
  const evidence = run.findings.find(finding => finding.id === position.finding_id)?.evidence.find(item => item.span_id === position.evidence_span_id);
  return { runId: run.id, position, pageNumber: evidence?.page_number || null };
}
export type ReviewActionState = {
  status: "idle" | "preparing" | "generating" | "uncertain" | "interrupting";
  error: string | null;
  canRetryRequest: boolean;
  requestRejected?: boolean;
};
const idleReviewAction = (): ReviewActionState => ({ status: "idle", error: null, canRetryRequest: false });
export type AskActionState = ReviewActionState & { runId?: string; findingId?: string };
export const paidActionBusy = (state: WorkspaceSaveState) =>
  (state.reviewAction?.status || "idle") !== "idle" || (state.askAction?.status || "idle") !== "idle";
const hasProcessing = (workspace: ReviewWorkspaceResponse) =>
  workspace.runs.some(run => runStatus(run) === "processing") ||
  (workspace.ask_turns || []).some(turn => turn.status === "processing");

/** Mirror the server's successful fresh-question boundary; display only, never dispatches. */
export function askHistorySummary(turns: ReviewAskTurn[], runId: string, findingId: string) {
  let eligible = turns.filter(turn => turn.run_id === runId && turn.finding_id === findingId &&
    ["ready", "incomplete"].includes(turn.status) && turn.answer.length > 0);
  for (let index = eligible.length - 1; index >= 0; index -= 1) {
    if (!eligible[index].include_history) { eligible = eligible.slice(index); break; }
  }
  return { count: Math.min(eligible.length, 6), truncated: eligible.length > 6 };
}

export function evidenceMatches(evidence: ReviewEvidence, source: DocumentSourceResponse | null): boolean {
  if (!source || evidence.source_revision_id !== source.source_revision_id) return false;
  const page = source.source_extraction?.pages.find(item => item.page_number === evidence.page_number);
  if (!page) return false;
  const characters = Array.from(page.text); // Source offsets count Unicode code points, not UTF-16 units.
  const firstIndex = page.spans.findIndex(item => item.id === evidence.span_id);
  const first = page.spans[firstIndex];
  const exactSpan = (span: typeof first) => !!span && Number.isInteger(span.start) && Number.isInteger(span.end) &&
    span.start >= 0 && span.end > span.start && span.end <= characters.length &&
    characters.slice(span.start, span.end).join("") === span.text;
  if (!exactSpan(first)) return false;
  if (evidence.end_span_id == null) return first.text === evidence.quote;

  const lastIndex = page.spans.findIndex(item => item.id === evidence.end_span_id);
  if (lastIndex < firstIndex) return false; // A missing, reversed or cross-page end cannot be guessed.
  const last = page.spans[lastIndex];
  if (!last) return false;
  const allSpans = source.source_extraction!.pages.flatMap(item => item.spans);
  if (allSpans.filter(item => item.id === first.id).length !== 1 ||
      allSpans.filter(item => item.id === last.id).length !== 1) return false;
  const passageSpans = page.spans.slice(firstIndex, lastIndex + 1);
  for (let index = 0; index < passageSpans.length; index += 1) {
    const span = passageSpans[index];
    if (!exactSpan(span) || allSpans.filter(item => item.id === span.id).length !== 1) return false;
    const previous = passageSpans[index - 1];
    if (previous && (span.start < previous.end ||
        characters.slice(previous.end, span.start).join("").trim() !== "")) return false;
  }
  // An outside span overlapping the selected passage makes its anchor range ambiguous.
  if (page.spans.some((span, index) => (index < firstIndex || index > lastIndex) &&
      span.start < last.end && span.end > first.start)) return false;
  return characters.slice(first.start, last.end).join("") === evidence.quote;
}

type QueueEntry = { key: string; operation: ReviewWorkspaceOperation | null };

// A disposed controller cannot cancel a PUT that may already be committing.
// Keep reads in a replacement controller behind those same-tab writes, without
// retrying them or rebasing genuine external conflicts. Entries expire on settle.
const inFlightWrites = new WeakMap<ReviewWorkspaceTransport, Map<string, Set<Promise<ReviewWorkspaceResponse>>>>();
const WRITE_SETTLE_TIMEOUT_MS = 20000;
function trackWrite(transport: ReviewWorkspaceTransport, documentId: string, request: Promise<ReviewWorkspaceResponse>) {
  let documents = inFlightWrites.get(transport);
  if (!documents) { documents = new Map(); inFlightWrites.set(transport, documents); }
  let requests = documents.get(documentId);
  if (!requests) { requests = new Set(); documents.set(documentId, requests); }
  requests.add(request);
  const settled = () => {
    requests.delete(request);
    if (!requests.size) documents.delete(documentId);
  };
  void request.then(settled, settled);
  return request;
}

async function waitForWrites(transport: ReviewWorkspaceTransport, documentId: string) {
  const requests = inFlightWrites.get(transport)?.get(documentId);
  if (!requests?.size) return;
  await new Promise<void>((resolve, reject) => {
    let finished = false;
    const finish = (error?: Error) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      if (error) reject(error);
      else resolve();
    };
    const timer = setTimeout(() => finish(new Error(
      "An earlier save is still awaiting confirmation. Saved work was not reloaded. Keep this page open and retry loading after the save finishes.",
    )), WRITE_SETTLE_TIMEOUT_MS);
    // A timeout ends this read attempt, not the tracked write. A later retry
    // must still wait unless that request has actually settled.
    void Promise.allSettled([...requests]).then(() => finish());
  });
}

export type SaveStatus = "loading" | "saved" | "saving" | "failed" | "conflict" | "review";
export interface WorkspaceSaveState {
  workspace: ReviewWorkspaceResponse | null;
  status: SaveStatus;
  error: string | null;
  pending: number;
  localDrafts: Record<string, string>;
  localAskDrafts: Record<string, string>;
  briefDraft: ReviewBrief | null;
  reviewAction: ReviewActionState;
  askAction: AskActionState;
}

export function hasUnconfirmedChanges(state: WorkspaceSaveState): boolean {
  return state.pending > 0 || ["preparing", "generating", "uncertain", "interrupting"].includes(state.reviewAction?.status) ||
    ["preparing", "generating", "uncertain", "interrupting"].includes(state.askAction?.status) ||
    !!state.workspace?.ask_turns?.some(turn => turn.status === "processing") ||
    ["loading", "failed", "conflict", "review"].includes(state.status) ||
    !!(state.briefDraft && state.workspace && !sameBrief(state.briefDraft, state.workspace.brief));
}

/** Serial writes use confirmed revisions only. Conflicts never auto-rebase edits. */
export class ReviewWorkspaceController {
  private current: WorkspaceSaveState = {
    workspace: null, status: "loading", error: null, pending: 0, localDrafts: {}, localAskDrafts: {}, briefDraft: null,
    reviewAction: idleReviewAction(), askAction: idleReviewAction(),
  };
  private listeners = new Set<() => void>();
  private queue: QueueEntry[] = [];
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  private askTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private sending = false;
  private stopped = false;
  private generation = 0;
  private pendingAttempt: { revision: number; requestId: string; modelId: string; reasoningEffort: string; rejected?: boolean } | null = null;
  private pendingAskAttempt: { revision: number; requestId: string; modelId: string; runId: string;
    findingId: string; question: string; includeHistory: boolean; reasoningEffort: string; rejected?: boolean } | null = null;
  private pendingWaiters = new Set<() => void>();

  constructor(private documentId: string, private transport: ReviewWorkspaceTransport, private debounceMs = 500) {}
  getSnapshot = () => this.current;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };

  private emit(values: Partial<WorkspaceSaveState> = {}) {
    if (this.stopped) return;
    this.current = { ...this.current, ...values, pending: this.queue.length + this.timers.size + this.askTimers.size };
    this.listeners.forEach(listener => listener());
    this.pendingWaiters.forEach(listener => listener());
  }

  async load() {
    const generation = ++this.generation;
    try {
      await waitForWrites(this.transport, this.documentId);
      if (this.stopped || generation !== this.generation) return;
      const workspace = await this.transport.load(this.documentId);
      if (this.stopped || generation !== this.generation) return;
      this.emit({ workspace, status: "saved", error: null });
      void this.drain();
    } catch (error) {
      if (generation === this.generation) this.emit({ status: "failed", error: safeMessage(error) });
    }
  }

  setBriefDraft(brief: ReviewBrief) { this.emit({ briefDraft: brief }); }
  saveBrief() {
    if (this.current.briefDraft) this.enqueue({ type: "set_brief", brief: { ...this.current.briefDraft } });
  }

  setDraft(runId: string, findingId: string, text: string) {
    const key = draftKey(runId, findingId);
    this.emit({ localDrafts: { ...this.current.localDrafts, [key]: text } });
    const old = this.timers.get(key);
    if (old) clearTimeout(old);
    this.timers.set(key, setTimeout(() => {
      this.timers.delete(key);
      this.enqueue({ type: "set_draft", run_id: runId, finding_id: findingId, text });
    }, this.debounceMs));
    this.emit();
  }

  saveQuestion(runId: string, findingId: string, text: string) {
    const key = draftKey(runId, findingId);
    const timer = this.timers.get(key);
    if (timer) clearTimeout(timer);
    this.timers.delete(key);
    this.emit({ localDrafts: { ...this.current.localDrafts, [key]: text } });
    this.enqueue({ type: "set_draft", run_id: runId, finding_id: findingId, text });
    this.enqueue({ type: "save_question", run_id: runId, finding_id: findingId, text });
  }

  /** Confirmed removal never clears recovery drafts or bypasses unresolved writes. */
  removeQuestion(runId: string, findingId: string) {
    const workspace = this.current.workspace;
    if (this.stopped || !workspace || this.current.status !== "saved" || this.current.pending > 0 ||
        paidActionBusy(this.current) || hasProcessing(workspace) ||
        !workspace.runs.some(run => run.id === runId && run.findings.some(finding => finding.id === findingId)) ||
        !workspace.personal[runId]?.saved_questions[findingId]) return;
    this.enqueue({ type: "remove_question", run_id: runId, finding_id: findingId });
  }

  setAskDraft(runId: string, findingId: string, text: string) {
    const key = draftKey(runId, findingId);
    this.emit({ localAskDrafts: { ...this.current.localAskDrafts, [key]: text } });
    const old = this.askTimers.get(key);
    if (old) clearTimeout(old);
    this.askTimers.set(key, setTimeout(() => {
      this.askTimers.delete(key);
      this.enqueue({ type: "set_ask_draft", run_id: runId, finding_id: findingId, text });
    }, this.debounceMs));
    this.emit();
  }

  enqueue(operation: ReviewWorkspaceOperation) {
    const key = operation.type === "set_brief" ? "brief" :
      operation.type === "set_position" ? `position:${operation.run_id}` :
      `${operation.type}:${draftKey(operation.run_id, operation.finding_id)}`;
    const index = this.queue.findIndex((entry, i) => entry.key === key && !(this.sending && i === 0));
    const entry = { key, operation };
    if (index >= 0) this.queue[index] = entry;
    else this.queue.push(entry);
    this.emit();
    void this.drain();
  }

  createFixture() {
    if (paidActionBusy(this.current) || !this.current.workspace?.fixture_available || this.queue.some(item => item.key === "fixture")) return;
    this.queue.push({ key: "fixture", operation: null });
    this.emit();
    void this.drain();
  }

  private async drain() {
    if (this.stopped || this.sending || !this.current.workspace || !this.queue.length ||
        ["generating", "uncertain", "interrupting"].includes(this.current.reviewAction.status) ||
        ["generating", "uncertain", "interrupting"].includes(this.current.askAction.status) ||
        ["failed", "conflict", "review", "loading"].includes(this.current.status)) return;
    this.sending = true;
    const entry = this.queue[0];
    const revision = this.current.workspace.revision;
    this.emit({ status: "saving", error: null });
    try {
      const workspace = await trackWrite(this.transport, this.documentId, entry.operation
        ? this.transport.update(this.documentId, revision, entry.operation)
        : this.transport.fixture(this.documentId, revision));
      if (this.stopped) return;
      this.queue.shift();
      const localDrafts = { ...this.current.localDrafts };
      const localAskDrafts = { ...this.current.localAskDrafts };
      const operation = entry.operation;
      if (operation?.type === "set_draft") {
        const key = draftKey(operation.run_id, operation.finding_id);
        if (localDrafts[key] === operation.text) delete localDrafts[key];
      }
      if (operation?.type === "set_ask_draft") {
        const key = draftKey(operation.run_id, operation.finding_id);
        if (localAskDrafts[key] === operation.text) delete localAskDrafts[key];
      }
      const briefDraft = this.current.briefDraft && sameBrief(this.current.briefDraft, workspace.brief)
        ? null : this.current.briefDraft;
      this.emit({ workspace, localDrafts, localAskDrafts, briefDraft, status: "saved" });
    } catch (error) {
      const conflict = typeof error === "object" && error !== null && "code" in error && error.code === "REVISION_CONFLICT";
      this.emit({ status: conflict ? "conflict" : "failed", error: safeMessage(error) });
    } finally {
      this.sending = false;
      if (!this.stopped) void this.drain();
    }
  }

  /** Keep pending intentions and local wording, but do not apply them after reload. */
  async reloadSaved() {
    if (this.sending || ["preparing", "generating", "interrupting"].includes(this.current.reviewAction.status) ||
        ["preparing", "generating", "interrupting"].includes(this.current.askAction.status)) return;
    this.emit({ status: "loading", error: null });
    this.flushDrafts();
    const generation = ++this.generation;
    try {
      await waitForWrites(this.transport, this.documentId);
      if (this.stopped || generation !== this.generation) return;
      const workspace = await this.transport.load(this.documentId);
      if (this.stopped || generation !== this.generation) return;
      let reviewAction = this.current.reviewAction;
      if (this.pendingAttempt) {
        if (this.pendingAttempt.rejected || workspace.runs.some(run => run.id === this.pendingAttempt!.requestId)) {
          const previousError = this.pendingAttempt.rejected ? this.current.reviewAction.error : null;
          this.pendingAttempt = null;
          reviewAction = { ...idleReviewAction(), error: previousError };
        } else reviewAction = { ...reviewAction, canRetryRequest: true };
      }
      let askAction = this.current.askAction;
      if (this.pendingAskAttempt) {
        if (this.pendingAskAttempt.rejected || workspace.ask_turns?.some(turn => turn.id === this.pendingAskAttempt!.requestId)) {
          askAction = { ...askAction, ...idleReviewAction(), error: this.pendingAskAttempt.rejected ? askAction.error : null };
          this.pendingAskAttempt = null;
        } else askAction = { ...askAction, canRetryRequest: true };
      }
      this.emit({ workspace, status: this.queue.length ? "review" : "saved", error: null, reviewAction, askAction });
    } catch (error) {
      if (generation === this.generation) this.emit({ status: "failed", error: safeMessage(error) });
    }
  }

  retryPending() {
    if (this.current.status === "conflict" || this.current.status === "loading") return;
    this.emit({ status: "saved", error: null });
    this.flushDrafts();
    void this.drain();
  }

  /** Paid work never enters the recoverable local-write queue. */
  async startReview(modelId: string, requestId: string, reasoningEffort = "medium") {
    if (this.stopped || paidActionBusy(this.current) || !this.current.workspace ||
        hasProcessing(this.current.workspace) ||
        ["loading", "failed", "conflict", "review"].includes(this.current.status) || !modelId || !requestId) return;
    this.emit({ reviewAction: { status: "preparing", error: null, canRetryRequest: false } });
    this.saveBrief();
    this.flushDrafts();
    await this.waitForWrites();
    if (this.stopped) return;
    if (this.current.status !== "saved" || this.current.pending ||
        (this.current.briefDraft && !sameBrief(this.current.briefDraft, this.current.workspace!.brief))) {
      this.emit({ reviewAction: { ...idleReviewAction(), error: "Review was not started. Confirm pending changes and the latest brief first." } });
      return;
    }
    this.pendingAttempt = { revision: this.current.workspace!.revision, requestId, modelId, reasoningEffort };
    await this.sendReviewAttempt();
  }

  private waitForWrites(): Promise<void> {
    return new Promise(resolve => {
      const check = () => {
        if (this.stopped || !this.current.pending || ["failed", "conflict", "review"].includes(this.current.status)) {
          this.pendingWaiters.delete(check);
          resolve();
        }
      };
      this.pendingWaiters.add(check);
      check();
    });
  }

  private async sendReviewAttempt() {
    const attempt = this.pendingAttempt;
    if (!attempt || this.stopped) return;
    this.emit({ reviewAction: { status: "generating", error: null, canRetryRequest: false } });
    try {
      const workspace = await this.transport.generate(this.documentId, attempt.revision, attempt.requestId, attempt.modelId, attempt.reasoningEffort);
      if (this.stopped) return;
      this.pendingAttempt = null;
      this.acceptReviewResponse(workspace);
    } catch (error) {
      const rejected = isPreflightRejection(error);
      if (this.pendingAttempt) this.pendingAttempt.rejected = rejected;
      this.emit({ reviewAction: { status: "uncertain", canRetryRequest: false,
        requestRejected: rejected,
        error: rejected ? `Review was not started. ${safeMessage(error)} Refresh saved state and resolve this before starting again.`
          : `${safeMessage(error)} The request was not retried. Refresh saved state to check whether it was recorded.` } });
    }
  }

  /** Explicit retry only after GET found no run, using the original id and snapshot. */
  async retryReviewRequest() {
    if (this.current.reviewAction.status !== "uncertain" || !this.current.reviewAction.canRetryRequest || this.sending) return;
    await this.sendReviewAttempt();
  }

  /** Finding questions keep the selected run's context, never save or use a draft brief. */
  async startAsk(runId: string, findingId: string, question: string, modelId: string,
    requestId: string, includeHistory = true, reasoningEffort = "medium") {
    const workspace = this.current.workspace;
    const run = workspace?.runs.find(item => item.id === runId);
    if (this.stopped || paidActionBusy(this.current) || !workspace || hasProcessing(workspace) ||
        !run?.findings.some(item => item.id === findingId) ||
        !["ready", "incomplete"].includes(runStatus(run)) ||
        ["loading", "failed", "conflict", "review"].includes(this.current.status) ||
        !question.trim() || question.length > 5000 || !modelId || !requestId) return;
    const target = { runId, findingId };
    this.emit({ askAction: { ...target, status: "preparing", error: null, canRetryRequest: false } });
    this.flushDrafts();
    await this.waitForWrites();
    if (this.stopped) return;
    const currentDraft = this.current.localAskDrafts[draftKey(runId, findingId)] ??
      this.current.workspace?.personal[runId]?.ask_drafts?.[findingId];
    if (this.current.status !== "saved" || this.current.pending ||
        (currentDraft !== undefined && currentDraft !== question)) {
      this.emit({ askAction: { ...target, ...idleReviewAction(),
        error: "Question was not sent. Confirm pending changes and your latest question first." } });
      return;
    }
    this.pendingAskAttempt = { revision: this.current.workspace!.revision, requestId, modelId,
      runId, findingId, question, includeHistory, reasoningEffort };
    await this.sendAskAttempt();
  }

  private async sendAskAttempt() {
    const attempt = this.pendingAskAttempt;
    if (!attempt || this.stopped) return;
    const target = { runId: attempt.runId, findingId: attempt.findingId };
    this.emit({ askAction: { ...target, status: "generating", error: null, canRetryRequest: false } });
    try {
      const workspace = await this.transport.ask(this.documentId, attempt.revision, attempt.requestId,
        attempt.modelId, attempt.runId, attempt.findingId, attempt.question, attempt.includeHistory, attempt.reasoningEffort);
      if (this.stopped) return;
      this.pendingAskAttempt = null;
      this.acceptReviewResponse(workspace);
    } catch (error) {
      const rejected = isPreflightRejection(error);
      if (this.pendingAskAttempt) this.pendingAskAttempt.rejected = rejected;
      this.emit({ askAction: { ...target, status: "uncertain", canRetryRequest: false, requestRejected: rejected,
        error: rejected ? `Question was not sent. ${safeMessage(error)} Refresh saved state before starting again.`
          : `${safeMessage(error)} The question was not retried. Refresh saved state to check whether it was recorded.` } });
    }
  }

  async retryAskRequest() {
    if (this.current.askAction.status !== "uncertain" || !this.current.askAction.canRetryRequest || this.sending) return;
    await this.sendAskAttempt();
  }

  async interruptAsk(turnId: string) {
    const turn = this.current.workspace?.ask_turns?.find(item => item.id === turnId);
    if (this.stopped || this.sending || paidActionBusy(this.current) || this.current.status !== "saved" ||
        this.current.pending || turn?.status !== "processing") return;
    this.emit({ askAction: { status: "interrupting", error: null, canRetryRequest: false,
      runId: turn.run_id, findingId: turn.finding_id } });
    try {
      const workspace = await this.transport.interruptAsk(this.documentId, this.current.workspace!.revision, turnId);
      if (!this.stopped) this.acceptReviewResponse(workspace);
    } catch (error) {
      this.emit({ status: "failed", error: "The interrupted Ask state could not be confirmed. Refresh saved state.",
        askAction: { ...idleReviewAction(), runId: turn.run_id, findingId: turn.finding_id,
          error: `${safeMessage(error)} Refresh saved state before trying again.` } });
    }
  }

  async interruptRun(runId: string) {
    if (this.stopped || this.sending || paidActionBusy(this.current) ||
        !this.current.workspace?.runs.some(run => run.id === runId && runStatus(run) === "processing")) return;
    this.emit({ reviewAction: { status: "interrupting", error: null, canRetryRequest: false } });
    try {
      const workspace = await this.transport.interrupt(this.documentId, this.current.workspace.revision, runId);
      if (!this.stopped) this.acceptReviewResponse(workspace);
    } catch (error) {
      this.emit({ status: "failed", error: "The interrupted state could not be confirmed. Refresh saved state.",
        reviewAction: { ...idleReviewAction(), error: `${safeMessage(error)} Refresh saved state before trying again.` } });
    }
  }

  private acceptReviewResponse(workspace: ReviewWorkspaceResponse) {
    // Preserve edits made while a long request was running. Reapply only explicitly.
    this.emit({ workspace, status: "loading", error: null, reviewAction: idleReviewAction(), askAction: idleReviewAction() });
    this.flushDrafts();
    this.emit({ status: this.queue.length ? "review" : "saved" });
  }

  flushDrafts() {
    for (const [key, timer] of this.timers) {
      clearTimeout(timer);
      this.timers.delete(key);
      const [runId, findingId] = JSON.parse(key) as [string, string];
      this.enqueue({ type: "set_draft", run_id: runId, finding_id: findingId, text: this.current.localDrafts[key] });
    }
    for (const [key, timer] of this.askTimers) {
      clearTimeout(timer);
      this.askTimers.delete(key);
      const [runId, findingId] = JSON.parse(key) as [string, string];
      this.enqueue({ type: "set_ask_draft", run_id: runId, finding_id: findingId, text: this.current.localAskDrafts[key] });
    }
  }

  dispose() {
    this.stopped = true;
    this.generation += 1;
    this.timers.forEach(timer => clearTimeout(timer));
    this.timers.clear();
    this.askTimers.forEach(timer => clearTimeout(timer));
    this.askTimers.clear();
    this.listeners.clear();
    this.pendingWaiters.forEach(listener => listener());
  }
}

function safeMessage(error: unknown) {
  return error instanceof Error ? error.message : "The workspace could not be saved. Your local wording is still here.";
}

function isPreflightRejection(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error &&
    ["REQUEST_ID_CONFLICT", "REVIEW_RUN_LIMIT", "REVIEW_ALREADY_PROCESSING", "REVIEW_MODEL_CHANGED", "REVIEW_REASONING_CHANGED",
      "REVIEW_INPUT_REJECTED", "API_KEY_REQUIRED", "REVISION_CONFLICT", "ASK_INPUT_REJECTED",
      "INVALID_QUESTION", "ASK_REVIEW_UNAVAILABLE", "ASK_TURN_LIMIT", "ASK_ALREADY_PROCESSING", "ASK_STORAGE_LIMIT"].includes(String(error.code));
}
