// Root application component: orchestrates sidebar navigation ->
// file upload -> ecommerce dashboard (KPIs, main chart, secondary charts, latest table).
// AI Summary and Chat sections have been removed from the visible main dashboard UI.

import { useCallback, useState } from "react";
import AssistantSidebar from "./components/AssistantSidebar";
import DashboardPresentation from "./components/DashboardPresentation";
import FileUpload from "./components/FileUpload";
import LatestReviews from "./components/LatestReviews";
import Loading from "./components/Loading";
import QuickStatsCard from "./components/QuickStatsCard";
import SecondaryCharts from "./components/SecondaryCharts";
import SettingsPanel from "./components/SettingsPanel";
import Sidebar from "./components/Sidebar";
import TotalSalesChart from "./components/TotalSalesChart";
import WorkbooksPanel from "./components/WorkbooksPanel";
import { getDashboard, getErrorMessage } from "./services/api";
import { SettingsProvider, useSettings } from "./settings/SettingsContext";

function ErrorAlert({ message, onDismiss }) {
  if (!message) return null;

  return (
    <div className="flex items-start justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 shadow-sm">
      <span>{message}</span>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="font-semibold text-rose-500 hover:text-rose-700"
          aria-label="Dismiss error"
        >
          ✕
        </button>
      )}
    </div>
  );
}

export default function App() {
  // The settings are read from storage once, when the provider mounts, and
  // shared with everything that needs them.
  return (
    <SettingsProvider>
      <AppContent />
    </SettingsProvider>
  );
}

function AppContent() {
  const { settings } = useSettings();
  const [activeNav, setActiveNav] = useState("Dashboard");
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isAssistantOpen, setIsAssistantOpen] = useState(false);

  const [dataset, setDataset] = useState(null);
  const [dashboardData, setDashboardData] = useState(null);
  const [isSectionsLoading, setIsSectionsLoading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [sectionsError, setSectionsError] = useState("");
  // The workbook the assistant queries, when one has been chosen. The
  // assistant falls back to the active dataset when there is none.
  const [activeWorkbook, setActiveWorkbook] = useState(null);

  const loadDashboardSections = useCallback(async () => {
    setIsSectionsLoading(true);
    setSectionsError("");
    setDashboardData(null);

    try {
      const data = await getDashboard();
      setDashboardData(data);
    } catch (err) {
      setSectionsError(getErrorMessage(err));
    } finally {
      setIsSectionsLoading(false);
    }
  }, []);

  const handleUploadSuccess = useCallback(
    (data) => {
      setUploadError("");
      setDataset(data);
      loadDashboardSections();
    },
    [loadDashboardSections]
  );

  const handleUploadError = useCallback((message) => {
    setUploadError(message);
  }, []);

  // The overview of a workbook: it becomes the active dataset, and the
  // dashboard is drawn from it. The activation returns the same shape as
  // an upload, so the rest of the dashboard is set up the same way.
  const handleOverview = useCallback(
    (data) => {
      setUploadError("");
      setDataset(data);
      setActiveNav("Dashboard");
      loadDashboardSections();
    },
    [loadDashboardSections]
  );

  const handleNavSelect = useCallback((nav) => {
    // The AI Assistant is a panel beside the dashboard, not a page of its
    // own: it opens on the right and the dashboard stays where it is.
    if (nav === "AI Assistant") {
      setIsAssistantOpen(true);
      return;
    }
    setIsAssistantOpen(false);
    setActiveNav(nav);
  }, []);

  return (
    <div className="app-container">
      {/* Fixed Collapsible Left Sidebar */}
      <Sidebar
        activeNav={activeNav}
        onNavSelect={handleNavSelect}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapse={() => setIsSidebarCollapsed((prev) => !prev)}
        isMobileOpen={isMobileMenuOpen}
        onCloseMobile={() => setIsMobileMenuOpen(false)}
      />

      {/* Main Content Area */}
      <div
        className={`main-wrapper transition-all duration-300 ${
          isSidebarCollapsed ? "lg:ml-20" : "lg:ml-64"
        }`}
      >
        {/* On small screens the sidebar is hidden, so the menu is opened
            from a button that floats over the content instead. */}
        <button
          type="button"
          onClick={() => setIsMobileMenuOpen(true)}
          className="lg:hidden fixed left-4 top-4 z-30 flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-surface text-slate-600 shadow-sm transition-colors hover:bg-slate-50"
          title="Open menu"
          aria-label="Open menu"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>

        <div className="dashboard-layout">
          {/* Content */}
          {activeNav === "Workbooks" ? (
            <WorkbooksPanel
              activeWorkbookId={activeWorkbook?.id}
              onOverview={handleOverview}
              onUseWorkbook={(workbook) => {
                setActiveWorkbook(workbook);
                setIsAssistantOpen(true);
              }}
            />
          ) : activeNav === "Settings" ? (
            <SettingsPanel
              onWorkbooksChanged={() => setActiveWorkbook(null)}
            />
          ) : activeNav !== "Dashboard" ? (
            <div className="rounded-xl border border-slate-200/80 bg-surface p-8 text-center shadow-sm">
              <h2 className="text-base font-bold text-slate-800">{activeNav}</h2>
              <p className="mt-1 text-xs text-slate-400">Section under preparation.</p>
              <button
                type="button"
                onClick={() => setActiveNav("Dashboard")}
                className="mt-4 rounded-xl border border-slate-200 bg-surface px-3.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                Return to Dashboard
              </button>
            </div>
          ) : (
            <>
              <h1 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
                Dashboard
              </h1>

              {/* Upload is the only actionable surface before a dataset exists. */}
              <section className="rounded-xl border border-slate-200/80 bg-surface p-5 shadow-sm">
                <FileUpload
                  dataset={dataset}
                  error={uploadError}
                  onUploadSuccess={handleUploadSuccess}
                  onUploadError={handleUploadError}
                  onClearError={() => setUploadError("")}
                />
              </section>

              {dataset && (
                <>
                  <ErrorAlert message={sectionsError} onDismiss={() => setSectionsError("")} />

                  {isSectionsLoading && <Loading label="Building your ecommerce dashboard..." />}

                  {!isSectionsLoading && dashboardData && (
                    <>
                      {/* Main chart spans the left column; supporting charts fill a 2x2 block. */}
                      <div className="main-content-grid">
                        <TotalSalesChart chart={dashboardData.main_chart} />
                        <SecondaryCharts
                          charts={dashboardData.secondary_charts}
                          kpis={dashboardData.kpis}
                        />
                      </div>

                      {/* Headline metrics, between the charts and the activity table */}
                      <QuickStatsCard stats={dashboardData.quick_stats || []} />

                      {/* Bottom: Latest Reviews / Orders Table */}
                      {dashboardData.latest_table && (
                        <LatestReviews table={dashboardData.latest_table} />
                      )}
                    </>
                  )}
                </>
              )}

              {/* The generation action appears only after upload succeeds. */}
              {dataset && <DashboardPresentation dataset={dataset} settings={settings} />}
            </>
          )}
        </div>
      </div>

      {/* The AI Assistant lives in a right-hand panel beside the dashboard. */}
      <AssistantSidebar
        isOpen={isAssistantOpen}
        onClose={() => setIsAssistantOpen(false)}
        dataset={dataset}
        hasDataset={Boolean(dataset)}
        workbook={activeWorkbook}
        showSupportingData={settings.ai_assistant.show_supporting_data}
      />
    </div>
  );
}
