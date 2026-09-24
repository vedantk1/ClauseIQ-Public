import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import ts from "typescript";

function compile(path) {
  return ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText;
}

const helpers = {};
vm.runInNewContext(compile("../src/lib/pdfPageNavigation.ts"), { exports: helpers });
const { PdfPageNavigationSession, pdfPageIndex, pdfSourceKey, securePdfDocumentOptions } = helpers;

test("physical PDF pages use validated one-based to zero-based conversion", () => {
  assert.equal(pdfPageIndex(1, 25), 0);
  assert.equal(pdfPageIndex(25, 25), 24);
  for (const page of [0, -1, 26, 1.5, NaN, Infinity]) assert.equal(pdfPageIndex(page, 25), null);
  for (const count of [0, -1, 1.5, NaN]) assert.equal(pdfPageIndex(1, count), null);
});

test("browser bookmark restores page, coordinates, zoom and mode; fresh source jumps take precedence", async () => {
  const bookmark = { version: 1, pageNumber: 24, location: { pageNumber: 24, left: 0, top: 345 }, zoom: "page-fit", mode: "single" };
  for (const restore of [true, false]) {
    const remembered = [];
    const h = viewerHarness({ bookmark, remembered });
    h.render({ documentId: "doc", sourceRevisionId: "rev", rememberView: true, navigationRequest: { requestId: 1, pageNumber: 15, restore } });
    await h.flush(); h.render();
    assert.equal(h.viewer().initialPage, 23);
    assert.equal(h.viewer().initialLocation, bookmark.location);
    assert.equal(h.viewer().scale, "page-fit"); assert.equal(h.viewer().viewMode, "single");
    h.viewer().onReady(h.controller, 25);
    assert.deepEqual(h.jumps, restore ? [] : [14]);
    const pageNumber = restore ? 24 : 15;
    h.viewer().onPageChange(pageNumber - 1);
    h.viewer().onViewChange({ pageNumber, left: 0, top: 300 }, .8);
    h.unmount();
    assert.equal(remembered.at(-1)[1].pageNumber, pageNumber);
    assert.equal(remembered.at(-1)[1].location.top, 300);
    assert.equal(remembered.at(-1)[2], undefined, "unmount flushes the latest preference to durable storage");
  }
});

test("a resume anchor remains available without a browser bookmark and invalid citations remain errors", async () => {
  const errors = [];
  const h = viewerHarness();
  const props = { documentId: "doc", sourceRevisionId: "rev", rememberView: true, onNavigationError: message => errors.push(message) };
  h.render({ ...props, navigationRequest: { requestId: 1, pageNumber: 15, restore: true } });
  await h.flush(); h.render(); h.viewer().onReady(h.controller, 25);
  assert.deepEqual(h.jumps, [14]);
  h.render({ ...props, navigationRequest: { requestId: 2, pageNumber: 40 } });
  await h.flush();
  assert.deepEqual(h.jumps, [14]); assert.match(errors[0], /outside this PDF/);
  h.unmount();
});

test("only the latest request is applied after the PDF loads", () => {
  const session = new PdfPageNavigationSession("source-1", "continuous");
  assert.equal(session.request({ requestId: 1, pageNumber: 20 }), null);
  assert.equal(session.request({ requestId: 2, pageNumber: 25 }), null);
  assert.equal(session.pageChanged(0), null);
  assert.equal(session.loaded(25).pageIndex, 24);
  assert.equal(session.pageChanged(0), null); // Initial page must not overwrite the requested position.
  assert.equal(session.pageChanged(24), 25);
  assert.equal(session.pageNumber, 25);
});

test("same request is idempotent while a new request ID can revisit the same evidence", () => {
  const session = new PdfPageNavigationSession("source-1", "continuous");
  session.loaded(25);
  assert.equal(session.request({ requestId: 1, pageNumber: 25 }).pageIndex, 24);
  assert.equal(session.pageChanged(24), 25);
  assert.equal(session.request({ requestId: 1, pageNumber: 25 }), null);
  assert.equal(session.pageChanged(8), 9);
  assert.equal(session.request({ requestId: 2, pageNumber: 25 }).pageIndex, 24);
  assert.equal(session.pageChanged(24), 25);
  assert.equal(session.request({ requestId: 3, pageNumber: 25 }).pageIndex, 24);
  assert.equal(session.pageChanged(8), 9); // Same-page jumps need not emit another page event.
});

