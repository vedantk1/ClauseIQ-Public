import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const exports = {};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../src/components/workspace/SourceReadNotice.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, esModuleInterop: true },
}).outputText, { exports, require(name) {
  if (name === "react") return React;
  assert.equal(name, "./WorkspaceControls");
  return { Action: props => React.createElement("button", props) };
} });
const props = { sourceStatus: "ready", metadataStatus: "ready", sourceError: null, metadataError: null,
  onRetrySource() {}, onRetryMetadata() {} };
const render = input => renderToStaticMarkup(React.createElement(exports.SourceReadNotice, { ...props, ...input }));

test("successful independent reads need no warning", () => assert.equal(render({}), ""));
test("loading has honest status and no retry controls", () => {
  const html = render({ sourceStatus: "loading", metadataStatus: "loading" });
  assert.match(html, /Loading source text/);
  assert.match(html, /Loading agreement details/);
  assert.doesNotMatch(html, /<button/);
});
test("source failure offers only read retry and protects drafts and paid boundary", () => {
  const html = render({ sourceStatus: "error", sourceError: "Source unavailable" });
  assert.match(html, /role="alert"/);
  assert.match(html, /Retry source loading/);
  assert.match(html, /does not discard drafts, extract the PDF again or run AI/);
  assert.doesNotMatch(html, /Retry agreement details/);
});
test("metadata failure does not describe source text as unavailable", () => {
  const html = render({ metadataStatus: "error", metadataError: "Details unavailable" });
  assert.match(html, /Retry agreement details/);
  assert.doesNotMatch(html, /Retry source loading|Loading source text/);
});
test("each retry control calls only its corresponding handler", () => {
  const calls = [];
  const tree = exports.SourceReadNotice({ ...props, sourceStatus: "error", metadataStatus: "error",
    sourceError: "Source unavailable", metadataError: "Details unavailable",
    onRetrySource: () => calls.push("source"), onRetryMetadata: () => calls.push("metadata") });
  const walk = node => !node || typeof node !== "object" ? [] : [node, ...React.Children.toArray(node.props?.children).flatMap(walk)];
  const actions = walk(tree).filter(node => typeof node.props?.onClick === "function");
  assert.equal(actions.length, 2);
  actions[0].props.onClick(); actions[1].props.onClick();
  assert.deepEqual(calls, ["source", "metadata"]);
});
