import type {
  DocumentSourceResponse, ReviewBrief, ReviewEvidence, ReviewPersonalState, ReviewPosition,
  ReviewRun, ReviewWorkspaceOperation, ReviewWorkspaceResponse,
} from "@clauseiq/shared-types";
import type { ReviewWorkspaceTransport } from "@/lib/reviewWorkspaceApi";

export const emptyPersonal = (): ReviewPersonalState => ({
  drafts: {}, saved_questions: {}, markers: {}, opened_finding_ids: [],
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
export type ReviewActionState = {
  status: "idle" | "preparing" | "generating" | "uncertain" | "interrupting";
  error: string | null;
  canRetryRequest: boolean;
  requestRejected?: boolean;
};
const idleReviewAction = (): ReviewActionState => ({ status: "idle", error: null, canRetryRequest: false });

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
export type SaveStatus = "loading" | "saved" | "saving" | "failed" | "conflict" | "review";
export interface WorkspaceSaveState {
  workspace: ReviewWorkspaceResponse | null;
  status: SaveStatus;
  error: string | null;
  pending: number;
  localDrafts: Record<string, string>;
  briefDraft: ReviewBrief | null;
  reviewAction: ReviewActionState;
}

export function hasUnconfirmedChanges(state: WorkspaceSaveState): boolean {
  return state.pending > 0 || ["preparing", "generating", "uncertain", "interrupting"].includes(state.reviewAction?.status) ||
    ["loading", "failed", "conflict", "review"].includes(state.status) ||
    !!(state.briefDraft && state.workspace && !sameBrief(state.briefDraft, state.workspace.brief));
}

/** Serial writes use confirmed revisions only. Conflicts never auto-rebase edits. */
export class ReviewWorkspaceController {
  private current: WorkspaceSaveState = {
    workspace: null, status: "loading", error: null, pending: 0, localDrafts: {}, briefDraft: null,
    reviewAction: idleReviewAction(),
  };
  private listeners = new Set<() => void>();
  private queue: QueueEntry[] = [];
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  private sending = false;
  private stopped = false;
  private generation = 0;
  private pendingAttempt: { revision: number; requestId: string; modelId: string; rejected?: boolean } | null = null;
  private pendingWaiters = new Set<() => void>();

  constructor(private documentId: string, private transport: ReviewWorkspaceTransport, private debounceMs = 500) {}
  getSnapshot = () => this.current;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };

  private emit(values: Partial<WorkspaceSaveState> = {}) {
    if (this.stopped) return;
    this.current = { ...this.current, ...values, pending: this.queue.length + this.timers.size };
    this.listeners.forEach(listener => listener());
    this.pendingWaiters.forEach(listener => listener());
  }

  async load() {
    const generation = ++this.generation;
    try {
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
    if (!this.current.workspace?.fixture_available || this.queue.some(item => item.key === "fixture")) return;
    this.queue.push({ key: "fixture", operation: null });
    this.emit();
    void this.drain();
  }

  private async drain() {
    if (this.stopped || this.sending || !this.current.workspace || !this.queue.length ||
        ["generating", "uncertain", "interrupting"].includes(this.current.reviewAction.status) ||
        ["failed", "conflict", "review", "loading"].includes(this.current.status)) return;
    this.sending = true;
    const entry = this.queue[0];
    const revision = this.current.workspace.revision;
    this.emit({ status: "saving", error: null });
    try {
      const workspace = entry.operation
        ? await this.transport.update(this.documentId, revision, entry.operation)
        : await this.transport.fixture(this.documentId, revision);
      if (this.stopped) return;
      this.queue.shift();
      const localDrafts = { ...this.current.localDrafts };
      const operation = entry.operation;
      if (operation?.type === "set_draft") {
        const key = draftKey(operation.run_id, operation.finding_id);
        if (localDrafts[key] === operation.text) delete localDrafts[key];
      }
      const briefDraft = this.current.briefDraft && sameBrief(this.current.briefDraft, workspace.brief)
        ? null : this.current.briefDraft;
      this.emit({ workspace, localDrafts, briefDraft, status: "saved" });
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
    if (this.sending || ["preparing", "generating", "interrupting"].includes(this.current.reviewAction.status)) return;
    this.emit({ status: "loading", error: null });
    this.flushDrafts();
    const generation = ++this.generation;
    try {
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
      this.emit({ workspace, status: this.queue.length ? "review" : "saved", error: null, reviewAction });
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
  async startReview(modelId: string, requestId: string) {
    if (this.stopped || this.current.reviewAction.status !== "idle" || !this.current.workspace ||
        this.current.workspace.runs.some(run => runStatus(run) === "processing") ||
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
    this.pendingAttempt = { revision: this.current.workspace!.revision, requestId, modelId };
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
      const workspace = await this.transport.generate(this.documentId, attempt.revision, attempt.requestId, attempt.modelId);
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

  async interruptRun(runId: string) {
    if (this.stopped || this.sending || this.current.reviewAction.status !== "idle" ||
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
    this.emit({ workspace, status: "loading", error: null, reviewAction: idleReviewAction() });
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
  }

  dispose() {
    this.stopped = true;
    this.generation += 1;
    this.timers.forEach(timer => clearTimeout(timer));
    this.timers.clear();
    this.listeners.clear();
    this.pendingWaiters.forEach(listener => listener());
  }
}

function safeMessage(error: unknown) {
  return error instanceof Error ? error.message : "The workspace could not be saved. Your local wording is still here.";
}

function isPreflightRejection(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error &&
    ["REQUEST_ID_CONFLICT", "REVIEW_RUN_LIMIT", "REVIEW_ALREADY_PROCESSING", "REVIEW_MODEL_CHANGED",
      "REVIEW_INPUT_REJECTED", "API_KEY_REQUIRED", "REVISION_CONFLICT"].includes(String(error.code));
}
