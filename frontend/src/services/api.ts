/**
 * services/api.ts
 * ===============
 * The single Axios client for the Flask backend.
 *
 * Two jobs:
 *
 * 1. **Unwrap the envelope.** Every backend response is
 *    `{success, data, message, error}`; the interceptor returns `data` (plus the
 *    message where callers need it) so components never write `res.data.data`.
 *
 * 2. **Normalise failures.** Network errors, HTTP errors and backend
 *    `error.code` payloads all become one `ApiClientError`, so a component can
 *    render `error.message` and trust it is a sentence meant for a human.
 *
 * Base URL: empty by default, i.e. same-origin relative requests, which the
 * Vite dev proxy forwards to the backend. Set `VITE_API_BASE_URL` to point the
 * built bundle at a backend on another host.
 */

import axios, { AxiosError, type AxiosInstance, type AxiosRequestConfig } from 'axios';
import type {
  AnalyticsResponse,
  ApiEnvelope,
  CameraSource,
  CamerasResponse,
  ClassesResponse,
  DetectionRecord,
  DetectionResponse,
  DeviceConfigResponse,
  DeviceStatus,
  DeviceStatusResponse,
  HealthResponse,
  HistoryFilters,
  HistoryQuery,
  ModelStatus,
  PaginatedData,
  PlantsResponse,
  StatsResponse,
} from './types';

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

/** Capture can block while the firmware is polled, so it needs a long ceiling. */
const DEFAULT_TIMEOUT = 20_000;
const CAPTURE_TIMEOUT = 120_000;
const PREDICT_TIMEOUT = 90_000;

export class ApiClientError extends Error {
  readonly code: string;
  readonly status: number | null;
  readonly details: unknown;
  readonly isNetworkError: boolean;

  constructor(
    message: string,
    options: {
      code?: string;
      status?: number | null;
      details?: unknown;
      isNetworkError?: boolean;
    } = {},
  ) {
    super(message);
    this.name = 'ApiClientError';
    this.code = options.code ?? 'UNKNOWN';
    this.status = options.status ?? null;
    this.details = options.details;
    this.isNetworkError = options.isNetworkError ?? false;
  }

  /** True when the backend is probably not running at all. */
  get isBackendUnreachable(): boolean {
    return this.isNetworkError || this.code === 'BACKEND_UNREACHABLE';
  }

  get isModelUnavailable(): boolean {
    return this.code === 'MODEL_UNAVAILABLE';
  }

  get isDeviceUnreachable(): boolean {
    return this.code === 'DEVICE_UNREACHABLE';
  }
}

const client: AxiosInstance = axios.create({
  baseURL: API_BASE_URL || undefined,
  timeout: DEFAULT_TIMEOUT,
  headers: { Accept: 'application/json' },
});

function toClientError(error: unknown): ApiClientError {
  if (error instanceof ApiClientError) return error;

  const axiosError = error as AxiosError<ApiEnvelope<unknown>>;

  if (axiosError?.code === 'ECONNABORTED' || axiosError?.code === 'ETIMEDOUT') {
    return new ApiClientError(
      'The request timed out. The backend may be busy loading the model, or an ESP32-CAM capture is still in progress.',
      { code: 'TIMEOUT', isNetworkError: false },
    );
  }

  if (axiosError?.response) {
    const body = axiosError.response.data;
    const backendError = body?.error;
    return new ApiClientError(
      backendError?.message || axiosError.message || 'The request failed.',
      {
        code: backendError?.code ?? `HTTP_${axiosError.response.status}`,
        status: axiosError.response.status,
        details: backendError?.details,
      },
    );
  }

  if (axiosError?.request) {
    return new ApiClientError(
      'Cannot reach the backend. Start it with `python app.py` in the backend folder, then retry.',
      { code: 'BACKEND_UNREACHABLE', isNetworkError: true },
    );
  }

  return new ApiClientError(
    error instanceof Error ? error.message : 'An unexpected error occurred.',
    { code: 'UNKNOWN' },
  );
}

