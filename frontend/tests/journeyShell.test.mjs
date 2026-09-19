import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { appHeaderHarness } from "./appHeaderHarness.mjs";

function loadModule(path, imports = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, React, require(name) {
    assert.ok(name in imports, `Unexpected dependency: ${name}`);
    return imports[name];
  } });
  return exports;
}

function nodes(element) {
  if (!React.isValidElement(element)) return [];
  return [element, ...React.Children.toArray(element.props.children).flatMap(nodes)];
}
function node(tree, predicate) {
  const found = nodes(tree).find(predicate);
  assert.ok(found, "Expected UI node was missing");
  return found;
}
const render = element => renderToStaticMarkup(element);

test("home redirects to Library without mounting upload or dispatching AI", () => {
  const destinations = [];
  const Home = loadModule("../src/app/page.tsx", { "next/navigation": { redirect: value => destinations.push(value) } }).default;
  Home();
  assert.deepEqual(destinations, ["/documents"]);
});

test("shared navigation marks Settings and excludes retired entry points", () => {
  const { AppHeader } = appHeaderHarness();
  const html = render(React.createElement(AppHeader, { current: "settings" }));
  assert.match(html, /href="\/settings"[^>]*aria-current="page"/);
  assert.match(html, /Switch to Graphite theme/);
  const [primary, secondary] = html.split("<details");
  assert.doesNotMatch(primary, /legacy-analysis|Analytics|About ClauseIQ/);
  assert.match(secondary, /href="\/about"/);
  assert.doesNotMatch(html, /legacy-analysis|\/analytics/);
  assert.doesNotMatch(html, /href="\/"/);
});

test("More closes on ordinary link navigation without intercepting modified links", () => {
  const { AppHeader } = appHeaderHarness();
  const link = node(AppHeader({}), item => item.props.href === "/about");
  const menu = { open: true };
  const event = { button: 0, currentTarget: { closest: () => menu }, preventDefault() { assert.fail("Unguarded navigation remains native"); } };
  link.props.onClick(event);
  assert.equal(menu.open, false);
  for (const override of [{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }, { button: 2 }]) {
    menu.open = true;
    link.props.onClick({ ...event, ...override });
    assert.equal(menu.open, true);
  }
});

