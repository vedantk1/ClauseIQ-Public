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
  vm.runInNewContext(compiled, { exports, React, ...globals,
    require(name) { assert.ok(name in imports, `Unexpected import: ${name}`); return imports[name]; },
  });
  return exports;
}

// Deterministic DOM boundary checks; the combined UI checkpoint covers browser focus itself.
class Element {
  constructor(document, { tabIndex = 0, disabled = false, hidden = false, inert = false, visibility = "visible" } = {}) {
    Object.assign(this, { ownerDocument: document, tabIndex, disabled, hidden, inert, visibility, isConnected: true, children: [], parent: null });
  }
  append(...children) { children.forEach(child => { child.parent = this; this.children.push(child); }); return this; }
  contains(target) { return this === target || this.children.some(child => child.contains(target)); }
  querySelectorAll() { return this.children.flatMap(child => [child, ...child.querySelectorAll()]); }
  matches() { return this.disabled; }
  closest() { return this.hidden || this.inert ? this : this.parent?.closest() || null; }
  getClientRects() { return this.closest() ? [] : [{}]; }
  focus() {
    if (!this.isConnected || this.disabled || this.closest() || this.visibility === "hidden") return;
    this.ownerDocument.activeElement = this;
    this.ownerDocument.dispatch("focusin", { target: this });
  }
}

function environment(overflow = "", priority = "") {
  const listeners = new Map();
  let value = overflow;
  let importance = priority;
  const document = {
    activeElement: null,
    body: { style: {
      getPropertyValue: () => value, getPropertyPriority: () => importance,
      setProperty(name, next, nextPriority = "") { assert.equal(name, "overflow"); value = next; importance = nextPriority; },
      removeProperty(name) { assert.equal(name, "overflow"); value = ""; importance = ""; },
    } },
    defaultView: { getComputedStyle: element => ({ visibility: element.visibility }) },
    addEventListener(name, handler, capture) { assert.equal(capture, true); listeners.set(name, handler); },
    removeEventListener(name, handler, capture) { assert.equal(capture, true); assert.equal(listeners.get(name), handler); listeners.delete(name); },
    dispatch(name, event) { listeners.get(name)?.(event); },
  };
  const helper = loadModule("../src/components/ui/modalFocus.ts", {}, { HTMLElement: Element });
  const trigger = new Element(document);
  trigger.focus();
  return {
    document, helper, trigger, listeners,
    overflow: () => [value, importance],
    element: options => new Element(document, options),
    dialog() { return new Element(document, { tabIndex: -1 }); },
    key(key, shiftKey = false) {
      const event = { key, shiftKey, prevented: false, stopped: false,
        preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.stopped = true; } };
      document.dispatch("keydown", event);
      return event;
    },
  };
}

test("dialog traps both Tab directions and restores its opener and exact prior scroll style", () => {
  const env = environment("scroll", "important");
  const first = env.element(), last = env.element();
  const dialog = env.dialog().append(first, last);
  const close = env.helper.mountModal(dialog, () => {});
  assert.equal(env.document.activeElement, dialog);
  assert.deepEqual(env.overflow(), ["hidden", ""]);
  assert.equal(env.key("Tab").prevented, true);
  assert.equal(env.document.activeElement, first);
  assert.equal(env.key("Tab", true).prevented, true);
  assert.equal(env.document.activeElement, last);
  assert.equal(env.key("Tab").prevented, true);
  assert.equal(env.document.activeElement, first);
  assert.equal(env.key("Tab").prevented, false); // Native movement between interior controls.
  close();
  assert.equal(env.document.activeElement, env.trigger);
  assert.deepEqual(env.overflow(), ["scroll", "important"]);
  assert.equal(env.listeners.size, 0);
  close(); // Strict-mode/unmount cleanup is safe to repeat.
});

test("empty dialogs retain focus and remove only the overflow value they introduced", () => {
  const env = environment();
  const dialog = env.dialog();
  const close = env.helper.mountModal(dialog, () => {});
  for (const backwards of [false, true]) {
    assert.equal(env.key("Tab", backwards).prevented, true);
    assert.equal(env.document.activeElement, dialog);
  }
  close();
  assert.deepEqual(env.overflow(), ["", ""]);
});

