export const DEFAULT_SETTINGS = Object.freeze({
  mode: "light",
  accent: "blue",
  customAccent: "#2563eb",
  density: "comfortable",
  reduceMotion: false,
});

export const ACCENTS = Object.freeze({
  blue: "#2563eb",
  violet: "#7c3aed",
  emerald: "#059669",
  rose: "#e11d48",
  amber: "#d97706",
  slate: "#475569",
});

const HEX_COLOR = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

export function normalizeSettings(value) {
  const stored = value && typeof value === "object" ? value : {};
  return {
    mode: ["light", "dark", "system"].includes(stored.mode) ? stored.mode : DEFAULT_SETTINGS.mode,
    accent: Object.hasOwn(ACCENTS, stored.accent) || stored.accent === "custom"
      ? stored.accent : DEFAULT_SETTINGS.accent,
    customAccent: typeof stored.customAccent === "string" && HEX_COLOR.test(stored.customAccent)
      ? stored.customAccent : DEFAULT_SETTINGS.customAccent,
    density: ["comfortable", "compact"].includes(stored.density) ? stored.density : DEFAULT_SETTINGS.density,
    reduceMotion: stored.reduceMotion === true,
  };
}
