import test from "node:test";
import assert from "node:assert/strict";
import { ACCENTS, DEFAULT_SETTINGS, normalizeSettings } from "./appearanceUtils.js";

test("normalizes valid saved appearance settings", () => {
  assert.deepEqual(normalizeSettings({
    mode: "dark", accent: "violet", customAccent: "#aabbcc",
    density: "compact", reduceMotion: true,
  }), {
    mode: "dark", accent: "violet", customAccent: "#aabbcc",
    density: "compact", reduceMotion: true,
  });
});

test("falls back safely for invalid or malformed stored preferences", () => {
  assert.deepEqual(normalizeSettings(null), { ...DEFAULT_SETTINGS });
  assert.deepEqual(normalizeSettings({
    mode: "neon", accent: "not-a-preset", customAccent: "red",
    density: "wide", reduceMotion: "yes",
  }), { ...DEFAULT_SETTINGS });
});

test("accepts custom accents and supported preset colours only", () => {
  assert.equal(normalizeSettings({ accent: "custom", customAccent: "#AbC" }).accent, "custom");
  assert.equal(normalizeSettings({ accent: "custom", customAccent: "rgb(1,2,3)" }).customAccent, "#2563eb");
  assert.equal(ACCENTS.slate, "#475569");
});
