import test from "node:test";
import assert from "node:assert/strict";
import { resolveRoute, PAGE_META, NAV_GROUPS } from "./routeConfig.js";

test("resolves primary workspace routes", () => {
  assert.equal(resolveRoute("/").id, "overview");
  assert.equal(resolveRoute("/upload").id, "upload");
  assert.equal(resolveRoute("/datasets").id, "datasets");
  assert.equal(resolveRoute("/settings").id, "settings");
});

test("resolves dataset-scoped workflow routes and decodes identifiers", () => {
  assert.deepEqual(resolveRoute("/datasets/sales%20data/processing"), {
    id: "processing",
    datasetId: "sales data",
  });
  assert.equal(resolveRoute("/datasets/abc/profile").id, "profile");
  assert.equal(resolveRoute("/datasets/abc/analytics").id, "analytics");
});

test("returns a not-found route for unknown paths", () => {
  assert.equal(resolveRoute("/unknown").id, "notFound");
  assert.ok(PAGE_META.overview);
  assert.ok(NAV_GROUPS.some((group) => group.items.some((item) => item.path === "/datasets")));
});