/** Perform a request and return the unwrapped `data` payload. */
async function request<T>(config: AxiosRequestConfig): Promise<T> {
  try {
    const response = await client.request<ApiEnvelope<T>>(config);
    const body = response.data;

    if (body && typeof body === 'object' && 'success' in body) {
      if (!body.success) {
        throw new ApiClientError(body.error?.message ?? 'The request failed.', {
          code: body.error?.code,
          status: response.status,
          details: body.error?.details,
        });
      }
      return body.data;
    }
    // Endpoints outside the envelope convention (e.g. GET /api).
    return body as unknown as T;
  } catch (error) {
    throw toClientError(error);
  }
}

/** Same as `request`, but keeps the human-readable `message` from the envelope. */
async function requestWithMessage<T>(
  config: AxiosRequestConfig,
): Promise<{ data: T; message: string | null }> {
  try {
    const response = await client.request<ApiEnvelope<T>>(config);
    const body = response.data;
    if (!body.success) {
      throw new ApiClientError(body.error?.message ?? 'The request failed.', {
        code: body.error?.code,
        status: response.status,
        details: body.error?.details,
      });
    }
    return { data: body.data, message: body.message };
  } catch (error) {
    throw toClientError(error);
  }
}

/* ------------------------------------------------------------------ */
/* System                                                              */
/* ------------------------------------------------------------------ */

export const systemApi = {
  /**
   * `/api/health` answers 503 when the model or database is unusable, but the
   * body still describes *why*. `validateStatus` lets that body through so the
   * dashboard can show "backend up, model missing" instead of a generic error.
   */
  async health(): Promise<HealthResponse> {
    try {
      const response = await client.get<ApiEnvelope<HealthResponse>>('/api/health', {
        validateStatus: (status) => status === 200 || status === 503,
      });
      return response.data.data;
    } catch (error) {
      throw toClientError(error);
    }
  },

  classes(): Promise<ClassesResponse> {
    return request<ClassesResponse>({ url: '/api/classes', method: 'GET' });
  },

  reloadModel(): Promise<{ reloaded: boolean; model: ModelStatus }> {
    return request({ url: '/api/model/reload', method: 'POST', timeout: PREDICT_TIMEOUT });
  },
};

/* ------------------------------------------------------------------ */
/* Detection                                                           */
/* ------------------------------------------------------------------ */

export interface PredictOptions {
  threshold?: number;
  save?: boolean;
  /**
   * Which camera produced the image. Recorded with the detection so history
   * and analytics can be filtered by camera; it does not change how the image
   * is processed - every source runs the identical pipeline.
   */
  cameraSource?: CameraSource;
  onProgress?: (percent: number) => void;
}

