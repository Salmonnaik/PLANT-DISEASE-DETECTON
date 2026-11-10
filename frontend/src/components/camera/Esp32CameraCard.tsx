import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  Lightbulb,
  LightbulbOff,
  Network,
  RadioTower,
  Save,
  Signal,
  Wifi,
  Zap,
} from 'lucide-react';
import { cameraApi, deviceApi, detectionApi, ApiClientError } from '@/services/api';
import type { CameraInfo, DetectionResponse } from '@/services/types';
import { Card, CardBody, CardHeader, LiveDot, Notice, Spinner } from '@/components/ui';
import { classNames, formatRelative } from '@/utils/format';
import { signalMeta } from '@/utils/status';

interface Esp32CameraCardProps {
  camera: CameraInfo | null;
  onAnalyzed: (result: DetectionResponse, message: string | null) => void;
  onChanged: () => void;
  canPredict: boolean;
  threshold?: number;
  className?: string;
}

/**
 * ESP32-CAM control card.
 *
 * Unlike the webcam, this camera is reached by the *backend* over Wi-Fi, so
 * everything here is a server round-trip: the address, the reachability probe,
 * the LED and the capture. The address field is the important part - on a DHCP
 * network the board's IP changes between sessions, and the first thing that
 * breaks is the dashboard still pointing at the old one.
 */