test("More closes before guarded destination callbacks without bypassing the guard", () => {
  const { AppHeader } = appHeaderHarness();
  const menu = { open: true }, calls = [];
  const onNavigate = destination => { assert.equal(menu.open, false); calls.push(destination); };
  const tree = AppHeader({ guarded: true, onNavigate });
  const button = node(tree, item => item.type === "button" && item.props.children === "About ClauseIQ");
  button.props.onClick({ currentTarget: { closest: () => menu } });
  assert.deepEqual(calls, ["/about"]);
  menu.open = true;
  let prevented = false;
  const link = node(AppHeader({ onNavigate }), item => item.props.href === "/about");
  link.props.onClick({ button: 0, currentTarget: { closest: () => menu }, preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.deepEqual(calls, ["/about", "/about"]);
});

test("Escape closes an open More menu and returns focus to its summary", () => {
  const { AppHeader } = appHeaderHarness();
  const details = node(AppHeader({}), item => item.type === "details");
  let focused = 0, prevented = 0;
  const target = { open: true, querySelector: selector => {
    assert.equal(selector, "summary"); return { focus: () => focused++ };
  } };
  const event = { key: "Escape", currentTarget: target, preventDefault: () => prevented++ };
  details.props.onKeyDown({ ...event, key: "Enter" });
  assert.equal(target.open, true);
  details.props.onKeyDown(event);
  assert.equal(target.open, false);
  assert.equal(focused, 1);
  assert.equal(prevented, 1);
  details.props.onKeyDown(event);
  assert.equal(focused, 1);
});

test("retired analytics bookmarks redirect to Library without loading dashboard data", () => {
  const destinations = [];
  const Analytics = loadModule("../src/app/analytics/page.tsx", {
    "next/navigation": { redirect: destination => destinations.push(destination) },
  }).default;
  Analytics();
  assert.deepEqual(destinations, ["/documents"]);
});

const modelSelection = loadModule("../src/lib/modelSelection.ts");
const model = (id, legacy = false) => ({ id, name: id, description: "Synthetic model catalog entry", legacy,
  input_price_per_million: 1, output_price_per_million: 2, pricing_verified_on: "test reference", pricing_note: "" });
const defaultSettings = { has_api_key: true, model_id: "review-model", query_gate_model_id: "saved-legacy",
  available_models: [model("review-model"), model("other-model"), model("saved-legacy", true)],
  retention_days: 0, toast_notifications_enabled: true };

function settingsHarness(overrides = {}) {
  const slots = [], effects = [], calls = [];
  let index = 0;
  const hooks = { ...React,
    useState(initial) {
      const current = index++;
      if (!(current in slots)) slots[current] = initial;
      return [slots[current], value => { slots[current] = typeof value === "function" ? value(slots[current]) : value; }];
    },
    useEffect(effect) {
      const current = index++;
      if (!(current in slots)) { slots[current] = true; effects.push(effect); }
    },
  };
  const context = { settings: defaultSettings, isLoading: false, error: null,
    refresh: async () => calls.push(["refresh"]),
    updateSettings: async update => calls.push(["settings", JSON.parse(JSON.stringify(update))]),
    saveApiKey: async key => calls.push(["key", key]),
    removeApiKey: async () => calls.push(["remove"]), ...overrides };
  const Button = ({ children, loading: _loading, variant: _variant, ...props }) => React.createElement("button", props, children);
  const Modal = () => null;
  const Settings = loadModule("../src/app/settings/page.tsx", {
    react: hooks, "@/context/WorkspaceContext": { useWorkspace: () => context },
    "@/lib/modelSelection": modelSelection, "@/components/Button": Button,
    "@/components/Card": ({ children, ...props }) => React.createElement("div", props, children),
    "@/components/ui/ConfirmModal": Modal, "./Settings.module.css": {},
  }).default;
  const view = () => { index = 0; return Settings(); };
  view(); effects.splice(0).forEach(effect => effect());
  return { view, calls, context,
    html: () => render(view()),
    change: (id, value) => node(view(), item => item.props.id === id).props.onChange({ target: { value } }),
    toggle: number => { const input = nodes(view()).filter(item => item.type === "input" && item.props.type === "checkbox")[number]; input.props.onChange({ target: { checked: !input.props.checked } }); },
    submit: number => nodes(view()).filter(item => item.type === "form")[number].props.onSubmit({ preventDefault() {} }),
    modal: title => node(view(), item => item.type === Modal && item.props.title === title),
    click: label => node(view(), item => item.type === Button && item.props.children === label).props.onClick(),
  };
}

test("Settings groups render locally with no secret value, model changes or nested main", () => {
  const h = settingsHarness();
  const html = h.html();
  for (const label of ["OpenAI API key", "AI models", "Document library", "Notifications", "Key saved locally"])
    assert.ok(html.includes(label), label);
  assert.match(html, /type="password"[^>]*value=""/);
  assert.match(html, /saved legacy model/);
  assert.doesNotMatch(html, /<main|type="text"[^>]*id="openai-key"/);
  assert.deepEqual(h.calls, []);
});

test("Settings save preserves distinct review and query choices and disabled retention", async () => {
  const h = settingsHarness();
  h.change("analysis-model", "other-model");
  h.submit(1);
  await Promise.resolve();
  assert.deepEqual(h.calls, [["settings", { model_id: "other-model", query_gate_model_id: "saved-legacy", retention_days: 0, toast_notifications_enabled: true }]]);
});

test("automatic deletion remains opt-in and requires explicit confirmation", async () => {
  const h = settingsHarness();
  h.toggle(0);
  h.change("retention-days", "90");
  h.submit(1);
  assert.deepEqual(h.calls, []);
  const confirmation = h.modal("Enable automatic deletion?");
  assert.equal(confirmation.props.isOpen, true);
  assert.match(confirmation.props.message, /90 days ago.*permanent deletion/);
  confirmation.props.onClose();
  assert.deepEqual(h.calls, []);
  h.submit(1);
  h.modal("Enable automatic deletion?").props.onConfirm();
  await Promise.resolve();
  assert.equal(h.calls[0][1].retention_days, 90);
});

test("invalid retention and unavailable saved models cannot silently save", () => {
  const h = settingsHarness();
  h.toggle(0); h.change("retention-days", "0"); h.submit(1);
  assert.deepEqual(h.calls, []);
  assert.match(h.html(), /whole number of days/);
  const missing = settingsHarness({ settings: { ...defaultSettings, model_id: "unavailable" } });
  missing.submit(1);
  assert.deepEqual(missing.calls, []);
  assert.match(missing.html(), /Unavailable model: unavailable/);
});

test("key removal still requires confirmation and never removes documents", async () => {
  const h = settingsHarness();
  h.click("Remove key");
  assert.equal(h.modal("Remove your API key?").props.isOpen, true);
  assert.deepEqual(h.calls, []);
  h.modal("Remove your API key?").props.onConfirm();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(h.calls, [["remove"]]);
  assert.match(h.html(), /Saved documents remain available/);
});

test("connection failure keeps explicit retry separate from mutations", () => {
  const h = settingsHarness({ settings: null, error: "Synthetic connection failure" });
  assert.match(h.html(), /Synthetic connection failure/);
  assert.deepEqual(h.calls, []);
  h.click("Retry connection");
  assert.deepEqual(h.calls, [["refresh"]]);
});