test("mode changes preserve reading position but source or revision changes reset it", () => {
  const source = pdfSourceKey("doc-1", "revision-1");
  const first = new PdfPageNavigationSession(source, "continuous");
  first.loaded(25);
  first.pageChanged(8);
  const single = new PdfPageNavigationSession(source, "single", first);
  assert.equal(single.pageNumber, 9);
  assert.equal(single.pageChanged(8), null);
  single.loaded(25);
  assert.equal(single.pageChanged(8), 9);
  assert.equal(new PdfPageNavigationSession(pdfSourceKey("doc-1", "revision-2"), "single", single).pageNumber, 1);
  assert.equal(new PdfPageNavigationSession(pdfSourceKey("doc-2", "revision-1"), "single", single).pageNumber, 1);
});

test("invalid or removed requests never choose a substitute page", () => {
  const session = new PdfPageNavigationSession("source-1", "continuous");
  session.request({ requestId: 1, pageNumber: 40 });
  assert.match(session.loaded(25).error, /outside this PDF/);
  assert.equal(session.pageNumber, 1);
  const pending = new PdfPageNavigationSession("source-1", "continuous");
  pending.request({ requestId: 1, pageNumber: 25 });
  pending.clearRequest();
  assert.equal(pending.loaded(25), null);
  assert.equal(pending.pageChanged(0), 1);
});

test("PDF.js advisory mitigation overrides unsafe input without mutating it", () => {
  const options = { isEvalSupported: true, url: "blob:synthetic" };
  const safe = securePdfDocumentOptions(options);
  assert.equal(safe.isEvalSupported, false);
  assert.equal(safe.url, options.url);
  assert.equal(options.isEvalSupported, true);
});

function findElement(element, predicate) {
  if (!element || typeof element !== "object") return null;
  if (predicate(element)) return element;
  for (const child of React.Children.toArray(element.props?.children)) {
    const found = findElement(child, predicate);
    if (found) return found;
  }
  return null;
}

