
import { useEffect, useState } from "react";
import api from "./services/api";
import UploadPanel from "./components/dataset/UploadPanel";
import ToastNotice from "./components/ToastNotice";
import DatasetHistory from "./components/dataset/DatasetHistory";
import AppLayout from "./components/layout/AppLayout";
import { useAppLocation, useAppNavigate } from "./app/navigation";
import { resolveRoute } from "./app/routeConfig";
import DataExplorer from "./components/explorer/DataExplorer";
import AnalyticsDashboard from "./components/AnalyticsDashboard";
import AnalyticsModelSelector from "./components/AnalyticsModelSelector";
import AddModelPage from "./pages/AddModel";
import { getAllWorkflowResults, saveWorkflowResult, deleteWorkflowResult } from "./services/workflowStore";
import "./App.css";

function App() {
  const navigate = useAppNavigate();
  const location = useAppLocation();
  const route = resolveRoute(location.split("?")[0].split("#")[0]);
  const [file, setFile] = useState(null);

  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);

  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [uploadToast, setUploadToast] = useState(null);

  const [datasets, setDatasets] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [historyError, setHistoryError] = useState("");

  const [actionError, setActionError] = useState("");
  const [actionSuccess, setActionSuccess] = useState("");

  const [deletingId, setDeletingId] = useState(null);
  const [downloadingId, setDownloadingId] = useState(null);
  const [workflowByDataset, setWorkflowByDataset] = useState({});
  const [processingId, setProcessingId] = useState(null);
  const [profilingId, setProfilingId] = useState(null);
  const [analyticsId, setAnalyticsId] = useState(null);
  const [workflowError, setWorkflowError] = useState("");

  const activeDataset = datasets.find((item) => String(item.dataset_id) === String(route.datasetId)) || null;
  const activeWorkflow = activeDataset ? workflowByDataset[activeDataset.dataset_id] || {} : {};

  const updateWorkflow = (datasetId, patch) => {
    setWorkflowByDataset((current) => ({
      ...current,
      [datasetId]: { ...(current[datasetId] || {}), ...patch },
    }));
  };

  const handleProcess = async (dataset, force = false) => {
    if (!dataset?.dataset_id) return;
    setProcessingId(dataset.dataset_id);
    setWorkflowError("");
    try {
      const response = await api.post(`/api/datasets/${dataset.dataset_id}/process${force ? "?force=true" : ""}`);
      updateWorkflow(dataset.dataset_id, { processingResult: response.data, processingSavedAt: new Date().toISOString() });
      saveWorkflowResult(dataset.dataset_id, "processing", response.data).catch((storageError) => console.warn("Could not persist processing results:", storageError));
      await fetchDatasets();
    } catch (err) {
      setWorkflowError(err.response?.data?.detail || err.message || "Unable to process this dataset.");
    } finally {
      setProcessingId(null);
    }
  };

  const handleUnderstand = async (dataset, force = false) => {
    if (!dataset?.dataset_id) return;
    setProfilingId(dataset.dataset_id);
    setWorkflowError("");
    try {
      const response = await api.post(`/api/datasets/${dataset.dataset_id}/understand${force ? "?force=true" : ""}`);
      updateWorkflow(dataset.dataset_id, { understandingResult: response.data, understandingSavedAt: new Date().toISOString() });
      saveWorkflowResult(dataset.dataset_id, "profile", response.data).catch((storageError) => console.warn("Could not persist profile results:", storageError));
      await fetchDatasets();
    } catch (err) {
      setWorkflowError(err.response?.data?.detail || err.message || "Unable to profile this dataset.");
    } finally {
      setProfilingId(null);
    }
  };

  const handleGenerateAnalytics = async (dataset, force = false) => {
    if (!dataset?.dataset_id) return;
    setAnalyticsId(dataset.dataset_id);
    setWorkflowError("");
    try {
      const response = await api.post(`/api/datasets/${dataset.dataset_id}/analytics${force ? "?force=true" : ""}`, undefined, { timeout: 21 * 60 * 1000 });
      updateWorkflow(dataset.dataset_id, { analyticsResult: response.data, analyticsSavedAt: new Date().toISOString() });
      saveWorkflowResult(dataset.dataset_id, "analytics", response.data).catch((storageError) => console.warn("Could not persist analytics results:", storageError));
      await fetchDatasets();
    } catch (err) {
      setWorkflowError(err.response?.data?.detail || err.message || "Unable to generate analytics.");
    } finally {
      setAnalyticsId(null);
    }
  };



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

  // Restore detailed workflow payloads from browser-persistent IndexedDB storage.
  useEffect(() => {
    let ignore = false;
    getAllWorkflowResults().then((records) => {
      if (ignore) return;
      const restored = {};
      for (const record of records) {
        const stages = record.stages || {};
        restored[record.datasetId] = {
          ...(stages.processing ? { processingResult: stages.processing.result, processingSavedAt: stages.processing.savedAt } : {}),
          ...(stages.profile ? { understandingResult: stages.profile.result, understandingSavedAt: stages.profile.savedAt } : {}),
          ...(stages.analytics ? { analyticsResult: stages.analytics.result, analyticsSavedAt: stages.analytics.savedAt } : {}),
        };
      }
      setWorkflowByDataset(restored);
    }).catch((storageError) => console.warn("Could not restore saved workflow history:", storageError));
    return () => { ignore = true; };
  }, []);

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
      setUploadToast({ type: "error", title: "Unsupported file", message: "Only .xlsx workbooks are currently supported." });
      return;
    }

    if (selectedFile.size === 0) {
      setFile(null);
      setError("The selected file is empty.");
      setUploadToast({ type: "error", title: "Empty file", message: "Please choose a workbook that contains data." });
      return;
    }

    if (selectedFile.size > 25 * 1024 * 1024) {
      setFile(null);
      setError("File exceeds the maximum size of 25 MB.");
      setUploadToast({ type: "error", title: "File too large", message: "The maximum upload size is 25 MB." });
      return;
    }

    setFile(selectedFile);
    setUploadToast(null);
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
      setUploadToast({ type: "success", title: "Upload successful", message: `${response.data.filename || file.name} was added to My Datasets.` });
      setFile(null);
      setProgress(100);

      // Refresh history after a successful upload
      await fetchDatasets();

    } catch (err) {
      const detail = err.response?.data?.detail;
      const message = err.response?.status === 409
        ? (detail || "File already exists. This workbook has already been uploaded.")
        : (detail || err.message || "Upload failed. Please try again.");
      setError(message);
      setUploadToast({ type: "error", title: "Upload failed", message });
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


  // Delete an uploaded Excel workbook
  const handleDelete = async (dataset) => {
    setDeletingId(dataset.dataset_id);
    setActionError("");
    setActionSuccess("");

    try {
      await api.delete(
        `/api/datasets/${dataset.dataset_id}`
      );
      await deleteWorkflowResult(dataset.dataset_id).catch((storageError) => console.warn("Could not clear deleted dataset history:", storageError));
      setWorkflowByDataset((current) => { const next = { ...current }; delete next[dataset.dataset_id]; return next; });

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

  const uploadPage = (
    <div className="app-container dedicated-page upload-page">
      <header className="app-header upload-page-header">
        <div>
          <p className="eyebrow">WORKSPACE / DATA INGESTION</p>
          <h1>Upload Dataset</h1>
          <p className="subtitle">Choose an Excel workbook to add it to your analytics workspace.</p>
        </div>
      </header>
      <UploadPanel file={file} uploading={uploading} progress={progress}
        onFileChange={handleFileChange} onUpload={handleUpload} />
      <ToastNotice
        type={uploadToast?.type || "info"}
        title={uploadToast?.title}
        message={uploadToast?.message}
        onDismiss={() => setUploadToast(null)}
      />
    </div>
  );

  const datasetsPage = (
    <div className="app-container dedicated-page">
      <header className="app-header">
        <div>
          <p className="eyebrow">WORKSPACE / LIBRARY</p>
          <h1>My Datasets</h1>
          <p className="subtitle">Manage your uploaded workbooks and open a dataset workspace.</p>
        </div>
        <button className="upload-button page-primary-action" onClick={() => navigate("/upload")}>+ Upload Dataset</button>
      </header>
      <DatasetHistory datasets={datasets} loading={loadingHistory} error={historyError}
        onRefresh={fetchDatasets}
        onOpenDataset={(dataset) => navigate(`/datasets/${encodeURIComponent(dataset.dataset_id)}/processing`)}
        onDownload={handleDownload} onDelete={handleDelete}
        downloadingId={downloadingId} deletingId={deletingId} />
      {(actionError || actionSuccess) && (
        <div className={`status-message ${actionError ? "error" : "success"}`} role={actionError ? "alert" : "status"}>
          <strong>{actionError ? "Action failed" : "Action completed"}</strong>
          <p>{actionError || actionSuccess}</p>
        </div>
      )}
    </div>
  );

  const stage = route.id;
  const stageDataset = activeDataset;
  const stagePage = (
    <div className="app-container dedicated-page workflow-page">
      <header className="app-header workflow-page-header">
        <div>
          <p className="eyebrow">DATA WORKFLOW / {stage === "processing" ? "MODULE 2" : stage === "profile" ? "MODULE 3" : "MODULE 4"}</p>
          <h1>{stage === "processing" ? "Data Processing" : stage === "profile" ? "Data Profile" : "Analytics"}</h1>
          <p className="subtitle">{stage === "processing" ? "Review workbook normalisation, worksheet quality and processed previews." : stage === "profile" ? "Inspect column types, distributions, missing values and statistical summaries." : "Explore verified KPIs, charts and analytical findings generated for this dataset."}</p>
        </div>
        <div className="workflow-page-actions">
          {stageDataset && <span className="workflow-dataset-name" title={stageDataset.filename}>{stageDataset.filename}</span>}
          <button className="secondary-button compact-action" onClick={() => navigate("/datasets")}>All datasets</button>
        </div>
      </header>
      {!stageDataset ? (
        <section className="workflow-empty-state"><h2>Select a dataset to continue</h2><p>Choose a workbook from My Datasets to open its processing, profile and analytics workspace.</p><button className="primary-button compact-action" onClick={() => navigate("/datasets")}>Choose dataset</button></section>
      ) : (
        <>
          <nav className="workflow-stage-nav" aria-label="Dataset workflow">
            {[["processing", "Processing"], ["profile", "Data Profile"], ["analytics", "Analytics"]].map(([id, labelText]) => (
              <button key={id} className={stage === id ? "active" : ""} aria-current={stage === id ? "page" : undefined} onClick={() => navigate(`/datasets/${encodeURIComponent(stageDataset.dataset_id)}/${id}`)}>{labelText}</button>
            ))}
          </nav>
          <section className="workflow-history" aria-label="Saved workflow history">
            <div className="workflow-history-heading"><div><h2>Workflow history</h2><p>Saved results are restored automatically when you reopen this workspace.</p></div><span className="workflow-history-count">{[activeWorkflow.processingResult, activeWorkflow.understandingResult, activeWorkflow.analyticsResult].filter(Boolean).length} of 3 completed</span></div>
            <div className="workflow-history-grid">
              {[{ id: "processing", label: "Processing", value: activeWorkflow.processingResult, savedAt: activeWorkflow.processingSavedAt }, { id: "profile", label: "Understanding & profile", value: activeWorkflow.understandingResult, savedAt: activeWorkflow.understandingSavedAt }, { id: "analytics", label: "Analytics", value: activeWorkflow.analyticsResult, savedAt: activeWorkflow.analyticsSavedAt }].map((item) => (
                <button type="button" key={item.id} className={`workflow-history-item ${item.value ? "is-complete" : ""}`} onClick={() => navigate(`/datasets/${encodeURIComponent(stageDataset.dataset_id)}/${item.id}`)}>
                  <span className="workflow-history-status">{item.value ? "Completed" : "Not run"}</span><strong>{item.label}</strong><small>{item.savedAt ? `Saved ${new Date(item.savedAt).toLocaleString()}` : "No saved result"}</small>
                </button>
              ))}
            </div>
          </section>
          {workflowError && <div className="status-message error" role="alert"><strong>Workflow action failed</strong><p>{workflowError}</p></div>}
          {stage === "processing" && (
            <>
              <div className="workflow-action-strip"><div><strong>Workbook processing</strong><span>Run the existing processing service for this dataset.</span></div><button className="primary-button compact-action" onClick={() => handleProcess(stageDataset, Boolean(activeWorkflow.processingResult))} disabled={processingId === stageDataset.dataset_id}>{processingId === stageDataset.dataset_id ? "Processing…" : activeWorkflow.processingResult ? "Reprocess dataset" : "Process dataset"}</button></div>
              {activeWorkflow.processingResult ? <DataExplorer stage="processing" processingResult={activeWorkflow.processingResult} /> : <div className="workflow-empty-state"><h2>{processingId === stageDataset.dataset_id ? "Processing workbook…" : "This dataset has not been processed in this session"}</h2><p>Start processing to inspect worksheet previews, normalisation and data-quality results.</p></div>}
            </>
          )}
          {stage === "profile" && (
            <>
              <div className="workflow-action-strip"><div><strong>Dataset profiling</strong><span>{activeWorkflow.processingResult || stageDataset.processing_status === "processed" ? "This workbook has completed processing." : "Profiling requires a successfully processed dataset."}</span></div><button className="primary-button compact-action" onClick={() => handleUnderstand(stageDataset, Boolean(activeWorkflow.understandingResult))} disabled={!(activeWorkflow.processingResult || stageDataset.processing_status === "processed") || profilingId === stageDataset.dataset_id}>{profilingId === stageDataset.dataset_id ? "Profiling…" : activeWorkflow.understandingResult ? "Re-run profile" : "Generate profile"}</button></div>
              {activeWorkflow.understandingResult ? <DataExplorer stage="profile" understandingResult={activeWorkflow.understandingResult} /> : <div className="workflow-empty-state"><h2>{profilingId === stageDataset.dataset_id ? "Profiling workbook…" : "No profile available yet"}</h2><p>Process this dataset first, then generate its column-level profile.</p>{!activeWorkflow.processingResult && <button className="secondary-button compact-action" onClick={() => navigate(`/datasets/${encodeURIComponent(stageDataset.dataset_id)}/processing`)}>Go to processing</button>}</div>}
            </>
          )}
          {stage === "analytics" && (
            <>
              <AnalyticsModelSelector />
              <div className="workflow-action-strip"><div><strong>Analytics generation</strong><span>Generate dataset-specific KPIs, charts and insights.</span></div><button className="primary-button compact-action" onClick={() => handleGenerateAnalytics(stageDataset, Boolean(activeWorkflow.analyticsResult))} disabled={!(activeWorkflow.processingResult || stageDataset.processing_status === "processed") || analyticsId === stageDataset.dataset_id}>{analyticsId === stageDataset.dataset_id ? "Generating…" : activeWorkflow.analyticsResult ? "Regenerate analytics" : "Generate analytics"}</button></div>
              {activeWorkflow.analyticsResult ? <AnalyticsDashboard result={activeWorkflow.analyticsResult} /> : <div className="workflow-empty-state"><h2>{analyticsId === stageDataset.dataset_id ? "Generating analytics…" : "No analytics generated yet"}</h2><p>Process this dataset first, then generate its analytics using the configured planner.</p>{!activeWorkflow.processingResult && <button className="secondary-button compact-action" onClick={() => navigate(`/datasets/${encodeURIComponent(stageDataset.dataset_id)}/processing`)}>Go to processing</button>}</div>}
            </>
          )}
        </>
      )}
    </div>
  );

  const overviewPage = (
    <div className="app-container dedicated-page">
      <header className="app-header" id="app-header">
        <div>
          <p className="eyebrow">AI DATA ANALYTICS ASSISTANT</p>
          <h1>Overview</h1>
          <p className="subtitle">A clear view of your data workspace and recent activity.</p>
        </div>
        <button className="upload-button page-primary-action" onClick={() => navigate("/upload")}>+ Upload Dataset</button>
      </header>
      <section className="overview-summary-grid" aria-label="Workspace summary">
        <article className="overview-summary-card"><span>Uploaded datasets</span><strong>{loadingHistory ? "—" : datasets.length}</strong><small>Workbooks in your workspace</small></article>
        <article className="overview-summary-card"><span>Processed datasets</span><strong>{loadingHistory ? "—" : datasets.filter((item) => item.processing_status === "processed").length}</strong><small>Ready for profiling</small></article>
        <article className="overview-summary-card"><span>Profiles completed</span><strong>{loadingHistory ? "—" : datasets.filter((item) => item.understanding_status === "understood").length}</strong><small>Datasets with generated profiles</small></article>
        <article className="overview-summary-card"><span>Analytics generated</span><strong>{loadingHistory ? "—" : datasets.filter((item) => item.analytics_status === "analysed").length}</strong><small>Datasets with analytics results</small></article>
      </section>
      <section className="overview-section">
        <div className="overview-section-heading">
          <div><h2>Recent datasets</h2><p>Continue working with a recently uploaded workbook.</p></div>
          <button className="secondary-button" onClick={() => navigate("/datasets")}>View all datasets →</button>
        </div>
        {loadingHistory ? <div className="history-card"><p className="empty-message">Loading your datasets...</p></div>
          : historyError ? <div className="status-message error" role="alert">{historyError}</div>
          : datasets.length === 0 ? (
            <div className="overview-empty-card">
              <strong>Your workspace is ready for its first dataset.</strong>
              <p>Upload an Excel workbook to start processing, profiling and analytics.</p>
              <button className="upload-button" onClick={() => navigate("/upload")}>Upload your first dataset</button>
            </div>
          ) : (
            <div className="overview-recent-list">
              {datasets.slice(0, 5).map((dataset) => (
                <div className="overview-recent-row" key={dataset.dataset_id}>
                  <div className="overview-file-icon">▤</div>
                  <div className="overview-recent-copy"><strong>{dataset.filename}</strong><span>{dataset.status || "Uploaded"}</span></div>
                  <button className="secondary-button" onClick={() => navigate(`/datasets/${encodeURIComponent(dataset.dataset_id)}/processing`)}>Open →</button>
                </div>
              ))}
            </div>
          )}
      </section>
    </div>
  );

  return (
    <AppLayout pageContent={{ upload: uploadPage, datasets: datasetsPage, processing: stagePage, profile: stagePage, analytics: stagePage, addModel: <AddModelPage /> }}>
      {overviewPage}
    </AppLayout>
  );
}

export default App;
