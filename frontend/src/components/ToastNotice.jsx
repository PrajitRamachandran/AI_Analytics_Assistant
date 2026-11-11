import { useEffect } from "react";

export default function ToastNotice({ type = "info", title, message, onDismiss, duration = 5500 }) {
  useEffect(() => {
    if (!message || !duration) return undefined;
    const timeout = window.setTimeout(onDismiss, duration);
    return () => window.clearTimeout(timeout);
  }, [message, duration, onDismiss]);

  if (!message) return null;
  return (
    <div className={`app-toast app-toast-${type}`} role={type === "error" ? "alert" : "status"} aria-live={type === "error" ? "assertive" : "polite"}>
      <span className="app-toast-icon" aria-hidden="true">{type === "error" ? "!" : "✓"}</span>
      <div className="app-toast-copy"><strong>{title || (type === "error" ? "Something went wrong" : "Success")}</strong><span>{message}</span></div>
      <button onClick={onDismiss} aria-label="Dismiss notification">×</button>
    </div>
  );
}