function viewerHarness({ fetchPdf, bookmark = null, remembered = [] } = {}) {
  const slots = [];
  let cursor = 0;
  let effects = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
  const hooks = {
    ...React,
    useState(initial) {
      const index = cursor++;
      slots[index] ??= { value: typeof initial === "function" ? initial() : initial };
      return [slots[index].value, (next) => { slots[index].value = typeof next === "function" ? next(slots[index].value) : next; }];
    },
    useRef(current) {
      const index = cursor++;
      slots[index] ??= { current };
      return slots[index];
    },
    useMemo(factory, deps) {
      const index = cursor++;
      if (!same(slots[index]?.deps, deps)) slots[index] = { deps, value: factory() };
      return slots[index].value;
    },
    useCallback(callback, deps) { return hooks.useMemo(() => callback, deps); },
    useEffect(effect, deps) {
      const index = cursor++;
      if (!same(slots[index]?.deps, deps)) {
        effects.push(() => {
          slots[index]?.cleanup?.();
          slots[index] = { deps, cleanup: effect() };
        });
      }
    },
  };
  const jumps = [];
  const requests = [];
  const searches = [];
  const createdUrls = [];
  const revokedUrls = [];
  const matches = [];
  const PdfJsRenderer = () => null;
  const Button = () => null;
  const empty = () => null;
  const controller = {
    jumpToPage: (index) => jumps.push(index),
    search: (query) => searches.push(query),
    nextMatch: () => matches.push("next"),
    previousMatch: () => matches.push("previous"),
  };
  const imports = {
    react: hooks,
    "./pdf/PdfJsRenderer": PdfJsRenderer,
    "./Card": empty, "./Button": Button, "./DropdownMenu": empty,
    "@/config/config": { apiUrl: "http://127.0.0.1:8000" },
    "@/lib/api": { LOCAL_API_HEADERS: { "X-ClauseIQ-Local": "1" } },
    "@/utils/pdfHighlightUtils": { getRiskHighlightColor: () => "transparent", getRiskBorderColor: () => "transparent" },
    "@/lib/pdfPageNavigation": helpers,
    "@/lib/readerViewState": { readReaderView: () => bookmark, rememberReaderView: (...args) => remembered.push(args) },
  };
  const exports = {};
  vm.runInNewContext(compile("../src/components/PDFViewer.tsx"), {
    exports, console: { error() {}, warn() {} }, AbortController, setTimeout, clearTimeout,
    window: { addEventListener() {}, removeEventListener() {} },
    URL: {
      createObjectURL() { const url = `blob:synthetic-${createdUrls.length + 1}`; createdUrls.push(url); return url; },
      revokeObjectURL: (url) => revokedUrls.push(url),
    },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return fetchPdf ? fetchPdf(url, options) : { ok: true, blob: async () => ({}) };
    },
    require(name) {
      if (name.endsWith(".module.css")) return new Proxy({}, { get: (_, key) => key === "__esModule" ? false : `pdf-${String(key)}` });
      if (name.endsWith(".css")) return {};
      assert.ok(name in imports, `Unexpected dependency: ${name}`);
      return imports[name];
    },
  });
  let props;
  let tree;
  return {
    jumps, requests, searches, createdUrls, revokedUrls, matches, controller,
    render(nextProps = props) { props = nextProps; cursor = 0; tree = exports.default(props); return tree; },
    async flush() { const pending = effects; effects = []; pending.forEach((effect) => effect()); for (let i = 0; i < 6; i += 1) await Promise.resolve(); },
    viewer() { return findElement(tree, (item) => item.type === PdfJsRenderer)?.props; },
    text() { return JSON.stringify(tree); },
    unmount() { slots.forEach((slot) => slot.cleanup?.()); },
    toggleMode() { const input = findElement(tree, item => item.type === "select" && item.props["aria-label"] === "PDF reading mode"); input.props.onChange({ target: { value: input.props.value === "continuous" ? "single" : "continuous" } }); },
    setZoom(value) { findElement(tree, item => item.type === "select" && item.props["aria-label"] === "PDF zoom").props.onChange({ target: { value: String(value) } }); },
    zoomIn() { findElement(tree, (item) => item.type === Button && item.props.title === "Zoom in").props.onClick(); },
    click(title) { findElement(tree, (item) => item.type === Button && item.props.title === title).props.onClick(); },
    clickText(text) { findElement(tree, (item) => item.type === Button && item.props.children === text).props.onClick(); },
    pageInput() { return findElement(tree, item => item.type === "input" && item.props["aria-label"] === "PDF page number")?.props; },
    enterPage(value) { this.pageInput().onChange({ target: { value } }); },
    submitPage() { findElement(tree, item => item.type === "form").props.onSubmit({ preventDefault() {} }); },
  };
}

test("component waits for load, uses latest target, fences old callbacks and preserves mode position", async () => {
  const harness = viewerHarness();
  const pages = [];
  const errors = [];
  const props = {
    documentId: "doc-1", sourceRevisionId: "revision-1",
    navigationRequest: { requestId: 1, pageNumber: 20 },
    onPageChange: (page) => pages.push(page), onNavigationError: (message) => errors.push(message),
    highlightClause: { id: "legacy-clause", text: "Do not fuzzy match new evidence" },
  };
  harness.render(props);
  await harness.flush();
  harness.render({ ...props, navigationRequest: { requestId: 2, pageNumber: 25 } });
  const first = harness.viewer();
  assert.ok(first);
  assert.equal(first.scale, 1);
  assert.equal(first.viewMode, "continuous");
  assert.deepEqual(harness.jumps, []);
  first.onReady(harness.controller, 25);
  assert.deepEqual(harness.jumps, [24]);
  await harness.flush();
  first.onPageChange(0);
  first.onPageChange(24);
  assert.deepEqual(pages, [25]);
  assert.ok(harness.searches.every((query) => !query)); // Source evidence must not become a text search.
  assert.equal(harness.requests[0].options.headers["X-ClauseIQ-Local"], "1");

  harness.zoomIn();
  harness.render();
  assert.equal(harness.viewer().scale, 1.2);
  harness.toggleMode();
  harness.render();
  await harness.flush();
  const single = harness.viewer();
  assert.equal(single.initialPage, 24);
  assert.equal(single.scale, 1.2);
  assert.equal(single.viewMode, "single");
  single.onReady(harness.controller, 25);
  first.onPageChange(2); // Callback from the previous mode.
  first.onError("Old renderer error");
  assert.deepEqual(pages, [25]);
  harness.render();
  assert.ok(harness.viewer(), "An obsolete renderer must not replace the active viewer with an error");
  assert.equal(harness.requests.length, 1, "Scale and mode changes reuse the fetched source");

  harness.render({ ...props, sourceRevisionId: "revision-2", navigationRequest: { requestId: 3, pageNumber: 30 } });
  first.onReady(harness.controller, 25); // Callback from the previous source.
  assert.deepEqual(harness.jumps, [24]);
  await harness.flush();
  harness.render();
  await harness.flush();
  const replacement = harness.viewer();
  assert.equal(replacement.initialPage, 0);
  replacement.onReady(harness.controller, 25);
  assert.equal(errors.length, 1);
  assert.match(errors[0], /outside this PDF/);
  assert.deepEqual(harness.jumps, [24]);
});

