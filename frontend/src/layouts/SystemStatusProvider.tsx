import { createContext, useContext, type ReactNode } from 'react';
import { useHealth } from '@/hooks';
import type { HealthResponse } from '@/services/types';
import { ApiClientError } from '@/services/api';

/**
 * Shares one `/api/health` poll across the whole dashboard.
 *
 * Several places need it at once - the sidebar badge, the top bar indicator,
 * the test-mode banner, the Detect page's "can I predict?" check. Without a
 * shared provider each would poll independently and hit the single-threaded
 * Flask dev server four times every twenty seconds.
 */

interface SystemStatusValue {
  health: HealthResponse | null;
  error: ApiClientError | null;
  isLoading: boolean;
  isRefreshing: boolean;
  lastUpdated: Date | null;
  refresh: () => Promise<void>;
  /** The backend answered at least once and is currently reachable. */
  isBackendOnline: boolean;
  isTestMode: boolean;
  canPredict: boolean;
  isDeviceOnline: boolean;
}

const SystemStatusContext = createContext<SystemStatusValue | null>(null);

export function SystemStatusProvider({ children }: { children: ReactNode }) {
  const { data, error, isLoading, isRefreshing, lastUpdated, refresh } = useHealth();

  const value: SystemStatusValue = {
    health: data,
    error,
    isLoading,
    isRefreshing,
    lastUpdated,
    refresh,
    isBackendOnline: Boolean(data) && !error?.isBackendUnreachable,
    isTestMode: Boolean(data?.model.is_test_mode),
    canPredict: Boolean(data?.model.can_predict),
    isDeviceOnline: Boolean(data?.device.is_online),
  };

  return <SystemStatusContext.Provider value={value}>{children}</SystemStatusContext.Provider>;
}

export function useSystemStatus(): SystemStatusValue {
  const context = useContext(SystemStatusContext);
  if (!context) {
    throw new Error('useSystemStatus must be used inside a SystemStatusProvider.');
  }
  return context;
}
