import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Camera,
  Info,
  Leaf,
  Lightbulb,
  RotateCcw,
  ScanLine,
  Settings2,
  Sliders,
  Upload,
  Zap,
} from 'lucide-react';
import { detectionApi, ApiClientError } from '@/services/api';
import type { CameraSource, DetectionResponse } from '@/services/types';
import { useSystemStatus } from '@/layouts/SystemStatusProvider';
import { useCameras } from '@/hooks';
import { ImageDropzone } from '@/components/detection/ImageDropzone';
import { PredictionResult } from '@/components/detection/PredictionResult';
import { WebcamCapture } from '@/components/camera/WebcamCapture';
import {
  CameraSourceSelector,
  type CameraOption,
} from '@/components/camera/CameraSourceSelector';
import { PlantSpeciesSelector } from '@/components/analysis/PlantSpeciesSelector';
import { DiagnosisDashboard } from '@/components/analysis/DiagnosisDashboard';
import {
  CapturedImagePanel,
  DiagnosisSummaryBar,
} from '@/components/analysis/DiagnosisLayout';
import {
  AnalysingOverlay,
  Card,
  CardBody,
  CardHeader,
  ErrorState,
  LiveDot,
  Notice,
  Spinner,
} from '@/components/ui';
import { classNames } from '@/utils/format';

type Phase = 'idle' | 'capturing' | 'analysing';

