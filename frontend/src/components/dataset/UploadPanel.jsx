function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function UploadPanel({ file, uploading, progress, onFileChange, onUpload }) {
  return (
    <section className="upload-card upload-card-compact" id="upload-card" aria-labelledby="upload-heading">
      <div className="upload-card-intro">
        <div className="upload-icon" aria-hidden="true">📊</div>
        <div>
          <h2 id="upload-heading">Upload Excel Workbook</h2>
          <p className="upload-description">Choose an Excel workbook to begin your analysis.</p>
        </div>
      </div>

      <div className="upload-picker-row">
        <label className="file-picker">
          <span>Choose Excel File</span>
          <input
            type="file"
            accept=".xlsx"
            onChange={(event) => { if (event.target.files?.[0]) onFileChange(event.target.files[0]); }}
            disabled={uploading}
            aria-label="Choose an Excel workbook"
          />
        </label>
        <p className="file-hint">.xlsx format <span aria-hidden="true">·</span> Maximum size 25 MB</p>
      </div>

      {file && (
        <div className="upload-selection-row">
          <button type="button" className="upload-button upload-button-inline" onClick={onUpload} disabled={uploading}>
            {uploading ? `Uploading ${progress}%…` : "Upload File"}
          </button>
          <div className="selected-file selected-file-compact" aria-live="polite">
            <span className="selected-file-icon" aria-hidden="true">📄</span>
            <div className="file-details">
              <strong title={file.name}>{file.name}</strong>
              <small>{formatFileSize(file.size)} · Ready to upload</small>
            </div>
            {!uploading && <button type="button" className="remove-selected-file" onClick={() => onFileChange(null)} aria-label="Remove selected file">×</button>}
          </div>
        </div>
      )}

      {uploading && (
        <div className="progress-section upload-progress-compact" aria-live="polite">
          <div className="progress-label"><span>Uploading workbook</span><span>{progress}%</span></div>
          <div className="progress-track" role="progressbar" aria-valuenow={progress} aria-valuemin="0" aria-valuemax="100" aria-label="Upload progress">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}
    </section>
  );
}
