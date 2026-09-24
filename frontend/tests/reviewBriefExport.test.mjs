import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

function loadModule(path, imports = {}, globals = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, ...globals,
    require(name) { assert.ok(name in imports, `Unexpected dependency: ${name}`); return imports[name]; },
  });
  return exports;
}

const settle = async () => { for (let index = 0; index < 12; index += 1) await Promise.resolve(); };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
function nodes(node) {
  if (!React.isValidElement(node)) return [];
  if (typeof node.type === "function") return nodes(node.type(node.props));
  return [node, ...React.Children.toArray(node.props.children).flatMap(nodes)];
}

function harness({ copy, download, overrides = {} } = {}) {
  const slots = [];
  let cursor = 0;
  const copies = [], downloads = [];
  const props = { filename: "synthetic.pdf", run: { id: "run-1" }, source: null,
    personal: { saved_questions: { "finding-1": { text: "Confirmed question?" } }, markers: {}, drafts: {} }, ...overrides };
  const hooks = { ...React,
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], update => { slots[index] = typeof update === "function" ? update(slots[index]) : update; }];
    },
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
  };
  const component = loadModule("../src/components/workspace/ReviewBriefExport.tsx", {
    react: hooks,
    "./WorkspaceControls": { Action: props => React.createElement("button", props) },
    "./reviewBrief": { buildReviewBrief(input) {
      if (!input.run || (!Object.keys(input.personal.saved_questions).length && !Object.values(input.personal.markers).some(value => value !== "not_marked"))) return null;
      return { filename: "synthetic-review-brief.md", markdown: `# ${input.filename}\n${input.personal.saved_questions["finding-1"]?.text || "Marked finding"}` };
    } },
    "./reviewBriefDelivery": {
      copyReviewBrief(markdown) { copies.push(markdown); return copy?.(markdown) ?? Promise.resolve(); },
      downloadReviewBrief(filename, markdown) { downloads.push({ filename, markdown }); return download?.(filename, markdown); },
    },
  }, { fetch() { assert.fail("Rendering or exporting a local brief must not call an API"); } }).ReviewBriefExport;
  const tree = () => { cursor = 0; return component(props); };
  const button = label => nodes(tree()).find(node => node.type === "button" && node.props.children === label);
  return { props, copies, downloads, tree, button,
    click(label) { const action = button(label); assert.ok(action, `Missing action: ${label}`); action.props.onClick(); },
    html: () => renderToStaticMarkup(tree()),
    fallback: () => nodes(tree()).find(node => node.type === "textarea"),
  };
}

test("rendering the export controls never starts delivery or calls an API", () => {
  const h = harness();
  assert.match(h.html(), /Export review brief/);
  assert.match(h.html(), /Drafts and Ask answers are excluded/);
  assert.equal(h.button("Copy brief").props.disabled, false);
  assert.equal(h.button("Download Markdown").props.disabled, false);
  assert.deepEqual(h.copies, []);
  assert.deepEqual(h.downloads, []);
});

test("compact export avoids a duplicate empty-state explanation but retains blocking feedback", () => {
  const h = harness({ overrides: { compact: true, personal: { saved_questions: {}, markers: {}, drafts: {} } } });
  assert.doesNotMatch(h.html(), /Export review brief|Save a question or add a personal marker/);
  assert.equal(h.button("Copy brief").props.disabled, true);
  assert.equal(h.button("Download Markdown").props.disabled, true);
  h.props.unavailable = "Resolve pending changes before exporting.";
  assert.match(h.html(), /Resolve pending changes before exporting/);
  assert.deepEqual(h.copies, []);
  assert.deepEqual(h.downloads, []);
});

for (const [name, overrides] of [
  ["no run", { run: null }],
  ["no confirmed work", { personal: { saved_questions: {}, markers: {}, drafts: { "finding-1": "Unsaved" } } }],
  ["unavailable saved state", { unavailable: "Resolve pending changes before exporting." }],
]) {
  test(`${name} disables export and also guards directly invoked handlers`, async () => {
    const h = harness({ overrides });
    for (const label of ["Copy brief", "Download Markdown"]) {
      assert.equal(h.button(label).props.disabled, true);
      h.click(label);
    }
    await settle();
    assert.deepEqual(h.copies, []);
    assert.deepEqual(h.downloads, []);
    assert.match(h.html(), overrides.unavailable ? /Resolve pending changes/ : /Save a question or add a personal marker/);
  });
}

test("copy waits for the clipboard promise and fences duplicate clicks before rerender", async () => {
  const pending = deferred();
  const h = harness({ copy: () => pending.promise });
  const click = h.button("Copy brief").props.onClick;
  click(); click();
  assert.equal(h.copies.length, 1);
  assert.equal(h.button("Copying…").props.disabled, true);
  assert.doesNotMatch(h.html(), /Review brief copied/);
  pending.resolve();
  await settle();
  assert.match(h.html(), /role="status"[^>]*>Review brief copied/);
  assert.equal(h.button("Copy brief").props.disabled, false);
  assert.equal(h.fallback(), undefined);
});

test("clipboard rejection offers a readonly selected manual fallback without raw error details", async () => {
  const h = harness({ copy: () => Promise.reject(new Error("private clipboard detail")) });
  h.click("Copy brief");
  await settle();
  assert.match(h.html(), /role="alert"/);
  assert.match(h.html(), /Clipboard access was unavailable/);
  assert.doesNotMatch(h.html(), /private clipboard detail|Review brief copied/);
  assert.equal(h.fallback().props.readOnly, true);
  assert.equal(h.fallback().props.value, h.copies[0]);
  let selected = false;
  h.fallback().props.onFocus({ currentTarget: { select() { selected = true; } } });
  assert.equal(selected, true);
  assert.equal(h.button("Download Markdown").props.disabled, false);
});