test("legacy viewer uses exact clause search without automatic fuzzy substitutes", async () => {
  const harness = viewerHarness();
  const completions = [];
  const clause = { id: "legacy-clause", text: "Exact source clause text" };
  harness.render({ documentId: "legacy-doc", highlightClause: clause, onHighlightComplete: (result) => completions.push(result) });
  await harness.flush();
  harness.render();
  const viewer = harness.viewer();
  assert.equal(viewer.scale, 1);
  viewer.onReady(harness.controller, 25);
  harness.render();
  await harness.flush();
  assert.ok(harness.searches.includes(clause.text));
  assert.ok(harness.searches.every((query) => !query || query === clause.text));
  viewer.onSearchChange({ current: 0, total: 0, pending: false });
  harness.render();
  await harness.flush();
  assert.equal(completions.at(-1)?.found, false);
  assert.deepEqual(harness.jumps, []);
});

test("explicit physical-page navigation does not search even before source metadata is available", async () => {
  const harness = viewerHarness();
  harness.render({
    documentId: "source-doc", navigationRequest: { requestId: 1, pageNumber: 25 },
    highlightClause: { id: "legacy-clause", text: "Must not become the source-page target" },
    highlightText: "Must not become a fallback target either",
  });
  await harness.flush();
  harness.render();
  const viewer = harness.viewer();
  viewer.onReady(harness.controller, 25);
  harness.render();
  await harness.flush();
  assert.deepEqual(harness.jumps, [24]);
  assert.ok(harness.searches.every((query) => !query));
});

test("authenticated PDF fetch is cancelled and blob URLs are revoked when a source changes or unmounts", async () => {
  const harness = viewerHarness();
  harness.render({ documentId: "doc-1", sourceRevisionId: "revision-1" });
  await harness.flush();
  harness.render();
  assert.equal(harness.viewer().fileUrl, "blob:synthetic-1");
  assert.equal(harness.requests[0].url, "http://127.0.0.1:8000/api/v1/documents/doc-1/pdf");
  assert.equal(harness.requests[0].options.headers["X-ClauseIQ-Local"], "1");
  harness.render({ documentId: "doc-1", sourceRevisionId: "revision-2" });
  assert.equal(harness.viewer(), undefined, "Old source must not render under the next revision");
  await harness.flush();
  harness.render();
  assert.equal(harness.requests[0].options.signal.aborted, true);
  assert.deepEqual(harness.revokedUrls, ["blob:synthetic-1"]);
  assert.equal(harness.viewer().fileUrl, "blob:synthetic-2");
  harness.unmount();
  assert.equal(harness.requests[1].options.signal.aborted, true);
  assert.deepEqual(harness.revokedUrls, ["blob:synthetic-1", "blob:synthetic-2"]);
});