export function Esp32CameraCard({
  camera,
  onAnalyzed,
  onChanged,
  canPredict,
  threshold,
  className,
}: Esp32CameraCardProps) {
  const device = camera?.device ?? null;
  const addresses = camera?.addresses;

  const [ipInput, setIpInput] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [isCapturing, setIsCapturing] = useState(false);
  const [ledBusy, setLedBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<ApiClientError | string | null>(null);

  // Seed the field with whatever address is in force, but never overwrite what
  // the user is in the middle of typing.
  useEffect(() => {
    if (ipInput === '' && addresses?.effective) {
      setIpInput(addresses.effective);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addresses?.effective]);

  const isOnline = Boolean(camera?.available);
  const signal = signalMeta(device?.wifi_signal_quality);
  const busy = isSaving || isTesting || isCapturing || ledBusy;

  const handleSaveIp = useCallback(async () => {
    setIsSaving(true);
    setError(null);
    setMessage(null);
    try {
      const result = await cameraApi.setConfig(ipInput.trim());
      setMessage(
        result.live_probe?.reachable
          ? `Saved ${result.ip_address ?? 'default'}. Camera responded in ${result.live_probe.latency_ms} ms.`
          : `Saved ${result.ip_address ?? 'default'}, but the camera did not answer: ${result.live_probe?.reason ?? 'no response'}`,
      );
      onChanged();
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setIsSaving(false);
    }
  }, [ipInput, onChanged]);

  const handleTest = useCallback(async () => {
    setIsTesting(true);
    setError(null);
    setMessage(null);
    try {
      const result = await deviceApi.ping(device?.device_name);
      setMessage(
        result.reachable
          ? `Camera at ${result.ip_address} responded in ${result.latency_ms} ms.`
          : (result.reason ?? 'The camera did not respond.'),
      );
      onChanged();
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setIsTesting(false);
    }
  }, [device?.device_name, onChanged]);

  const handleLed = useCallback(
    async (state: 'on' | 'off') => {
      setLedBusy(true);
      setError(null);
      setMessage(null);
      try {
        await deviceApi.setLed(state, device?.device_name);
        setMessage(`White LED switched ${state}.`);
        onChanged();
      } catch (caught) {
        setError(caught as ApiClientError);
      } finally {
        setLedBusy(false);
      }
    },
    [device?.device_name, onChanged],
  );

  const handleCapture = useCallback(async () => {
    setIsCapturing(true);
    setError(null);
    setMessage(null);
    try {
      const response = await detectionApi.capture({
        led: true,
        device: device?.device_name,
        threshold,
      });
      onAnalyzed(response.data, response.message);
      setMessage(response.message);
      onChanged();
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setIsCapturing(false);
    }
  }, [device?.device_name, threshold, onAnalyzed, onChanged]);

  return (
    <Card className={className}>
      <CardHeader
        title="ESP32-CAM"
        subtitle="OV2640 module reached over Wi-Fi by the backend"
        icon={<Camera className="h-4 w-4" />}
        actions={<LiveDot online={isOnline} label={isOnline ? 'Online' : 'Offline'} />}
      />

      <CardBody className="space-y-4">
        {/* ---- Connection state ---- */}
        <div
          className={classNames(
            'rounded-xl border px-4 py-3',
            isOnline ? 'border-leaf-200 bg-leaf-50' : 'border-bark-200 bg-bark-50',
          )}
        >
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                Status
              </dt>
              <dd className={classNames('mt-0.5 font-semibold', isOnline ? 'text-leaf-700' : 'text-bark-600')}>
                {isOnline ? 'Online' : 'Offline'}
              </dd>
            </div>
            <div>
              <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                Address in use
              </dt>
              <dd className="mt-0.5 truncate font-mono text-xs text-bark-700">
                {addresses?.effective ?? 'none'}
              </dd>
            </div>
            <div>
              <dt className="flex items-center gap-1 text-2xs font-semibold uppercase tracking-wider text-bark-400">
                <Signal className="h-3 w-3" />
                Signal
              </dt>
              <dd className={classNames('mt-0.5 font-medium', signal.textClass)}>
                {device?.wifi_rssi != null ? `${device.wifi_rssi} dBm` : '--'}
              </dd>
            </div>
            <div>
              <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                Last capture
              </dt>
              <dd className="mt-0.5 text-bark-700">{formatRelative(device?.last_capture_at)}</dd>
            </div>
          </dl>

          {addresses && (
            <p className="mt-2.5 text-2xs text-bark-500">
              Address resolved from <strong>{addresses.effective_from}</strong>
              {addresses.effective_from === 'heartbeat' &&
                ' (the board reported it in its heartbeat)'}
              {addresses.effective_from === 'none' &&
                ' - no address is configured and no heartbeat has arrived'}
              .
            </p>
          )}
        </div>

        {/* ---- IP configuration ---- */}
        <div>
          <label htmlFor="esp32-ip" className="label">
            <Network className="mr-1 inline h-3 w-3" />
            Camera IP address
          </label>
          <div className="flex gap-2">
            <input
              id="esp32-ip"
              type="text"
              value={ipInput}
              onChange={(event) => setIpInput(event.target.value)}
              placeholder="192.168.1.50"
              className="input font-mono"
              disabled={busy}
              spellCheck={false}
              autoComplete="off"
            />
            <button
              type="button"
              onClick={() => void handleSaveIp()}
              className="btn-primary shrink-0"
              disabled={busy}
            >
              {isSaving ? <Spinner /> : <Save className="h-4 w-4" />}
              Save
            </button>
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-bark-500">
            Enter the address printed in the board's serial monitor at 115200 baud. Leave it empty
            and save to clear it - the backend then falls back to{' '}
            <code className="font-mono text-2xs">ESP32_CAM_IP</code> in <code className="font-mono text-2xs">.env</code>,
            or to the address the board reports in its heartbeat.
          </p>
        </div>

        {/* ---- Controls ---- */}
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => void handleTest()}
            className="btn-secondary"
            disabled={busy}
          >
            {isTesting ? <Spinner /> : <RadioTower className="h-4 w-4" />}
            Check connection
          </button>
          <button
            type="button"
            onClick={() => void handleLed(device?.led_state === 'on' ? 'off' : 'on')}
            className="btn-secondary"
            disabled={busy}
          >
            {ledBusy ? (
              <Spinner />
            ) : device?.led_state === 'on' ? (
              <LightbulbOff className="h-4 w-4" />
            ) : (
              <Lightbulb className="h-4 w-4 text-harvest-500" />
            )}
            {device?.led_state === 'on' ? 'LED off' : 'LED on'}
          </button>

          <button
            type="button"
            onClick={() => void handleCapture()}
            className="btn-primary col-span-2"
            disabled={busy || !canPredict}
          >
            {isCapturing ? <Spinner /> : <Zap className="h-4 w-4" />}
            {isCapturing ? 'Capturing and analysing...' : 'Capture image and analyse'}
          </button>
        </div>

        {isCapturing && (
          <p className="rounded-xl bg-leaf-50 px-3.5 py-2.5 text-xs leading-relaxed text-leaf-800">
            The backend first requests the frame directly from the camera. If that is blocked, it
            queues a command the board collects on its next poll, which can take up to 30 seconds.
          </p>
        )}

        {/* ---- Feedback ---- */}
        {message && !error && (
          <Notice tone="success" icon={<CheckCircle2 className="h-4 w-4" />}>
            {message}
          </Notice>
        )}

        {error && (
          <Notice tone="danger" icon={<AlertTriangle className="h-4 w-4" />} title="Camera error">
            <p className="whitespace-pre-line">
              {typeof error === 'string' ? error : error.message}
            </p>
          </Notice>
        )}

        {!isOnline && !error && (
          <Notice tone="warning" icon={<Wifi className="h-4 w-4" />} title="No heartbeat received">
            The board has not contacted this backend. Confirm it is powered, joined to the same
            2.4 GHz network, and that <code className="font-mono text-xs">FLASK_SERVER_IP</code> in
            the sketch matches this computer's LAN address.
          </Notice>
        )}
      </CardBody>
    </Card>
  );
}

export default Esp32CameraCard;
