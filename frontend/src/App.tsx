import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import DashboardLayout from '@/layouts/DashboardLayout';
import LandingPage from '@/pages/LandingPage';
import { Spinner } from '@/components/ui';

/**
 * Routing.
 *
 * The landing page is eager (it is the first paint and must be instant); the
 * dashboard pages are code-split, which keeps Recharts out of the initial
 * bundle for a visitor who only reads the landing page.
 */
const DashboardPage = lazy(() => import('@/pages/DashboardPage'));
const DetectionPage = lazy(() => import('@/pages/DetectionPage'));
const CameraPage = lazy(() => import('@/pages/CameraPage'));
const HistoryPage = lazy(() => import('@/pages/HistoryPage'));
const AnalyticsPage = lazy(() => import('@/pages/AnalyticsPage'));
const DevicePage = lazy(() => import('@/pages/DevicePage'));
const AboutPage = lazy(() => import('@/pages/AboutPage'));

function RouteFallback() {
  return (
    <div className="flex min-h-[55vh] flex-col items-center justify-center gap-3 text-bark-400">
      <Spinner className="h-6 w-6 text-leaf-500" />
      <p className="text-sm font-medium">Loading page...</p>
    </div>
  );
}

function NotFoundPage() {
  return (
    <div className="card flex flex-col items-center gap-3 px-6 py-16 text-center">
      <p className="text-5xl font-bold text-leaf-200">404</p>
      <h2 className="text-lg font-semibold text-bark-800">Page not found</h2>
      <p className="max-w-md text-sm text-bark-500">
        That route does not exist in the dashboard. Use the sidebar to continue.
      </p>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />

      <Route
        element={
          <Suspense fallback={<RouteFallback />}>
            <DashboardLayout />
          </Suspense>
        }
      >
        <Route
          path="/dashboard"
          element={
            <Suspense fallback={<RouteFallback />}>
              <DashboardPage />
            </Suspense>
          }
        />
        <Route
          path="/detect"
          element={
            <Suspense fallback={<RouteFallback />}>
              <DetectionPage />
            </Suspense>
          }
        />
        <Route
          path="/cameras"
          element={
            <Suspense fallback={<RouteFallback />}>
              <CameraPage />
            </Suspense>
          }
        />
        <Route
          path="/history"
          element={
            <Suspense fallback={<RouteFallback />}>
              <HistoryPage />
            </Suspense>
          }
        />
        <Route
          path="/analytics"
          element={
            <Suspense fallback={<RouteFallback />}>
              <AnalyticsPage />
            </Suspense>
          }
        />
        <Route
          path="/device"
          element={
            <Suspense fallback={<RouteFallback />}>
              <DevicePage />
            </Suspense>
          }
        />
        <Route
          path="/about"
          element={
            <Suspense fallback={<RouteFallback />}>
              <AboutPage />
            </Suspense>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>

      <Route path="/index.html" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
