export function filterCharts(charts, query = "", chartType = "all") {
  const normalizedQuery = String(query || "").trim().toLowerCase();
  return (Array.isArray(charts) ? charts : []).filter((chart) => {
    const typeMatches = chartType === "all" || chart.chart_type === chartType;
    const searchable = [chart.title, chart.description, chart.worksheet_name, chart.chart_type]
      .filter(Boolean).join(" ").toLowerCase();
    return typeMatches && (!normalizedQuery || searchable.includes(normalizedQuery));
  });
}

export function formatMetric(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number" && Number.isFinite(value)) {
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
  }
  return String(value);
}
