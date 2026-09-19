import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

// Exercise the real TypeScript client without a browser, a running backend,
// external credentials, or paid provider requests.
function createClient(fetch, globals = {}) {
  const source = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(compiled, {
    exports,
    require: (name) => {
      assert.equal(name, "@/lib/toast");
      return { default: { error() {}, success() {} } };
    },
    process: { env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:8000" } },
    fetch, FormData, AbortController, URLSearchParams, setTimeout, clearTimeout, Error, TypeError, SyntaxError,
    console: { error() {}, warn() {} },
    ...globals,
  });
  return exports.apiClient;
}

test("every JSON request carries the local boundary header without account credentials", async () => {
  const calls = [];
  const client = createClient(async (url, options) => {
    calls.push({ url, options });
    return Response.json({ success: true, data: { saved: true } });
  });
  for (const method of ["get", "post", "put", "patch", "delete"]) {
    const response = await client[method]("/workspace");
    assert.equal(response.success, true);
  }
  assert.equal(calls.length, 5);
  for (const { url, options } of calls) {
    assert.equal(url, "http://127.0.0.1:8000/api/v1/workspace");
    assert.equal(options.headers["X-ClauseIQ-Local"], "1");
    assert.equal(options.headers["Content-Type"], "application/json");
    assert.equal(options.headers.Authorization, undefined);
  }
});

test("PDF uploads keep the local boundary and let the browser set multipart boundaries", async () => {
  let request;
  const client = createClient(async (_url, options) => {
    request = options;
    return Response.json({ success: true, data: { id: "fixture-document" } });
  });
  await client.uploadFile("/analysis/analyze/", new File(["%PDF-fixture"], "agreement.pdf", { type: "application/pdf" }));
  assert.equal(request.headers["X-ClauseIQ-Local"], "1");
  assert.equal(request.headers["Content-Type"], undefined);
  assert.ok(request.body instanceof FormData);
  assert.equal(request.body.get("file").name, "agreement.pdf");
});

test("access failures are surfaced without account refresh or a retry loop", async () => {
  let requests = 0;
  const client = createClient(async () => {
    requests += 1;
    return Response.json({ success: false, error: { code: "LOCAL_REQUEST_REQUIRED", message: "Local workspace access required" } }, { status: 403 });
  });
  const response = await client.get("/documents/");
  assert.equal(requests, 1);
  assert.equal(response.success, false);
  assert.equal(response.error.code, "LOCAL_REQUEST_REQUIRED");
});

test("the client preserves backend validation messages", async () => {
  const client = createClient(async () => Response.json({ detail: "Retention must be non-negative" }, { status: 422 }));
  const response = await client.put("/workspace/settings", { retention_days: -1 });
  assert.equal(response.success, false);
  assert.equal(response.error.message, "Retention must be non-negative");
});

test("workspace network diagnostics contain only allowlisted transport metadata", async () => {
  const messages = [];
  const client = createClient(async () => { throw new Error("private filename and key must not be logged"); }, {
    console: { error: (...args) => messages.push(args) }, navigator: { onLine: false },
  });
  const response = await client.get("/documents/private-id/source", undefined, { diagnosticScope: "workspace-source" });
  assert.equal(response.error.code, "NETWORK_ERROR");
  assert.equal(response.error.message, "The local API could not be reached.");
  assert.equal(messages.length, 1);
  const [label, serialized] = messages[0];
  const fields = JSON.parse(serialized);
  assert.equal(label, "Workspace read failed");
  assert.deepEqual(Object.keys(fields).sort(), ["category", "elapsedMs", "online", "phase", "resource"]);
  assert.equal(fields.category, "network");
  assert.equal(fields.resource, "workspace-source");
  assert.equal(fields.online, false);
  assert.equal(fields.phase, "headers");
  assert.doesNotMatch(JSON.stringify(messages), /private|key|\/documents|http:/);
});

test("explicit read cancellation aborts once and stays separate from failures", async () => {
  const messages = [];
  const controller = new AbortController();
  let calls = 0;
  const client = createClient((_url, { signal }) => new Promise((_resolve, reject) => {
    calls++;
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  }), { console: { error: (...args) => messages.push(args) } });
  const pending = client.get("/documents/fixture/source", undefined, {
    signal: controller.signal, timeout: 20000, diagnosticScope: "workspace-source",
  });
  controller.abort();
  const response = await pending;
  assert.equal(response.error.code, "REQUEST_CANCELLED");
  assert.equal(calls, 1);
  assert.deepEqual(messages, []);
});

test("workspace timeouts are bounded and reported without an automatic retry or URL", async () => {
  let timeout;
  let calls = 0;
  let cleared = 0;
  const messages = [];
  const client = createClient((_url, { signal }) => new Promise((_resolve, reject) => {
    calls++;
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  }), {
    setTimeout(callback, ms) { assert.equal(ms, 20000); timeout = callback; return 1; },
    clearTimeout() { cleared++; }, console: { error: (...args) => messages.push(args) },
  });
  const pending = client.get("/documents/private-id/source", undefined, { timeout: 20000, diagnosticScope: "workspace-source" });
  timeout();
  const response = await pending;
  assert.equal(response.error.code, "REQUEST_TIMEOUT");
  assert.equal(response.error.details.url, undefined);
  assert.equal(JSON.parse(messages[0][1]).category, "timeout");
  assert.equal(calls, 1);
  assert.equal(cleared, 1);
});

test("workspace read timeout includes stalled response bodies but does not alter write timeout semantics", async () => {
  for (const method of ["get", "post"]) {
    let timeout;
    let cleared = false;
    let finish;
    const client = createClient(async (_url, { signal }) => ({ status: 200, ok: true,
      json: () => new Promise((resolve, reject) => {
        finish = resolve;
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      }),
    }), {
      setTimeout(callback) { timeout = callback; return 1; },
      clearTimeout() { cleared = true; },
    });
    const options = { timeout: 20000, ...(method === "get" ? { diagnosticScope: "workspace-source" } : {}) };
    const pending = client[method]("/fixture", undefined, options);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(typeof finish, "function");
    assert.equal(cleared, method === "post");
    if (method === "get") timeout();
    else finish({ success: true, data: { saved: true } });
    const result = await pending;
    assert.equal(result.success, method === "post");
    if (method === "get") assert.equal(result.error.code, "REQUEST_TIMEOUT");
  }
});

test("HTTP failure diagnostics never log backend error fields or resource identifiers", async () => {
  const messages = [];
  const client = createClient(async () => Response.json({ detail: "private source body" }, { status: 503 }), {
    console: { error: (...args) => messages.push(args) },
  });
  const result = await client.get("/documents/private-id", undefined, { diagnosticScope: "workspace-metadata" });
  assert.equal(result.success, false);
  assert.equal(messages.length, 1);
  assert.equal(JSON.parse(messages[0][1]).category, "http");
  assert.equal(JSON.parse(messages[0][1]).status, 503);
  assert.equal(JSON.parse(messages[0][1]).phase, "body");
  assert.doesNotMatch(JSON.stringify(messages), /private|detail|\/documents/);
});

test("workspace-state body failures have readable phase diagnostics without response content", async () => {
  const messages = [];
  const client = createClient(async () => ({ status: 200, ok: true,
    json: async () => { throw new Error("private response text"); },
  }), { console: { error: (...args) => messages.push(args) } });
  const result = await client.get("/documents/private-id/review-workspace", undefined,
    { diagnosticScope: "workspace-state" });
  assert.equal(result.error.code, "PARSE_ERROR");
  const fields = JSON.parse(messages.find(([label]) => label === "Workspace read failed")[1]);
  assert.equal(fields.resource, "workspace-state");
  assert.equal(fields.category, "response-format");
  assert.equal(fields.phase, "body");
  assert.equal(fields.status, 200);
  assert.doesNotMatch(JSON.stringify(messages), /private|response text|\/documents/);
});

test("workspace body transport failures are distinct from invalid JSON and retain status safely", async () => {
  for (const [error, code, category] of [
    [new TypeError("private body stream detail"), "NETWORK_ERROR", "network"],
    [new SyntaxError("private response JSON excerpt"), "PARSE_ERROR", "response-format"],
  ]) {
    const messages = [];
    let calls = 0;
    const client = createClient(async () => {
      calls++;
      return { status: 200, ok: true, json: async () => { throw error; } };
    }, { console: { error: (...args) => messages.push(args) } });
    const result = await client.get("/documents/private-id/source", undefined,
      { diagnosticScope: "workspace-source" });
    assert.equal(result.error.code, code);
    assert.equal(result.error.details.status, 200);
    const fields = JSON.parse(messages.find(([label]) => label === "Workspace read failed")[1]);
    assert.equal(fields.category, category);
    assert.equal(fields.phase, "body");
    assert.equal(fields.status, 200);
    assert.equal(calls, 1);
    assert.doesNotMatch(JSON.stringify(messages), /private|stream detail|JSON excerpt|\/documents/);
    if (code === "NETWORK_ERROR") {
      assert.equal(result.error.message, "The local API response could not be fully read.");
      assert.deepEqual(Object.keys(result.error.details), ["status"]);
    }
  }
});

test("legacy body failures and invalid decoded envelopes keep response-format semantics", async () => {
  for (const workspaceRead of [false, true]) {
    const client = createClient(async () => ({ status: 200, ok: true, json: async () => {
      if (!workspaceRead) throw new TypeError("legacy body detail");
      return null;
    } }));
    const result = await client.get("/fixture", undefined,
      workspaceRead ? { diagnosticScope: "workspace-source" } : undefined);
    assert.equal(result.error.code, "PARSE_ERROR");
    assert.equal(result.error.details.status, 200);
    if (!workspaceRead) assert.equal(result.error.details.parseError, "legacy body detail");
  }
});

test("body transport classification does not swallow caller cancellation or read timeout", async () => {
  for (const cancellation of ["caller", "timeout"]) {
    const controller = new AbortController();
    const messages = [];
    let timeout;
    let calls = 0;
    const client = createClient(async (_url, { signal }) => {
      calls++;
      return { status: 200, ok: true, json: () => new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new TypeError("private interrupted body")));
      }) };
    }, {
      setTimeout(callback) { timeout = callback; return 1; }, clearTimeout() {},
      console: { error: (...args) => messages.push(args) },
    });
    const pending = client.get("/documents/private-id/source", undefined, {
      signal: controller.signal, timeout: 20000, diagnosticScope: "workspace-source",
    });
    await new Promise(resolve => setImmediate(resolve));
    if (cancellation === "caller") controller.abort();
    else timeout();
    const result = await pending;
    assert.equal(result.error.code, cancellation === "caller" ? "REQUEST_CANCELLED" : "REQUEST_TIMEOUT");
    assert.equal(calls, 1);
    if (cancellation === "caller") assert.deepEqual(messages, []);
    else {
      const fields = JSON.parse(messages[0][1]);
      assert.equal(fields.category, "timeout");
      assert.equal(fields.phase, "body");
    }
    assert.doesNotMatch(JSON.stringify(messages), /private|interrupted body|\/documents/);
  }
});
