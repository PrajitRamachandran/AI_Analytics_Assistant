export const NAV_GROUPS = [
  {
    label: "WORKSPACE",
    items: [
      { id: "overview", label: "Overview", path: "/", icon: "◫" },
      { id: "upload", label: "Upload Dataset", path: "/upload", icon: "⇧" },
      { id: "datasets", label: "My Datasets", path: "/datasets", icon: "▤" },
    ],
  },
  {
    label: "DATA WORKFLOW",
    items: [
      { id: "processing", label: "Data Processing", path: "/processing", icon: "⚙" },
      { id: "profile", label: "Data Profile", path: "/profile", icon: "⌕" },
      { id: "analytics", label: "Analytics", path: "/analytics", icon: "▥" },
    ],
  },
];

export const PAGE_META = {
  overview: { title: "Overview", description: "Your analytics workspace at a glance." },
  upload: { title: "Upload Dataset", description: "Add an Excel workbook to your workspace." },
  datasets: { title: "My Datasets", description: "Browse and manage your uploaded workbooks." },
  processing: { title: "Data Processing", description: "Prepare worksheets and inspect data quality." },
  profile: { title: "Data Profile", description: "Understand columns, distributions and data quality." },
  analytics: { title: "Analytics", description: "Explore generated KPIs, charts and insights." },
  settings: { title: "Settings", description: "Manage your workspace preferences." },
};

export function resolveRoute(pathname) {
  if (pathname === "/") return { id: "overview" };
  if (pathname === "/upload") return { id: "upload" };
  if (pathname === "/datasets") return { id: "datasets" };
  if (pathname === "/settings") return { id: "settings" };

  const datasetRoute = pathname.match(/^\/datasets\/([^/]+)\/(processing|profile|analytics)$/);
  if (datasetRoute) {
    const stage = datasetRoute[2];
    return { id: stage, datasetId: decodeURIComponent(datasetRoute[1]) };
  }

  if (pathname === "/processing") return { id: "processing" };
  if (pathname === "/profile") return { id: "profile" };
  if (pathname === "/analytics") return { id: "analytics" };
  return { id: "notFound" };
}
