
import { useEffect, useState } from "react";
import api from "./services/api";
import "./App.css";

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
    setActionError("");
    setActionSuccess("");

    try {
      const response = await api.post(
        `/api/datasets/${dataset.dataset_id}/process`,
        {},
        { timeout: 120000 }
      );

      setProcessingResult(response.data);
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

              <button
                className="refresh-button"
                onClick={() => setProcessingResult(null)}
              >
                Close
              </button>
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
                    <span className="column-chip" key={column.name}>
                      {column.name}
                      <small>{column.data_category}</small>
                    </span>
                  ))}
                </div>

                <div className="quality-summary">
                  <span>Empty rows removed: {sheet.quality.removed_empty_row_count}</span>
                  <span>Empty columns removed: {sheet.quality.removed_empty_column_count}</span>
                  <span>Duplicate rows found: {sheet.quality.duplicate_row_count}</span>
                </div>

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