export const detectionApi = {
  /**
   * Classify an image from the browser.
   *
   * Takes a `File`, which is what both callers naturally hold: the file picker
   * yields one directly, and a webcam capture produces a Blob that
   * `useWebcam` already wraps in a `File`. One function therefore serves the
   * upload and webcam paths without duplicating the multipart construction.
   */
  async predictUpload(
    file: File,
    options: PredictOptions = {},
  ): Promise<{ data: DetectionResponse; message: string | null }> {
    const form = new FormData();
    form.append('image', file, file.name);
    if (options.threshold !== undefined) form.append('threshold', String(options.threshold));
    if (options.save !== undefined) form.append('save', String(options.save));
    form.append('camera_source', options.cameraSource ?? 'file_upload');

    return requestWithMessage<DetectionResponse>({
      url: '/api/predict',
      method: 'POST',
      data: form,
      timeout: PREDICT_TIMEOUT,
      onUploadProgress: (event) => {
        if (options.onProgress && event.total) {
          options.onProgress(Math.round((event.loaded / event.total) * 100));
        }
      },
    });
  },

  /** Classify a webcam frame. Thin wrapper that fixes the camera source. */
  predictWebcam(
    file: File,
    options: Omit<PredictOptions, 'cameraSource'> = {},
  ): Promise<{ data: DetectionResponse; message: string | null }> {
    return detectionApi.predictUpload(file, { ...options, cameraSource: 'laptop_webcam' });
  },

  /**
   * Universal analysis - works for ANY plant species.
   *
   * Unlike `predictUpload`, this does not force the image into one of the
   * classifier's ten trained classes. Pass `plantSpecies` when the user has
   * told us what the plant is: it is the most reliable species signal
   * available and makes the care guidance species-specific.
   */
  async analyzePlant(
    file: File,
    options: PredictOptions & { plantSpecies?: string | null; useVisionApi?: boolean } = {},
  ): Promise<{ data: DetectionResponse; message: string | null }> {
    const form = new FormData();
    form.append('image', file, file.name);
    if (options.threshold !== undefined) form.append('threshold', String(options.threshold));
    if (options.save !== undefined) form.append('save', String(options.save));
    form.append('camera_source', options.cameraSource ?? 'file_upload');
    if (options.plantSpecies) form.append('plant_species', options.plantSpecies);
    if (options.useVisionApi !== undefined) {
      form.append('use_vision_api', String(options.useVisionApi));
    }

    return requestWithMessage<DetectionResponse>({
      url: '/api/analyze-plant',
      method: 'POST',
      data: form,
      // The optional vision API call adds a network round-trip on top of
      // local inference, so this needs more headroom than /api/predict.
      timeout: 150_000,
      onUploadProgress: (event) => {
        if (options.onProgress && event.total) {
          options.onProgress(Math.round((event.loaded / event.total) * 100));
        }
      },
    });
  },

  /**
   * Ask the backend to capture from the ESP32-CAM and classify the frame.
   *
   * This can take up to `CAPTURE_JOB_TIMEOUT` seconds on the server when the
   * push fallback is used, hence the long client timeout.
   */
  capture(
    options: { led?: boolean; device?: string; threshold?: number } = {},
  ): Promise<{ data: DetectionResponse; message: string | null }> {
    return requestWithMessage<DetectionResponse>({
      url: '/api/capture',
      method: 'POST',
      data: {
        led: options.led ?? true,
        ...(options.device ? { device: options.device } : {}),
        ...(options.threshold !== undefined ? { threshold: options.threshold } : {}),
      },
      timeout: CAPTURE_TIMEOUT,
    });
  },
};

/* ------------------------------------------------------------------ */
/* History                                                             */
/* ------------------------------------------------------------------ */

export const historyApi = {
  list(query: HistoryQuery = {}): Promise<PaginatedData<DetectionRecord>> {
    const params: Record<string, string | number> = {};
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '' && value !== 'all') {
        params[key] = value as string | number;
      }
    });
    return request<PaginatedData<DetectionRecord>>({
      url: '/api/history',
      method: 'GET',
      params,
    });
  },

  filters(): Promise<HistoryFilters> {
    return request<HistoryFilters>({ url: '/api/history/filters', method: 'GET' });
  },

  get(id: number): Promise<DetectionRecord> {
    return request<DetectionRecord>({ url: `/api/history/${id}`, method: 'GET' });
  },

  remove(id: number): Promise<{ id: number; image_file_removed: boolean }> {
    return request({ url: `/api/history/${id}`, method: 'DELETE' });
  },

  /**
   * Download a record's diagnosis report as a PDF.
   *
   * Fetched as a blob and handed to the browser through a temporary anchor
   * rather than navigating to the URL, so the Axios error handling (and the
   * JSON error envelope the backend returns on failure) still applies instead
   * of the browser silently opening a broken download.
   */
  async downloadReport(id: number): Promise<void> {
    try {
      const response = await client.get(`/api/history/${id}/report`, {
        responseType: 'blob',
        timeout: 60_000,
      });

      const disposition = String(response.headers['content-disposition'] ?? '');
      const match = disposition.match(/filename="?([^"]+)"?/);
      const filename = match?.[1] ?? `plantguard-diagnosis-${id}.pdf`;

      const url = URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      // Revoke on the next tick; revoking immediately cancels the download in
      // some browsers.
      window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
    } catch (error) {
      throw toClientError(error);
    }
  },

  clear(deleteFiles = true): Promise<{ rows_deleted: number; files_deleted: number }> {
    return request({
      url: '/api/history',
      method: 'DELETE',
      params: { confirm: 'true', delete_files: String(deleteFiles) },
    });
  },
};

