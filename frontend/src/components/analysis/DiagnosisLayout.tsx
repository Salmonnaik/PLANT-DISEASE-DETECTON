import { useState } from 'react';
import {
  Activity,
  Camera,
  Download,
  FileText,
  Gauge,
  Image as ImageIcon,
  Leaf,
  RotateCcw,
  ScanLine,
  Stethoscope,
  Upload,
} from 'lucide-react';
import type { DetectionResponse, UniversalAnalysis } from '@/services/types';
import { historyApi, imageUrl, ApiClientError } from '@/services/api';
import { Card, CardBody, CardHeader, Notice, Spinner } from '@/components/ui';
import { CameraSourceBadge } from '@/components/camera/CameraSourceBadge';
import { classNames, formatBytes } from '@/utils/format';

const SEVERITY_PILL: Record<string, string> = {
  none: 'badge-healthy',
  mild: 'badge-healthy',
  moderate: 'badge-uncertain',
  severe: 'badge-diseased',
  unknown: 'badge-neutral',
};

/* ------------------------------------------------------------------ */
/* Left panel: the image and its actions                               */
/* ------------------------------------------------------------------ */

interface ImagePanelProps {
  result: DetectionResponse;
  localPreviewUrl?: string | null;
  onRetake: () => void;
  onUploadAnother: () => void;
  onAnalyseAnother: () => void;
}

export function CapturedImagePanel({
  result,
  localPreviewUrl,
  onRetake,
  onUploadAnother,
  onAnalyseAnother,
}: ImagePanelProps) {
  const source = imageUrl(result.image.url) ?? localPreviewUrl ?? undefined;

  return (
    <Card className="h-fit">
      <CardHeader
        title="Captured / Uploaded Image"
        icon={<ImageIcon className="h-4 w-4" />}
        actions={<CameraSourceBadge source={result.camera_source} short />}
      />
      <CardBody className="space-y-3">
        <div className="overflow-hidden rounded-xl border border-bark-200 bg-bark-900">
          {source ? (
            <img
              src={source}
              alt="Analysed leaf"
              className="aspect-square w-full object-cover"
            />
          ) : (
            <div className="flex aspect-square w-full items-center justify-center text-bark-500">
              <ImageIcon className="h-10 w-10" />
            </div>
          )}
        </div>

        <p className="text-2xs text-bark-400">
          {result.image.width}&times;{result.image.height} &middot;{' '}
          {formatBytes(result.image.size_bytes)} &middot; {result.image.format.toUpperCase()}
          {result.detection_id ? ` · record #${result.detection_id}` : ' · not saved'}
        </p>

        <div className="grid grid-cols-2 gap-2">
          <button type="button" onClick={onRetake} className="btn-secondary btn-sm">
            <RotateCcw className="h-3.5 w-3.5" />
            Retake
          </button>
          <button type="button" onClick={onUploadAnother} className="btn-secondary btn-sm">
            <Upload className="h-3.5 w-3.5" />
            Upload Another
          </button>
        </div>

        <button type="button" onClick={onAnalyseAnother} className="btn-primary w-full">
          <ScanLine className="h-4 w-4" />
          Analyse Another Leaf
        </button>
      </CardBody>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Bottom bar: the headline figures and the report download            */
/* ------------------------------------------------------------------ */

interface SummaryBarProps {
  result: DetectionResponse;
  analysis: UniversalAnalysis;
}

export function DiagnosisSummaryBar({ result, analysis }: SummaryBarProps) {
  const [isDownloading, setIsDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const classifierPercent =
    result.prediction?.is_validated_prediction && analysis.evidence_sources.classifier.used
      ? `${(result.prediction.confidence * 100).toFixed(0)}%`
      : null;

  const handleDownload = async () => {
    if (!result.detection_id) {
      setError(
        'This analysis was not saved, so there is no stored record to build a report from.',
      );
      return;
    }
    setIsDownloading(true);
    setError(null);
    try {
      await historyApi.downloadReport(result.detection_id);
    } catch (caught) {
      const apiError = caught as ApiClientError;
      setError(apiError.message);
    } finally {
      setIsDownloading(false);
    }
  };

  const cells = [
    {
      icon: Leaf,
      label: 'Plant',
      value: analysis.plant.name,
      tone: 'bg-leaf-100 text-leaf-700',
    },
    {
      icon: Stethoscope,
      label: 'Condition',
      value: analysis.condition.label,
      tone: 'bg-blight-100 text-blight-700',
    },
    {
      icon: Activity,
      label: 'Confidence',
      // A real percentage only when a trained classifier produced it.
      value: classifierPercent ?? analysis.confidence_level,
      tone: 'bg-sky-100 text-sky-700',
      capitalise: !classifierPercent,
    },
    {
      icon: Gauge,
      label: 'Severity (est.)',
      value: analysis.severity.label,
      tone: 'bg-harvest-100 text-harvest-700',
      pill: SEVERITY_PILL[analysis.severity.level],
    },
  ];

  return (
    <Card>
      <CardBody className="space-y-3">
        <div className="grid items-center gap-4 lg:grid-cols-[1fr_auto]">
          <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {cells.map((cell) => (
              <div key={cell.label} className="flex items-center gap-2.5">
                <span
                  className={classNames(
                    'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg',
                    cell.tone,
                  )}
                >
                  <cell.icon className="h-4 w-4" />
                </span>
                <div className="min-w-0">
                  <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                    {cell.label}
                  </dt>
                  <dd
                    className={classNames(
                      'truncate text-sm font-bold text-bark-900',
                      cell.capitalise && 'capitalize',
                    )}
                    title={String(cell.value)}
                  >
                    {cell.pill ? (
                      <span className={cell.pill}>{cell.value}</span>
                    ) : (
                      cell.value
                    )}
                  </dd>
                </div>
              </div>
            ))}
          </dl>

          <button
            type="button"
            onClick={() => void handleDownload()}
            className="btn-primary btn-lg shrink-0"
            disabled={isDownloading || !result.detection_id}
            title={
              result.detection_id
                ? 'Download the full diagnosis as a PDF'
                : 'Not available - this analysis was not saved'
            }
          >
            {isDownloading ? <Spinner /> : <Download className="h-5 w-5" />}
            {isDownloading ? 'Preparing...' : 'Download Report'}
          </button>
        </div>

        {error && (
          <Notice tone="danger" icon={<FileText className="h-4 w-4" />}>
            {error}
          </Notice>
        )}

        {!classifierPercent && (
          <p className="text-2xs leading-snug text-bark-400">
            Confidence is shown as a qualitative level because no trained classifier applied to
            this plant. A rule match has no calibrated probability, so no percentage is given.
          </p>
        )}
      </CardBody>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* Empty-state hint used before the first analysis                     */
/* ------------------------------------------------------------------ */

export function DiagnosisPlaceholder() {
  return (
    <Card className="h-full">
      <CardBody className="flex h-full flex-col items-center justify-center gap-3 py-16 text-center">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-leaf-50 text-leaf-500">
          <Camera className="h-7 w-7" />
        </span>
        <h3 className="text-base font-semibold text-bark-800">No analysis yet</h3>
        <p className="max-w-sm text-sm leading-relaxed text-bark-500">
          Capture a leaf with the webcam or the ESP32-CAM, or upload an image, then press
          <strong> Analyse plant</strong>. The full diagnosis - plant, condition, symptoms,
          causes, treatment and prevention - appears here.
        </p>
      </CardBody>
    </Card>
  );
}

export default CapturedImagePanel;
