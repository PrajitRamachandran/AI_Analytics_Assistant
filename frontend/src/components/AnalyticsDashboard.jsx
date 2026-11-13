import { useMemo, useState } from "react";
import { filterCharts, getChartTypes } from "./analyticsUtils";
import "./AnalyticsDashboard.css";

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value ?? "—");
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

function safeData(chart) {
  return Array.isArray(chart?.data)
    ? chart.data.filter((point) => Number.isFinite(point?.value) && point?.label !== undefined)
    : [];
}

function BarChart({ chart }) {
  const data = safeData(chart);
  const max = Math.max(...data.map((point) => Math.abs(point.value)), 1);
  const width = 820;
  const rowHeight = 38;
  const height = Math.max(180, data.length * rowHeight + 48);
  const labelWidth = 190;
  const valueWidth = 85;
  const plotWidth = width - labelWidth - valueWidth - 30;

  return (
    <svg className="analytics-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={chart.title}>
      {data.map((point, index) => {
        const y = 24 + index * rowHeight;
        const barWidth = Math.max(2, (Math.abs(point.value) / max) * plotWidth);
        return (
          <g key={`${point.label}-${index}`}>
            <text x={labelWidth - 12} y={y + 19} textAnchor="end" className="chart-axis-label">
              {String(point.label).length > 24 ? `${String(point.label).slice(0, 21)}…` : point.label}
            </text>
            <rect x={labelWidth} y={y + 4} width={barWidth} height="22" rx="5" className="chart-bar" />
            <text x={Math.min(labelWidth + barWidth + 8, width - valueWidth)} y={y + 20} className="chart-value-label">
              {formatNumber(point.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function TrendChart({ chart, area = false }) {
  const data = safeData(chart);
  const width = 820;
  const height = 300;
  const left = 64;
  const right = 24;
  const top = 24;
  const bottom = 58;
  const values = data.map((point) => point.value);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 1);
  const range = max - min || 1;
  const x = (index) => left + (data.length <= 1 ? 0 : index * (width - left - right) / (data.length - 1));
  const y = (value) => top + (max - value) * (height - top - bottom) / range;
  const points = data.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const areaPoints = data.length ? `${x(0)},${height - bottom} ${points} ${x(data.length - 1)},${height - bottom}` : "";

  return (
    <svg className="analytics-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={chart.title}>
      {[0, 1, 2, 3].map((tick) => {
        const value = min + (range * tick) / 3;
        const yy = y(value);
        return (
          <g key={tick}>
            <line x1={left} x2={width - right} y1={yy} y2={yy} className="chart-grid-line" />
            <text x={left - 10} y={yy + 4} textAnchor="end" className="chart-axis-label">{formatNumber(value)}</text>
          </g>
        );
      })}
      {area && <polygon points={areaPoints} className="chart-area" />}
      <polyline points={points} className="chart-line" />
      {data.map((point, index) => (
        <g key={`${point.label}-${index}`}>
          <circle cx={x(index)} cy={y(point.value)} r="4.5" className="chart-point" />
          <text x={x(index)} y={height - 24} textAnchor="middle" className="chart-axis-label">
            {String(point.label).length > 12 ? `${String(point.label).slice(0, 10)}…` : point.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

function polarPoint(cx, cy, radius, angle) {
  return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
}

function PieChart({ chart, donut = false }) {
  const data = safeData(chart).filter((point) => point.value >= 0);
  const total = data.reduce((sum, point) => sum + point.value, 0);
  if (data.length < 2 || total <= 0) return <BarChart chart={chart} />;

  const cx = 180;
  const cy = 150;
  const radius = 112;
  let angle = -Math.PI / 2;
  const slices = data.map((point, index) => {
    const start = angle;
    const end = angle + (point.value / total) * Math.PI * 2;
    angle = end;
    const startPoint = polarPoint(cx, cy, radius, start);
    const endPoint = polarPoint(cx, cy, radius, end);
    const largeArc = end - start > Math.PI ? 1 : 0;
    const path = `M ${cx} ${cy} L ${startPoint.x} ${startPoint.y} A ${radius} ${radius} 0 ${largeArc} 1 ${endPoint.x} ${endPoint.y} Z`;
    return { ...point, index, path, share: (point.value / total) * 100 };
  });

  return (
    <div className="chart-pie-layout">
      <svg className="chart-pie-svg" viewBox="0 0 360 300" role="img" aria-label={chart.title}>
        {slices.map((slice) => (
          <path key={`${slice.label}-${slice.index}`} d={slice.path} className={`chart-slice chart-slice-${slice.index % 8}`}>
            <title>{`${slice.label}: ${formatNumber(slice.value)} (${slice.share.toFixed(1)}%)`}</title>
          </path>
        ))}
        {donut && <circle cx={cx} cy={cy} r="59" className="chart-donut-hole" />}
        {donut && <text x={cx} y={cy + 5} textAnchor="middle" className="chart-donut-total">{formatNumber(total)}</text>}
      </svg>
      <ul className="chart-legend">
        {slices.map((slice) => (
          <li key={`${slice.label}-${slice.index}`}>
            <span className={`chart-legend-swatch chart-slice-${slice.index % 8}`} />
            <span className="chart-legend-label">{slice.label}</span>
            <strong>{slice.share.toFixed(1)}%</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DataTable({ chart }) {
  const rows = Array.isArray(chart.table_data) ? chart.table_data : [];
  const columns = Array.isArray(chart.table_columns) && chart.table_columns.length
    ? chart.table_columns
    : Object.keys(rows[0] || {});
  return (
    <div className="analytics-table-wrap">
      <table className="analytics-data-table">
        <thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>{columns.map((column) => <td key={column}>{formatNumber(row[column])}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {chart.table_truncated && <p className="analytics-table-note">Showing the first 100 rows of this result.</p>}
    </div>
  );
}

function HistogramChart({ chart }) {
  const data = safeData(chart);
  const max = Math.max(...data.map((point) => point.value), 1);
  const width = 820;
  const height = 300;
  const left = 54;
  const right = 24;
  const top = 22;
  const bottom = 74;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const slot = data.length ? plotWidth / data.length : plotWidth;
  return (
    <svg className="analytics-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={chart.title}>
      {[0, 1, 2, 3].map((tick) => {
        const value = (max * tick) / 3;
        const y = top + plotHeight - (value / max) * plotHeight;
        return <g key={tick}>
          <line x1={left} x2={width - right} y1={y} y2={y} className="chart-grid-line" />
          <text x={left - 8} y={y + 4} textAnchor="end" className="chart-axis-label">{formatNumber(value)}</text>
        </g>;
      })}
      {data.map((point, index) => {
        const barHeight = (point.value / max) * plotHeight;
        const x = left + index * slot + slot * 0.08;
        return <g key={`${point.label}-${index}`}>
          <rect x={x} y={top + plotHeight - barHeight} width={Math.max(1, slot * 0.84)} height={barHeight} rx="3" className="chart-bar" />
          <text x={x + slot * 0.42} y={height - 45} textAnchor="middle" className="chart-axis-label">{String(point.label).slice(0, 18)}</text>
        </g>;
      })}
    </svg>
  );
}

function ScatterChart({ chart }) {
  const points = Array.isArray(chart.scatter_data) ? chart.scatter_data : [];
  if (!points.length) return <div className="analytics-empty-filter">No valid numeric pairs to plot.</div>;
  const width = 820;
  const height = 300;
  const left = 66;
  const right = 24;
  const top = 20;
  const bottom = 52;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  const px = (v) => left + ((v - minX) / rangeX) * (width - left - right);
  const py = (v) => top + ((maxY - v) / rangeY) * (height - top - bottom);
  return (
    <svg className="analytics-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={chart.title}>
      {[0, 1, 2, 3].map((tick) => {
        const yValue = minY + (rangeY * tick) / 3;
        const yy = py(yValue);
        return <g key={tick}>
          <line x1={left} x2={width - right} y1={yy} y2={yy} className="chart-grid-line" />
          <text x={left - 9} y={yy + 4} textAnchor="end" className="chart-axis-label">{formatNumber(yValue)}</text>
        </g>;
      })}
      {points.map((point, index) => <circle key={index} cx={px(point.x)} cy={py(point.y)} r="4" className="chart-scatter-dot">
        <title>{`${chart.x_label}: ${formatNumber(point.x)} · ${chart.y_label}: ${formatNumber(point.y)}`}</title>
      </circle>)}
      <text x={width / 2} y={height - 10} textAnchor="middle" className="chart-axis-label">{chart.x_label}</text>
      <text x="14" y={height / 2} transform={`rotate(-90 14 ${height / 2})`} textAnchor="middle" className="chart-axis-label">{chart.y_label}</text>
    </svg>
  );
}

function ChartRenderer({ chart }) {
  const hasData = chart.chart_type === "scatter"
    ? Array.isArray(chart.scatter_data) && chart.scatter_data.some((point) => Number.isFinite(point?.x) && Number.isFinite(point?.y))
    : chart.chart_type === "table"
      ? Array.isArray(chart.table_data) && chart.table_data.length > 0
      : safeData(chart).length > 0;

  if (!hasData) {
    return <div className="analytics-empty-filter">This analysis returned no valid values to visualise.</div>;
  }

  switch (chart.chart_type) {
    case "line": return <TrendChart chart={chart} />;
    case "area": return <TrendChart chart={chart} area />;
    case "pie": return <PieChart chart={chart} />;
    case "donut": return <PieChart chart={chart} donut />;
    case "table": return <DataTable chart={chart} />;
    case "scatter": return <ScatterChart chart={chart} />;
    case "histogram": return <HistogramChart chart={chart} />;
    case "bar": return <BarChart chart={chart} />;
    // Unknown future chart types remain inspectable as a table instead of
    // being silently misrepresented as a bar chart.
    default: return <DataTable chart={chart} />;
  }
}

export default function AnalyticsDashboard({ result }) {
  const [chartQuery, setChartQuery] = useState("");
  const [chartType, setChartType] = useState("all");
  const charts = useMemo(
    () => filterCharts(result?.charts || [], chartQuery, chartType),
    [result?.charts, chartQuery, chartType],
  );
  const availableChartTypes = useMemo(
    () => getChartTypes(result?.charts),
    [result?.charts],
  );
  if (!result) return null;

  return (
    <section className="analytics-dashboard">
      <div className="analytics-dashboard-heading">
        <div>
          <p className="eyebrow">MODULES 4–6 · DETERMINISTIC RESULTS</p>
          <h2>Analytics Dashboard</h2>
          <p className="subtitle">{result.filename} · {result.worksheet_count} worksheet(s) · {formatNumber(result.row_count)} rows analyzed</p>
        </div>
        <span className="analytics-status">Analysis complete</span>
      </div>

      {result.user_request && (
        <div className="analytics-request-summary">
          <strong>Requested analysis</strong>
          <p>{result.user_request}</p>
        </div>
      )}

      <div className="analytics-kpi-grid">
        {(result.kpis || []).map((kpi) => (
          <article className="analytics-kpi" key={kpi.id}>
            <span>{kpi.label}</span>
            <strong>{formatNumber(kpi.value)}</strong>
          </article>
        ))}
      </div>

      {Array.isArray(result.charts) && result.charts.length > 0 ? (
        <>
          <div className="analytics-chart-toolbar">
            <div>
              <h3>Charts & insights</h3>
              <p>{charts.length} of {result.charts.length} visualisations</p>
            </div>
            <div className="analytics-chart-filters">
              <label className="analytics-search">
                <span className="sr-only">Search charts</span>
                <input value={chartQuery} onChange={(event) => setChartQuery(event.target.value)} placeholder="Search charts..." />
              </label>
              <label className="analytics-type-filter">
                <span className="sr-only">Filter chart type</span>
                <select value={chartType} onChange={(event) => setChartType(event.target.value)}>
                  <option value="all">All chart types</option>
                  {availableChartTypes.map((type) => (
                    <option value={type} key={type}>{type.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase())}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          {charts.length > 0 ? <div className="analytics-chart-grid">
          {charts.map((chart) => (
            <article className="analytics-chart-card" key={chart.id}>
              <div className="analytics-chart-heading">
                <div>
                  <h3>{chart.title}</h3>
                  <p>{chart.description}</p>
                </div>
                <span>{chart.worksheet_name}</span>
              </div>
              <div className="analytics-chart-scroll"><ChartRenderer chart={chart} /></div>
              {chart.insight && <p className="analytics-chart-insight">{chart.insight}</p>}
              <p className="analytics-chart-footnote">{chart.x_label} · {chart.y_label} · Calculated from workbook rows</p>
            </article>
          ))}
          </div> : <div className="analytics-empty-filter">No charts match these filters. Try a different search or chart type.</div>}
        </>
      ) : (
        <div className="status-message info">
          {result.user_request
            ? "No chartable analysis could be generated for this request using the available dataset columns."
            : "Analytics completed, but this workbook did not produce a chartable grouped result. This can happen when the available columns are descriptive text, identifiers, or scalar-only measures."}
          {result.plan?.limitations?.length > 0 && (
            <ul>{result.plan.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>
          )}
        </div>
      )}

      <article className="analytics-operations-card">
        <h3>Executed analyses</h3>
        {Array.isArray(result.results) && result.results.length > 0 ? (
          result.results.map((item, index) => (
            <div className="analytics-operation-row" key={item.operation_id || index}>
              <div>
                <strong>{item.title || "Untitled analysis"}</strong>
                <span>{item.worksheet_name || "Unknown worksheet"} · {String(item.operation_type || "analysis").replaceAll("_", " ")}</span>
              </div>
              {item.value !== undefined ? <strong>{formatNumber(item.value)}</strong> : <span>{Array.isArray(item.records) ? item.records.length : 0} result row(s)</span>}
            </div>
          ))
        ) : <p className="empty-message">No analytical operations were necessary for this workbook.</p>}
      </article>
    </section>
  );
}
