/** Physical PDF pages are one-based outside the renderer. No text matching occurs here. */
export interface PdfNavigationRequest {
  requestId: number;
  pageNumber: number;
  /** Saved resume anchor, not a fresh citation click; a browser bookmark wins. */
  restore?: boolean;
}

export type PdfNavigationResult = { pageIndex: number } | { error: string } | null;

export function pdfSourceKey(documentId: string, sourceRevisionId?: string): string {
  return JSON.stringify([documentId, sourceRevisionId ?? null]);
}

export function pdfPageIndex(pageNumber: number, pageCount: number): number | null {
  return Number.isInteger(pageNumber) && Number.isInteger(pageCount) &&
    pageNumber >= 1 && pageNumber <= pageCount ? pageNumber - 1 : null;
}

/** One load session. Replacing it makes callbacks from older viewers ignorable. */
export class PdfPageNavigationSession {
  readonly sourceKey: string;
  readonly viewMode: string;
  pageNumber = 1;
  private pageCount: number | null = null;
  private pending: PdfNavigationRequest | null = null;
  private lastRequest: PdfNavigationRequest | null = null;
  private awaitingPage: number | null = null;

  constructor(sourceKey: string, viewMode: string, previous?: PdfPageNavigationSession | null) {
    this.sourceKey = sourceKey;
    this.viewMode = viewMode;
    if (previous?.sourceKey === sourceKey) {
      this.pageNumber = previous.pageNumber;
      this.lastRequest = previous.lastRequest;
      this.pending = previous.pending ?? (previous.awaitingPage != null ? previous.lastRequest : null);
    }
  }

  request(request: PdfNavigationRequest): PdfNavigationResult {
    if (this.lastRequest?.requestId === request.requestId && this.lastRequest.pageNumber === request.pageNumber) {
      return null;
    }
    this.lastRequest = { ...request };
    this.pending = { ...request };
    return this.applyPending();
  }

  loaded(pageCount: number): PdfNavigationResult {
    if (!Number.isInteger(pageCount) || pageCount < 1) {
      return { error: "The PDF page count is unavailable. The requested page could not be opened." };
    }
    this.pageCount = pageCount;
    return this.applyPending();
  }

  pageChanged(pageIndex: number): number | null {
    if (this.pageCount == null || !Number.isInteger(pageIndex) || pdfPageIndex(pageIndex + 1, this.pageCount) == null) {
      return null;
    }
    const pageNumber = pageIndex + 1;
    // A viewer can emit its initial page before a queued jump is displayed.
    if (this.awaitingPage != null && pageNumber !== this.awaitingPage) {
      return null;
    }
    this.awaitingPage = null;
    this.pageNumber = pageNumber;
    return pageNumber;
  }

  navigationFailed(): void {
    this.awaitingPage = null;
  }

  clearRequest(): void {
    this.pending = null;
    this.lastRequest = null;
    this.awaitingPage = null;
  }

  private applyPending(): PdfNavigationResult {
    if (!this.pending || this.pageCount == null) return null;
    const request = this.pending;
    this.pending = null;
    const pageIndex = pdfPageIndex(request.pageNumber, this.pageCount);
    if (pageIndex == null) {
      this.awaitingPage = null;
      return { error: "The requested source page is outside this PDF. No substitute page was selected." };
    }
    this.awaitingPage = this.pageNumber === request.pageNumber ? null : request.pageNumber;
    return { pageIndex };
  }
}

/** Defense in depth: PDF-supplied values must not enable dynamic code generation. */
export function securePdfDocumentOptions<T extends object>(options: T): T & { isEvalSupported: false } {
  return { ...options, isEvalSupported: false };
}
