import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the DataAgentKit playground", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>DataAgentKit/);
  assert.match(html, /Ask your data/);
  assert.match(html, /Northstar Retail Agent/);
  assert.match(html, /Eval suite/);
  assert.match(html, /One repo/);
  assert.match(html, /og\.png/);
});

test("renders the zero-key query experience and quality gates", async () => {
  const html = await (await render()).text();
  assert.match(html, /Which region generated the most net revenue in 2026/);
  assert.match(html, /schema_columns/);
  assert.match(html, /sensitive_data_policy/);
  assert.match(html, /result_equivalence/);
  assert.match(html, /deterministic demo/);
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(source, /Victoria824\/DataAgentKit@v0\.2\.0/);
  assert.match(source, /Reproducible benchmark/);
});
