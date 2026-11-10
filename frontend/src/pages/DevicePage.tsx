import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  Clock,
  Cpu,
  Info,
  Lightbulb,
  LightbulbOff,
  MemoryStick,
  Network,
  RadioTower,
  RefreshCw,
  Signal,
  Terminal,
  Wifi,
  Zap,
} from 'lucide-react';
import { deviceApi, ApiClientError } from '@/services/api';
import type { DetectionResponse, TroubleshootingItem } from '@/services/types';
import { detectionApi } from '@/services/api';
import { useDeviceStatus } from '@/hooks';
import { PredictionResult } from '@/components/detection/PredictionResult';
import {
  Card,
  CardBody,
  CardHeader,
  ErrorState,
  LiveDot,
  Notice,
  Spinner,
} from '@/components/ui';
import {
  classNames,
  formatBytes,
  formatDateTime,
  formatDuration,
  formatRelative,
  formatSecondsAgo,
} from '@/utils/format';
import { signalMeta } from '@/utils/status';

/* ------------------------------------------------------------------ */
/* Troubleshooting list                                                */
/* ------------------------------------------------------------------ */

const SEVERITY_STYLES: Record<
  TroubleshootingItem['severity'],
  { wrap: string; icon: typeof Info; iconClass: string }
> = {
  ok: { wrap: 'border-leaf-200 bg-leaf-50', icon: CheckCircle2, iconClass: 'text-leaf-600' },
  info: { wrap: 'border-bark-200 bg-bark-50', icon: Info, iconClass: 'text-bark-500' },
  warning: { wrap: 'border-harvest-300 bg-harvest-50', icon: AlertTriangle, iconClass: 'text-harvest-600' },
  error: { wrap: 'border-blight-200 bg-blight-50', icon: AlertTriangle, iconClass: 'text-blight-600' },
};

