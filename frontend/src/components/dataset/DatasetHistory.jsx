import { useEffect, useRef, useState } from "react";
import { formatDate, formatFileSize } from "./datasetFormatters";

export default function DatasetHistory({
  datasets,
  loading,
  error,
  onRefresh,
  onOpenDataset,
  onDownload,
  onDelete,
  downloadingId,
  deletingId,
}) {
  const [deleteCandidate, setDeleteCandidate] = useState(null);
  const cancelDeleteRef = useRef(null);

  useEffect(() => {
    if (!deleteCandidate) return undefined;
    const previousFocus = document.activeElement;
    cancelDeleteRef.current?.focus();
    const handleKeyDown = (event) => {
      if (event.key === "Escape") setDeleteCandidate(null);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus?.();
    };
  }, [deleteCandidate]);

  return (
    <section className="history-section" id="history-section" aria-labelledby="history-heading">
      <div className="history-header">
        <div>
          <h2 id="history-heading">Uploaded Files</h2>
          <p className="subtitle">Your previously uploaded datasets.</p>
        </div>
        <button className="refresh-button" onClick={onRefresh} disabled={loading}>
          {loading ? "Refreshing..." : "↻ Refresh"}
        </button>
      </div>

      <div className="history-card">
        {loading ? (
          <p className="empty-message" role="status">Loading your datasets...</p>
        ) : error ? (
          <div className="status-message error" role="alert">
            <strong>Unable to load history</strong>
            <p>{error}</p>
          </div>
        ) : datasets.length === 0 ? (
          <div className="empty-state">
            <span aria-hidden="true">📂</span>
            <h3>No uploaded files yet</h3>
            <p>Your uploaded Excel files will appear here.</p>
          </div>
        ) : (
          <>
            <div className="dataset-summary"><strong>{datasets.length} dataset(s)</strong></div>
            <div className="table-wrapper">
              <table className="dataset-table">
                <thead>
                  <tr>
                    <th scope="col">Filename</th>
                    <th scope="col">Size</th>
                    <th scope="col">Uploaded At</th>
                    <th scope="col">Status</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {datasets.map((dataset) => (
                    <tr key={dataset.dataset_id}>
                      <td className="filename-cell">📄 {dataset.filename}</td>
                      <td>{formatFileSize(dataset.file_size)}</td>
                      <td>{formatDate(dataset.uploaded_at)}</td>
                      <td><span className="status-badge">{dataset.status}</span></td>
                      <td>
                        <div className="action-buttons dataset-management-actions">
                          <button className="process-button" onClick={() => onOpenDataset?.(dataset)}>
                            Open workspace →
                          </button>
                          <button className="download-button" onClick={() => onDownload(dataset)} disabled={downloadingId === dataset.dataset_id}>
                            {downloadingId === dataset.dataset_id ? "Downloading..." : "↓ Download"}
                          </button>
                          <button className="delete-button" onClick={() => setDeleteCandidate(dataset)} disabled={deletingId === dataset.dataset_id}>
                            {deletingId === dataset.dataset_id ? "Deleting..." : "Delete"}
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

      {deleteCandidate && (
        <div className="app-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDeleteCandidate(null); }}>
          <section className="app-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title" aria-describedby="delete-dialog-description">
            <div className="app-dialog-icon danger" aria-hidden="true">!</div>
            <h3 id="delete-dialog-title">Delete this dataset?</h3>
            <p id="delete-dialog-description">This will permanently delete <strong>{deleteCandidate.filename}</strong> and its saved processing, profiling and analytics results. This action cannot be undone.</p>
            <div className="app-dialog-actions">
              <button ref={cancelDeleteRef} className="secondary-button" onClick={() => setDeleteCandidate(null)}>Cancel</button>
              <button className="delete-button" onClick={() => { const target = deleteCandidate; setDeleteCandidate(null); onDelete(target); }} disabled={Boolean(deletingId)}>Delete dataset</button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
