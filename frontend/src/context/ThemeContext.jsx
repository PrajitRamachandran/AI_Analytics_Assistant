import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ACCENTS, DEFAULT_SETTINGS, normalizeSettings } from "./appearanceUtils";

const STORAGE_KEY = "ai-data-analytics-appearance";
const ThemeContext = createContext(null);

function readSettings() {
  try {
    return normalizeSettings(JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null"));
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

function readSystemDark() {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

export function ThemeProvider({ children }) {
  const [settings, setSettings] = useState(readSettings);
  const [systemDark, setSystemDark] = useState(readSystemDark);

  useEffect(() => {
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!media) return undefined;
    const update = (event) => setSystemDark(event.matches);
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);

  const resolvedTheme = settings.mode === "system"
    ? (systemDark ? "dark" : "light")
    : settings.mode;

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolvedTheme;
    root.dataset.density = settings.density;
    root.dataset.reducedMotion = String(settings.reduceMotion);

    const accent = settings.accent === "custom"
      ? settings.customAccent
      : ACCENTS[settings.accent] || ACCENTS.blue;
    root.style.setProperty("--accent", accent);
    root.style.setProperty("--accent-hover", `color-mix(in srgb, ${accent} 84%, #000)`);
    root.style.setProperty("--accent-soft", `color-mix(in srgb, ${accent} 9%, var(--surface))`);
    root.style.setProperty("--accent-border", `color-mix(in srgb, ${accent} 30%, var(--border))`);

    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      // Keep the selected appearance active for this session if storage is unavailable.
    }
  }, [resolvedTheme, settings]);

  const updateSetting = useCallback((key, value) => {
    setSettings((current) => normalizeSettings({ ...current, [key]: value }));
  }, []);

  const toggleTheme = useCallback(() => {
    setSettings((current) => ({
      ...current,
      mode: (current.mode === "dark" || (current.mode === "system" && systemDark)) ? "light" : "dark",
    }));
  }, [systemDark]);

  const resetSettings = useCallback(() => setSettings({ ...DEFAULT_SETTINGS }), []);
  const value = useMemo(() => ({
    settings, resolvedTheme, updateSetting, toggleTheme, resetSettings,
  }), [settings, resolvedTheme, updateSetting, toggleTheme, resetSettings]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider");
  return context;
}