test("a late source response cannot create a blob URL after cancellation", async () => {
  let finishFirst;
  const firstResponse = new Promise((resolve) => { finishFirst = resolve; });
  const harness = viewerHarness({ fetchPdf: (url) => url.includes("doc-1/")
    ? firstResponse : { ok: true, blob: async () => ({}) } });
  harness.render({ documentId: "doc-1" });
  await harness.flush();
  harness.render({ documentId: "doc-2" });
  await harness.flush();
  finishFirst({ ok: true, blob: async () => ({}) });
  await harness.flush();
  harness.render();
  assert.deepEqual(harness.createdUrls, ["blob:synthetic-1"]);
  assert.equal(harness.viewer().fileUrl, "blob:synthetic-1");
});

test("PDF fetch failures expose a safe message without raw server or network detail", async () => {
  const harness = viewerHarness({ fetchPdf: () => { throw new Error("sensitive internal response"); } });
  harness.render({ documentId: "doc-1" });
  await harness.flush();
  harness.render();
  assert.equal(harness.viewer(), undefined);
  assert.match(harness.text(), /[Ff]ailed to load PDF/);
  assert.doesNotMatch(harness.text(), /sensitive internal response/);
});

test("retry keeps the reading position but ignores callbacks from the failed renderer", async () => {
  const harness = viewerHarness();
  const pages = [];
  harness.render({ documentId: "doc-1", onPageChange: (page) => pages.push(page) });
  await harness.flush();
  harness.render();
  const failed = harness.viewer();
  failed.onReady(harness.controller, 25);
  failed.onPageChange(8);
  failed.onError("Unable to render this PDF");
  harness.render();
  harness.clickText("Retry PDF");
  harness.render();
  await harness.flush();
  harness.render();
  const replacement = harness.viewer();
  assert.equal(replacement.initialPage, 8);
  replacement.onReady(harness.controller, 25);
  failed.onPageChange(2);
  failed.onReady(harness.controller, 2);
  failed.onError("Late error from the failed renderer");
  harness.render();
  assert.deepEqual(pages, [9]);
  assert.ok(harness.viewer(), "An obsolete render attempt must not replace a successful retry with an error");
  assert.equal(harness.viewer().initialPage, 8);
});

test("page and zoom controls stay bounded and do not refetch the source", async () => {
  const harness = viewerHarness();
  harness.render({ documentId: "doc-1" });
  await harness.flush();
  harness.render();
  const viewer = harness.viewer();
  viewer.onReady(harness.controller, 3);
  viewer.onPageChange(0);
  harness.render();
  harness.click("Previous page");
  assert.deepEqual(harness.jumps, []);
  harness.click("Next page");
  assert.deepEqual(harness.jumps, [1]);
  viewer.onPageChange(2);
  harness.render();
  harness.click("Next page");
  assert.deepEqual(harness.jumps, [1]);
  for (let index = 0; index < 20; index += 1) { harness.zoomIn(); harness.render(); }
  assert.equal(harness.viewer().scale, 3);
  for (let index = 0; index < 20; index += 1) { harness.click("Zoom out"); harness.render(); }
  assert.equal(harness.viewer().scale, 0.5);
  harness.setZoom(1);
  harness.render();
  assert.equal(harness.viewer().scale, 1);
  assert.equal(harness.requests.length, 1);
});

test("compact reader preserves the full-height canvas and groups reading controls", async () => {
  const harness = viewerHarness();
  const tree = harness.render({ documentId: "doc-1", fileName: "synthetic.pdf" });
  assert.equal(tree.type, "section");
  assert.equal(tree.props["aria-label"], "PDF reader: synthetic.pdf");
  assert.match(tree.props.className, /pdf-reader/);
  assert.ok(findElement(tree, item => item.props?.className === "pdf-canvas"));
  assert.ok(findElement(tree, item => item.props?.["aria-label"] === "PDF reading controls"));
  assert.ok(findElement(tree, item => item.props?.role === "group" && item.props["aria-label"] === "Page navigation"));
  assert.ok(findElement(tree, item => item.props?.role === "group" && item.props["aria-label"] === "PDF zoom"));
  assert.equal(harness.pageInput().disabled, true);
  assert.equal(findElement(tree, item => item.type === "h3" && item.props.children === "synthetic.pdf"), null);
  const css = readFileSync(new URL("../src/components/pdf/PDFReader.module.css", import.meta.url), "utf8");
  assert.match(css, /\.reader\s*\{[^}]*height:\s*100%[^}]*min-height:\s*0/);
  assert.match(css, /\.canvas\s*\{[^}]*flex:\s*1[^}]*min-height:\s*0/);
});