export default function DetectionPage() {
  const { health, isDeviceOnline, canPredict, refresh: refreshHealth } = useSystemStatus();
  const { data: cameras } = useCameras();

  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [result, setResult] = useState<DetectionResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [useLed, setUseLed] = useState(true);
  const [threshold, setThreshold] = useState<number | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [cameraSource, setCameraSource] = useState<CameraSource>('file_upload');
  const [plantSpecies, setPlantSpecies] = useState<string | null>(null);

  const resultRef = useRef<HTMLDivElement>(null);
  const objectUrlRef = useRef<string | null>(null);

  const effectiveThreshold = threshold ?? health?.model.confidence_threshold ?? 0.7;
  const isBusy = phase !== 'idle';

  const esp32Camera = cameras?.cameras.find((camera) => camera.id === 'esp32_cam');

  const cameraOptions: CameraOption[] = [
    {
      id: 'file_upload',
      label: 'Upload an image',
      description: 'Analyse a photograph already saved on this computer.',
      available: true,
      statusText: 'Always available',
      enabled: true,
    },
    {
      id: 'laptop_webcam',
      label: 'Laptop webcam',
      description: 'Capture live with the camera on this computer.',
      available: null,
      statusText: 'Managed by your browser',
      enabled: true,
    },
    {
      id: 'esp32_cam',
      label: 'ESP32-CAM',
      description: 'Capture with the OV2640 module over Wi-Fi.',
      available: isDeviceOnline,
      statusText: isDeviceOnline
        ? `Online at ${esp32Camera?.effective_address ?? 'the configured address'}`
        : 'Offline - a capture will still be attempted',
      enabled: true,
    },
  ];

  // Object URLs must be revoked explicitly or the blobs leak for the session.
  useEffect(
    () => () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    },
    [],
  );

  const scrollToResult = useCallback(() => {
    window.setTimeout(() => {
      resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 80);
  }, []);

  /**
   * Threshold slider, shared by every camera panel.
   *
   * Rendered through a function rather than duplicated per panel so the three
   * sources cannot drift apart: whichever camera is selected, the operator is
   * adjusting the one value that is sent with the request.
   */
  const renderThresholdControl = () => (
    <>
      <button
        type="button"
        onClick={() => setShowAdvanced((value) => !value)}
        className="btn-ghost btn-sm w-full justify-between"
      >
        <span className="inline-flex items-center gap-2">
          <Sliders className="h-4 w-4" />
          Advanced settings
        </span>
        <span className="text-xs text-bark-400">
          threshold {(effectiveThreshold * 100).toFixed(0)}%
        </span>
      </button>

      {showAdvanced && (
        <div className="mt-2 space-y-2 rounded-xl border border-bark-100 bg-bark-50 p-3.5">
          <label htmlFor="threshold" className="label mb-0">
            Confidence threshold
          </label>
          <input
            id="threshold"
            type="range"
            min={0.3}
            max={0.95}
            step={0.05}
            value={effectiveThreshold}
            onChange={(event) => setThreshold(Number(event.target.value))}
            disabled={isBusy}
            className="w-full accent-leaf-600"
          />
          <div className="flex items-center justify-between text-xs text-bark-500">
            <span>30%</span>
            <span className="font-semibold text-bark-700">
              {(effectiveThreshold * 100).toFixed(0)}%
            </span>
            <span>95%</span>
          </div>
          <p className="text-xs leading-relaxed text-bark-500">
            Below this confidence the result is reported as <strong>uncertain</strong> and no disease
            is named. Raising it reduces false diagnoses but returns more uncertain results. Applies
            to every camera source.
          </p>
          {threshold !== null && (
            <button
              type="button"
              onClick={() => setThreshold(null)}
              className="btn-ghost btn-sm w-full"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Reset to server default
            </button>
          )}
        </div>
      )}
    </>
  );

  const handleSelectFile = useCallback((selected: File) => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    const url = URL.createObjectURL(selected);
    objectUrlRef.current = url;

    setFile(selected);
    setPreviewUrl(url);
    setResult(null);
    setError(null);
    setMessage(null);
  }, []);

  const handleClear = useCallback(() => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = null;
    setFile(null);
    setPreviewUrl(null);
    setResult(null);
    setError(null);
    setMessage(null);
  }, []);

  /**
   * Return to the capture state.
   *
   * Backs the Retake, Upload Another and Analyse Another Leaf buttons. All
   * three clear the result and scroll back to the controls; they differ only
   * in wording, which matches where the user's attention is.
   */
  const startOver = useCallback(() => {
    handleClear();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [handleClear]);

  const analyseUpload = useCallback(async () => {
    if (!file) return;
    setPhase('analysing');
    setError(null);
    setMessage(null);

    try {
      // A file chosen from disk is always recorded as file_upload, even if the
      // webcam panel happens to be selected - the image did not come from the
      // camera, and the history must not claim it did.
      const response = await detectionApi.analyzePlant(file, {
        threshold: effectiveThreshold,
        cameraSource: 'file_upload',
        plantSpecies,
      });
      setResult(response.data);
      setMessage(response.message);
      scrollToResult();
    } catch (caught) {
      setError(caught as ApiClientError);
      void refreshHealth();
    } finally {
      setPhase('idle');
    }
  }, [file, effectiveThreshold, plantSpecies, scrollToResult, refreshHealth]);

  const captureFromCamera = useCallback(async () => {
    setPhase('capturing');
    setError(null);
    setMessage(null);
    setResult(null);
    handleClear();

    try {
      const response = await detectionApi.capture({ led: useLed, threshold: effectiveThreshold });
      setResult(response.data);
      setMessage(response.message);
      scrollToResult();
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setPhase('idle');
      void refreshHealth();
    }
  }, [useLed, effectiveThreshold, handleClear, scrollToResult, refreshHealth]);

  return (
    <div className="space-y-5">
      {/* Universal analysis does not need the trained classifier, so a missing
          model is informational here rather than blocking. */}
      {!canPredict && health && (
        <Notice tone="warning" icon={<Info className="h-4 w-4" />} title="No trained classifier">
          <p className="whitespace-pre-line">{health.model.message}</p>
          <p className="mt-1">
            Universal analysis still works: symptoms are measured directly from the image and
            possible causes are listed from those measurements, for any plant species.
          </p>
        </Notice>
      )}

      {/* The capture controls give way to the diagnosis once there is a
          result, so the finding gets the full width instead of competing with
          inputs the user has finished with. The Retake / Upload Another /
          Analyse Another Leaf buttons bring them back. */}
      {!result && (
      <>
      {/* ---- Plant species ---- */}
      <Card>
        <CardHeader
          title="Plant species"
          subtitle="Any plant can be analysed - naming it makes the advice specific"
          icon={<Leaf className="h-4 w-4" />}
        />
        <CardBody>
          <PlantSpeciesSelector
            value={plantSpecies}
            onChange={setPlantSpecies}
            disabled={isBusy}
          />
        </CardBody>
      </Card>

      {/* ---- Camera source selection ---- */}
      <Card>
        <CardHeader
          title="Choose a camera source"
          subtitle="All three feed the same model, preprocessing and confidence threshold"
          icon={<Settings2 className="h-4 w-4" />}
          actions={
            <Link to="/cameras" className="btn-ghost btn-sm">
              Manage cameras
            </Link>
          }
        />
        <CardBody>
          <CameraSourceSelector
            options={cameraOptions}
            value={cameraSource}
            onChange={(next) => {
              setCameraSource(next);
              setError(null);
            }}
          />
        </CardBody>
      </Card>

      {cameraSource === 'laptop_webcam' && (
        <div className="grid gap-5 lg:grid-cols-5">
          <WebcamCapture
            className="lg:col-span-3"
            onAnalyzed={(response, responseMessage) => {
              setResult(response);
              setMessage(responseMessage);
              handleClear();
              scrollToResult();
            }}
            canPredict={canPredict}
            threshold={effectiveThreshold}
            mode="universal"
            plantSpecies={plantSpecies}
          />

          <Card className="lg:col-span-2">
            <CardHeader
              title="Webcam capture tips"
              subtitle="Same rules the model was trained under"
              icon={<Info className="h-4 w-4" />}
            />
            <CardBody className="space-y-3">
              {[
                'Hold a single leaf flat against a plain background, filling the dashed guide.',
                'Face a window or lamp - do not let the laptop screen be the only light source.',
                'Keep the leaf about 15-25 cm from the lens so autofocus can lock on.',
                'Review the still before analysing; retake it if the leaf is cut off or blurred.',
              ].map((tip) => (
                <p key={tip} className="flex gap-2 text-sm leading-relaxed text-bark-600">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-leaf-500" />
                  {tip}
                </p>
              ))}
              <div className="divider" />
              {renderThresholdControl()}
            </CardBody>
          </Card>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-5">
        {/* ---- Capture from hardware ---- */}
        <Card className={classNames('lg:col-span-2', cameraSource !== 'esp32_cam' && 'hidden')}>
          <CardHeader
            title="Capture with ESP32-CAM"
            subtitle="Takes a fresh photograph through the camera module"
            icon={<Camera className="h-4 w-4" />}
            actions={<LiveDot online={isDeviceOnline} label={isDeviceOnline ? 'Ready' : 'Offline'} />}
          />
          <CardBody className="space-y-4">
            <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-bark-100 bg-bark-50 px-3.5 py-3">
              <input
                type="checkbox"
                checked={useLed}
                onChange={(event) => setUseLed(event.target.checked)}
                disabled={isBusy}
                className="mt-0.5 h-4 w-4 rounded border-bark-300 text-leaf-600 focus:ring-leaf-500"
              />
              <span className="min-w-0">
                <span className="flex items-center gap-1.5 text-sm font-semibold text-bark-800">
                  <Lightbulb className="h-4 w-4 text-harvest-500" />
                  Switch on the white LED
                </span>
                <span className="mt-0.5 block text-xs leading-relaxed text-bark-500">
                  The firmware lights the LED, lets exposure settle, grabs the frame and switches it
                  off again. Consistent lighting is what makes repeat scans comparable.
                </span>
              </span>
            </label>

            <button
              type="button"
              onClick={() => void captureFromCamera()}
              disabled={isBusy || !canPredict}
              className="btn-primary w-full btn-lg"
            >
              {phase === 'capturing' ? <Spinner /> : <Zap className="h-5 w-5" />}
              {phase === 'capturing' ? 'Capturing...' : 'Capture image using ESP32-CAM'}
            </button>

            {!isDeviceOnline && (
              <p className="text-xs leading-relaxed text-bark-500">
                The camera has not sent a heartbeat. A capture will still be attempted - the backend
                tries a direct request first, then queues a command the board picks up on its next
                poll. See{' '}
                <Link to="/device" className="link">
                  Device Management
                </Link>{' '}
                for diagnostics.
              </p>
            )}

            {phase === 'capturing' && (
              <div className="rounded-xl bg-leaf-50 px-3.5 py-3 text-xs leading-relaxed text-leaf-800">
                Requesting a frame. If the camera is not directly reachable the backend waits for the
                board to collect the queued command, which can take up to 30 seconds.
              </div>
            )}

            <div className="divider" />

            {renderThresholdControl()}
          </CardBody>
        </Card>

        {/* ---- Upload ---- */}
        <Card
          className={classNames(
            'relative lg:col-span-3',
            cameraSource === 'laptop_webcam' && 'hidden',
          )}
        >
          {phase === 'analysing' && <AnalysingOverlay />}
          <CardHeader
            title="Upload an image"
            subtitle="Analyse a photograph already on this device"
            icon={<Upload className="h-4 w-4" />}
            actions={
              file && (
                <button type="button" onClick={handleClear} className="btn-ghost btn-sm" disabled={isBusy}>
                  Clear
                </button>
              )
            }
          />
          <CardBody className="space-y-4">
            <ImageDropzone
              onSelect={handleSelectFile}
              onClear={handleClear}
              selectedFile={file}
              previewUrl={previewUrl}
              disabled={isBusy}
            />

            <button
              type="button"
              onClick={() => void analyseUpload()}
              disabled={!file || isBusy}
              className={classNames('btn-primary w-full btn-lg', !file && 'opacity-60')}
            >
              {phase === 'analysing' ? <Spinner /> : <ScanLine className="h-5 w-5" />}
              {phase === 'analysing' ? 'Analysing...' : 'Analyse plant'}
            </button>
          </CardBody>
        </Card>

        {/* ---- Settings panel for the file-upload source ---- */}
        <Card className={classNames('lg:col-span-2', cameraSource !== 'file_upload' && 'hidden')}>
          <CardHeader
            title="Detection settings"
            subtitle="Applied to whichever camera you use"
            icon={<Sliders className="h-4 w-4" />}
          />
          <CardBody className="space-y-3">
            {renderThresholdControl()}
            <div className="divider" />
            <p className="text-xs leading-relaxed text-bark-500">
              Uploading a file records the detection as <strong>File upload</strong> rather than as
              a camera capture, so the history stays an accurate record of where each image came
              from.
            </p>
          </CardBody>
        </Card>
      </div>
      </>
      )}

      {/* ---- Errors ---- */}
      {error && (
        <Card>
          <ErrorState
            error={error}
            onRetry={
              error.isDeviceUnreachable
                ? () => void captureFromCamera()
                : file
                  ? () => void analyseUpload()
                  : undefined
            }
            isRetrying={isBusy}
          />
        </Card>
      )}

      {/* ---- Result ---- */}
      <div ref={resultRef}>
        {result && (
          <div className="animate-fade-in-up space-y-4">
            {message && (
              <p className="text-sm text-bark-500">{message}</p>
            )}

            {result.analysis ? (
              <>
                {/* Image on the left, the full diagnosis on the right. */}
                <div className="grid gap-4 lg:grid-cols-[minmax(0,19rem)_1fr]">
                  <CapturedImagePanel
                    result={result}
                    localPreviewUrl={previewUrl}
                    onRetake={startOver}
                    onUploadAnother={startOver}
                    onAnalyseAnother={startOver}
                  />
                  <DiagnosisDashboard result={result} analysis={result.analysis} />
                </div>

                <DiagnosisSummaryBar result={result} analysis={result.analysis} />
              </>
            ) : (
              // Classifier-only results (e.g. a direct ESP32-CAM push) keep the
              // original card, which matches their narrower payload.
              <PredictionResult result={result} localPreviewUrl={previewUrl} />
            )}
          </div>
        )}
      </div>

      {/* ---- Guidance ---- */}
      {!result && !error && (
        <Card>
          <CardHeader
            title="How to get a reliable reading"
            subtitle="The same rules apply to camera captures and uploads"
            icon={<Info className="h-4 w-4" />}
          />
          <CardBody>
            <div className="grid gap-5 sm:grid-cols-3">
              {[
                {
                  title: 'Fill the frame with one leaf',
                  body: 'The model was trained on single-leaf images on a plain background. Several leaves, or a whole plant, makes the prediction unreliable.',
                },
                {
                  title: 'Light it evenly',
                  body: 'Use the white LED at roughly 10-15 cm. Harsh direct sun creates blown highlights, and shade hides the lesion colour the model keys on.',
                },
                {
                  title: 'Hold steady and focus',
                  body: 'Blurred frames are rejected by the quality gate before inference, and reported as "unusable image" rather than guessed at.',
                },
              ].map((tip) => (
                <div key={tip.title}>
                  <h3 className="text-sm font-semibold text-bark-800">{tip.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-bark-600">{tip.body}</p>
                </div>
              ))}
            </div>

            {health?.model.loaded && (
              <div className="mt-5 rounded-xl bg-bark-50 px-4 py-3">
                <p className="label mb-1.5">This model can only predict these classes</p>
                <div className="flex flex-wrap gap-1.5">
                  {health.model.class_names.map((name) => (
                    <span key={name} className="chip font-mono text-2xs">
                      {name}
                    </span>
                  ))}
                </div>
                <p className="mt-2.5 text-xs leading-relaxed text-bark-500">
                  A leaf of any other crop, or a disease outside this list, cannot be identified
                  correctly - the model will return the closest class it knows, usually with low
                  confidence.
                </p>
              </div>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}