test("disabled, hidden, inert and negative-tab-index controls are excluded from the focus loop", () => {
  const env = environment();
  const hiddenParent = env.element({ hidden: true }).append(env.element());
  const first = env.element(), last = env.element();
  const dialog = env.dialog().append(env.element({ disabled: true }), env.element({ tabIndex: -1 }),
    hiddenParent, env.element({ inert: true }), env.element({ visibility: "hidden" }), first, last);
  const close = env.helper.mountModal(dialog, () => {});
  env.key("Tab");
  assert.equal(env.document.activeElement, first);
  env.key("Tab", true);
  assert.equal(env.document.activeElement, last);
  close();
});

test("positive tab indexes retain native priority and outside focus is returned to the dialog", () => {
  const env = environment();
  const zero = env.element(), second = env.element({ tabIndex: 2 }), first = env.element({ tabIndex: 1 });
  const dialog = env.dialog().append(zero, second, first);
  const close = env.helper.mountModal(dialog, () => {});
  env.key("Tab");
  assert.equal(env.document.activeElement, first);
  env.key("Tab", true);
  assert.equal(env.document.activeElement, zero);
  env.trigger.focus();
  assert.equal(env.document.activeElement, first);
  close();
});

test("only the top nested dialog handles Escape/Tab and scroll stays locked until all dialogs close", () => {
  const env = environment("auto");
  let outerEscapes = 0, innerEscapes = 0;
  const outerButton = env.element(), innerButton = env.element();
  const outer = env.dialog().append(outerButton), inner = env.dialog().append(innerButton);
  const closeOuter = env.helper.mountModal(outer, () => outerEscapes++);
  outerButton.focus();
  const closeInner = env.helper.mountModal(inner, () => innerEscapes++);
  assert.equal(env.helper.isTopModal(outer), false);
  assert.equal(env.helper.isTopModal(inner), true);
  env.key("Tab");
  assert.equal(env.document.activeElement, innerButton);
  const escape = env.key("Escape");
  assert.equal(escape.prevented, true);
  assert.equal(escape.stopped, true);
  assert.equal(innerEscapes, 1);
  assert.equal(outerEscapes, 0);
  closeInner();
  assert.equal(env.document.activeElement, outerButton);
  assert.deepEqual(env.overflow(), ["hidden", ""]);
  env.key("Escape");
  assert.equal(outerEscapes, 1);
  closeOuter();
  assert.equal(env.document.activeElement, env.trigger);
  assert.deepEqual(env.overflow(), ["auto", ""]);
});

test("closing a parent first does not steal child focus or leave a stale restoration target", () => {
  const env = environment();
  const outerButton = env.element(), innerButton = env.element();
  const outer = env.dialog().append(outerButton), inner = env.dialog().append(innerButton);
  const closeOuter = env.helper.mountModal(outer, () => {});
  outerButton.focus();
  const closeInner = env.helper.mountModal(inner, () => {});
  innerButton.focus();
  closeOuter();
  assert.equal(env.document.activeElement, innerButton);
  assert.deepEqual(env.overflow(), ["hidden", ""]);
  closeInner();
  assert.equal(env.document.activeElement, env.trigger);
});

test("nested restoration falls back inside the parent if its opener was removed or disabled", () => {
  for (const removed of [false, true]) {
    const env = environment();
    const safe = env.element(), opener = env.element();
    const outer = env.dialog().append(safe, opener);
    const closeOuter = env.helper.mountModal(outer, () => {});
    opener.focus();
    const closeInner = env.helper.mountModal(env.dialog(), () => {});
    if (removed) opener.isConnected = false;
    else opener.disabled = true;
    closeInner();
    assert.equal(env.document.activeElement, safe);
    closeOuter();
  }
});

