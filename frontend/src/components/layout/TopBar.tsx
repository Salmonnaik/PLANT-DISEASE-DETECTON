import { useLocation } from 'react-router-dom';
import { Menu, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import { useSystemStatus } from '@/layouts/SystemStatusProvider';
import { Spinner } from '@/components/ui';
import { classNames, formatRelative } from '@/utils/format';
import { NAV_ITEMS } from './Sidebar';

interface TopBarProps {
  onOpenSidebar: () => void;
}

export function TopBar({ onOpenSidebar }: TopBarProps) {
  const { pathname } = useLocation();
  const { isBackendOnline, isRefreshing, refresh, health, lastUpdated } = useSystemStatus();

  const lastCheckedLabel = lastUpdated
    ? `Last health check ${formatRelative(lastUpdated.toISOString())}`
    : 'Checking backend...';

  const current = NAV_ITEMS.find((item) => pathname.startsWith(item.to));

  return (
    <header className="sticky top-0 z-20 border-b border-bark-100 bg-white/85 backdrop-blur-md">
      <div className="flex items-center gap-3 px-4 py-3 sm:px-6">
        <button
          type="button"
          onClick={onOpenSidebar}
          className="btn-ghost btn-sm lg:hidden"
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </button>

        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg font-semibold text-bark-900 sm:text-xl">
            {current?.label ?? 'Dashboard'}
          </h1>
          <p className="hidden truncate text-sm text-bark-500 sm:block">
            {current?.description ?? 'Smart plant disease detection'}
          </p>
        </div>

        {/* Backend connection indicator */}
        <div
          className={classNames(
            'hidden items-center gap-2 rounded-xl border px-3 py-1.5 sm:flex',
            isBackendOnline
              ? 'border-leaf-200 bg-leaf-50 text-leaf-700'
              : 'border-blight-200 bg-blight-50 text-blight-700',
          )}
          title={
            isBackendOnline
              ? `Flask backend reachable${health?.app.version ? ` (v${health.app.version})` : ''}`
              : 'Flask backend is not responding'
          }
        >
          {isBackendOnline ? <Wifi className="h-4 w-4" /> : <WifiOff className="h-4 w-4" />}
          <span className="text-xs font-semibold">{isBackendOnline ? 'API online' : 'API offline'}</span>
        </div>

        <button
          type="button"
          onClick={() => void refresh()}
          className="btn-secondary btn-sm"
          disabled={isRefreshing}
          title={lastCheckedLabel}
        >
          {isRefreshing ? <Spinner /> : <RefreshCw className="h-3.5 w-3.5" />}
          <span className="hidden sm:inline">Refresh</span>
        </button>
      </div>
    </header>
  );
}

export default TopBar;
