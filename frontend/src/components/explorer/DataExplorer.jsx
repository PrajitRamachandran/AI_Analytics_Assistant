import { useMemo, useState } from "react";

function displayValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 6 });
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function label(value) {
  return String(value || "unknown").replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function StatGrid({ items, className = "" }) {
  return (
    <div className={`explorer-stat-grid ${className}`}>
      {items.map(([name, value]) => (
        <div className="explorer-stat" key={name}>
          <span>{name}</span>
          <strong>{displayValue(value)}</strong>
        </div>
      ))}
    </div>
  );
}

function PreviewTable({ rows }) {
  const columns = Object.keys(rows?.[0] || {});
  if (!rows?.length || !columns.length) return <p className="explorer-empty">No preview rows are available for this worksheet.</p>;
  return (
    <div className="explorer-table-scroll">
      <table className="explorer-table">
        <thead><tr><th className="row-number">#</th>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              <td className="row-number">{index + 1}</td>
              {columns.map((column) => <td key={column} title={displayValue(row[column])}>{displayValue(row[column])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProcessingAudit({ sheet }) {
  const columns = sheet.columns || [];
  return (
    <details className="explorer-audit">
      <summary>Normalisation audit <span>{columns.length} columns</span></summary>
      <div className="explorer-table-scroll">
        <table className="explorer-table">
          <thead><tr><th>Column</th><th>Original header</th><th>Detected meaning</th><th>Cells changed</th><th>Unparsed</th></tr></thead>
          <tbody>
            {columns.map((column) => (
              <tr key={column.name}>
                <td>{column.name}</td><td>{column.original_name || "—"}</td>
                <td>{label(column.normalization?.semantic_type || column.data_category)}</td>
                <td>{displayValue(column.normalization?.cells_changed ?? 0)}</td>
                <td>{displayValue(column.normalization?.unparseable_count ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {columns.some((column) => column.normalization?.notes?.length || column.normalization?.unparseable_samples?.length) && (
        <div className="explorer-audit-notes">
          {columns.filter((column) => column.normalization?.notes?.length || column.normalization?.unparseable_samples?.length).map((column) => (
            <div key={column.name}>
              <strong>{column.name}</strong>
              {column.normalization?.notes?.map((note, index) => <p key={index}>{note}</p>)}
              {column.normalization?.unparseable_samples?.length > 0 && <p>Preserved unparsed examples: {column.normalization.unparseable_samples.join(", ")}</p>}
            </div>
          ))}
        </div>
      )}
    </details>
  );
}

function ColumnProfile({ column }) {
  const stats = [
    ["Pandas dtype", column.pandas_dtype],
    ["Non-empty", column.non_null_count],
    ["Missing", column.missing_value_count],
    ["Blank strings", column.blank_string_count],
    ["Missing %", `${displayValue(column.missing_percentage)}%`],
    ["Unique values", column.unique_value_count],
    ["Unique %", `${displayValue(column.unique_value_percentage)}%`],
  ];
  return (
    <details className="explorer-column-profile">
      <summary>
        <span className="explorer-column-name">
          <strong>{column.column_name}</strong>
          {column.original_name !== column.column_name && <small>Original: {column.original_name}</small>}
        </span>
        <span className="explorer-tags">
          <span className={`explorer-type type-${column.inferred_type || "other"}`}>{label(column.inferred_type)}</span>
          <span className="explorer-role">{label(column.semantic_role)}</span>
        </span>
      </summary>
      <div className="explorer-column-body">
        <StatGrid items={stats} />
        {column.sample_values?.length > 0 && (
          <div className="explorer-detail">
            <h5>Sample values</h5>
            <div className="explorer-chips">{column.sample_values.map((value, index) => <span key={index}>{displayValue(value)}</span>)}</div>
          </div>
        )}
        {column.numerical_statistics && (
          <div className="explorer-detail">
            <h5>Numerical statistics</h5>
            <StatGrid items={[
              ["Minimum", column.numerical_statistics.minimum], ["Maximum", column.numerical_statistics.maximum],
              ["Mean", column.numerical_statistics.mean], ["Median", column.numerical_statistics.median],
              ["Total", column.numerical_statistics.total], ["Std. deviation", column.numerical_statistics.standard_deviation],
            ]}/>
          </div>
        )}
        {column.categorical_statistics && (
          <div className="explorer-detail">
            <h5>Category distribution <span>{displayValue(column.categorical_statistics.unique_category_count)} unique</span></h5>
            {column.categorical_statistics.most_frequent?.length ? (
              <div className="explorer-frequency">
                {column.categorical_statistics.most_frequent.map((item, index) => (
                  <div key={index}><span>{displayValue(item.value)}</span><strong>{displayValue(item.count)}</strong></div>
                ))}
              </div>
            ) : <p className="explorer-empty">No category frequencies available.</p>}
          </div>
        )}
        {column.date_statistics && (
          <div className="explorer-detail"><h5>Date range</h5><StatGrid items={[["Earliest", column.date_statistics.earliest], ["Latest", column.date_statistics.latest]]}/></div>
        )}
        {column.mixed_value_types?.length > 0 && (
          <div className="explorer-detail"><h5>Mixed underlying value types</h5><div className="explorer-chips">{column.mixed_value_types.map((type) => <span key={type}>{type}</span>)}</div></div>
        )}
      </div>
    </details>
  );
}

function WorksheetTabs({ worksheets, activeKey, onChange }) {
  return (
    <div className="explorer-worksheet-tabs" role="tablist" aria-label="Worksheets">
      {Object.entries(worksheets).map(([key, sheet]) => (
        <button key={key} role="tab" aria-selected={activeKey === key} className={activeKey === key ? "active" : ""} onClick={() => onChange(key)}>
          {sheet.worksheet_name || key}
        </button>
      ))}
    </div>
  );
}

export default function DataExplorer({
  processingResult, understandingResult, understandingId, understandingError,
  analyticsId, processedDatasetId, onUnderstand, onGenerateAnalytics,
  onCloseProcessing, onCloseUnderstanding, stage = "all",
}) {
  const processingSheets = processingResult?.worksheets || {};
  const profileSheets = understandingResult?.worksheets || {};
  const sheetSource = Object.keys(profileSheets).length ? profileSheets : processingSheets;
  const [selectedSheet, setSelectedSheet] = useState("");
  const activeKey = selectedSheet in sheetSource ? selectedSheet : Object.keys(sheetSource)[0] || "";
  const activeSheet = sheetSource[activeKey];
  const hasContent = stage === "processing" ? Boolean(processingResult) : stage === "profile" ? Boolean(understandingResult || understandingId || understandingError) : processingResult || understandingResult || understandingId || understandingError;
  const combinedStats = useMemo(() => {
    const processing = processingResult?.processing;
    if (!processing) return [];
    return [
      ["Worksheets", processing.total_worksheet_count],
      ["Processed", processing.successful_worksheet_count],
      ["Failed", processing.failed_worksheet_count],
      ["Normalised cells", processing.normalized_cell_count ?? 0],
      ["Unparsed cells", processing.unparseable_cell_count ?? 0],
    ];
  }, [processingResult]);

  if (!hasContent) return null;

  return (
    <section className="data-explorer-workspace" id="data-explorer-section" aria-labelledby="explorer-title">
      <header className="explorer-page-header">
        <div>
          <p className="eyebrow">{stage === "processing" ? "MODULE 2 · DATA PREPARATION" : stage === "profile" ? "MODULE 3 · DATA PROFILING" : "DATA WORKFLOW"}</p>
          <h2 id="explorer-title">{stage === "processing" ? "Processing results" : stage === "profile" ? "Dataset profile" : "Data Explorer"}</h2>
          <p className="subtitle">{understandingResult?.filename || processingResult?.filename || "Explore worksheet previews, normalisation and column-level statistics."}</p>
        </div>
        <div className="explorer-header-actions">
          {stage === "all" && processingResult && (
            <>
              <button className="understand-button" onClick={onGenerateAnalytics} disabled={Boolean(analyticsId) || !processedDatasetId}>
                {analyticsId ? "Generating analytics..." : "Generate analytics"}
              </button>
              <button className="understand-button" onClick={onUnderstand} disabled={!processedDatasetId || understandingId === processedDatasetId}>
                {understandingId === processedDatasetId ? "Profiling..." : understandingResult ? "Re-run understanding" : "Understand dataset"}
              </button>
            </>
          )}
          {stage === "all" && processingResult && <button className="refresh-button" onClick={onCloseProcessing}>Close processing</button>}
          {stage === "all" && understandingResult && <button className="refresh-button" onClick={onCloseUnderstanding}>Close profile</button>}
        </div>
      </header>

      {processingResult && stage !== "profile" && (
        <section className="explorer-panel">
          <div className="explorer-section-heading"><div><h3>Processing overview</h3><p>Workbook normalisation and data-quality results.</p></div><span className="explorer-status">Processed</span></div>
          <StatGrid items={combinedStats} className="explorer-processing-stats"/>
          {Object.keys(processingSheets).length > 0 && (
            <>
              <WorksheetTabs worksheets={processingSheets} activeKey={activeKey in processingSheets ? activeKey : Object.keys(processingSheets)[0]} onChange={setSelectedSheet}/>
              {(() => {
                const key = activeKey in processingSheets ? activeKey : Object.keys(processingSheets)[0];
                const sheet = processingSheets[key];
                if (!sheet) return null;
                return (
                  <div className="explorer-sheet-content">
                    <div className="explorer-section-heading"><div><h4>{sheet.worksheet_name || key}</h4><p>{displayValue(sheet.row_count)} rows · {displayValue(sheet.column_count)} columns</p></div></div>
                    <div className="explorer-chips">
                      {(sheet.columns || []).map((column) => <span key={column.name}>{column.name}<small>{label(column.data_category)}</small></span>)}
                    </div>
                    <StatGrid className="explorer-quality-stats" items={[
                      ["Empty rows removed", sheet.quality?.removed_empty_row_count],
                      ["Empty columns removed", sheet.quality?.removed_empty_column_count],
                      ["Duplicate rows retained", sheet.quality?.duplicate_row_count],
                      ["Missing cells", sheet.quality?.total_missing_value_count],
                      ["Blank strings", sheet.quality?.total_blank_string_count],
                      ["Whitespace-padded values", sheet.quality?.total_whitespace_padded_string_count],
                    ]}/>
                    <ProcessingAudit sheet={sheet}/>
                    <div className="explorer-section-heading preview-heading"><div><h4>Data preview</h4><p>Preview rows returned by the processing service.</p></div><span>{sheet.preview?.length || 0} rows</span></div>
                    <PreviewTable rows={sheet.preview || []}/>
                  </div>
                );
              })()}
            </>
          )}
          {Object.keys(processingResult.worksheet_errors || {}).length > 0 && <div className="status-message error"><strong>Some worksheets could not be processed</strong>{Object.entries(processingResult.worksheet_errors).map(([name, message]) => <p key={name}><strong>{name}:</strong> {message}</p>)}</div>}
        </section>
      )}

      {stage !== "processing" && understandingId && <div className="understanding-loading" role="status"><span className="loading-spinner"/><div><strong>Profiling your dataset...</strong><p>Calculating worksheet and column-level statistics.</p></div></div>}
      {stage !== "processing" && understandingError && <div className="status-message error" role="alert"><strong>Dataset understanding failed</strong><p>{understandingError}</p><button className="understand-button" onClick={onUnderstand} disabled={Boolean(understandingId)}>Try again</button></div>}

      {understandingResult && stage !== "processing" && (
        <section className="explorer-panel">
          <div className="explorer-section-heading"><div><h3>Dataset profile</h3><p>Statistical overview of the uploaded workbook.</p></div><span className="explorer-status">Profile complete</span></div>
          <StatGrid items={[
            ["Worksheets", understandingResult.total_worksheet_count],
            ["Successfully profiled", understandingResult.successful_worksheet_count],
            ["Failed", understandingResult.failed_worksheet_count],
          ]}/>
          {Object.keys(profileSheets).length > 0 ? (
            <>
              <WorksheetTabs worksheets={profileSheets} activeKey={activeKey in profileSheets ? activeKey : Object.keys(profileSheets)[0]} onChange={setSelectedSheet}/>
              {(() => {
                const key = activeKey in profileSheets ? activeKey : Object.keys(profileSheets)[0];
                const sheet = profileSheets[key];
                if (!sheet) return null;
                return (
                  <div className="explorer-sheet-content">
                    <div className="explorer-section-heading"><div><h4>{sheet.worksheet_name || key}</h4><p>{displayValue(sheet.row_count)} rows · {displayValue(sheet.column_count)} columns</p></div></div>
                    <StatGrid className="explorer-profile-stats" items={[
                      ["Numerical", sheet.numerical_column_count], ["Categorical", sheet.categorical_column_count],
                      ["Date", sheet.date_column_count], ["Text", sheet.text_column_count], ["Boolean", sheet.boolean_column_count],
                      ["Missing values", sheet.total_missing_value_count], ["Blank strings", sheet.total_blank_string_count], ["Duplicate rows", sheet.duplicate_row_count],
                    ]}/>
                    <div className="explorer-section-heading preview-heading"><div><h4>Column profiles</h4><p>Expand a column to inspect its statistics and sample values.</p></div><span>{sheet.columns?.length || 0} columns</span></div>
                    {sheet.columns?.length ? <div className="explorer-profile-list">{sheet.columns.map((column) => <ColumnProfile key={column.column_name} column={column}/>)}</div> : <p className="explorer-empty">No column profiles are available for this worksheet.</p>}
                  </div>
                );
              })()}
            </>
          ) : <p className="explorer-empty">No worksheet profiles are available.</p>}
          {Object.keys(understandingResult.worksheet_errors || {}).length > 0 && <div className="status-message error"><strong>Some worksheets could not be profiled</strong>{Object.entries(understandingResult.worksheet_errors).map(([name, message]) => <p key={name}><strong>{name}:</strong> {message}</p>)}</div>}
        </section>
      )}
    </section>
  );
}