test("optional document actions share the reader toolbar and survive PDF failure", async () => {
  const action = React.createElement("button", { "aria-label": "Extracted text" }, "Extracted text");
  const harness = viewerHarness();
  let tree = harness.render({ documentId: "doc-1", toolbarActions: action });
  let toolbar = findElement(tree, item => item.props?.className === "pdf-toolbar");
  assert.ok(findElement(toolbar, item => item.props?.["aria-label"] === "Extracted text"));
  await harness.flush();
  harness.render();
  harness.viewer().onError("Unable to render");
  tree = harness.render();
  toolbar = findElement(tree, item => item.props?.className === "pdf-toolbar");
  assert.ok(findElement(toolbar, item => item.props?.["aria-label"] === "Extracted text"), "extraction remains reachable if rendering fails");
});

test("reading mode uses one native field with an unboxed inline label", () => {
  const harness = viewerHarness();
  const tree = harness.render({ documentId: "doc-1" });
  const label = findElement(tree, item => item.type === "label" && item.props.className === "pdf-modeControl");
  assert.ok(label);
  assert.ok(findElement(label, item => item.type === "span" && item.props.children === "View"));
  const select = findElement(label, item => item.type === "select");
  assert.equal(select.props["aria-label"], "PDF reading mode");
  assert.equal(select.props.value, "continuous");
  assert.equal(findElement(label, item => item.type === "button" || item.type === "svg"), null);
  const css = readFileSync(new URL("../src/components/pdf/PDFReader.module.css", import.meta.url), "utf8");
  const labelRule = css.match(/\.modeControl\s*\{([^}]+)\}/)?.[1];
  assert.match(labelRule, /display:\s*inline-flex/);
  assert.match(labelRule, /align-items:\s*center/);
  assert.match(labelRule, /white-space:\s*nowrap/);
  assert.doesNotMatch(labelRule, /border:|background:|padding:/);
  assert.match(css, /\.toolbar select\s*\{[^}]*height:\s*32px/);
  assert.match(css, /\.toolbar select:focus-visible\s*\{[^}]*outline:/);
});

test("direct page entry is physical, range-checked and independent of text search", async () => {
  const harness = viewerHarness();
  harness.render({ documentId: "source-doc", sourceRevisionId: "revision-1" });
  await harness.flush();
  harness.render();
  const viewer = harness.viewer();
  viewer.onReady(harness.controller, 25);
  viewer.onPageChange(0);
  harness.render();
  assert.equal(harness.pageInput().disabled, false);
  harness.enterPage("25");
  harness.render();
  harness.submitPage();
  assert.deepEqual(harness.jumps, [24]);
  viewer.onPageChange(24);
  harness.render();
  assert.equal(harness.pageInput().value, "25");
  for (const value of ["0", "26", "1.5", "one", "", "-1", "Infinity"]) {
    harness.enterPage(value);
    harness.render();
    harness.submitPage();
    harness.render();
    assert.equal(harness.pageInput()["aria-invalid"], true, value);
    assert.match(harness.text(), /Enter a page number from 1 to 25/);
  }
  assert.deepEqual(harness.jumps, [24]);
  assert.ok(harness.searches.every(query => !query));
  assert.equal(harness.requests.length, 1);
});

test("failed direct page entry gives a safe inline error and preserves the reader", async () => {
  const harness = viewerHarness();
  harness.render({ documentId: "doc-1" });
  await harness.flush();
  harness.render();
  harness.viewer().onReady({ ...harness.controller, jumpToPage() { throw new Error("private renderer detail"); } }, 25);
  harness.render();
  harness.enterPage("2");
  harness.render();
  harness.submitPage();
  harness.render();
  assert.match(harness.text(), /That page could not be opened/);
  assert.doesNotMatch(harness.text(), /private renderer detail/);
  assert.ok(harness.viewer());
});
