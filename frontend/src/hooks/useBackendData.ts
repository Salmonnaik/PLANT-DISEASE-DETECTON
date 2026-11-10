/**
 * useBackendData
 * ==============
 * One typed hook per API endpoint, each a thin wrapper over `useApiResource`.
 *
 * Poll intervals are chosen per resource rather than globally: device liveness
 * changes second-to-second and needs frequent polling, statistics only change
 * when a scan happens, and the class list never changes while the server runs.
 */

import { useCallback, useMemo } from 'react';
import { cameraApi, deviceApi, historyApi, plantApi, statsApi, systemApi } from '@/services/api';
import type { HistoryQuery } from '@/services/types';
import { useApiResource, type UseApiResourceOptions } from './useApiResource';

/** Health drives the global "backend offline" and "test mode" banners. */
export function useHealth(options: UseApiResourceOptions = {}) {
  return useApiResource(() => systemApi.health(), [], { pollMs: 20_000, ...options });
}

export function useStats(days = 14, recent = 5, options: UseApiResourceOptions = {}) {
  const fetcher = useCallback(() => statsApi.overview({ days, recent }), [days, recent]);
  return useApiResource(fetcher, [days, recent], { pollMs: 15_000, ...options });
}

export function useAnalytics(days = 30, options: UseApiResourceOptions = {}) {
  const fetcher = useCallback(() => statsApi.analytics(days), [days]);
  return useApiResource(fetcher, [days], { pollMs: 30_000, ...options });
}

/** The camera's online state is the fastest-moving value in the app. */
export function useDeviceStatus(pollMs = 6_000, options: UseApiResourceOptions = {}) {
  return useApiResource(() => deviceApi.status(), [], { pollMs, ...options });
}

/** Static for the lifetime of the server process, so it is fetched once. */
export function useClasses(options: UseApiResourceOptions = {}) {
  return useApiResource(() => systemApi.classes(), [], options);
}

export function useHistory(query: HistoryQuery, options: UseApiResourceOptions = {}) {
  // Serialise the query so the dependency is a primitive: a new object literal
  // on every render would otherwise retrigger the fetch endlessly.
  const key = useMemo(() => JSON.stringify(query), [query]);
  const fetcher = useCallback(() => historyApi.list(query), [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return useApiResource(fetcher, [key], options);
}

export function useHistoryFilters(options: UseApiResourceOptions = {}) {
  return useApiResource(() => historyApi.filters(), [], options);
}

/**
 * Available camera sources.
 *
 * Polled on the same cadence as the device status, because the ESP32-CAM entry
 * carries its online state and that is the fastest-moving value on the page.
 */
export function useCameras(pollMs = 8_000, options: UseApiResourceOptions = {}) {
  return useApiResource(() => cameraApi.list(), [], { pollMs, ...options });
}

export function useDeviceConfig(options: UseApiResourceOptions = {}) {
  return useApiResource(() => cameraApi.getConfig(), [], options);
}

/** Plant species with care profiles. Static for the server's lifetime. */
export function usePlants(options: UseApiResourceOptions = {}) {
  return useApiResource(() => plantApi.list(), [], options);
}
