import type {
  DocumentSourceResponse, ReviewBrief, ReviewEvidence, ReviewPersonalState,
  ReviewWorkspaceOperation, ReviewWorkspaceResponse,
} from "@clauseiq/shared-types";
import type { ReviewWorkspaceTransport } from "@/lib/reviewWorkspaceApi";

export const emptyPersonal = (): ReviewPersonalState => ({
  drafts: {}, saved_questions: {}, markers: {}, opened_finding_ids: [],
  position: { view: "overview", finding_id: null, evidence_span_id: null },
});
export const draftKey = (runId: string, findingId: string) => JSON.stringify([runId, findingId]);
export const sameBrief = (a: ReviewBrief, b: ReviewBrief) =>
  a.perspective === b.perspective && a.role === b.role && a.priorities === b.priorities;

export function evidenceMatches(evidence: ReviewEvidence, source: DocumentSourceResponse | null): boolean {
  if (!source || evidence.source_revision_id !== source.source_revision_id) return false;
  const page = source.source_extraction?.pages.find(item => item.page_number === evidence.page_number);
  const span = page?.spans.find(item => item.id === evidence.span_id);
  return !!page && !!span && span.text === evidence.quote &&
    Array.from(page.text).slice(span.start, span.end).join("") === evidence.quote;
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
}

export function hasUnconfirmedChanges(state: WorkspaceSaveState): boolean {
  return state.pending > 0 || ["loading", "failed", "conflict", "review"].includes(state.status) ||
    !!(state.briefDraft && state.workspace && !sameBrief(state.briefDraft, state.workspace.brief));
}

/** Serial writes use confirmed revisions only. Conflicts never auto-rebase edits. */
export class ReviewWorkspaceController {
  private current: WorkspaceSaveState = {
    workspace: null, status: "loading", error: null, pending: 0, localDrafts: {}, briefDraft: null,
  };
  private listeners = new Set<() => void>();
  private queue: QueueEntry[] = [];
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  private sending = false;
  private stopped = false;
  private generation = 0;

  constructor(private documentId: string, private transport: ReviewWorkspaceTransport, private debounceMs = 500) {}
  getSnapshot = () => this.current;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => this.listeners.delete(listener); };

  private emit(values: Partial<WorkspaceSaveState> = {}) {
    if (this.stopped) return;
    this.current = { ...this.current, ...values, pending: this.queue.length + this.timers.size };
    this.listeners.forEach(listener => listener());
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
    if (this.sending) return;
    this.emit({ status: "loading", error: null });
    this.flushDrafts();
    const generation = ++this.generation;
    try {
      const workspace = await this.transport.load(this.documentId);
      if (this.stopped || generation !== this.generation) return;
      this.emit({ workspace, status: this.queue.length ? "review" : "saved", error: null });
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
  }
}

function safeMessage(error: unknown) {
  return error instanceof Error ? error.message : "The workspace could not be saved. Your local wording is still here.";
}
