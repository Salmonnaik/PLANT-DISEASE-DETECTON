import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  Camera,
  CameraOff,
  Laptop,
  Play,
  RefreshCw,
  RotateCcw,
  ScanLine,
  ShieldAlert,
  Square,
} from 'lucide-react';
import { detectionApi, ApiClientError } from '@/services/api';
import type { DetectionResponse } from '@/services/types';
import { useWebcam, type CapturedFrame } from '@/hooks';
import { Card, CardBody, CardHeader, LiveDot, Notice, Spinner } from '@/components/ui';
import { classNames, formatBytes } from '@/utils/format';

interface WebcamCaptureProps {
  onAnalyzed: (result: DetectionResponse, message: string | null) => void;
  /**
   * False when the backend has no usable model. Ignored in universal mode,
   * which measures symptoms with computer vision and does not need one.
   */
  canPredict: boolean;
  threshold?: number;
  className?: string;
  /**
   * 'universal' analyses any plant species via /api/analyze-plant.
   * 'classifier' uses the 10-class model via /api/predict.
   */
  mode?: 'universal' | 'classifier';
  /** The plant the user selected, passed through in universal mode. */
  plantSpecies?: string | null;
}

/**
 * Laptop webcam capture card.
 *
 * Deliberately a two-step flow (capture, then analyse) rather than one button.
 * A live preview frame is easy to get wrong - the leaf drifts out of frame, a
 * hand is in the way - and reviewing the still before spending an inference
 * pass gives the operator a chance to retake it. The same reason the ESP32-CAM
 * result is shown before anything is acted on.
 */
