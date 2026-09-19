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
    require(name) { assert.ok(name in imports, `Unexpected dependency: ${name}`); return imports[name]; },
  });
  return exports;
}

function environment(saved = null, blocked = false) {
  let stored = saved;
  const writes = [];
  const classes = new Set(["light"]);
  const root = {
    attributes: {}, style: {},
    setAttribute(key, value) { this.attributes[key] = value; },
    classList: { add(value) { classes.add(value); }, remove(value) { classes.delete(value); } },
  };
  const localStorage = {
    getItem() { if (blocked) throw new Error("Storage blocked"); return stored; },
    setItem(key, value) { if (blocked) throw new Error("Storage blocked"); writes.push([key, value]); stored = value; },
  };
  const globals = { window: { localStorage }, localStorage, document: { documentElement: root } };
  return { globals, root, classes, writes, stored: () => stored };
}

const helpers = loadModule("../src/lib/theme.ts");

test("only Black and Graphite are supported, with deterministic legacy migration", () => {
  for (const [value, expected] of [
    ["black", "black"], ["graphite", "graphite"], ["dark", "graphite"],
    ["light", "black"], [null, "black"], [undefined, "black"], ["system", "black"],
    ["invalid", "black"], ["__proto__", "black"], [{}, "black"],
  ]) assert.equal(helpers.normalizeTheme(value), expected);
  assert.equal(helpers.DEFAULT_THEME, "black");
  assert.equal(helpers.nextTheme("black"), "graphite");
  assert.equal(helpers.nextTheme("graphite"), "black");
});

test("pre-hydration bootstrap agrees with normalization, including blocked storage", () => {
  for (const saved of ["black", "graphite", "dark", "light", "system", "__proto__", null]) {
    const env = environment(saved);
    vm.runInNewContext(helpers.THEME_BOOTSTRAP_SCRIPT, env.globals);
    assert.equal(env.root.attributes["data-theme"], helpers.normalizeTheme(saved));
    assert.equal(env.root.style.colorScheme, "dark");
    assert.deepEqual([...env.classes], ["dark"]);
    assert.equal(env.writes.length, 0);
  }
  const env = environment("graphite", true);
  assert.doesNotThrow(() => vm.runInNewContext(helpers.THEME_BOOTSTRAP_SCRIPT, env.globals));
  assert.equal(env.root.attributes["data-theme"], "black");
});

test("blocked storage never stops applying an in-session theme", () => {
  const env = environment("graphite", true);
  const lib = loadModule("../src/lib/theme.ts", {}, env.globals);
  assert.equal(lib.readSavedTheme(), "black");
  assert.doesNotThrow(() => lib.persistTheme("graphite"));
  lib.applyTheme("graphite");
  assert.equal(env.root.attributes["data-theme"], "graphite");
  assert.equal(env.root.style.colorScheme, "dark");
  assert.deepEqual([...env.classes], ["dark"]);
});

// Execute the real provider effects against a small deterministic hook runtime.
// This catches ordering regressions without adding a browser-test dependency.
function providerHarness(saved, blocked = false) {
  const env = environment(saved, blocked);
  const lib = loadModule("../src/lib/theme.ts", {}, env.globals);
  let theme = "black";
  let dirty = false;
  let cursor = 0;
  let effects = [];
  let reads = 0;
  const slots = [];
  const dispatch = action => {
    assert.equal(action.type, "UI_SET_THEME");
    if (theme !== action.payload) { theme = action.payload; dirty = true; }
  };
  const app = { useAppState: () => ({ state: { ui: { theme } }, dispatch }) };
  const runtime = { ...React,
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], value => { if (slots[index] !== value) { slots[index] = value; dirty = true; } }];
    },
    useEffect(effect, deps) {
      const index = cursor++;
      if (!slots[index] || deps.some((value, i) => value !== slots[index][i])) effects.push(effect);
      slots[index] = deps;
    },
    useCallback(callback) { return callback; },
  };
  const Provider = loadModule("../src/components/ThemeProvider.tsx", {
    react: runtime, "../store/appState": app,
    "../lib/theme": { ...lib, readSavedTheme() { reads += 1; return lib.readSavedTheme(); } },
  }).default;
  const { useTheme } = loadModule("../src/hooks/useTheme.ts", {
    react: runtime, "../store/appState": app, "../lib/theme": lib,
  });
  function flush() {
    let passes = 0;
    do {
      assert.ok(passes++ < 5, "Theme effects must settle");
      cursor = 0; effects = []; dirty = false;
      Provider({ children: null });
      effects.forEach(effect => effect());
    } while (dirty);
  }
  return { ...env, flush, useTheme, theme: () => theme, reads: () => reads };
}

test("provider initializes once, migrates persisted dark, and keeps both controls coherent", () => {
  const h = providerHarness("dark");
  h.flush();
  assert.equal(h.theme(), "graphite");
  assert.deepEqual(h.writes, [["clauseiq-theme", "graphite"]]);
  assert.equal(h.reads(), 1);
  const firstControl = h.useTheme();
  const secondControl = h.useTheme();
  assert.equal(firstControl.theme, secondControl.theme);
  assert.equal(firstControl.nextThemeLabel, "Black");
  firstControl.toggleTheme();
  h.flush();
  assert.equal(h.useTheme().theme, "black");
  assert.equal(h.root.attributes["data-theme"], "black");
  assert.equal(h.stored(), "black");
  h.useTheme().toggleTheme();
  h.flush();
  assert.equal(h.theme(), "graphite");
  assert.equal(h.root.attributes["data-theme"], "graphite");
  assert.equal(h.stored(), "graphite");
  assert.equal(h.reads(), 1, "Re-renders and hook consumers do not re-read storage");
});

test("provider removes legacy light and remains usable with unavailable persistence", () => {
  const oldLight = providerHarness("light");
  oldLight.flush();
  assert.equal(oldLight.theme(), "black");
  assert.equal(oldLight.stored(), "black");
  const blocked = providerHarness("graphite", true);
  blocked.flush();
  blocked.useTheme().setTheme("graphite");
  blocked.flush();
  assert.equal(blocked.theme(), "graphite");
  assert.equal(blocked.root.attributes["data-theme"], "graphite");
});

test("global theme control shows the current name and labels its actual target", () => {
  for (const [themeLabel, nextThemeLabel] of [["Black", "Graphite"], ["Graphite", "Black"]]) {
    const Toggle = loadModule("../src/components/ThemeToggle.tsx", {
      react: React,
      "lucide-react": { Palette: props => React.createElement("svg", props) },
      "../hooks/useTheme": { useTheme: () => ({ themeLabel, nextThemeLabel, toggleTheme() {} }) },
      "./Button": ({ variant, size, ...props }) => React.createElement("button", props),
    }).default;
    const html = renderToStaticMarkup(React.createElement(Toggle, { showLabel: true }));
    assert.match(html, new RegExp(`>${themeLabel}</span>`));
    assert.match(html, new RegExp(`aria-label="Switch to ${nextThemeLabel} theme"`));
    assert.doesNotMatch(html, /light mode|dark mode/i);
  }
});
