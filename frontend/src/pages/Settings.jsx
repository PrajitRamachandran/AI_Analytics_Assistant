import { useEffect, useState } from "react";
import { useTheme } from "../context/ThemeContext";
import { ACCENTS } from "../context/appearanceUtils";
import api from "../services/api";

const ACCENT_OPTIONS = [
  { id: "blue", label: "Blue" },
  { id: "violet", label: "Violet" },
  { id: "emerald", label: "Emerald" },
  { id: "rose", label: "Rose" },
  { id: "amber", label: "Amber" },
  { id: "slate", label: "Slate" },
];

export default function Settings() {
  const { settings, resolvedTheme, updateSetting, resetSettings } = useTheme();
  const [confirmReset, setConfirmReset] = useState(false);
  const [apiKeys, setApiKeys] = useState({});
  const [keysLoading, setKeysLoading] = useState(true);
  const [keysError, setKeysError] = useState("");

  useEffect(() => {
    let active = true;
    api.get("/api/settings/api-keys")
      .then((response) => {
        if (active) setApiKeys(response.data.environment || {});
      })
      .catch((error) => {
        if (active) setKeysError(error.response?.data?.detail || "Unable to load environment configuration.");
      })
      .finally(() => {
        if (active) setKeysLoading(false);
      });
    return () => { active = false; };
  }, []);

  return (
    <div className="settings-page">
      <header className="settings-page-heading">
        <div>
          <p className="eyebrow">WORKSPACE PREFERENCES</p>
          <h1>Settings</h1>
          <p className="subtitle">Control the appearance, accessibility and comfort of your workspace.</p>
        </div>
        <span className="settings-theme-indicator"><span className={`settings-theme-dot ${resolvedTheme}`} /> {resolvedTheme === "dark" ? "Dark appearance" : "Light appearance"}</span>
      </header>

      <section className="settings-section">
        <div className="settings-section-heading">
          <div><h2>Appearance</h2><p>Choose how the application looks across every workflow.</p></div>
        </div>
        <div className="settings-row">
          <div className="settings-copy"><strong>Colour theme</strong><span>Use light, dark, or automatically follow your operating system.</span></div>
          <div className="settings-segmented" role="group" aria-label="Colour theme">
            {[{ id: "light", label: "Light" }, { id: "dark", label: "Dark" }, { id: "system", label: "System" }].map((option) => (
              <button key={option.id} className={settings.mode === option.id ? "selected" : ""} onClick={() => updateSetting("mode", option.id)} aria-pressed={settings.mode === option.id}>{option.label}</button>
            ))}
          </div>
        </div>

        <div className="settings-row settings-row-stack">
          <div className="settings-copy"><strong>Accent colour</strong><span>Applied to primary actions, active navigation, focus rings and chart highlights.</span></div>
          <div className="settings-accent-grid" role="group" aria-label="Accent colour presets">
            {ACCENT_OPTIONS.map((option) => (
              <button key={option.id} className={`settings-accent-option ${settings.accent === option.id ? "selected" : ""}`} onClick={() => updateSetting("accent", option.id)} aria-pressed={settings.accent === option.id}>
                <span className="settings-accent-swatch" style={{ "--swatch": ACCENTS[option.id] }} />
                {option.label}
              </button>
            ))}
            <button className={`settings-accent-option ${settings.accent === "custom" ? "selected" : ""}`} onClick={() => updateSetting("accent", "custom")} aria-pressed={settings.accent === "custom"}>
              <span className="settings-accent-swatch settings-custom-swatch" style={{ "--swatch": settings.customAccent }} />
              Custom
            </button>
          </div>
          <div className="settings-custom-colour">
            <label htmlFor="custom-accent">Custom accent</label>
            <input id="custom-accent" type="color" value={settings.customAccent} onChange={(event) => { updateSetting("customAccent", event.target.value); updateSetting("accent", "custom"); }} />
            <code>{settings.customAccent.toUpperCase()}</code>
          </div>
        </div>

        <div className="settings-row">
          <div className="settings-copy"><strong>Interface density</strong><span>Choose the spacing used in cards, tables and content sections.</span></div>
          <div className="settings-segmented" role="group" aria-label="Interface density">
            {[{ id: "comfortable", label: "Comfortable" }, { id: "compact", label: "Compact" }].map((option) => (
              <button key={option.id} className={settings.density === option.id ? "selected" : ""} onClick={() => updateSetting("density", option.id)} aria-pressed={settings.density === option.id}>{option.label}</button>
            ))}
          </div>
        </div>

        <div className="settings-row">
          <div className="settings-copy"><strong>Reduce motion</strong><span>Minimise transitions and animations throughout the interface.</span></div>
          <button className={`settings-switch ${settings.reduceMotion ? "on" : ""}`} role="switch" aria-checked={settings.reduceMotion} onClick={() => updateSetting("reduceMotion", !settings.reduceMotion)}>
            <span /> <span className="settings-switch-label">{settings.reduceMotion ? "On" : "Off"}</span>
          </button>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-heading">
          <div>
            <h2>Model credentials & configuration</h2>
            <p>Environment values used by your analytics model providers. Secret values are masked and never exposed in full.</p>
          </div>
        </div>
        {keysLoading ? <p className="settings-inline-message">Loading environment configuration…</p>
          : keysError ? <p className="settings-inline-message is-error" role="alert">{keysError}</p>
          : <div className="settings-env-list">
            {Object.entries(apiKeys).map(([key, item]) => (
              <div className="settings-env-row" key={key}>
                <div><strong>{key}</strong><small>{item.secret ? "Secret credential" : "Configuration value"}</small></div>
                <code>{item.configured ? item.value : "Not configured"}</code>
                <span className={`settings-env-status ${item.configured ? "is-configured" : ""}`}>{item.configured ? "Configured" : "Missing"}</span>
              </div>
            ))}
            {Object.keys(apiKeys).length === 0 && <p className="settings-inline-message">No environment configuration was returned by the backend.</p>}
          </div>}
        <p className="settings-inline-message">Values are read from the backend <code>.env</code> file. To replace a credential, add or reconnect the relevant model from the Analytics model selector.</p>
      </section>

      <section className="settings-section settings-preview-section">
        <div className="settings-section-heading"><div><h2>Preview</h2><p>See how your selected appearance affects common interface elements.</p></div></div>
        <div className="settings-preview-card">
          <div><span className="settings-preview-label">SAMPLE KPI</span><strong>24,580</strong><small>+12.8% compared with previous period</small></div>
          <div className="settings-preview-actions"><button className="settings-preview-primary">Primary action</button><button className="settings-preview-secondary">Secondary</button></div>
        </div>
      </section>

      <section className="settings-section settings-reset-section">
        <div><h2>Reset preferences</h2><p>Restore light theme, blue accent, comfortable density and standard motion.</p></div>
        {!confirmReset ? (
          <button className="secondary-button" onClick={() => setConfirmReset(true)}>Reset preferences</button>
        ) : (
          <div className="settings-reset-confirm" role="group" aria-label="Confirm reset preferences">
            <span>Reset all appearance preferences?</span>
            <button className="secondary-button" onClick={() => { resetSettings(); setConfirmReset(false); }}>Confirm reset</button>
            <button className="settings-cancel-button" onClick={() => setConfirmReset(false)}>Cancel</button>
          </div>
        )}
      </section>
    </div>
  );
}