export function WebcamCapture({
  onAnalyzed,
  canPredict,
  threshold,
  className,
  mode = 'universal',
  plantSpecies = null,
}: WebcamCaptureProps) {
  const webcam = useWebcam();
  const [frame, setFrame] = useState<CapturedFrame | null>(null);
  const [isAnalysing, setIsAnalysing] = useState(false);
  const [apiError, setApiError] = useState<ApiClientError | null>(null);

  // Releasing the camera when the component unmounts matters: otherwise the
  // webcam indicator light stays on after navigating to another page.
  useEffect(() => () => webcam.stop(), []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCapture = useCallback(async () => {
    setApiError(null);
    const captured = await webcam.capture();
    if (captured) setFrame(captured);
  }, [webcam]);

  const handleRetake = useCallback(() => {
    setFrame(null);
    setApiError(null);
  }, []);

  const handleAnalyse = useCallback(async () => {
    if (!frame) return;
    setIsAnalysing(true);
    setApiError(null);
    try {
      const response =
        mode === 'universal'
          ? await detectionApi.analyzePlant(frame.file, {
              threshold,
              cameraSource: 'laptop_webcam',
              plantSpecies,
            })
          : await detectionApi.predictWebcam(frame.file, { threshold });
      onAnalyzed(response.data, response.message);
    } catch (caught) {
      setApiError(caught as ApiClientError);
    } finally {
      setIsAnalysing(false);
    }
  }, [frame, threshold, onAnalyzed, mode, plantSpecies]);

  // Universal mode works without a trained model, so capture stays enabled.
  const canAnalyse = mode === 'universal' || canPredict;

  const isLive = webcam.status === 'live';
  const isStarting = webcam.status === 'starting';

  return (
    <Card className={className}>
      <CardHeader
        title="Laptop webcam"
        subtitle="Captured in your browser, then sent to the same model"
        icon={<Laptop className="h-4 w-4" />}
        actions={
          <LiveDot
            online={isLive}
            label={isLive ? 'Live' : isStarting ? 'Starting' : 'Stopped'}
          />
        }
      />

      <CardBody className="space-y-4">
        {/* ---- Unsupported / insecure context ---- */}
        {!webcam.isSupported && (
          <Notice
            tone="danger"
            icon={<ShieldAlert className="h-4 w-4" />}
            title="Webcam capture is not available here"
          >
            {webcam.isSecureContext ? (
              <p>This browser does not support the MediaDevices API required for webcam capture.</p>
            ) : (
              <p>
                Browsers only grant camera access in a secure context. Open the dashboard at{' '}
                <code className="rounded bg-blight-100 px-1.5 py-0.5 font-mono text-xs">
                  http://localhost:5173
                </code>{' '}
                instead of a LAN IP address, or serve it over HTTPS.
              </p>
            )}
          </Notice>
        )}

        {/* ---- Preview / captured still ---- */}
        <div className="relative overflow-hidden rounded-2xl border border-bark-200 bg-bark-900">
          {/* The video element must stay mounted even while hidden: the hook
              attaches the MediaStream to it before a frame exists. */}
          <video
            ref={webcam.videoRef}
            playsInline
            muted
            autoPlay
            className={classNames(
              'aspect-video w-full bg-bark-900 object-cover',
              frame || !isLive ? 'hidden' : 'block',
            )}
          />

          {frame && (
            <img
              src={frame.previewUrl}
              alt="Captured webcam frame"
              className="aspect-video w-full object-contain"
            />
          )}

          {!frame && !isLive && (
            <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 text-bark-400">
              <CameraOff className="h-10 w-10" />
              <p className="text-sm font-medium">
                {isStarting ? 'Starting the camera...' : 'Camera is off'}
              </p>
              {!isStarting && webcam.isSupported && (
                <p className="max-w-xs text-center text-xs text-bark-500">
                  Press Start camera. Your browser will ask for permission the first time.
                </p>
              )}
            </div>
          )}

          {isLive && !frame && (
            <>
              {/* Framing guide: the model was trained on a single centred leaf,
                  so showing the target area improves results more than any
                  amount of post-processing would. */}
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <div className="h-[72%] w-[72%] rounded-2xl border-2 border-dashed border-leaf-300/60" />
              </div>
              <div className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 rounded-lg bg-bark-950/70 px-2.5 py-1 backdrop-blur">
                <p className="text-2xs font-medium text-leaf-100">
                  Fill the dashed area with one leaf
                </p>
              </div>
              {webcam.resolution && (
                <div className="pointer-events-none absolute right-2 top-2 rounded-lg bg-bark-950/70 px-2 py-1 font-mono text-2xs text-leaf-100 backdrop-blur">
                  {webcam.resolution.width}&times;{webcam.resolution.height}
                </div>
              )}
            </>
          )}

          {isAnalysing && (
            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-bark-950/70 backdrop-blur-sm">
              <Spinner className="h-6 w-6 text-leaf-300" />
              <p className="text-sm font-semibold text-white">Running inference...</p>
            </div>
          )}
        </div>

        {/* ---- Camera selection ---- */}
        {webcam.isSupported && webcam.devices.length > 1 && !frame && (
          <div>
            <label htmlFor="webcam-device" className="label">
              Camera
            </label>
            <div className="flex gap-2">
              <select
                id="webcam-device"
                className="select"
                value={webcam.activeDeviceId ?? ''}
                onChange={(event) => void webcam.start(event.target.value)}
                disabled={isStarting || isAnalysing}
              >
                {webcam.devices.map((device) => (
                  <option key={device.deviceId} value={device.deviceId}>
                    {device.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void webcam.refreshDevices()}
                className="btn-secondary"
                title="Re-scan for cameras"
              >
                <RefreshCw className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ---- Controls ---- */}
        <div className="grid grid-cols-2 gap-2">
          {!isLive ? (
            <button
              type="button"
              onClick={() => void webcam.start()}
              disabled={!webcam.isSupported || isStarting || isAnalysing}
              className="btn-primary col-span-2"
            >
              {isStarting ? <Spinner /> : <Play className="h-4 w-4" />}
              {isStarting ? 'Starting camera...' : 'Start camera'}
            </button>
          ) : (
            <>
              {!frame ? (
                <button
                  type="button"
                  onClick={() => void handleCapture()}
                  className="btn-primary"
                  disabled={isAnalysing}
                >
                  <Camera className="h-4 w-4" />
                  Capture image
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleRetake}
                  className="btn-secondary"
                  disabled={isAnalysing}
                >
                  <RotateCcw className="h-4 w-4" />
                  Retake image
                </button>
              )}

              <button
                type="button"
                onClick={webcam.stop}
                className="btn-secondary"
                disabled={isAnalysing}
              >
                <Square className="h-4 w-4" />
                Stop camera
              </button>
            </>
          )}

          <button
            type="button"
            onClick={() => void handleAnalyse()}
            disabled={!frame || isAnalysing || !canAnalyse}
            className="btn-primary col-span-2"
          >
            {isAnalysing ? <Spinner /> : <ScanLine className="h-4 w-4" />}
            {isAnalysing ? 'Analysing...' : 'Analyse plant'}
          </button>
        </div>

        {frame && (
          <p className="text-xs text-bark-500">
            Captured {frame.width}&times;{frame.height} JPEG, {formatBytes(frame.sizeBytes)}. Review
            it, then press Analyse plant - or retake if the leaf is not clearly in frame.
          </p>
        )}

        {/* ---- Errors ---- */}
        {webcam.error && (
          <Notice tone="warning" icon={<AlertTriangle className="h-4 w-4" />} title="Camera problem">
            <p>{webcam.error}</p>
            {webcam.permission === 'denied' && (
              <p className="mt-1">
                Permission is currently blocked for this site. Reset it in the browser's site
                settings, reload the page, and press Start camera again.
              </p>
            )}
          </Notice>
        )}

        {apiError && (
          <Notice tone="danger" icon={<AlertTriangle className="h-4 w-4" />} title="Analysis failed">
            <p className="whitespace-pre-line">{apiError.message}</p>
          </Notice>
        )}

        {!canAnalyse && (
          <Notice tone="warning" title="No model available">
            The backend cannot classify images right now, so analysis is disabled. Train a model
            with <code className="font-mono text-xs">python ml/train.py</code>.
          </Notice>
        )}

        {mode === 'universal' && !canPredict && (
          <Notice tone="info" title="Universal analysis mode">
            No trained classifier is available, but any plant can still be analysed: symptoms
            are measured directly from the image and possible causes are listed from those
            measurements.
          </Notice>
        )}
      </CardBody>
    </Card>
  );
}

export default WebcamCapture;
