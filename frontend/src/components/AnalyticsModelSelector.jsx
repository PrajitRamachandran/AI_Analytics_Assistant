import { useEffect, useState } from "react";
import api from "../services/api";

export default function AnalyticsModelSelector() {
  const [models, setModels] = useState([]);
  const [selected, setSelected] = useState({ provider: "", model: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadModels = async () => {
    setLoading(true);
    setError("");
    try {
      const response = await api.get("/api/models");
      setModels(Array.isArray(response.data.models) ? response.data.models : []);
      setSelected(response.data.selected || { provider: "", model: "" });
    } catch (err) {
      setError(err.response?.data?.detail || "Unable to load available models.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadModels(); }, []);

  const saveSelection = async (event) => {
    const [provider, ...parts] = event.target.value.split("::");
    const model = parts.join("::");
    if (!provider || !model) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const response = await api.put("/api/models/selection", { provider, model });
      setSelected(response.data.selected || { provider, model });
      setNotice(response.data.connection_ready === false
        ? "Selection saved, but the provider connection check failed. Check your backend configuration."
        : "Model saved. Future analytics generation will use this selection.");
    } catch (err) {
      setError(err.response?.data?.detail || "Unable to save the selected model.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="analytics-model-card" aria-labelledby="analytics-model-title">
      <div className="analytics-model-copy">
        <span className="analytics-model-icon" aria-hidden="true">✦</span>
        <div>
          <p className="eyebrow">ANALYTICS CONFIGURATION</p>
          <h2 id="analytics-model-title">Planner model</h2>
          <p>Choose the model that plans charts and insights. All numerical calculations remain deterministic.</p>
          {selected.model && <span className="analytics-active-model">Active · {selected.provider} / {selected.model}</span>}
        </div>
      </div>
      <div className="analytics-model-controls">
        <label className="sr-only" htmlFor="analytics-page-model">Select analytics model</label>
        <select id="analytics-page-model" value={selected.provider && selected.model ? `${selected.provider}::${selected.model}` : ""} onChange={saveSelection} disabled={loading || saving || models.length === 0}>
          <option value="">{loading ? "Discovering models…" : "Select a model"}</option>
          {models.map((item) => <option key={`${item.provider}::${item.model}`} value={`${item.provider}::${item.model}`}>{item.provider === "ollama" ? "Local · " : "Cloud · "}{item.model}</option>)}
        </select>
        <button type="button" className="secondary-button compact-action" onClick={loadModels} disabled={loading || saving}>{loading ? "Loading…" : "Refresh"}</button>
      </div>
      {saving && <p className="analytics-model-feedback">Saving model selection…</p>}
      {error && <p className="analytics-model-feedback is-error" role="alert">{error}</p>}
      {notice && <p className="analytics-model-feedback" role="status">{notice}</p>}
      {!loading && models.length === 0 && !error && <p className="analytics-model-feedback">No models found. Start Ollama or configure a provider in the backend.</p>}
    </section>
  );
}
