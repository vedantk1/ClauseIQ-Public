import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import React from "react";
import ts from "typescript";

export const HeaderLink = ({ children, ...props }) => React.createElement("a", props, children);

export function appHeaderHarness({ nextThemeLabel = "Graphite", toggleTheme = () => {}, Link = HeaderLink } = {}) {
  const icon = props => React.createElement("svg", props);
  const imports = {
    react: React, "next/link": Link,
    "lucide-react": { BookOpen: icon, MoreHorizontal: icon, Palette: icon, Settings: icon },
    "@/hooks/useTheme": { useTheme: () => ({ nextThemeLabel, toggleTheme }) },
    "./AppHeader.module.css": Object.fromEntries(["header", "identity", "brand", "context", "navigation", "link", "theme", "more", "menu", "menuLink"].map(name => [name, name])),
  };
  const compiled = ts.transpileModule(readFileSync(new URL("../src/components/shell/AppHeader.tsx", import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, { exports, React, require(name) {
    assert.ok(name in imports, `Unexpected shared-header dependency: ${name}`);
    return imports[name];
  } });
  return exports;
}
