import { useState } from "react";
import { useAppNavigate } from "../app/navigation";
import api from "../services/api";

export default function AddModelPage() {
  const navigate = useAppNavigate();
  const [provider, setProvider] = useState("");
  const [command, setCommand] = useState("ollama pull ");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [cloudPreset, setCloudPreset] = useState("google");
  const [baseUrl, setBaseUrl] = useState("https://generativelanguage.googleapis.com/v1beta/openai/");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const addModel = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      let response;
      if (provider === "local") {
        response = await api.post("/api/models/local", { command });
      } else {
        let parsedUrl;
        try {
          parsedUrl = new URL(baseUrl.trim());
        } catch {
          throw new Error("Enter a valid provider API URL.");
        }
        if (!["http:", "https:"].includes(parsedUrl.protocol) || !parsedUrl.hostname) {
          throw new Error("Provider API URL must use HTTP or HTTPS.");
        }
        response = await api.post("/api/models/cloud", {
          api_key: apiKey.trim(),
          model: model.trim(),
          base_url: baseUrl.trim(),
        });
      }
      setNotice(response.data.message || "Model added successfully.");
      setTimeout(() => navigate("/analytics"), 900);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || "Unable to add this model.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="app-container dedicated-page model-setup-page">
      <header className="app-header">
        <div>
          <p className="eyebrow">ANALYTICS CONFIGURATION / MODEL LIBRARY</p>
          <h1>Add a model</h1>
          <p className="subtitle">Connect a model to power analytics planning. Choose where the model runs.</p>
        </div>
        <button className="secondary-button" type="button" onClick={() => navigate("/analytics")}>← Back to model selector</button>
      </header>

      {!provider ? (
        <div className="model-provider-grid">
          <button type="button" className="model-provider-card" onClick={() => setProvider("local")}>
            <span className="model-provider-icon">⌘</span>
            <strong>Local model</strong>
            <span>Pull and run a model on this machine using Ollama. Your model stays local.</span>
            <small>Requires Ollama installed and running</small>
          </button>
          <button type="button" className="model-provider-card" onClick={() => setProvider("cloud")}>
            <span className="model-provider-icon">☁</span>
            <strong>Cloud model</strong>
            <span>Connect a hosted model using your provider API key and model identifier.</span>
            <small>Google Gemini, Groq, and OpenAI-compatible cloud APIs</small>
          </button>
        </div>
      ) : (
        <form className="model-setup-form" onSubmit={addModel}>
          <div className="model-setup-form-heading">
            <div><p className="eyebrow">{provider === "local" ? "LOCAL PROVIDER" : "CLOUD PROVIDER"}</p><h2>{provider === "local" ? "Connect an Ollama model" : "Connect a cloud model"}</h2></div>
            <button type="button" className="settings-cancel-button" onClick={() => { setProvider(""); setError(""); }}>Change provider</button>
          </div>
          {provider === "local" ? (
            <>
              <label htmlFor="ollama-command">Ollama pull command</label>
              <input id="ollama-command" value={command} onChange={(event) => setCommand(event.target.value)} placeholder="ollama pull llama3.2" required />
              <p className="model-form-help">Paste the command exactly as you would run it in a terminal, for example: <code>ollama pull llama3.2</code>. The backend runs the pull command without invoking a shell.</p>
            </>
          ) : (
            <>
              <label htmlFor="cloud-provider-preset">Cloud provider</label>
              <select
                id="cloud-provider-preset"
                value={cloudPreset}
                onChange={(event) => {
                  const nextPreset = event.target.value;
                  setCloudPreset(nextPreset);
                  if (nextPreset === "google") {
                    setBaseUrl("https://generativelanguage.googleapis.com/v1beta/openai/");
                    if (!model.trim() || model === "llama-3.3-70b-versatile") setModel("gemini-2.5-flash");
                  } else if (nextPreset === "groq") {
                    setBaseUrl("https://api.groq.com/openai/v1");
                    if (!model.trim() || model === "gemini-2.5-flash") setModel("llama-3.3-70b-versatile");
                  } else {
                    setBaseUrl("");
                  }
                }}
              >
                <option value="google">Google Gemini</option>
                <option value="groq">Groq</option>
                <option value="custom">Custom OpenAI-compatible provider</option>
              </select>
              <label htmlFor="cloud-base-url">Provider API URL</label>
              <input
                id="cloud-base-url"
                type="url"
                value={baseUrl}
                onChange={(event) => { setBaseUrl(event.target.value); if (cloudPreset !== "custom") setCloudPreset("custom"); }}
                placeholder="https://provider.example.com/v1"
                required
              />
              <p className="model-form-help">
                {cloudPreset === "google"
                  ? "Google Gemini OpenAI-compatible endpoint. Use your Google AI Studio API key."
                  : cloudPreset === "groq"
                    ? "Groq OpenAI-compatible endpoint. Use your Groq API key."
                    : "Enter the provider's OpenAI-compatible API base URL, usually ending in /v1."}
              </p>
              <label htmlFor="cloud-api-key">Provider API key</label>
              <input id="cloud-api-key" type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Paste your provider API key" required />
              <label htmlFor="cloud-model">Model name / ID</label>
              <input id="cloud-model" value={model} onChange={(event) => setModel(event.target.value)} placeholder={cloudPreset === "google" ? "gemini-2.5-flash" : cloudPreset === "groq" ? "llama-3.3-70b-versatile" : "provider-model-id"} required />
              <p className="model-form-help">The API key and endpoint are stored by the backend in its configuration. The API key is never returned to the browser.</p>
            </>
          )}
          {error && <p className="model-form-message is-error" role="alert">{String(error)}</p>}
          {notice && <p className="model-form-message" role="status">{notice}</p>}
          <div className="model-form-actions">
            <button type="button" className="secondary-button" onClick={() => navigate("/analytics")}>Cancel</button>
            <button type="submit" className="primary-button" disabled={saving || (provider === "cloud" && (!apiKey.trim() || !model.trim() || !baseUrl.trim()))}>{saving ? (provider === "local" ? "Pulling model…" : "Verifying provider…") : "Add model"}</button>
          </div>
          {saving && provider === "local" && <p className="model-form-help">Model downloads can take several minutes depending on model size and connection speed. Keep the backend running.</p>}
        </form>
      )}
    </div>
  );
}
