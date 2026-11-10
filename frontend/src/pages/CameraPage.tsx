import { useCallback, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Camera,
  Cpu,
  GitMerge,
  Laptop,
  Layers,
  RefreshCw,
  ScanLine,
  Settings2,
} from 'lucide-react';
import type { CameraSource, DetectionResponse } from '@/services/types';
import { useCameras } from '@/hooks';
import { useSystemStatus } from '@/layouts/SystemStatusProvider';
import { WebcamCapture } from '@/components/camera/WebcamCapture';
import { Esp32CameraCard } from '@/components/camera/Esp32CameraCard';
import {
  CameraSourceSelector,
  type CameraOption,
} from '@/components/camera/CameraSourceSelector';
import { cameraSourceMeta } from '@/components/camera/CameraSourceBadge';
import { PredictionResult } from '@/components/detection/PredictionResult';
import { UniversalResult } from '@/components/analysis/UniversalResult';
import {
  Card,
  CardBody,
  CardHeader,
  ErrorState,
  Notice,
  Spinner,
} from '@/components/ui';
import { classNames, formatRelative } from '@/utils/format';

export default function CameraPage() {
  const { data, error, isLoading, isRefreshing, refresh } = useCameras();
  const { canPredict, health } = useSystemStatus();

  const [selected, setSelected] = useState<CameraSource>('laptop_webcam');
  const [result, setResult] = useState<DetectionResponse | null>(null);
  const [resultMessage, setResultMessage] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  const webcam = data?.cameras.find((camera) => camera.id === 'laptop_webcam') ?? null;
  const esp32 = data?.cameras.find((camera) => camera.id === 'esp32_cam') ?? null;

  const handleAnalyzed = useCallback((response: DetectionResponse, message: string | null) => {
    setResult(response);
    setResultMessage(message);
    window.setTimeout(
      () => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
      80,
    );
  }, []);

  const options = useMemo<CameraOption[]>(
    () => [
      {
        id: 'laptop_webcam',
        label: 'Laptop webcam',
        description: 'Capture with the camera on this computer, in the browser.',
        available: null,
        statusText: webcam?.enabled ? 'Managed by your browser' : 'Disabled in configuration',
        enabled: Boolean(webcam?.enabled ?? true),
      },
      {
        id: 'esp32_cam',
        label: 'ESP32-CAM',
        description: 'Capture with the OV2640 module over Wi-Fi.',
        available: Boolean(esp32?.available),
        statusText: esp32?.available
          ? `Online at ${esp32.effective_address}`
          : esp32?.effective_address
            ? `Offline (last known ${esp32.effective_address})`
            : 'No address configured',
        enabled: Boolean(esp32?.enabled ?? true),
      },
    ],
    [webcam, esp32],
  );

  if (error && !data) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refresh()} isRetrying={isRefreshing} />
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      {/* ---- Unified pipeline notice ---- */}
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-4 bg-leaf-gradient px-5 py-4 text-white">
          <div className="flex items-start gap-3">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/15">
              <GitMerge className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-lg font-semibold text-white">One model, two cameras</h2>
              <p className="mt-1 max-w-2xl text-sm leading-relaxed text-leaf-50/90">
                Both cameras post their JPEG to the same{' '}
                <code className="rounded bg-white/15 px-1.5 py-0.5 font-mono text-xs">
                  /api/predict
                </code>{' '}
                endpoint and receive identical treatment: the same validation, preprocessing,
                MobileNetV2 weights, class labels and confidence threshold. The camera is recorded
                with each detection, but it never changes the result.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            className="btn btn-sm shrink-0 border border-white/30 text-white hover:bg-white/10"
            disabled={isRefreshing}
          >
            {isRefreshing ? <Spinner /> : <RefreshCw className="h-3.5 w-3.5" />}
            Refresh
          </button>
        </div>

        {data && (
          <CardBody>
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
              {[
                { label: 'Shared endpoint', value: data.shared_pipeline.endpoint, mono: true },
                { label: 'Model', value: data.shared_pipeline.model ?? '--' },
                {
                  label: 'Input size',
                  value: data.shared_pipeline.image_size
                    ? `${data.shared_pipeline.image_size[0]}\u00d7${data.shared_pipeline.image_size[1]}`
                    : '--',
                },
                { label: 'Classes', value: data.shared_pipeline.num_classes },
                {
                  label: 'Threshold',
                  value: `${(data.shared_pipeline.confidence_threshold * 100).toFixed(0)}%`,
                },
                {
                  label: 'Quality gate',
                  value: data.shared_pipeline.quality_gate_enabled ? 'enabled' : 'disabled',
                },
              ].map((item) => (
                <div key={item.label} className="rounded-xl bg-bark-50 px-3.5 py-2.5">
                  <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                    {item.label}
                  </dt>
                  <dd
                    className={classNames(
                      'mt-0.5 text-sm font-semibold text-bark-800',
                      item.mono && 'font-mono text-xs',
                    )}
                  >
                    {item.value}
                  </dd>
                </div>
              ))}
            </dl>

            {health?.model.is_test_mode && (
              <Notice tone="warning" className="mt-4" title="Test mode applies to both cameras">
                The loaded model is untrained, so neither camera can produce a real diagnosis. The
                capture and upload paths are fully functional - only the model is not trained yet.
              </Notice>
            )}
          </CardBody>
        )}
      </Card>

      {/* ---- Source selection ---- */}
      <Card>
        <CardHeader
          title="Camera source"
          subtitle="Choose which camera to capture with"
          icon={<Settings2 className="h-4 w-4" />}
        />
        <CardBody>
          {isLoading ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="skeleton h-36" />
              <div className="skeleton h-36" />
            </div>
          ) : (
            <CameraSourceSelector options={options} value={selected} onChange={setSelected} />
          )}
        </CardBody>
      </Card>

      {/* ---- Active camera panel ---- */}
      <div className="grid gap-5 lg:grid-cols-2">
        {selected === 'laptop_webcam' ? (
          <WebcamCapture onAnalyzed={handleAnalyzed} canPredict={canPredict} />
        ) : (
          <Esp32CameraCard
            camera={esp32}
            onAnalyzed={handleAnalyzed}
            onChanged={() => void refresh()}
            canPredict={canPredict}
          />
        )}

        {/* ---- The other camera, as a summary ---- */}
        <div className="space-y-5">
          <Card>
            <CardHeader
              title="Camera comparison"
              subtitle="What each source is good for"
              icon={<Layers className="h-4 w-4" />}
            />
            <CardBody>
              <div className="space-y-3">
                {[
                  {
                    id: 'laptop_webcam' as CameraSource,
                    icon: Laptop,
                    strengths: [
                      'No hardware to wire or flash',
                      'Immediate - useful for testing the model',
                      'Higher resolution than the OV2640',
                    ],
                    limits: [
                      'Needs a person holding the laptop at the plant',
                      'Ambient lighting varies between captures',
                      'Requires a secure context (localhost or HTTPS)',
                    ],
                  },
                  {
                    id: 'esp32_cam' as CameraSource,
                    icon: Camera,
                    strengths: [
                      'Fixed position, repeatable framing',
                      'White LED gives consistent illumination',
                      'Can be triggered remotely from this dashboard',
                    ],
                    limits: [
                      '2 MP sensor with more noise than a webcam',
                      'Depends on Wi-Fi reach and a stable 5V supply',
                      'Needs flashing and wiring first',
                    ],
                  },
                ].map((entry) => {
                  const meta = cameraSourceMeta(entry.id);
                  const Icon = entry.icon;
                  const camera = data?.cameras.find((item) => item.id === entry.id);
                  return (
                    <div
                      key={entry.id}
                      className={classNames(
                        'rounded-xl border p-4 transition-colors',
                        selected === entry.id ? 'border-leaf-300 bg-leaf-50/50' : 'border-bark-100',
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="inline-flex items-center gap-2 text-sm font-semibold text-bark-800">
                          <Icon className="h-4 w-4" style={{ color: meta.colour }} />
                          {meta.label}
                        </span>
                        <span className="text-2xs font-medium text-bark-400">
                          {camera?.detections_recorded ?? 0} detections recorded
                        </span>
                      </div>

                      <div className="mt-2.5 grid gap-3 sm:grid-cols-2">
                        <div>
                          <p className="text-2xs font-bold uppercase tracking-wider text-leaf-700">
                            Strengths
                          </p>
                          <ul className="mt-1 space-y-1">
                            {entry.strengths.map((item) => (
                              <li key={item} className="flex gap-1.5 text-xs text-bark-600">
                                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-leaf-500" />
                                {item}
                              </li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <p className="text-2xs font-bold uppercase tracking-wider text-harvest-700">
                            Trade-offs
                          </p>
                          <ul className="mt-1 space-y-1">
                            {entry.limits.map((item) => (
                              <li key={item} className="flex gap-1.5 text-xs text-bark-600">
                                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-harvest-500" />
                                {item}
                              </li>
                            ))}
                          </ul>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </CardBody>
          </Card>

          {/* ---- Requirements for the selected camera ---- */}
          {(selected === 'laptop_webcam' ? webcam : esp32) && (
            <Card>
              <CardHeader
                title={`${cameraSourceMeta(selected).label} requirements`}
                subtitle="What has to be true for this camera to work"
                icon={<Cpu className="h-4 w-4" />}
              />
              <CardBody>
                <ul className="space-y-2">
                  {(selected === 'laptop_webcam' ? webcam : esp32)?.requirements.map((item) => (
                    <li key={item} className="flex gap-2 text-sm text-bark-600">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-leaf-400" />
                      {item}
                    </li>
                  ))}
                </ul>

                {(selected === 'laptop_webcam' ? webcam : esp32)?.notes && (
                  <p className="mt-3 rounded-xl bg-bark-50 px-3.5 py-2.5 text-xs leading-relaxed text-bark-600">
                    {(selected === 'laptop_webcam' ? webcam : esp32)?.notes}
                  </p>
                )}

                {selected === 'esp32_cam' && (
                  <Link to="/device" className="btn-secondary btn-sm mt-3">
                    <Cpu className="h-3.5 w-3.5" />
                    Full device diagnostics
                  </Link>
                )}
              </CardBody>
            </Card>
          )}

          {/* ---- Usage summary ---- */}
          {data && (
            <Card>
              <CardHeader title="Captures by camera" subtitle="From the detection history" />
              <CardBody className="space-y-2.5">
                {[...data.cameras, { ...data.file_upload, id: data.file_upload.id }].map((camera) => {
                  const meta = cameraSourceMeta(camera.id);
                  const Icon = meta.icon;
                  const total =
                    data.cameras.reduce((sum, item) => sum + item.detections_recorded, 0) +
                    data.file_upload.detections_recorded;
                  const share = total > 0 ? (camera.detections_recorded / total) * 100 : 0;

                  return (
                    <div key={camera.id}>
                      <div className="flex items-center justify-between gap-2 text-sm">
                        <span className="inline-flex items-center gap-2 text-bark-700">
                          <Icon className="h-3.5 w-3.5" style={{ color: meta.colour }} />
                          {meta.label}
                        </span>
                        <span className="font-semibold tabular-nums text-bark-800">
                          {camera.detections_recorded}
                        </span>
                      </div>
                      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-bark-100">
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{ width: `${share}%`, backgroundColor: meta.colour }}
                        />
                      </div>
                    </div>
                  );
                })}

                {esp32?.device?.last_capture_at && (
                  <p className="pt-1 text-xs text-bark-400">
                    ESP32-CAM last captured {formatRelative(esp32.device.last_capture_at)}.
                  </p>
                )}
              </CardBody>
            </Card>
          )}
        </div>
      </div>

      {/* ---- Result ---- */}
      <div ref={resultRef}>
        {result && (
          <div className="animate-fade-in-up space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="inline-flex items-center gap-2 text-lg font-semibold text-bark-900">
                <ScanLine className="h-5 w-5 text-leaf-600" />
                Analysis result
              </h2>
              {resultMessage && (
                <p className="truncate text-sm text-bark-500">{resultMessage}</p>
              )}
            </div>
            {result.analysis ? (
              <UniversalResult result={result} analysis={result.analysis} />
            ) : (
              <PredictionResult result={result} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
