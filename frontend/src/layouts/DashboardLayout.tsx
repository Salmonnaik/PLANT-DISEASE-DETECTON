import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from '@/components/layout/Sidebar';
import { TopBar } from '@/components/layout/TopBar';
import { SystemBanners } from '@/components/banners/SystemBanners';
import { SystemStatusProvider, useSystemStatus } from './SystemStatusProvider';

function LayoutShell() {
  const [isSidebarOpen, setSidebarOpen] = useState(false);
  const { pathname } = useLocation();
  const { health, error, refresh, isRefreshing } = useSystemStatus();

  // Scroll to the top on navigation; without this, moving from a long History
  // page to the Dashboard leaves the viewport halfway down the new page.
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
    setSidebarOpen(false);
  }, [pathname]);

  return (
    <div className="min-h-full bg-bark-50">
      <Sidebar isOpen={isSidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="lg:pl-72">
        <TopBar onOpenSidebar={() => setSidebarOpen(true)} />

        <main className="mx-auto w-full max-w-[1600px] space-y-5 px-4 py-5 sm:px-6 sm:py-6">
          <SystemBanners
            health={health}
            error={error}
            onRetry={() => void refresh()}
            isRetrying={isRefreshing}
          />
          <Outlet />

          <footer className="flex flex-col items-start justify-between gap-2 border-t border-bark-100 pt-5 text-xs text-bark-400 sm:flex-row sm:items-center">
            <p>
              AI-Based Smart Plant Disease Detection and Classification &middot; ESP32-CAM +
              MobileNetV2
            </p>
            {health && (
              <p className="font-mono">
                API v{health.app.version} &middot; Python {health.app.python_version}
                {health.model.tensorflow_version && ` \u00b7 TF ${health.model.tensorflow_version}`}
              </p>
            )}
          </footer>
        </main>
      </div>
    </div>
  );
}

export function DashboardLayout() {
  return (
    <SystemStatusProvider>
      <LayoutShell />
    </SystemStatusProvider>
  );
}

export default DashboardLayout;
