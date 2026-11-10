/**
 * useApiResource
 * ==============
 * The data-fetching primitive used by every page.
 *
 * Handles the four things each page would otherwise reimplement: loading state,
 * normalised errors, optional polling, and discarding results that arrive after
 * the component unmounted or after a newer request was issued.
 *
 * The fetcher is held in a ref and the effect keys off an explicit `deps` array.
 * Without that, passing an inline arrow function (the natural way to call this)
 * would change identity on every render and re-fetch forever.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiClientError } from '@/services/api';

export interface UseApiResourceOptions {
  /** Poll every N milliseconds while the tab is visible. 0 or undefined disables polling. */
  pollMs?: number;
  /** Skip fetching entirely (e.g. while a prerequisite is missing). */
  enabled?: boolean;
  /** Keep the previous value visible while refetching instead of flashing a skeleton. */
  keepPreviousData?: boolean;
}

export interface UseApiResourceResult<T> {
  data: T | null;
  error: ApiClientError | null;
  isLoading: boolean;
  isRefreshing: boolean;
  lastUpdated: Date | null;
  refresh: () => Promise<void>;
  setData: (value: T | null) => void;
}

export function useApiResource<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  options: UseApiResourceOptions = {},
): UseApiResourceResult<T> {
  const { pollMs = 0, enabled = true, keepPreviousData = true } = options;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(enabled);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const mountedRef = useRef(true);
  // Monotonic request id: only the newest in-flight request may write state,
  // which prevents a slow earlier response from overwriting a newer one.
  const requestIdRef = useRef(0);
  const hasDataRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(async (isBackground: boolean) => {
    if (!enabled) return;

    const requestId = ++requestIdRef.current;
    if (isBackground || (keepPreviousData && hasDataRef.current)) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }

    try {
      const result = await fetcherRef.current();
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      setData(result);
      hasDataRef.current = true;
      setError(null);
      setLastUpdated(new Date());
    } catch (caught) {
      if (!mountedRef.current || requestId !== requestIdRef.current) return;
      const normalised =
        caught instanceof ApiClientError
          ? caught
          : new ApiClientError(caught instanceof Error ? caught.message : 'Request failed.');
      setError(normalised);
      if (!keepPreviousData) {
        setData(null);
        hasDataRef.current = false;
      }
    } finally {
      if (mountedRef.current && requestId === requestIdRef.current) {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, [enabled, keepPreviousData]);

  // Initial fetch and refetch when deps change.
  useEffect(() => {
    if (!enabled) {
      setIsLoading(false);
      return;
    }
    void load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps]);

  // Polling, paused while the tab is hidden so a background tab does not
  // hammer the Flask dev server (which serves requests on a small thread pool).
  useEffect(() => {
    if (!enabled || !pollMs) return;

    let timer: number | undefined;

    const schedule = () => {
      timer = window.setInterval(() => {
        if (document.visibilityState === 'visible') {
          void load(true);
        }
      }, pollMs);
    };

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') void load(true);
    };

    schedule();
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      if (timer) window.clearInterval(timer);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, pollMs, ...deps]);

  const refresh = useCallback(() => load(true), [load]);

  return { data, error, isLoading, isRefreshing, lastUpdated, refresh, setData };
}

export default useApiResource;