test("download feedback says requested rather than claiming a file was saved", () => {
  const h = harness();
  h.click("Download Markdown");
  assert.deepEqual(h.downloads, [{ filename: "synthetic-review-brief.md", markdown: "# synthetic.pdf\nConfirmed question?" }]);
  assert.match(h.html(), /Markdown download requested\. Check your browser/);
  assert.doesNotMatch(h.html(), /download complete|file saved|downloaded successfully/i);
  assert.deepEqual(h.copies, []);
});

test("download failures retain the manual brief without exposing raw errors", () => {
  const h = harness({ download() { throw new Error("private browser detail"); } });
  h.click("Download Markdown");
  assert.match(h.html(), /The download could not be started/);
  assert.doesNotMatch(h.html(), /private browser detail|download requested/);
  assert.equal(h.fallback().props.readOnly, true);
  assert.equal(h.fallback().props.value, h.downloads[0].markdown);
});

test("changed content hides old feedback including late copy completion and manual fallbacks", async () => {
  const pending = deferred();
  const h = harness({ copy: () => pending.promise });
  h.click("Copy brief");
  h.props.filename = "other-synthetic.pdf";
  pending.resolve();
  await settle();
  assert.doesNotMatch(h.html(), /Review brief copied/);
  assert.equal(h.button("Copy brief").props.disabled, false);
  const rejected = harness({ copy: () => Promise.reject(new Error("denied")) });
  rejected.click("Copy brief");
  await settle();
  assert.ok(rejected.fallback());
  rejected.props.personal.saved_questions["finding-1"].text = "New confirmed wording?";
  assert.equal(rejected.fallback(), undefined);
  assert.doesNotMatch(rejected.html(), /Clipboard access was unavailable/);
});

test("becoming unavailable hides previous delivery feedback and disables later attempts", async () => {
  const h = harness();
  h.click("Copy brief");
  await settle();
  h.props.unavailable = "Finish saving first.";
  assert.doesNotMatch(h.html(), /Review brief copied/);
  h.click("Copy brief");
  h.click("Download Markdown");
  assert.equal(h.copies.length, 1);
  assert.equal(h.downloads.length, 0);
});

function deliveryHarness({ fail, clipboard = { writeText: async () => {} } } = {}) {
  const events = [], blobs = [], timers = [], copied = [];
  const link = {
    click() { events.push("click"); if (fail === "click") throw new Error("click failure"); },
    remove() { events.push("remove"); if (fail === "remove") throw new Error("remove failure"); },
  };
  const module = loadModule("../src/components/workspace/reviewBriefDelivery.ts", {}, {
    Blob,
    navigator: { clipboard: clipboard && { writeText(value) { copied.push(value); return clipboard.writeText(value); } } },
    URL: {
      createObjectURL(blob) { blobs.push(blob); events.push("create-url"); return "blob:review-brief"; },
      revokeObjectURL(url) { assert.equal(url, "blob:review-brief"); events.push("revoke-url"); },
    },
    document: {
      createElement(name) { assert.equal(name, "a"); events.push("create-anchor"); if (fail === "create") throw new Error("create failure"); return link; },
      body: { appendChild(node) { assert.equal(node, link); events.push("append"); if (fail === "append") throw new Error("append failure"); } },
    },
    setTimeout(callback, delay) { timers.push({ callback, delay }); },
    fetch() { assert.fail("Local delivery must not call an API"); },
  });
  return { ...module, events, blobs, copied, link, timers };
}

test("actual clipboard delivery preserves text and awaits the browser operation", async () => {
  const pending = deferred();
  const h = deliveryHarness({ clipboard: { writeText: () => pending.promise } });
  let done = false;
  const result = h.copyReviewBrief("Unicode wording: café — ₹").then(() => { done = true; });
  await settle();
  assert.equal(done, false);
  assert.deepEqual(h.copied, ["Unicode wording: café — ₹"]);
  pending.resolve();
  await result;
  assert.equal(done, true);
});

test("missing clipboard support rejects without starting another delivery path", async () => {
  const h = deliveryHarness({ clipboard: null });
  await assert.rejects(h.copyReviewBrief("Brief"), /Clipboard unavailable/);
  assert.deepEqual(h.events, []);
  assert.deepEqual(h.copied, []);
});

test("actual download uses UTF-8 Markdown and cleans up its temporary anchor and blob URL", async () => {
  const h = deliveryHarness();
  const markdown = "# Synthetic review\nCafé — ₹";
  h.downloadReviewBrief("synthetic-review.md", markdown);
  assert.equal(h.blobs[0].type, "text/markdown;charset=utf-8");
  assert.equal(await h.blobs[0].text(), markdown);
  assert.equal(h.link.href, "blob:review-brief");
  assert.equal(h.link.download, "synthetic-review.md");
  assert.equal(h.link.hidden, true);
  assert.deepEqual(h.events, ["create-url", "create-anchor", "append", "click", "remove"]);
  assert.equal(h.timers.length, 1);
  assert.ok(h.timers[0].delay > 0, "The browser must be allowed to consume the requested URL first");
  h.timers[0].callback();
  assert.equal(h.events.at(-1), "revoke-url");
});

for (const fail of ["create", "append", "click", "remove"]) {
  test(`download ${fail} failure still releases its blob URL`, () => {
    const h = deliveryHarness({ fail });
    assert.throws(() => h.downloadReviewBrief("synthetic-review.md", "Brief"));
    if (fail !== "create") assert.ok(h.events.includes("remove"));
    assert.equal(h.timers.length, 1);
    h.timers[0].callback();
    assert.equal(h.events.at(-1), "revoke-url");
  });
}
