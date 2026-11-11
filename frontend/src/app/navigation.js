import { useCallback, useSyncExternalStore } from "react";

function subscribe(onChange) {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

function getSnapshot() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

export function useAppLocation() {
  return useSyncExternalStore(subscribe, getSnapshot, () => "/");
}

export function useAppNavigate() {
  return useCallback((to, options = {}) => {
    if (!to || typeof to !== "string") return;
    const target = new URL(to, window.location.origin);
    if (target.origin !== window.location.origin) return;

    const next = `${target.pathname}${target.search}${target.hash}`;
    const current = getSnapshot();
    if (next === current) return;

    if (options.replace) {
      window.history.replaceState({}, "", next);
    } else {
      window.history.pushState({}, "", next);
    }
    window.dispatchEvent(new PopStateEvent("popstate"));
    window.scrollTo(0, 0);
  }, []);
}
