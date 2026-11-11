import { useTheme } from "../../context/ThemeContext";

export default function Topbar({ title, onMenuClick }) {
  const { resolvedTheme, toggleTheme } = useTheme();
  return (
    <header className="app-topbar">
      <div className="topbar-leading">
        <button className="mobile-menu-button" onClick={onMenuClick} aria-label="Open navigation">☰</button>
        <div className="breadcrumb">
          <span>Workspace</span>
          <span className="breadcrumb-separator">/</span>
          <strong>{title}</strong>
        </div>
      </div>
      <div className="topbar-actions">
        <span className="workspace-status"><span className="status-dot" /> Local workspace</span>
        <button
          className="icon-button theme-toggle"
          onClick={toggleTheme}
          aria-label={`Switch to ${resolvedTheme === "dark" ? "light" : "dark"} mode`}
          title={`Switch to ${resolvedTheme === "dark" ? "light" : "dark"} mode`}
        >
          {resolvedTheme === "dark" ? "☀" : "◐"}
        </button>
      </div>
    </header>
  );
}
