import test from "node:test";
import assert from "node:assert/strict";
import { formatDate, formatFileSize, isStageComplete } from "./datasetFormatters.js";

test("formatFileSize formats bytes, kilobytes, and megabytes", () => {
  assert.equal(formatFileSize(0), "0 B");
  assert.equal(formatFileSize(1024), "1.00 KB");
  assert.equal(formatFileSize(1024 * 1024), "1.00 MB");
});

test("formatDate handles missing and invalid timestamps safely", () => {
  assert.equal(formatDate(null), "Unknown");
  assert.equal(formatDate("not-a-date"), "Unknown");
  assert.notEqual(formatDate("2026-01-01T00:00:00Z"), "Unknown");
});

test("isStageComplete recognises completed workflow stages only", () => {
  assert.equal(isStageComplete("processed"), true);
  assert.equal(isStageComplete("understood"), true);
  assert.equal(isStageComplete("analysed"), true);
  assert.equal(isStageComplete("pending"), false);
  assert.equal(isStageComplete(undefined), false);
});
