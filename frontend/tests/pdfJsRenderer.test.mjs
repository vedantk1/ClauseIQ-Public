import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import ts from "typescript";

const compiled = ts.transpileModule(readFileSync(new URL("../src/components/pdf/PdfJsRenderer.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText;

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function harness() {
  const slots = [];
  let cursor = 0;
  let effects = [];
  let props;
  const viewers = [];
  const buses = [];
  const tasks = [];
  const observers = [];
  const importsSeen = [];
  const frames = new Map();
  const notices = { ready: [], pages: [], searches: [], errors: [] };
  const same = (a, b) => a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
  const hooks = {
    ...React,
    useRef(current) {
      const index = cursor++;
      slots[index] ??= { current };
      return slots[index];
    },
    useEffect(effect, deps) {
      const index = cursor++;
      if (!same(slots[index]?.deps, deps)) effects.push(() => {
        slots[index]?.cleanup?.();
        slots[index] = { deps, cleanup: effect() };
      });
    },
  };
  const container = { clientWidth: 900, clientHeight: 700 };
  const pages = {};
  const core = {
    version: "test-version", GlobalWorkerOptions: {},
    AnnotationMode: { ENABLE: 1 }, AnnotationEditorType: { DISABLE: -1 },
    VerbosityLevel: { ERRORS: 0 },
    getDocument(options) {
      const pending = deferred();
      const task = { ...pending, options, destroyed: 0, async destroy() { this.destroyed++; } };
      tasks.push(task);
      return task;
    },
  };
  class EventBus {
    listeners = new Map();
    dispatched = [];
    constructor() { buses.push(this); }
    on(name, callback) { this.listeners.set(name, callback); }
    off(name, callback) { if (this.listeners.get(name) === callback) this.listeners.delete(name); }
    dispatch(name, event) { this.dispatched.push({ name, event }); this.listeners.get(name)?.(event); }
  }
  class Viewer {
    currentScale = 0;
    currentPageNumber = 1;
    pagesCount = 0;
    jumps = [];
    pagesPromise = Promise.resolve();
    constructor(options) { this.options = options; viewers.push(this); }
    setDocument(document) { this.document = document; this.pagesCount = document?.numPages ?? 0; }
    scrollPageIntoView(options) {
      this.jumps.push(options);
      this.currentPageNumber = options.pageNumber;
      this.options.eventBus.dispatch("pagechanging", { pageNumber: options.pageNumber });
    }
    update() {
      this.options.eventBus.dispatch("updateviewarea", {
        location: { pageNumber: this.currentPageNumber, left: 3, top: 200 },
      });
    }
  }
  class LinkService {
    constructor(options) { this.options = options; }
    setViewer(viewer) { this.viewer = viewer; }
    setDocument(document) { this.document = document; }
  }
  const viewerModule = {
    PDFViewer: Viewer, PDFLinkService: LinkService,
    PDFFindController: class {
      state = null;
      constructor({ eventBus }) { eventBus.on("find", state => { this.state = state; }); }
    }, EventBus,
    ScrollMode: { PAGE: 3, VERTICAL: 0 }, LinkTarget: { BLANK: 2 }, FindState: { PENDING: 3 },
  };
  class ResizeObserver {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe(target) { this.target = target; }
    disconnect() { this.disconnected = true; }
  }
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, AbortController, ResizeObserver,
    requestAnimationFrame(callback) { const id = frames.size + 1; frames.set(id, callback); return id; },
    cancelAnimationFrame(id) { frames.delete(id); },
    require(name) {
      if (name.endsWith(".css")) return {};
      if (name === "react") return hooks;
      if (name === "@/lib/pdfPageNavigation") return { securePdfDocumentOptions: options => ({ ...options, isEvalSupported: false }) };
      importsSeen.push(name);
      if (name === "pdfjs-dist") return core;
      if (name === "pdfjs-dist/web/pdf_viewer.mjs") {
        assert.ok(importsSeen.indexOf("pdfjs-dist") < importsSeen.length - 1, "Core must initialize before viewer");
        return viewerModule;
      }
      throw new Error(`Unexpected dependency: ${name}`);
    },
  });
  function attachRefs(element) {
    if (!element || typeof element !== "object") return;
    if (element.props.ref) element.props.ref.current = element.props.className === "pdfViewer" ? pages : container;
    React.Children.toArray(element.props.children).forEach(attachRefs);
  }
  return {
    viewers, buses, tasks, observers, frames, notices, core, container,
    render(changes = {}) {
      props = {
        fileUrl: "blob:synthetic-1", scale: 1, viewMode: "continuous", initialPage: 0,
        onReady: (controller, count) => notices.ready.push({ controller, count }),
        onPageChange: page => notices.pages.push(page),
        onSearchChange: result => notices.searches.push(result),
        onError: message => notices.errors.push(message),
        ...props, ...changes,
      };
      cursor = 0;
      attachRefs(exports.default(props));
    },
    async flush() {
      const pending = effects;
      effects = [];
      pending.forEach(effect => effect());
      for (let i = 0; i < 10; i++) await Promise.resolve();
    },
    async loaded(count = 25) {
      tasks.at(-1).resolve({ numPages: count });
      await this.flush();
      buses.at(-1).dispatch("pagesinit", {});
    },
    cleanup() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}

test("renderer imports only after mount, loads versioned local assets and disables executable/editable PDF features", async () => {
  const h = harness();
  h.render();
  assert.equal(h.tasks.length, 0);
  await h.flush();
  const options = h.tasks[0].options;
  assert.equal(options.url, "blob:synthetic-1");
  assert.equal(options.isEvalSupported, false);
  assert.equal(options.enableXfa, false);
  assert.equal(h.core.GlobalWorkerOptions.workerSrc, "/pdfjs/test-version/pdf.worker.min.mjs");
  for (const key of ["cMapUrl", "standardFontDataUrl", "wasmUrl", "iccUrl"]) assert.match(options[key], /^\/pdfjs\/test-version\//);
  const viewerOptions = h.viewers[0].options;
  assert.equal(viewerOptions.annotationEditorMode, -1);
  assert.equal(viewerOptions.annotationMode, 1);
  assert.equal(viewerOptions.enableAutoLinking, false);
  assert.equal(Object.hasOwn(viewerOptions, "scriptingManager"), true);
  assert.equal(viewerOptions.scriptingManager, undefined);
  assert.equal(viewerOptions.linkService.options.externalLinkRel, "noopener noreferrer nofollow");
  h.cleanup();
});

test("ready follows initial scale and allows a newer queued page jump before any initial page callback", async () => {
  const h = harness();
  h.render({ scale: 1.4, initialPage: 7, onReady(controller, count) {
    h.notices.ready.push({ controller, count });
    assert.equal(h.viewers[0].currentScale, 1.4);
    assert.deepEqual(h.notices.pages, []);
    controller.jumpToPage(24);
  } });
  await h.flush();
  assert.deepEqual(h.notices.ready, []);
  await h.loaded();
  assert.equal(h.notices.ready[0].count, 25);
  assert.ok(h.notices.pages.length > 0);
  assert.ok(h.notices.pages.every(page => page === 24));
  const controller = h.notices.ready[0].controller;
  for (const page of [-1, 25, 1.5, NaN]) assert.throws(() => controller.jumpToPage(page), /outside this PDF/);
  assert.equal(h.viewers[0].currentPageNumber, 25);
  h.cleanup();
});

test("callback updates and zoom do not reload PDF; zoom and resize preserve physical page", async () => {
  const h = harness();
  h.render({ initialPage: 12 });
  await h.flush();
  await h.loaded();
  const updatedPages = [];
  h.render({ scale: 1.2, onPageChange: page => updatedPages.push(page) });
  await h.flush();
  assert.equal(h.tasks.length, 1);
  assert.equal(h.viewers[0].currentScale, 1.2);
  assert.equal(h.viewers[0].currentPageNumber, 13);
  assert.ok(updatedPages.includes(12));
  h.container.clientHeight = 450;
  h.observers[0].callback();
  for (const callback of h.frames.values()) callback();
  assert.equal(h.viewers[0].currentPageNumber, 13);
  assert.equal(h.viewers[0].jumps.at(-1).destArray[1].name, "XYZ");
  h.cleanup();
});

test("mode/source replacement tears down old worker, listeners, observer and stale callbacks", async () => {
  const h = harness();
  h.render();
  await h.flush();
  await h.loaded();
  const old = h.notices.ready[0].controller;
  const lateCallback = h.buses[0].listeners.get("pagechanging");
  h.render({ fileUrl: "blob:synthetic-2", viewMode: "single", initialPage: 9 });
  await h.flush();
  assert.equal(h.tasks[0].destroyed, 1);
  assert.equal(h.viewers[0].document, null);
  assert.equal(h.viewers[0].options.abortSignal.aborted, true);
  assert.equal(h.observers[0].disconnected, true);
  // The isolated bus retains the controller's own listener, but no React-facing
  // subscriptions survive; the entire old controller/bus is then collectible.
  assert.deepEqual([...h.buses[0].listeners.keys()], ["find"]);
  const count = h.notices.pages.length;
  lateCallback({ pageNumber: 3 });
  old.jumpToPage(3);
  old.search("old document");
  assert.equal(h.notices.pages.length, count);
  await h.loaded();
  assert.equal(h.viewers[1].scrollMode, 3);
  assert.equal(h.viewers[1].currentPageNumber, 10);
  h.cleanup();
});

test("a load resolving after cleanup cannot attach document or publish ready", async () => {
  const h = harness();
  h.render();
  await h.flush();
  h.cleanup();
  h.tasks[0].resolve({ numPages: 25 });
  await h.flush();
  assert.equal(h.viewers[0].document, null);
  assert.equal(h.notices.ready.length, 0);
  assert.equal(h.notices.errors.length, 0);
});

test("search uses exact query and ignores obsolete query control-state callbacks", async () => {
  const h = harness();
  h.render();
  await h.flush();
  await h.loaded();
  const controller = h.notices.ready[0].controller;
  assert.equal(h.buses[0].dispatched.filter(event => event.name === "find").length, 0);
  controller.search("  first  ");
  controller.search("second");
  const count = h.notices.searches.length;
  h.buses[0].dispatch("updatefindcontrolstate", { state: 0, rawQuery: "first", matchesCount: { current: 1, total: 8 } });
  assert.equal(h.notices.searches.length, count);
  const findController = h.viewers[0].options.findController;
  findController.state = { query: "first" };
  h.buses[0].dispatch("updatefindmatchescount", { matchesCount: { current: 1, total: 8 } });
  assert.equal(h.notices.searches.length, count);
  findController.state = { query: "second" };
  h.buses[0].dispatch("updatefindmatchescount", { matchesCount: { current: 1, total: 2 } });
  assert.equal(h.notices.searches.at(-1).total, 2);
  h.buses[0].dispatch("updatefindcontrolstate", { state: 0, rawQuery: "second", matchesCount: { current: 1, total: 2 } });
  assert.equal(h.notices.searches.at(-1).total, 2);
  controller.nextMatch();
  controller.previousMatch();
  const finds = h.buses[0].dispatched.filter(event => event.name === "find");
  assert.equal(finds[0].event.query, "first");
  assert.equal(finds.at(-1).event.query, "second");
  assert.equal(finds.at(-1).event.findPrevious, true);
  controller.search("");
  assert.equal(h.notices.searches.at(-1).total, 0);
  assert.equal(h.notices.searches.at(-1).pending, false);
  h.cleanup();
});

test("load/password/render errors are safe and do not repeat raw PDF details", async () => {
  const failed = harness();
  failed.render();
  await failed.flush();
  failed.tasks[0].reject(new Error("raw private document content"));
  await failed.flush();
  assert.equal(failed.notices.errors.length, 1);
  assert.doesNotMatch(failed.notices.errors[0], /private document/);
  failed.cleanup();

  const locked = harness();
  locked.render();
  await locked.flush();
  locked.tasks[0].onPassword();
  locked.tasks[0].reject(new Error("raw password details"));
  await locked.flush();
  assert.match(locked.notices.errors[0], /Password-protected/);
  assert.equal(locked.notices.errors.length, 1);
  locked.cleanup();
});
