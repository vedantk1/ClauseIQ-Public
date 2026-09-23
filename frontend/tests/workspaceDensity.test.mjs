import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import postcss from "postcss";

function css(file) {
  const sheet = postcss.parse(readFileSync(new URL(`../src/components/${file}`, import.meta.url), "utf8"));
  return (selector, media = null) => {
    const values = {};
    sheet.walkRules(selector, rule => {
      const parentMedia = rule.parent.type === "atrule" ? rule.parent.params : null;
      if (parentMedia === media) rule.walkDecls(decl => { values[decl.prop] = decl.value; });
    });
    return values;
  };
}

// Layout intent only. The batched browser checkpoint checks the rendered result.
test("document canvas keeps the remaining viewport rather than a padded scrolling page", () => {
  const rules = css("workspace/ReviewWorkspace.module.css");
  const document = rules(".workspace :global(.cw-view-document)");
  assert.equal(document.display, "flex");
  assert.equal(document.padding, "0");
  assert.equal(document.overflow, "hidden");
  const frame = rules(".workspace:has(:global(.cw-view-document))", "(max-width: 950px)");
  assert.equal(frame.height, "100dvh");
  assert.equal(frame.overflow, "hidden");
  assert.equal(rules(".workspace :global(.cw-view-document)", "(max-width: 950px)").overflow, "hidden");
});

test("findings retain readable copy and prioritize the reading column", () => {
  const rules = css("workspace/ReviewWorkspace.module.css");
  assert.match(rules(".workspace :global(.cw-findings-layout)")["grid-template-columns"], /minmax\(360px, 1fr\)/);
  assert.equal(rules(".workspace :global(.cw-finding-section p)")["font-size"], "16px");
  assert.equal(rules(".workspace :global(.cw-finding-section p)")["line-height"], "1.7");
});

test("overview coverage belongs to the summary column instead of following the taller sidebar", () => {
  const component = readFileSync(new URL("../src/components/workspace/AgreementOverview.tsx", import.meta.url), "utf8");
  const main = component.indexOf('className="co-overview-main"');
  const coverage = component.indexOf('className="co-source-coverage"');
  const controls = component.indexOf('className="co-review-controls"');
  const sidebar = component.indexOf('className="co-activity"');
  assert.ok(main > 0 && main < coverage && coverage < controls && controls < sidebar);
  assert.match(component.slice(controls, sidebar), /<\/details>}\s*<\/div>\s*<aside/);
});

test("library toolbar shares a row without permanently reserved inspector space", () => {
  const rules = css("documents/Library.module.css");
  assert.equal(rules(".library :global(.cl-toolbar)").display, "flex");
  assert.equal(rules(".library :global(.cl-document-row)")["min-height"], "72px");
  assert.equal(rules(".library :global(.cl-library-grid)")["grid-template-columns"], undefined);
});
