import test from "node:test";
import assert from "node:assert/strict";
import { filterCharts, formatMetric, getChartTypes } from "./analyticsUtils.js";

const charts = [
  { id: "a", title: "Revenue by month", chart_type: "line", worksheet_name: "Sales" },
  { id: "b", title: "Orders by region", chart_type: "bar", worksheet_name: "Orders" },
  { id: "c", title: "Revenue share", chart_type: "donut", worksheet_name: "Sales" },
];

test("filters charts by title and worksheet without mutating input", () => {
  assert.deepEqual(filterCharts(charts, "sales").map((chart) => chart.id), ["a", "c"]);
  assert.equal(charts.length, 3);
});

test("filters charts by type and combined query", () => {
  assert.deepEqual(filterCharts(charts, "revenue", "line").map((chart) => chart.id), ["a"]);
  assert.deepEqual(filterCharts(charts, "", "bar").map((chart) => chart.id), ["b"]);
});

test("returns no charts for unmatched queries and formats KPI values", () => {
  assert.deepEqual(filterCharts(charts, "not found"), []);
  assert.equal(formatMetric(12500.126), "12,500.13");
  assert.equal(formatMetric(null), "—");
});

test("discovers chart filter options from actual chart payloads", () => {
  assert.deepEqual(getChartTypes([...charts, { chart_type: "heatmap" }, { chart_type: "bar" }]), [
    "bar", "donut", "heatmap", "line",
  ]);
});
