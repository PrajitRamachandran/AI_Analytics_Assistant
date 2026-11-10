
import { useEffect, useState } from "react";
import api from "./services/api";
import AnalyticsDashboard from "./components/AnalyticsDashboard";
import "./App.css";

// Allows two bounded local-LLM attempts plus workbook processing overhead.
const ANALYTICS_REQUEST_TIMEOUT_MS = 21 * 60 * 1000;

// Convert file size into a readable format
function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(2)} KB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

// Format uploaded timestamp
function formatDate(date) {
  if (!date) return "Unknown";

  return new Date(date).toLocaleString();
}


// Render profile values safely without exposing raw JSON objects.
function formatProfileValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, {
      maximumFractionDigits: 6,
    });
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatProfileLabel(value) {
  return String(value || "unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function ProfileStat({ label, value }) {
  return (
    <div className="profile-stat">
      <span>{label}</span>
      <strong>{formatProfileValue(value)}</strong>
    </div>
  );
}

function App() {
  const [file, setFile] = useState(null);

  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);

  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const [datasets, setDatasets] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [historyError, setHistoryError] = useState("");

  const [actionError, setActionError] = useState("");
  const [actionSuccess, setActionSuccess] = useState("");

  const [deletingId, setDeletingId] = useState(null);
  const [downloadingId, setDownloadingId] = useState(null);
  const [processingId, setProcessingId] = useState(null);
  const [processingResult, setProcessingResult] = useState(null);
  const [processedDatasetId, setProcessedDatasetId] = useState(null);

  const [understandingResult, setUnderstandingResult] = useState(null);
  const [understandingId, setUnderstandingId] = useState(null);
  const [understandingError, setUnderstandingError] = useState("");
  const [analyticsResult, setAnalyticsResult] = useState(null);
  const [analyticsId, setAnalyticsId] = useState(null);
  const [analyticsError, setAnalyticsError] = useState("");

  // Retrieve uploaded datasets from FastAPI
  const fetchDatasets = async () => {
    setLoadingHistory(true);
    setHistoryError("");

    try {
      const response = await api.get("/api/datasets");

      setDatasets(response.data.datasets);
    } catch (err) {
      setHistoryError(
        err.response?.data?.detail ||
        "Unable to retrieve uploaded files."
      );
    } finally {
      setLoadingHistory(false);
    }
  };

  // Initial history loading when the application opens
  useEffect(() => {
    let ignore = false;

    api.get("/api/datasets")
      .then((response) => {
        if (!ignore) {
          setDatasets(response.data.datasets);
        }
      })
      .catch((err) => {
        if (!ignore) {
          setHistoryError(
            err.response?.data?.detail ||
            "Unable to retrieve uploaded files."
          );
        }
      })
      .finally(() => {
        if (!ignore) {
          setLoadingHistory(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, []);

  // Handle file selection and basic validation
  const handleFileChange = (selectedFile) => {
    setResult(null);
    setError("");
    setProgress(0);
    setActionError("");
    setActionSuccess("");

    if (!selectedFile) {
      setFile(null);
      return;
    }

    if (!selectedFile.name.toLowerCase().endsWith(".xlsx")) {
      setFile(null);
      setError("Only .xlsx files are currently supported.");
      return;
    }

    if (selectedFile.size === 0) {
      setFile(null);
      setError("The selected file is empty.");
      return;
    }

    if (selectedFile.size > 25 * 1024 * 1024) {
      setFile(null);
      setError("File exceeds the maximum size of 25 MB.");
      return;
    }

    setFile(selectedFile);
  };

  // Upload the selected Excel workbook
  const handleUpload = async () => {
    if (!file) return;

    setUploading(true);
    setError("");
    setResult(null);
    setProgress(0);
    setActionError("");
    setActionSuccess("");

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await api.post(
        "/api/upload",
        formData,
        {
          onUploadProgress: (event) => {
            if (event.total) {
              setProgress(
                Math.round(
                  (event.loaded * 100) / event.total
                )
              );
            }
          },
        }
      );

      setResult(response.data);
      setFile(null);
      setProgress(100);

      // Refresh history after a successful upload
      await fetchDatasets();

    } catch (err) {
      setError(
        err.response?.data?.detail ||
        err.message ||
        "Upload failed. Please try again."
      );
    } finally {
      setUploading(false);
    }
  };

  // Download an uploaded Excel workbook
  const handleDownload = async (dataset) => {
    setDownloadingId(dataset.dataset_id);
    setActionError("");
    setActionSuccess("");

    try {
      const response = await api.get(
        `/api/datasets/${dataset.dataset_id}/download`,
        {
          responseType: "blob",
        }
      );

      const blobUrl = window.URL.createObjectURL(
        response.data
      );

      const link = document.createElement("a");

      link.href = blobUrl;
      link.download = dataset.filename;

      document.body.appendChild(link);
      link.click();
      link.remove();

      // Release the temporary browser URL
      window.setTimeout(() => {
        window.URL.revokeObjectURL(blobUrl);
      }, 1000);

      setActionSuccess(
        `${dataset.filename} downloaded successfully.`
      );

    } catch {
  setActionError(
    "Unable to download this file. Please try again."
  );
} finally {
      setDownloadingId(null);
    }
  };


  // Process an uploaded workbook through Module 2
  const handleProcess = async (dataset) => {
    setProcessingId(dataset.dataset_id);
    setProcessingResult(null);
    setProcessedDatasetId(null);
    setUnderstandingResult(null);
    setUnderstandingError("");
    setAnalyticsResult(null);
    setAnalyticsError("");
    setActionError("");
    setActionSuccess("");

    try {
      const response = await api.post(
        `/api/datasets/${dataset.dataset_id}/process`,
        {},
        { timeout: 120000 }
      );

      setProcessingResult(response.data);
      setProcessedDatasetId(dataset.dataset_id);
      setActionSuccess(`${dataset.filename} processed successfully.`);
      await fetchDatasets();

    } catch (err) {
      setActionError(
        err.response?.data?.detail ||
        "Unable to process this workbook. Please try again."
      );
    } finally {
      setProcessingId(null);
    }
  };

  // Generate Module 3 data understanding for a successfully processed dataset.
  const handleUnderstand = async () => {
    if (!processedDatasetId) return;

    setUnderstandingId(processedDatasetId);
    setUnderstandingError("");
    setUnderstandingResult(null);
    setAnalyticsResult(null);
    setAnalyticsError("");
    setActionError("");
    setActionSuccess("");

    try {
      const response = await api.post(
        `/api/datasets/${processedDatasetId}/understand`,
        {},
        { timeout: 120000 }
      );

      setUnderstandingResult(response.data);
      setActionSuccess(`${response.data.filename} profiled successfully.`);
    } catch (err) {
      setUnderstandingError(
        err.response?.data?.detail ||
        "Unable to understand this dataset. Please try again."
      );
    } finally {
      setUnderstandingId(null);
    }
  };

  // Generate a validated Module 4 plan, execute it deterministically, and return chart data.
  const handleGenerateAnalytics = async () => {
    if (!processedDatasetId) return;

    setAnalyticsId(processedDatasetId);
    setAnalyticsError("");
    setAnalyticsResult(null);
    setActionError("");
    setActionSuccess("");

    try {
      const response = await api.post(
        `/api/datasets/${processedDatasetId}/analytics`,
        {},
        { timeout: ANALYTICS_REQUEST_TIMEOUT_MS }
      );
      setAnalyticsResult(response.data);
      setActionSuccess("Analytics generated and executed successfully.");
    } catch (err) {
      setAnalyticsError(
        err.response?.data?.detail ||
        err.message ||
        "Unable to generate analytics. Please check the backend and Ollama."
      );
    } finally {
      setAnalyticsId(null);
    }
  };

  // Delete an uploaded Excel workbook
  const handleDelete = async (dataset) => {
    const confirmed = window.confirm(
      `Are you sure you want to delete "${dataset.filename}"?\n\nThis will permanently delete the stored file and its database record.`
    );

    if (!confirmed) return;

    setDeletingId(dataset.dataset_id);
    setActionError("");
    setActionSuccess("");

    try {
      await api.delete(
        `/api/datasets/${dataset.dataset_id}`
      );

      if (processedDatasetId === dataset.dataset_id) {
        setProcessingResult(null);
        setProcessedDatasetId(null);
        setUnderstandingResult(null);
        setUnderstandingError("");
        setAnalyticsResult(null);
        setAnalyticsError("");
      }

      setActionSuccess(
        `${dataset.filename} deleted successfully.`
      );

      await fetchDatasets();

    } catch (err) {
      setActionError(
        err.response?.data?.detail ||
        "Unable to delete the selected file."
      );
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <main className="app-container">

      {/* Application Header */}
      <header className="app-header">
        <div>
          <p className="eyebrow">
            AI DATA ANALYTICS ASSISTANT
          </p>

          <h1>Data Workspace</h1>

          <p className="subtitle">
            Upload your Excel workbooks and manage your datasets.
          </p>
        </div>
      </header>


      {/* Excel Upload Section */}
      <section className="upload-card">

        <div className="upload-icon">📊</div>

        <h2>Upload Excel Workbook</h2>

        <p className="upload-description">
          Select an Excel file to get started with your analysis.
        </p>

        <label className="file-picker">
          Choose Excel File

          <input
            type="file"
            accept=".xlsx"
            onChange={(event) =>
              handleFileChange(event.target.files?.[0])
            }
            disabled={uploading}
          />
        </label>

        <p className="file-hint">
          Supported format: .xlsx · Maximum size: 25 MB
        </p>


        {/* Selected File */}
        {file && (
          <div className="selected-file">
            <span>📄</span>

            <div className="file-details">
              <strong>{file.name}</strong>

              <small>
                {formatFileSize(file.size)}
              </small>
            </div>
          </div>
        )}


        {/* Upload Progress */}
        {uploading && (
          <div className="progress-section">

            <div className="progress-label">
              <span>Uploading...</span>
              <span>{progress}%</span>
            </div>

            <div className="progress-track">
              <div
                className="progress-fill"
                style={{ width: `${progress}%` }}
              />
            </div>

          </div>
        )}


        {/* Upload Button */}
        <button
          className="upload-button"
          onClick={handleUpload}
          disabled={!file || uploading}
        >
          {uploading ? "Uploading..." : "Upload File"}
        </button>


        {/* Upload Error */}
        {error && (
          <div className="status-message error">
            <strong>Upload Failed</strong>
            <p>{error}</p>
          </div>
        )}


        {/* Upload Success */}
        {result && (
          <div className="status-message success">
            <strong>Upload Successful!</strong>

            <p>{result.filename}</p>

            <small>
              Dataset ID: {result.dataset_id}
            </small>
          </div>
        )}

      </section>


      {/* Uploaded Files History */}
      <section className="history-section">

        <div className="history-header">

          <div>
            <h2>Uploaded Files</h2>

            <p className="subtitle">
              Your previously uploaded datasets.
            </p>
          </div>

          <button
            className="refresh-button"
            onClick={fetchDatasets}
            disabled={loadingHistory}
          >
            {loadingHistory ? "Refreshing..." : "↻ Refresh"}
          </button>

        </div>


        <div className="history-card">

          {/* Loading */}
          {loadingHistory ? (
            <p className="empty-message">
              Loading your datasets...
            </p>

          ) : historyError ? (

            /* History Error */
            <div className="status-message error">
              <strong>Unable to load history</strong>
              <p>{historyError}</p>
            </div>

          ) : datasets.length === 0 ? (

            /* Empty State */
            <div className="empty-state">
              <span>📂</span>

              <h3>No uploaded files yet</h3>

              <p>
                Your uploaded Excel files will appear here.
              </p>
            </div>

          ) : (

            /* Dataset Table */
            <>
              <div className="dataset-summary">
                <strong>
                  {datasets.length} dataset(s)
                </strong>
              </div>

              <div className="table-wrapper">

                <table className="dataset-table">

                  <thead>
                    <tr>
                      <th>Filename</th>
                      <th>Size</th>
                      <th>Uploaded At</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>

                  <tbody>
                    {datasets.map((dataset) => (

                      <tr key={dataset.dataset_id}>

                        <td className="filename-cell">
                          📄 {dataset.filename}
                        </td>

                        <td>
                          {formatFileSize(dataset.file_size)}
                        </td>

                        <td>
                          {formatDate(dataset.uploaded_at)}
                        </td>

                        <td>
                          <span className="status-badge">
                            {dataset.status}
                          </span>
                        </td>

                        <td>
                          <div className="action-buttons">

                            <button
                              className="process-button"
                              onClick={() => handleProcess(dataset)}
                              disabled={processingId === dataset.dataset_id}
                            >
                              {processingId === dataset.dataset_id
                                ? "Processing..."
                                : "⚙ Process"}
                            </button>

                            <button
                              className="download-button"
                              onClick={() =>
                                handleDownload(dataset)
                              }
                              disabled={
                                downloadingId === dataset.dataset_id
                              }
                            >
                              {downloadingId === dataset.dataset_id
                                ? "Downloading..."
                                : "↓ Download"}
                            </button>

                            <button
                              className="delete-button"
                              onClick={() =>
                                handleDelete(dataset)
                              }
                              disabled={
                                deletingId === dataset.dataset_id
                              }
                            >
                              {deletingId === dataset.dataset_id
                                ? "Deleting..."
                                : "Delete"}
                            </button>

                          </div>
                        </td>

                      </tr>

                    ))}
                  </tbody>

                </table>

              </div>
            </>
          )}

        </div>

        {/* Module 2 Processing Results */}
        {processingResult && (
          <section className="processing-results">
            <div className="processing-results-header">
              <div>
                <h2>Processing Results</h2>
                <p className="subtitle">{processingResult.filename}</p>
              </div>

              <div className="processing-header-actions">
                <button
                  className="understand-button"
                  onClick={handleGenerateAnalytics}
                  disabled={Boolean(analyticsId) || !processedDatasetId}
                >
                  {analyticsId ? "Generating analytics..." : "✦ Generate Analytics Dashboard"}
                </button>
                <button
                  className="understand-button"
                  onClick={handleUnderstand}
                  disabled={!processedDatasetId || understandingId === processedDatasetId}
                >
                  {understandingId === processedDatasetId
                    ? "Understanding..."
                    : understandingResult
                      ? "↻ Re-run Understanding"
                      : "✦ Understand Dataset"}
                </button>

                <button
                  className="refresh-button"
                  onClick={() => setProcessingResult(null)}
                >
                  Close
                </button>
              </div>
            </div>

            <div className="processing-summary">
              <div>
                <strong>{processingResult.processing.total_worksheet_count}</strong>
                <span>Total worksheets</span>
              </div>
              <div>
                <strong>{processingResult.processing.successful_worksheet_count}</strong>
                <span>Processed</span>
              </div>
              <div>
                <strong>{processingResult.processing.failed_worksheet_count}</strong>
                <span>Failed</span>
              </div>
              <div>
                <strong>{processingResult.processing.normalized_cell_count ?? 0}</strong>
                <span>Values normalised</span>
              </div>
              <div>
                <strong>{processingResult.processing.unparseable_cell_count ?? 0}</strong>
                <span>Unparsed values preserved</span>
              </div>
            </div>

            {Object.values(processingResult.worksheets).map((sheet) => (
              <article className="sheet-result-card" key={sheet.worksheet_name}>
                <div className="sheet-result-heading">
                  <h3>{sheet.worksheet_name}</h3>
                  <span>
                    {sheet.row_count} rows · {sheet.column_count} columns
                  </span>
                </div>

                <div className="column-chip-list">
                  {sheet.columns.map((column) => (
                    <span className="column-chip" key={column.name} title={`Original: ${column.original_name}`}>
                      {column.name}
                      <small>{column.data_category}</small>
                    </span>
                  ))}
                </div>

                <div className="quality-summary">
                  <span>Empty rows removed: {sheet.quality.removed_empty_row_count}</span>
                  <span>Empty columns removed: {sheet.quality.removed_empty_column_count}</span>
                  <span>Duplicate rows found: {sheet.quality.duplicate_row_count} (retained by default)</span>
                  <span>Missing cells: {sheet.quality.total_missing_value_count}</span>
                  <span>Blank strings: {sheet.quality.total_blank_string_count}</span>
                  <span>Whitespace-padded values: {sheet.quality.total_whitespace_padded_string_count}</span>
                </div>

                <details className="processing-audit">
                  <summary>View normalisation audit</summary>
                  <div className="table-wrapper">
                    <table className="dataset-table audit-table">
                      <thead>
                        <tr>
                          <th>Column</th>
                          <th>Original header</th>
                          <th>Detected meaning</th>
                          <th>Cells changed</th>
                          <th>Unparsed values</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sheet.columns.map((column) => (
                          <tr key={column.name}>
                            <td>{column.name}</td>
                            <td>{column.original_name}</td>
                            <td>{formatProfileLabel(column.normalization?.semantic_type || column.data_category)}</td>
                            <td>{column.normalization?.cells_changed ?? 0}</td>
                            <td>{column.normalization?.unparseable_count ?? 0}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {sheet.columns.some((column) => column.normalization?.notes?.length || column.normalization?.unparseable_samples?.length) && (
                    <div className="normalization-notes">
                      {sheet.columns.filter((column) => column.normalization?.notes?.length || column.normalization?.unparseable_samples?.length).map((column) => (
                        <div key={column.name}>
                          <strong>{column.name}</strong>
                          {column.normalization?.notes?.map((note, index) => <p key={index}>{note}</p>)}
                          {column.normalization?.unparseable_samples?.length > 0 && (
                            <p>Preserved unparsed examples: {column.normalization.unparseable_samples.join(", ")}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </details>

                {sheet.preview.length > 0 ? (
                  <div className="table-wrapper preview-wrapper">
                    <table className="dataset-table preview-table">
                      <thead>
                        <tr>
                          {Object.keys(sheet.preview[0]).map((column) => (
                            <th key={column}>{column}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {sheet.preview.map((row, rowIndex) => (
                          <tr key={rowIndex}>
                            {Object.keys(sheet.preview[0]).map((column) => (
                              <td key={column}>
                                {row[column] === null ? "—" : String(row[column])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="empty-message">No data rows available for preview.</p>
                )}
              </article>
            ))}

            {Object.keys(processingResult.worksheet_errors || {}).length > 0 && (
              <div className="status-message error">
                <strong>Some worksheets could not be processed</strong>
                {Object.entries(processingResult.worksheet_errors).map(([name, message]) => (
                  <p key={name}><strong>{name}:</strong> {message}</p>
                ))}
              </div>
            )}
          </section>
        )}

        {/* Module 3 Data Understanding Results */}
        {(understandingId || understandingError || understandingResult) && (
          <section className="understanding-results">
            <div className="understanding-results-header">
              <div>
                <p className="eyebrow">MODULE 3</p>
                <h2>Dataset Understanding</h2>
                <p className="subtitle">
                  {understandingResult?.filename || processingResult?.filename}
                </p>
              </div>

              {understandingResult && (
                <button
                  className="refresh-button"
                  onClick={() => setUnderstandingResult(null)}
                >
                  Close
                </button>
              )}
            </div>

            {understandingId && (
              <div className="understanding-loading">
                <span className="loading-spinner" />
                <div>
                  <strong>Understanding your dataset...</strong>
                  <p>Profiling worksheets and calculating column statistics.</p>
                </div>
              </div>
            )}

            {understandingError && (
              <div className="status-message error">
                <strong>Dataset understanding failed</strong>
                <p>{understandingError}</p>
                <button
                  className="understand-button retry-understand-button"
                  onClick={handleUnderstand}
                  disabled={Boolean(understandingId)}
                >
                  Try Again
                </button>
              </div>
            )}

            {understandingResult && (
              <>
                <div className="understanding-summary">
                  <ProfileStat
                    label="Worksheets"
                    value={understandingResult.total_worksheet_count}
                  />
                  <ProfileStat
                    label="Successfully profiled"
                    value={understandingResult.successful_worksheet_count}
                  />
                  <ProfileStat
                    label="Failed"
                    value={understandingResult.failed_worksheet_count}
                  />
                </div>

                {Object.keys(understandingResult.worksheets || {}).length > 0 ? (
                  <div className="understanding-sheet-list">
                    {Object.entries(understandingResult.worksheets).map(
                      ([sheetKey, sheet]) => (
                        <details className="understanding-sheet" key={sheetKey}>
                          <summary className="understanding-sheet-summary">
                            <div className="summary-main">
                              <strong>{sheet.worksheet_name || sheetKey}</strong>
                              <span>
                                {formatProfileValue(sheet.row_count)} rows
                                {" · "}
                                {formatProfileValue(sheet.column_count)} columns
                              </span>
                            </div>
                            <span className="expand-hint">View profile</span>
                          </summary>

                          <div className="worksheet-profile-content">
                            <div className="worksheet-profile-stats">
                              <ProfileStat label="Numerical" value={sheet.numerical_column_count} />
                              <ProfileStat label="Categorical" value={sheet.categorical_column_count} />
                              <ProfileStat label="Date" value={sheet.date_column_count} />
                              <ProfileStat label="Text" value={sheet.text_column_count} />
                              <ProfileStat label="Boolean" value={sheet.boolean_column_count} />
                              <ProfileStat label="Other" value={sheet.other_column_count} />
                              <ProfileStat label="Missing values" value={sheet.total_missing_value_count} />
                              <ProfileStat label="Blank strings" value={sheet.total_blank_string_count} />
                              <ProfileStat label="Duplicate rows" value={sheet.duplicate_row_count} />
                            </div>

                            <div className="column-profile-heading">
                              <h4>Column profiles</h4>
                              <span>{sheet.columns?.length || 0} columns</span>
                            </div>

                            {sheet.columns?.length ? (
                              <div className="column-profile-list">
                                {sheet.columns.map((column) => (
                                  <details className="column-profile" key={column.column_name}>
                                    <summary>
                                      <div className="column-summary-main">
                                        <strong>{column.column_name}</strong>
                                        {column.original_name !== column.column_name && (
                                          <span>Original: {column.original_name}</span>
                                        )}
                                      </div>
                                      <div className="column-summary-tags">
                                        <span className={`type-tag type-${column.inferred_type}`}>
                                          {formatProfileLabel(column.inferred_type)}
                                        </span>
                                        <span className="role-tag">
                                          {formatProfileLabel(column.semantic_role)}
                                        </span>
                                      </div>
                                    </summary>

                                    <div className="column-profile-content">
                                      <div className="column-metadata-grid">
                                        <ProfileStat label="Pandas dtype" value={column.pandas_dtype} />
                                        <ProfileStat label="Non-empty values" value={column.non_null_count} />
                                        <ProfileStat label="Missing values" value={column.missing_value_count} />
                                        <ProfileStat label="Blank strings" value={column.blank_string_count} />
                                        <ProfileStat label="Missing %" value={`${formatProfileValue(column.missing_percentage)}%`} />
                                        <ProfileStat label="Unique values" value={column.unique_value_count} />
                                        <ProfileStat label="Unique %" value={`${formatProfileValue(column.unique_value_percentage)}%`} />
                                      </div>

                                      {column.sample_values?.length > 0 && (
                                        <div className="profile-detail-block">
                                          <h5>Sample values</h5>
                                          <div className="sample-value-list">
                                            {column.sample_values.map((value, index) => (
                                              <span className="sample-value" key={`${column.column_name}-sample-${index}`}>
                                                {formatProfileValue(value)}
                                              </span>
                                            ))}
                                          </div>
                                        </div>
                                      )}

                                      {column.numerical_statistics && (
                                        <div className="profile-detail-block">
                                          <h5>Numerical statistics</h5>
                                          <div className="column-metadata-grid">
                                            <ProfileStat label="Minimum" value={column.numerical_statistics.minimum} />
                                            <ProfileStat label="Maximum" value={column.numerical_statistics.maximum} />
                                            <ProfileStat label="Mean" value={column.numerical_statistics.mean} />
                                            <ProfileStat label="Median" value={column.numerical_statistics.median} />
                                            <ProfileStat label="Total" value={column.numerical_statistics.total} />
                                            <ProfileStat label="Std. deviation" value={column.numerical_statistics.standard_deviation} />
                                          </div>
                                        </div>
                                      )}

                                      {column.categorical_statistics && (
                                        <div className="profile-detail-block">
                                          <h5>
                                            Category distribution
                                            <span>{column.categorical_statistics.unique_category_count} unique categories</span>
                                          </h5>
                                          {column.categorical_statistics.most_frequent?.length ? (
                                            <div className="frequency-list">
                                              {column.categorical_statistics.most_frequent.map((item, index) => (
                                                <div className="frequency-row" key={`${column.column_name}-frequency-${index}`}>
                                                  <span>{formatProfileValue(item.value)}</span>
                                                  <strong>{formatProfileValue(item.count)}</strong>
                                                </div>
                                              ))}
                                            </div>
                                          ) : (
                                            <p className="profile-muted">No category frequencies available.</p>
                                          )}
                                        </div>
                                      )}

                                      {column.date_statistics && (
                                        <div className="profile-detail-block">
                                          <h5>Date range</h5>
                                          <div className="column-metadata-grid">
                                            <ProfileStat label="Earliest" value={column.date_statistics.earliest} />
                                            <ProfileStat label="Latest" value={column.date_statistics.latest} />
                                          </div>
                                        </div>
                                      )}

                                      {column.mixed_value_types?.length > 0 && (
                                        <div className="profile-detail-block">
                                          <h5>Mixed underlying value types</h5>
                                          <div className="sample-value-list">
                                            {column.mixed_value_types.map((type) => (
                                              <span className="sample-value" key={type}>{type}</span>
                                            ))}
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  </details>
                                ))}
                              </div>
                            ) : (
                              <p className="empty-message">No column profiles are available for this worksheet.</p>
                            )}
                          </div>
                        </details>
                      )
                    )}
                  </div>
                ) : (
                  <p className="empty-message">No worksheet profiles are available.</p>
                )}

                {Object.keys(understandingResult.worksheet_errors || {}).length > 0 && (
                  <div className="status-message error">
                    <strong>Some worksheets could not be profiled</strong>
                    {Object.entries(understandingResult.worksheet_errors).map(([name, message]) => (
                      <p key={name}><strong>{name}:</strong> {message}</p>
                    ))}
                  </div>
                )}
              </>
            )}
          </section>
        )}

        {analyticsId && (
          <div className="understanding-loading">
            <span className="loading-spinner" />
            <div>
              <strong>Generating your analytics dashboard...</strong>
              <p>Ollama is preparing the plan. Pandas will calculate the actual results. This can take a few minutes on a local model.</p>
            </div>
          </div>
        )}

        {analyticsError && (
          <div className="status-message error">
            <strong>Analytics generation failed</strong>
            <p>{analyticsError}</p>
            <button
              className="understand-button retry-understand-button"
              onClick={handleGenerateAnalytics}
              disabled={Boolean(analyticsId)}
            >
              Try Again
            </button>
          </div>
        )}

        <AnalyticsDashboard result={analyticsResult} />

        {/* Download / Delete Feedback */}
        {actionError && (
          <div className="status-message error">
            <strong>Action Failed</strong>
            <p>{actionError}</p>
          </div>
        )}

        {actionSuccess && (
          <div className="status-message success">
            <strong>Success</strong>
            <p>{actionSuccess}</p>
          </div>
        )}

      </section>

    </main>
  );
}

export default App;