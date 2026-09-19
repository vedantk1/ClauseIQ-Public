import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");
const workspace = readFileSync(new URL("../src/components/workspace/ReviewWorkspace.module.css", import.meta.url), "utf8");
const tokens = selector => Object.fromEntries(
  [...css.slice(css.indexOf(selector)).split("}")[0].matchAll(/(--[\w-]+):\s*(#[\da-f]{6});/gi)]
    .map(([, name, value]) => [name, value]),
);
const black = tokens(":root {");
const graphite = { ...black, ...tokens('[data-theme="graphite"]') };
function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map(value => {
    const channel = parseInt(value, 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return channels.reduce((sum, channel, i) => sum + channel * [0.2126, 0.7152, 0.0722][i], 0);
}
function contrast(a, b) {
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

test("only dark palettes remain and Black surfaces/text are neutral", () => {
  assert.match(css, /color-scheme: dark/);
  assert.doesNotMatch(css + workspace, /data-theme=["']light/);
  for (const name of ["--bg-primary", "--bg-header", "--bg-surface", "--bg-elevated", "--bg-selected", "--text-primary", "--text-secondary", "--text-muted", "--border-muted"]) {
    const channels = black[name].slice(1).match(/../g);
    assert.equal(new Set(channels).size, 1, `${name} must not acquire a blue tint`);
  }
  assert.notEqual(black["--bg-primary"], graphite["--bg-primary"]);
});

test("normal reading text and small accents maintain contrast on every themed surface", () => {
  for (const [name, palette] of Object.entries({ black, graphite })) {
    for (const foreground of ["--text-primary", "--text-secondary", "--text-muted", "--accent-subtle"]) {
      for (const background of ["--bg-primary", "--bg-header", "--bg-surface", "--bg-elevated", "--bg-selected"]) {
        assert.ok(contrast(palette[foreground], palette[background]) >= 4.5, `${name}: ${foreground} on ${background}`);
      }
    }
    assert.ok(contrast("#ffffff", palette["--accent-purple"]) >= 4.5, `${name}: filled action`);
  }
});

test("workspace aliases global palette and disabled actions use neutral state tokens", () => {
  for (const token of ["bg-primary", "bg-surface", "text-primary", "text-secondary", "text-muted", "border-muted", "accent-subtle", "bg-selected", "bg-elevated"]) {
    assert.ok(workspace.includes(`var(--${token})`), token);
  }
  assert.match(workspace, /cw-primary:disabled[^}]+var\(--bg-disabled\)/);
  assert.match(workspace, /cw-primary:disabled[^}]+opacity: 1/);
});
