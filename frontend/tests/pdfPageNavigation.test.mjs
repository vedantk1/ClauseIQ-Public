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

function viewerHarness() {
  const slots = [];
  let cursor = 0;
  let effects = [];
  const same = (a, b) => a && b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
  const hooks = {
    ...React,
    useState(initial) {
      const index = cursor++;
      slots[index] ??= { value: initial };
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
  const zooms = [];
  const requests = [];
  const highlights = [];
  const Viewer = () => null;
  const Button = () => null;
  const empty = () => null;
  const navigation = { jumpToPage: (index) => jumps.push(index), GoToPreviousPage: empty, GoToNextPage: empty, CurrentPageLabel: empty };
  const search = { highlight: async () => [], clearHighlights() {}, jumpToMatch() {}, jumpToNextMatch() {}, jumpToPreviousMatch() {} };
  const imports = {
    react: hooks,
    "@react-pdf-viewer/core": { Worker: empty, Viewer, ScrollMode: { Page: "page", Vertical: "vertical" } },
    "@react-pdf-viewer/zoom": { zoomPlugin: () => ({ zoomTo: scale => zooms.push(scale) }) },
    "@react-pdf-viewer/page-navigation": { pageNavigationPlugin: () => navigation },
    "@react-pdf-viewer/search": { searchPlugin: () => search },
    "./Card": empty, "./Button": Button, "./DropdownMenu": empty,
    "@/config/config": { apiUrl: "http://127.0.0.1:8000" },
    "@/lib/api": { LOCAL_API_HEADERS: { "X-ClauseIQ-Local": "1" } },
    "@/utils/pdfHighlightUtils": { getRiskHighlightColor: () => "transparent", getRiskBorderColor: () => "transparent" },
    "@/hooks/usePDFHighlighting": { usePDFHighlighting: () => ({ executeHighlighting: async (clause) => { highlights.push(clause); }, highlightResult: null }) },
    "@/lib/pdfPageNavigation": helpers,
  };
  const exports = {};
  vm.runInNewContext(compile("../src/components/PDFViewer.tsx"), {
    exports, console, AbortController,
    URL: { createObjectURL: () => "blob:synthetic", revokeObjectURL() {} },
    fetch: async (url, options) => { requests.push({ url, options }); return { ok: true, blob: async () => ({}) }; },
    require(name) {
      if (name.endsWith(".css") || name === "../utils/pdfConsoleFilter") return {};
      assert.ok(name in imports, `Unexpected dependency: ${name}`);
      return imports[name];
    },
  });
  let props;
  let tree;
  return {
    jumps, zooms, requests, highlights,
    render(nextProps = props) { props = nextProps; cursor = 0; tree = exports.default(props); return tree; },
    async flush() { const pending = effects; effects = []; pending.forEach((effect) => effect()); for (let i = 0; i < 6; i += 1) await Promise.resolve(); },
    viewer() { return findElement(tree, (item) => item.type === Viewer)?.props; },
    toggleMode() { findElement(tree, (item) => item.type === Button && item.props.title?.startsWith("Switch to")).props.onClick(); },
    zoomIn() { findElement(tree, (item) => item.type === Button && item.props.title === "Zoom in").props.onClick(); },
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
  assert.equal(first.defaultScale, 1);
  assert.equal(first.enableSmoothScroll, false); // No stale pixel-offset animation across a resize.
  assert.deepEqual(harness.jumps, []);
  const doc = { numPages: 25 };
  first.onDocumentLoad({ doc });
  assert.deepEqual(harness.jumps, [24]);
  assert.deepEqual(harness.zooms, []); // No concurrent initial zoom can invalidate this jump's measurements.
  await harness.flush();
  first.onPageChange({ currentPage: 0, doc });
  first.onPageChange({ currentPage: 24, doc });
  assert.deepEqual(pages, [25]);
  assert.equal(first.transformGetDocumentParams({ isEvalSupported: true }).isEvalSupported, false);
  assert.equal(first.plugins.length, 2); // No legacy search/highlight plugin for source evidence.
  assert.ok(harness.highlights.every((clause) => clause === null));
  assert.equal(harness.requests[0].options.headers["X-ClauseIQ-Local"], "1");

  harness.zoomIn();
  harness.render();
  assert.deepEqual(harness.zooms, [1.2]);
  harness.toggleMode();
  harness.render();
  await harness.flush();
  const single = harness.viewer();
  assert.equal(single.initialPage, 24);
  assert.equal(single.defaultScale, 1.2);
  assert.equal(single.enableSmoothScroll, false);
  single.onDocumentLoad({ doc: { numPages: 25 } });
  assert.deepEqual(harness.zooms, [1.2]); // Remounts also start at the selected scale without a load-time resize.
  first.onPageChange({ currentPage: 2, doc }); // Callback from the previous mode.
  assert.deepEqual(pages, [25]);

  harness.render({ ...props, sourceRevisionId: "revision-2", navigationRequest: { requestId: 3, pageNumber: 30 } });
  first.onDocumentLoad({ doc }); // Callback from the previous source.
  assert.deepEqual(harness.jumps, [24]);
  await harness.flush();
  harness.render();
  await harness.flush();
  const replacement = harness.viewer();
  assert.equal(replacement.initialPage, 0);
  replacement.onDocumentLoad({ doc: { numPages: 25 } });
  assert.equal(errors.length, 1);
  assert.match(errors[0], /outside this PDF/);
  assert.deepEqual(harness.jumps, [24]);
});

test("legacy viewer retains its existing load-time zoom behavior", async () => {
  const harness = viewerHarness();
  harness.render({ documentId: "legacy-doc" });
  await harness.flush();
  harness.render();
  const viewer = harness.viewer();
  assert.equal(viewer.defaultScale, undefined);
  assert.equal(viewer.enableSmoothScroll, true);
  viewer.onDocumentLoad({ doc: { numPages: 25 } });
  assert.deepEqual(harness.zooms, [1]);
  assert.deepEqual(harness.jumps, []);
});

test("explicit physical-page navigation disables animation even before source metadata is available", async () => {
  const harness = viewerHarness();
  harness.render({ documentId: "source-doc", navigationRequest: { requestId: 1, pageNumber: 25 } });
  await harness.flush();
  harness.render();
  const viewer = harness.viewer();
  assert.equal(viewer.enableSmoothScroll, false);
  viewer.onDocumentLoad({ doc: { numPages: 25 } });
  assert.deepEqual(harness.jumps, [24]);
});
