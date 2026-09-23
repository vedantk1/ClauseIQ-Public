/** Browser-only reading preferences. Never persist source text or review content. */
export type PdfZoom = number | "page-width" | "page-fit";
export interface PdfLocation { pageNumber: number; left: number; top: number }
export interface ReaderViewState {
  version: 1;
  pageNumber: number;
  location?: PdfLocation;
  zoom: PdfZoom;
  mode: "single" | "continuous";
}
const memory = new Map<string, ReaderViewState>();
const prefix = "clauseiq.reader.v1:";
export const defaultReaderView: ReaderViewState = { version: 1, pageNumber: 1, zoom: 1, mode: "continuous" };

export function validReaderView(value: unknown): ReaderViewState | null {
  if (!value || typeof value !== "object") return null;
  const v = value as ReaderViewState;
  if (v.version !== 1 || !Number.isInteger(v.pageNumber) || v.pageNumber < 1 ||
      !["single", "continuous"].includes(v.mode) ||
      !(v.zoom === "page-width" || v.zoom === "page-fit" || typeof v.zoom === "number" && Number.isFinite(v.zoom) && v.zoom >= .5 && v.zoom <= 3)) return null;
  const location = v.location && v.location.pageNumber === v.pageNumber &&
    Number.isFinite(v.location.left) && Number.isFinite(v.location.top)
    ? { pageNumber: v.pageNumber, left: v.location.left, top: v.location.top } : undefined;
  return { version: 1, pageNumber: v.pageNumber, zoom: v.zoom, mode: v.mode, ...(location ? { location } : {}) };
}
function storage(): Storage | undefined {
  try { return typeof window === "undefined" ? undefined : window.localStorage; } catch { return undefined; }
}
export function readReaderView(key: string): ReaderViewState | null {
  if (memory.has(key)) return memory.get(key)!;
  try {
    const value = validReaderView(JSON.parse(storage()?.getItem(prefix + key) || "null"));
    if (value) memory.set(key, value);
    return value;
  } catch { return null; }
}
export function rememberReaderView(key: string, value: ReaderViewState, persist = true): void {
  const clean = validReaderView(value);
  if (!clean) return;
  memory.set(key, clean);
  if (persist) try { storage()?.setItem(prefix + key, JSON.stringify(clean)); } catch { /* Reading still works in memory. */ }
}
