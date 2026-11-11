function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function UploadPanel({ file, uploading, progress, error, result, onFileChange, onUpload, onViewDatasets }) {
  return (
    <section className="upload-card" id="upload-card" aria-labelledby="upload-heading">
      <div className="upload-icon" aria-hidden="true">📊</div>
      <h2 id="upload-heading">Upload Excel Workbook</h2>
      <p className="upload-description">Select an Excel file to get started with your analysis.</p>

      <label className="file-picker">
        Choose Excel File
        <input
          type="file"
          accept=".xlsx"
          onChange={(event) => onFileChange(event.target.files?.[0])}
          disabled={uploading}
          aria-label="Choose an Excel workbook"
        />
      </label>
      <p className="file-hint">Supported format: .xlsx · Maximum size: 25 MB</p>

      {file && (
        <div className="selected-file" aria-live="polite">
          <span aria-hidden="true">📄</span>
          <div className="file-details">
            <strong>{file.name}</strong>
            <small>{formatFileSize(file.size)}</small>
          </div>
        </div>
      )}

      {uploading && (
        <div className="progress-section" aria-live="polite">
          <div className="progress-label">
            <span>Uploading...</span>
            <span>{progress}%</span>
          </div>
          <div className="progress-track" role="progressbar" aria-valuenow={progress} aria-valuemin="0" aria-valuemax="100" aria-label="Upload progress">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      <button className="upload-button" onClick={onUpload} disabled={!file || uploading}>
        {uploading ? "Uploading..." : "Upload File"}
      </button>

      {error && (
        <div className="status-message error" role="alert">
          <strong>Upload Failed</strong>
          <p>{error}</p>
        </div>
      )}

      {result && (
        <div className="status-message success" role="status">
          <strong>Upload Successful!</strong>
          <p>{result.filename}</p>
          <small>Dataset ID: {result.dataset_id}</small>
          {onViewDatasets && (
            <button className="upload-success-link" type="button" onClick={onViewDatasets}>
              View my datasets →
            </button>
          )}
        </div>
      )}
    </section>
  );
}