function modalImports(react, helper, registrations = []) {
  return {
    react,
    "react-dom": { createPortal: content => content },
    "@/lib/utils": { cn: (...values) => values.filter(Boolean).join(" ") },
    "lucide-react": { X: () => React.createElement("svg") },
    "./modalFocus": helper || {
      isTopModal: () => true,
      mountModal(element, onEscape) { const entry = { element, onEscape, closed: false }; registrations.push(entry); return () => { entry.closed = true; }; },
    },
  };
}

function componentHarness() {
  const slots = [];
  const registrations = [];
  let cursor = 0;
  let effects = [];
  const hooks = { ...React,
    useRef(initial) { const index = cursor++; slots[index] ||= { current: initial }; return slots[index]; },
    useId() { const index = cursor++; slots[index] ||= `modal-${index}`; return slots[index]; },
    useEffect(effect, deps) {
      const index = cursor++;
      const old = slots[index];
      if (!old || deps.some((value, i) => old.deps[i] !== value)) {
        effects.push(() => { old?.cleanup?.(); slots[index] = { deps, cleanup: effect() }; });
      }
    },
  };
  const { default: Modal } = loadModule("../src/components/ui/Modal.tsx", modalImports(hooks, null, registrations), { document: { body: {} } });
  function find(element, predicate) {
    if (!React.isValidElement(element)) return null;
    if (predicate(element)) return element;
    return React.Children.toArray(element.props.children).map(child => find(child, predicate)).find(Boolean) || null;
  }
  return {
    registrations,
    render(props) {
      cursor = 0; effects = [];
      const tree = Modal(props);
      if (tree) {
        const dialog = find(tree, element => element.props.role === "dialog");
        dialog.props.ref.current ||= {};
      }
      effects.forEach(effect => effect());
      return tree;
    },
  };
}

test("mounted closed modals never register scroll/focus handlers", () => {
  const app = componentHarness();
  assert.equal(app.render({ isOpen: false, onClose() {}, children: "Closed" }), null);
  app.render({ isOpen: false, onClose() {}, children: "Still closed" });
  assert.equal(app.registrations.length, 0);
});

test("inline callbacks and dismissal-option changes update behavior without remounting the focus boundary", () => {
  const app = componentHarness();
  let oldCalls = 0, newCalls = 0;
  app.render({ isOpen: true, onClose: () => oldCalls++, children: "Open" });
  assert.equal(app.registrations.length, 1);
  app.registrations[0].onEscape();
  assert.equal(oldCalls, 1);
  app.render({ isOpen: true, onClose: () => newCalls++, closeOnEscapeKey: false, children: "Waiting" });
  app.registrations[0].onEscape();
  assert.equal(newCalls, 0);
  assert.equal(app.registrations.length, 1);
  assert.equal(app.registrations[0].closed, false);
  app.render({ isOpen: true, onClose: () => newCalls++, children: "Ready" });
  app.registrations[0].onEscape();
  assert.equal(newCalls, 1);
  app.render({ isOpen: true, onClose() {}, children: "Loading dismissal is a no-op" });
  app.registrations[0].onEscape();
  assert.equal(newCalls, 1);
  app.render({ isOpen: false, onClose() {} });
  assert.equal(app.registrations[0].closed, true);
});

test("simultaneously rendered dialogs have distinct accessible title IDs", () => {
  const { default: Modal } = loadModule("../src/components/ui/Modal.tsx", modalImports(React), { document: { body: {} } });
  const html = renderToStaticMarkup(React.createElement(React.Fragment, null,
    React.createElement(Modal, { isOpen: true, title: "First", onClose() {} }, "One"),
    React.createElement(Modal, { isOpen: true, title: "Second", onClose() {} }, "Two")));
  const labels = [...html.matchAll(/aria-labelledby="([^"]+)"/g)].map(match => match[1]);
  const headings = [...html.matchAll(/<h2 id="([^"]+)"/g)].map(match => match[1]);
  assert.equal(labels.length, 2);
  assert.equal(new Set(labels).size, 2);
  assert.deepEqual(labels, headings);
});