function TroubleshootingList({ items }: { items: TroubleshootingItem[] }) {
  return (
    <ul className="space-y-2.5">
      {items.map((item) => {
        const style = SEVERITY_STYLES[item.severity];
        const Icon = style.icon;
        return (
          <li
            key={item.title}
            className={classNames('flex items-start gap-3 rounded-xl border px-3.5 py-3', style.wrap)}
          >
            <Icon className={classNames('mt-0.5 h-4 w-4 shrink-0', style.iconClass)} />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-bark-800">{item.title}</p>
              <p className="mt-0.5 text-sm leading-relaxed text-bark-600">{item.detail}</p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export default function DevicePage() {
  const { data, error, isLoading, isRefreshing, refresh } = useDeviceStatus();

  const [isPinging, setIsPinging] = useState(false);
  const [isCapturing, setIsCapturing] = useState(false);
  const [ledBusy, setLedBusy] = useState(false);
  const [actionError, setActionError] = useState<ApiClientError | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [captureResult, setCaptureResult] = useState<DetectionResponse | null>(null);

  const device = data?.device ?? null;
  const configured = data?.configured;
  const isOnline = Boolean(data?.is_online);
  const signal = signalMeta(device?.wifi_signal_quality);

  const runPing = useCallback(async () => {
    setIsPinging(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const result = await deviceApi.ping(device?.device_name);
      setActionMessage(
        result.reachable
          ? `Camera at ${result.ip_address} responded in ${result.latency_ms} ms.`
          : (result.reason ?? 'The camera did not respond.'),
      );
      await refresh();
    } catch (caught) {
      setActionError(caught as ApiClientError);
    } finally {
      setIsPinging(false);
    }
  }, [device?.device_name, refresh]);

  const toggleLed = useCallback(
    async (state: 'on' | 'off') => {
      setLedBusy(true);
      setActionError(null);
      setActionMessage(null);
      try {
        await deviceApi.setLed(state, device?.device_name);
        setActionMessage(`White LED switched ${state}.`);
        await refresh();
      } catch (caught) {
        setActionError(caught as ApiClientError);
      } finally {
        setLedBusy(false);
      }
    },
    [device?.device_name, refresh],
  );

  const runCapture = useCallback(async () => {
    setIsCapturing(true);
    setActionError(null);
    setActionMessage(null);
    setCaptureResult(null);
    try {
      const response = await detectionApi.capture({ led: true, device: device?.device_name });
      setCaptureResult(response.data);
      setActionMessage(response.message);
      await refresh();
    } catch (caught) {
      setActionError(caught as ApiClientError);
    } finally {
      setIsCapturing(false);
    }
  }, [device?.device_name, refresh]);

  if (error && !data) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refresh()} isRetrying={isRefreshing} />
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      {/* ---- Status header ---- */}
      <Card className={classNames('overflow-hidden border-2', isOnline ? 'border-leaf-200' : 'border-bark-200')}>
        <div className={classNames('px-5 py-4', isOnline ? 'bg-leaf-50' : 'bg-bark-50')}>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-4">
              <span
                className={classNames(
                  'flex h-14 w-14 items-center justify-center rounded-2xl',
                  isOnline ? 'bg-leaf-gradient text-white shadow-glow-leaf' : 'bg-bark-200 text-bark-500',
                )}
              >
                <Cpu className="h-7 w-7" />
              </span>
              <div>
                <div className="flex items-center gap-2.5">
                  <h2 className="text-xl font-bold text-bark-900">
                    {device?.device_name ?? configured?.device_name ?? 'ESP32-CAM'}
                  </h2>
                  <LiveDot online={isOnline} label={isOnline ? 'Online' : 'Offline'} />
                </div>
                <p className="mt-1 font-mono text-sm text-bark-600">
                  {device?.ip_address ?? configured?.resolved_ip ?? 'no IP address registered'}
                </p>
                <p className="mt-0.5 text-xs text-bark-500">
                  {device?.last_seen
                    ? `Last heartbeat ${formatSecondsAgo(device.seconds_since_last_seen)} (offline after ${device.offline_after_seconds}s of silence)`
                    : 'Never contacted this backend'}
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => void runPing()} className="btn-secondary btn-sm" disabled={isPinging}>
                {isPinging ? <Spinner /> : <RadioTower className="h-3.5 w-3.5" />}
                Test connection
              </button>
              <button type="button" onClick={() => void refresh()} className="btn-secondary btn-sm" disabled={isRefreshing}>
                {isRefreshing ? <Spinner /> : <RefreshCw className="h-3.5 w-3.5" />}
                Refresh
              </button>
            </div>
          </div>
        </div>

        <CardBody>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            {[
              {
                label: 'Wi-Fi SSID',
                icon: Wifi,
                value: device?.wifi_ssid ?? '--',
              },
              {
                label: 'Signal',
                icon: Signal,
                value:
                  device?.wifi_rssi !== null && device?.wifi_rssi !== undefined
                    ? `${device.wifi_rssi} dBm`
                    : '--',
                detail: signal.label,
                className: signal.textClass,
              },
              {
                label: 'Free heap',
                icon: MemoryStick,
                value: device?.free_heap ? formatBytes(device.free_heap) : '--',
              },
              {
                label: 'Uptime',
                icon: Clock,
                value: formatDuration(device?.uptime_seconds),
              },
              {
                label: 'Total captures',
                icon: Camera,
                value: device?.total_captures ?? 0,
              },
              {
                label: 'LED state',
                icon: device?.led_state === 'on' ? Lightbulb : LightbulbOff,
                value: (device?.led_state ?? 'off').toUpperCase(),
                className: device?.led_state === 'on' ? 'text-harvest-600' : 'text-bark-500',
              },
            ].map((item) => (
              <div key={item.label} className="rounded-xl bg-bark-50 px-3.5 py-3">
                <dt className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-bark-400">
                  <item.icon className="h-3 w-3" />
                  {item.label}
                </dt>
                <dd className={classNames('mt-1 text-base font-semibold text-bark-800', item.className)}>
                  {item.value}
                </dd>
                {item.detail && <p className="text-2xs text-bark-400">{item.detail}</p>}
              </div>
            ))}
          </dl>
        </CardBody>
      </Card>

      {/* ---- Action feedback ---- */}
      {actionMessage && !actionError && (
        <Notice tone="success" icon={<CheckCircle2 className="h-4 w-4" />}>
          {actionMessage}
        </Notice>
      )}
      {actionError && (
        <Card>
          <ErrorState error={actionError} compact onRetry={() => setActionError(null)} />
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-5">
        {/* ---- Controls ---- */}
        <div className="space-y-5 lg:col-span-2">
          <Card>
            <CardHeader
              title="Camera controls"
              subtitle="Commands sent to the board over HTTP"
              icon={<Zap className="h-4 w-4" />}
            />
            <CardBody className="space-y-3">
              <button
                type="button"
                onClick={() => void runCapture()}
                className="btn-primary w-full"
                disabled={isCapturing}
              >
                {isCapturing ? <Spinner /> : <Camera className="h-4 w-4" />}
                {isCapturing ? 'Capturing and analysing...' : 'Capture image now'}
              </button>

              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => void toggleLed('on')}
                  className="btn-secondary"
                  disabled={ledBusy}
                >
                  {ledBusy ? <Spinner /> : <Lightbulb className="h-4 w-4 text-harvest-500" />}
                  LED on
                </button>
                <button
                  type="button"
                  onClick={() => void toggleLed('off')}
                  className="btn-secondary"
                  disabled={ledBusy}
                >
                  {ledBusy ? <Spinner /> : <LightbulbOff className="h-4 w-4" />}
                  LED off
                </button>
              </div>

              <p className="text-xs leading-relaxed text-bark-500">
                LED control needs a direct connection to the board, because the GPIO is driven by the
                firmware's own web server. Capture also works through the queued-command fallback
                when the backend cannot reach the camera directly.
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Connection settings"
              subtitle="Effective backend configuration"
              icon={<Network className="h-4 w-4" />}
            />
            <CardBody>
              <dl className="space-y-2.5 text-sm">
                {[
                  { label: 'Device name', value: configured?.device_name },
                  { label: 'Static IP (.env)', value: configured?.static_ip ?? 'not set' },
                  { label: 'Resolved IP', value: configured?.resolved_ip ?? 'unknown' },
                  { label: 'Capture endpoint', value: configured?.capture_path },
                  { label: 'Status endpoint', value: configured?.status_path },
                  { label: 'LED endpoint', value: configured?.led_path },
                  {
                    label: 'Offline threshold',
                    value: configured ? `${configured.offline_after_seconds}s` : undefined,
                  },
                  {
                    label: 'Push fallback',
                    value: configured?.push_fallback_enabled ? 'enabled' : 'disabled',
                  },
                  {
                    label: 'Device key required',
                    value: configured?.device_key_required ? 'yes' : 'no',
                  },
                ].map((row) => (
                  <div key={row.label} className="flex items-center justify-between gap-3">
                    <dt className="text-bark-500">{row.label}</dt>
                    <dd className="truncate font-mono text-xs text-bark-700">{row.value ?? '--'}</dd>
                  </div>
                ))}
              </dl>
            </CardBody>
          </Card>

          {device?.last_error && (
            <Notice tone="danger" icon={<AlertTriangle className="h-4 w-4" />} title="Last reported error">
              {device.last_error}
            </Notice>
          )}
        </div>

        {/* ---- Diagnostics ---- */}
        <div className="space-y-5 lg:col-span-3">
          <Card>
            <CardHeader
              title="Troubleshooting"
              subtitle="Generated from the camera's current state"
              icon={<Terminal className="h-4 w-4" />}
            />
            <CardBody>
              {isLoading ? (
                <div className="space-y-2">
                  <div className="skeleton h-16 w-full" />
                  <div className="skeleton h-16 w-full" />
                </div>
              ) : (
                <TroubleshootingList items={data?.troubleshooting ?? []} />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Device details"
              subtitle="Reported by the firmware heartbeat"
              icon={<Info className="h-4 w-4" />}
            />
            <CardBody>
              <dl className="grid gap-x-5 gap-y-3 sm:grid-cols-2">
                {[
                  { label: 'MAC address', value: device?.mac_address },
                  { label: 'Firmware version', value: device?.firmware_version },
                  { label: 'Camera module', value: device?.camera_model },
                  { label: 'Connection status', value: device?.connection_status },
                  { label: 'Last seen', value: formatDateTime(device?.last_seen) },
                  { label: 'Last capture', value: formatDateTime(device?.last_capture_at) },
                  { label: 'First registered', value: formatDateTime(device?.created_at) },
                  {
                    label: 'Last capture age',
                    value: device?.last_capture_at ? formatRelative(device.last_capture_at) : 'never',
                  },
                ].map((row) => (
                  <div key={row.label}>
                    <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                      {row.label}
                    </dt>
                    <dd className="mt-0.5 truncate text-sm text-bark-700">{row.value ?? '--'}</dd>
                  </div>
                ))}
              </dl>
            </CardBody>
          </Card>

          {(data?.pending_capture_jobs.length ?? 0) > 0 && (
            <Card>
              <CardHeader
                title="Queued capture commands"
                subtitle="Waiting for the firmware to collect them"
                icon={<Clock className="h-4 w-4" />}
              />
              <CardBody className="space-y-2">
                {data?.pending_capture_jobs.map((job) => (
                  <div
                    key={job.job_id}
                    className="flex items-center justify-between gap-3 rounded-xl bg-bark-50 px-3.5 py-2.5 text-sm"
                  >
                    <span className="font-mono text-xs text-bark-600">{job.job_id}</span>
                    <span className="text-bark-500">{job.status}</span>
                    <span className="text-xs text-bark-400">{job.age_seconds.toFixed(0)}s old</span>
                  </div>
                ))}
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader
              title="Wiring reference"
              subtitle="ESP32-CAM (AI Thinker) with the white illumination LED"
              icon={<Lightbulb className="h-4 w-4" />}
            />
            <CardBody>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-bark-100 text-left">
                      {['Signal', 'ESP32-CAM pin', 'Connects to'].map((heading) => (
                        <th
                          key={heading}
                          className="px-3 py-2 text-2xs font-bold uppercase tracking-wider text-bark-500"
                        >
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-bark-50">
                    {[
                      ['White LED anode (+)', 'GPIO 4', '220 \u03a9 resistor, then LED'],
                      ['White LED cathode (-)', 'GND', 'Common ground'],
                      ['Power', '5V', 'Regulated 5V, 1A or more'],
                      ['Ground', 'GND', 'Supply ground'],
                      ['Programming RX', 'U0T (TX)', 'USB-TTL RX'],
                      ['Programming TX', 'U0R (RX)', 'USB-TTL TX'],
                      ['Flash mode', 'GPIO 0', 'GND while flashing only'],
                    ].map(([signal_, pin, target]) => (
                      <tr key={signal_}>
                        <td className="px-3 py-2 font-medium text-bark-700">{signal_}</td>
                        <td className="px-3 py-2 font-mono text-xs text-leaf-700">{pin}</td>
                        <td className="px-3 py-2 text-bark-600">{target}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs leading-relaxed text-bark-500">
                GPIO 4 also drives the on-board flash LED, so the module works without an external
                LED - the external one simply gives better, more even illumination. Remember to
                disconnect GPIO 0 from GND after flashing, or the board stays in bootloader mode.
                Full details in <code className="font-mono">docs/circuit_diagram.md</code>.
              </p>
            </CardBody>
          </Card>
        </div>
      </div>

      {/* ---- Capture result ---- */}
      {captureResult && (
        <div className="animate-fade-in-up space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-bark-900">Capture result</h2>
            <Link to="/history" className="btn-ghost btn-sm">
              View in history
            </Link>
          </div>
          <PredictionResult result={captureResult} />
        </div>
      )}
    </div>
  );
}