/* ------------------------------------------------------------------ */
/* Statistics                                                          */
/* ------------------------------------------------------------------ */

export const statsApi = {
  overview(options: { recent?: number; days?: number } = {}): Promise<StatsResponse> {
    return request<StatsResponse>({
      url: '/api/stats',
      method: 'GET',
      params: { recent: options.recent ?? 5, days: options.days ?? 14 },
    });
  },

  analytics(days = 30): Promise<AnalyticsResponse> {
    return request<AnalyticsResponse>({ url: '/api/analytics', method: 'GET', params: { days } });
  },
};

/* ------------------------------------------------------------------ */
/* Device                                                              */
/* ------------------------------------------------------------------ */

export const deviceApi = {
  status(options: { ping?: boolean; device?: string } = {}): Promise<DeviceStatusResponse> {
    return request<DeviceStatusResponse>({
      url: '/api/device/status',
      method: 'GET',
      params: {
        ...(options.ping ? { ping: 'true' } : {}),
        ...(options.device ? { device: options.device } : {}),
      },
      timeout: options.ping ? 30_000 : DEFAULT_TIMEOUT,
    });
  },

  list(): Promise<{ count: number; devices: DeviceStatus[] }> {
    return request({ url: '/api/devices', method: 'GET' });
  },

  ping(device?: string): Promise<{ reachable: boolean; ip_address: string | null; latency_ms?: number; reason?: string }> {
    return request({
      url: '/api/device/ping',
      method: 'GET',
      params: device ? { device } : {},
      timeout: 30_000,
    });
  },

  setLed(state: 'on' | 'off', device?: string): Promise<{ led_state: string; ip_address: string | null }> {
    return request({
      url: '/api/device/led',
      method: 'POST',
      data: { state, ...(device ? { device } : {}) },
      timeout: 20_000,
    });
  },
};

/* ------------------------------------------------------------------ */
/* Cameras                                                             */
/* ------------------------------------------------------------------ */

export const plantApi = {
  /** Species with care profiles, plus what the classifier and vision API cover. */
  list(): Promise<PlantsResponse> {
    return request<PlantsResponse>({ url: '/api/plants', method: 'GET' });
  },
};

export const cameraApi = {
  /**
   * Describe the available camera sources.
   *
   * `ping` makes the backend probe the ESP32-CAM, which blocks for up to a few
   * seconds, so it is opt-in and used only when the user asks to test.
   */
  list(ping = false): Promise<CamerasResponse> {
    return request<CamerasResponse>({
      url: '/api/cameras',
      method: 'GET',
      params: ping ? { ping: 'true' } : {},
      timeout: ping ? 30_000 : DEFAULT_TIMEOUT,
    });
  },

  getConfig(): Promise<DeviceConfigResponse> {
    return request<DeviceConfigResponse>({ url: '/api/device/config', method: 'GET' });
  },

  /**
   * Save the ESP32-CAM address typed on the Camera Management page.
   *
   * Pass an empty string to clear it and fall back to the `.env` value or
   * heartbeat discovery. The backend probes the address immediately, so the
   * returned message says whether the camera actually answered.
   */
  setConfig(ipAddress: string): Promise<{
    ip_address: string | null;
    addresses: DeviceConfigResponse['addresses'];
    live_probe: { reachable: boolean; ip_address: string | null; latency_ms?: number; reason?: string };
  }> {
    return request({
      url: '/api/device/config',
      method: 'POST',
      data: { ip_address: ipAddress },
      timeout: 40_000,
    });
  },
};

/** Absolute URL for a stored image path returned by the API. */
export function imageUrl(path: string | null | undefined): string | undefined {
  if (!path) return undefined;
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

export default client;
