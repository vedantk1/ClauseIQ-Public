import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

// Exercise the real TypeScript client without a browser, a running backend,
// external credentials, or paid provider requests.
function createClient(fetch) {
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
    fetch, FormData, AbortController, URLSearchParams, setTimeout, clearTimeout,
    console: { error() {}, warn() {} },
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
