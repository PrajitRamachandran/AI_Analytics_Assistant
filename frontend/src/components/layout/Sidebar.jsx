import { NAV_GROUPS } from "../../app/routeConfig";

export default function Sidebar({
  activeItem,
  onNavigate,
  collapsed,
  onToggle,
  mobileOpen,
  onClose,
}) {
  return (
    <>
      {mobileOpen && (
        <button className="sidebar-backdrop" aria-label="Close navigation" onClick={onClose} />
      )}
      <aside className={`app-sidebar ${collapsed ? "is-collapsed" : ""} ${mobileOpen ? "is-mobile-open" : ""}`}>
        <div className="sidebar-brand">
          <div className="brand-mark" aria-hidden="true">A</div>
          {!collapsed && (
            <div className="brand-copy">
              <strong>AI Analytics</strong>
              <span>Analytics workspace</span>
            </div>
          )}
          <button
            className="sidebar-collapse"
            onClick={onToggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? "›" : "‹"}
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Main navigation">
          {NAV_GROUPS.map((group) => (
            <div className="sidebar-nav-group" key={group.label}>
              {!collapsed && <div className="sidebar-group-label">{group.label}</div>}
              {group.items.map((item) => (
                <button
                  className={`sidebar-nav-item ${activeItem === item.id ? "active" : ""}`}
                  key={item.id}
                  onClick={() => { onNavigate(item.path); onClose(); }}
                  title={collapsed ? item.label : undefined}
                  aria-current={activeItem === item.id ? "page" : undefined}
                >
                  <span className="nav-icon" aria-hidden="true">{item.icon}</span>
                  {!collapsed && <span>{item.label}</span>}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <button
            className={`sidebar-nav-item ${activeItem === "settings" ? "active" : ""}`}
            onClick={() => { onNavigate("/settings"); onClose(); }}
            title={collapsed ? "Settings" : undefined}
            aria-current={activeItem === "settings" ? "page" : undefined}
          >
            <span className="nav-icon" aria-hidden="true">⚙</span>
            {!collapsed && <span>Settings</span>}
          </button>
          {!collapsed && (
            <div className="sidebar-version">
              AI Data Analytics Assistant <span>V1 workspace</span>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
