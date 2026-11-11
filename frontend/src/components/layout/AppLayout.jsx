import { useEffect, useMemo, useState } from "react";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import RoutePlaceholder from "./RoutePlaceholder";
import Settings from "../../pages/Settings";
import { PAGE_META, resolveRoute } from "../../app/routeConfig";
import { useAppLocation, useAppNavigate } from "../../app/navigation";

export default function AppLayout({ children, pageContent = {} }) {
  const location = useAppLocation();
  const navigate = useAppNavigate();
  const route = useMemo(() => resolveRoute(location.split("?")[0].split("#")[0]), [location]);
  const activeItem = route.id;
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem("ai-data-analytics-sidebar") === "collapsed";
    } catch {
      return false;
    }
  });
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    try {
      window.localStorage.setItem("ai-data-analytics-sidebar", collapsed ? "collapsed" : "expanded");
    } catch {
      // Sidebar preference remains available for the current session.
    }
  }, [collapsed]);

  useEffect(() => {
    setMobileOpen(false);
  }, [location]);

  const page = PAGE_META[activeItem];
  const content = activeItem === "overview"
    ? children
    : activeItem === "settings"
      ? <Settings />
      : pageContent[activeItem] || (
        <RoutePlaceholder
          title={page?.title || "Page not found"}
          description={page?.description || "The page you requested does not exist."}
          stage={activeItem}
        />
      );

  return (
    <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      <Sidebar
        activeItem={activeItem}
        onNavigate={navigate}
        collapsed={collapsed}
        onToggle={() => setCollapsed((value) => !value)}
        mobileOpen={mobileOpen}
        onClose={() => setMobileOpen(false)}
      />
      <div className="app-main-column">
        <Topbar title={page?.title || "Workspace"} onMenuClick={() => setMobileOpen(true)} />
        <main className="app-main-content" key={location}>
          {content}
        </main>
      </div>
    </div>
  );
}
