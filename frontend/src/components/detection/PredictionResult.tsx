import {
  Activity,
  AlertTriangle,
  Clock,
  FlaskConical,
  Gauge,
  Image as ImageIcon,
  Leaf,
  ListOrdered,
  Stethoscope,
} from 'lucide-react';
import type { DetectionResponse } from '@/services/types';
import { Card, CardBody, CardHeader, ConfidenceMeter, Notice, StatusBadge } from '@/components/ui';
import { CameraSourceBadge } from '@/components/camera/CameraSourceBadge';
import { classNames, formatBytes } from '@/utils/format';
import { confidenceColour, severityMeta, statusMeta } from '@/utils/status';
import { imageUrl } from '@/services/api';
import { ProbabilityList } from './ProbabilityList';

interface PredictionResultProps {
  result: DetectionResponse;
  /** Local object URL when the user uploaded a file (shown before the stored copy exists). */
  localPreviewUrl?: string | null;
}

/**
 * The result panel.
 *
 * Layout follows what the operator needs in order: *what is it*, *how sure*,
 * *what do I do*, then the supporting evidence (full probabilities, image
 * quality metrics, timings). Inconclusive outcomes take over the headline
 * instead of being shown as a weak diagnosis.
 */
export function PredictionResult({ result, localPreviewUrl }: PredictionResultProps) {
  const prediction = result.prediction;
  const meta = statusMeta(prediction.detection_status);
  const info = prediction.disease_info;
  const severity = severityMeta(info?.severity);
  const colour = confidenceColour(prediction.confidence, prediction.confidence_threshold);
  const preview = imageUrl(result.image.url) ?? localPreviewUrl ?? undefined;

  return (
    <div className="space-y-4">
      {/* Test-mode warning sits above everything, per prediction. */}
      {!prediction.is_validated_prediction && prediction.warnings.length > 0 && (
        <Notice tone="warning" icon={<FlaskConical className="h-4 w-4" />} title="Not a real diagnosis">
          {prediction.warnings.map((warning) => (
            <p key={warning} className="mt-0.5">
              {warning}
            </p>
          ))}
        </Notice>
      )}

      {/* ---- Headline ---- */}
      <Card className={classNames('overflow-hidden border-2', meta.borderClass)}>
        <div className={classNames('px-5 py-4', meta.softBgClass)}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={prediction.detection_status} />
                <CameraSourceBadge source={result.camera_source} />
                {result.detection_id && (
                  <span className="chip font-mono text-2xs">record #{result.detection_id}</span>
                )}
              </div>

              {prediction.is_conclusive ? (
                <>
                  <h2 className="mt-3 text-2xl font-bold tracking-tight text-bark-900 sm:text-3xl">
                    {prediction.predicted_disease}
                  </h2>
                  <p className="mt-1 flex items-center gap-1.5 text-sm font-medium text-bark-600">
                    <Leaf className="h-4 w-4 text-leaf-600" />
                    {prediction.plant_name}
                    {prediction.predicted_class && (
                      <span className="ml-1 font-mono text-xs text-bark-400">
                        ({prediction.predicted_class})
                      </span>
                    )}
                  </p>
                </>
              ) : (
                <>
                  <h2 className="mt-3 text-2xl font-bold tracking-tight text-bark-900 sm:text-3xl">
                    {prediction.display_label}
                  </h2>
                  <p className="mt-1 max-w-2xl text-sm leading-relaxed text-bark-600">
                    {prediction.reason}
                  </p>
                </>
              )}
            </div>

            <div className="shrink-0 text-right">
              <p className="text-2xs font-bold uppercase tracking-wider text-bark-400">Confidence</p>
              <p className="text-4xl font-extrabold tabular-nums" style={{ color: colour }}>
                {prediction.confidence_percent.toFixed(1)}
                <span className="text-xl">%</span>
              </p>
            </div>
          </div>

          <div className="mt-4 max-w-md">
            <ConfidenceMeter
              confidence={prediction.confidence}
              threshold={prediction.confidence_threshold}
              colour={colour}
            />
          </div>
        </div>

        {/* ---- Image + facts ---- */}
        <CardBody className="grid gap-5 sm:grid-cols-[minmax(0,13rem)_1fr]">
          <div className="overflow-hidden rounded-xl border border-bark-100 bg-bark-900">
            {preview ? (
              <img
                src={preview}
                alt={`Analysed leaf: ${prediction.display_label}`}
                className="h-44 w-full object-cover sm:h-48"
              />
            ) : (
              <div className="flex h-44 items-center justify-center text-bark-500 sm:h-48">
                <ImageIcon className="h-8 w-8" />
              </div>
            )}
          </div>

          <dl className="grid grid-cols-2 gap-x-5 gap-y-3 text-sm">
            <div>
              <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">Status</dt>
              <dd className={classNames('mt-0.5 font-semibold', meta.textClass)}>{meta.label}</dd>
            </div>
            <div>
              <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                Severity
              </dt>
              <dd className="mt-0.5">
                {info ? <span className={severity.badgeClass}>{severity.label}</span> : '--'}
              </dd>
            </div>
            <div>
              <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                <Gauge className="mr-1 inline h-3 w-3" />
                Threshold
              </dt>
              <dd className="mt-0.5 font-medium text-bark-700">
                {(prediction.confidence_threshold * 100).toFixed(0)}%
              </dd>
            </div>
            <div>
              <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                <Clock className="mr-1 inline h-3 w-3" />
                Inference time
              </dt>
              <dd className="mt-0.5 font-medium text-bark-700">{prediction.inference_ms} ms</dd>
            </div>
            <div>
              <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">Image</dt>
              <dd className="mt-0.5 font-medium text-bark-700">
                {result.image.width}&times;{result.image.height} &middot;{' '}
                {formatBytes(result.image.size_bytes)}
              </dd>
            </div>
            <div>
              <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">Model</dt>
              <dd className="mt-0.5 font-medium text-bark-700">
                {prediction.model.base_model ?? 'MobileNetV2'} &middot; {prediction.model.num_classes}{' '}
                classes
              </dd>
            </div>
            <div>
              <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                Camera
              </dt>
              <dd className="mt-0.5 font-medium text-bark-700">{result.camera_source_label}</dd>
            </div>
          </dl>
        </CardBody>
      </Card>

      {/* ---- Image quality issues ---- */}
      {!prediction.image_quality.passed && prediction.image_quality.issues.length > 0 && (
        <Notice
          tone="warning"
          icon={<AlertTriangle className="h-4 w-4" />}
          title="Image quality problems detected"
        >
          <ul className="mt-1 list-inside list-disc space-y-0.5">
            {prediction.image_quality.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </Notice>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* ---- Disease reference ---- */}
        {info && prediction.is_conclusive && (
          <Card>
            <CardHeader
              title="Condition reference"
              subtitle="Static agronomic guidance - it does not influence the prediction"
              icon={<Stethoscope className="h-4 w-4" />}
            />
            <CardBody className="space-y-4">
              <p className="text-sm leading-relaxed text-bark-600">{info.description}</p>

              {info.symptoms.length > 0 && (
                <div>
                  <p className="label">Typical symptoms</p>
                  <ul className="space-y-1.5">
                    {info.symptoms.map((symptom) => (
                      <li key={symptom} className="flex gap-2 text-sm text-bark-600">
                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-harvest-500" />
                        {symptom}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {info.management.length > 0 && (
                <div>
                  <p className="label">Suggested management</p>
                  <ul className="space-y-1.5">
                    {info.management.map((action) => (
                      <li key={action} className="flex gap-2 text-sm text-bark-600">
                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-leaf-500" />
                        {action}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardBody>
          </Card>
        )}

        {/* ---- Probabilities ---- */}
        <Card className={prediction.is_conclusive && info ? '' : 'lg:col-span-2'}>
          <CardHeader
            title="Class probabilities"
            subtitle={`Softmax output over all ${prediction.model.num_classes} trained classes`}
            icon={<ListOrdered className="h-4 w-4" />}
          />
          <CardBody>
            <ProbabilityList
              items={prediction.class_probabilities}
              selectedClass={prediction.predicted_class}
              threshold={prediction.confidence_threshold}
            />
          </CardBody>
        </Card>
      </div>

      {/* ---- Quality metrics ---- */}
      <Card>
        <CardHeader
          title="Image quality measurements"
          subtitle="Computed before inference; a failure here returns 'unknown' instead of a guess"
          icon={<Activity className="h-4 w-4" />}
        />
        <CardBody>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            {[
              { label: 'Resolution', value: `${prediction.image_quality.metrics.width}\u00d7${prediction.image_quality.metrics.height}` },
              { label: 'Sharpness', value: prediction.image_quality.metrics.sharpness },
              { label: 'Brightness', value: prediction.image_quality.metrics.brightness },
              { label: 'Contrast', value: prediction.image_quality.metrics.contrast },
              {
                label: 'Leaf pixels',
                value: `${(prediction.image_quality.metrics.plant_pixel_ratio * 100).toFixed(1)}%`,
              },
            ].map((metric) => (
              <div key={metric.label} className="rounded-xl bg-bark-50 px-3 py-2.5">
                <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                  {metric.label}
                </dt>
                <dd className="mt-0.5 text-base font-semibold tabular-nums text-bark-800">
                  {metric.value}
                </dd>
              </div>
            ))}
          </dl>
        </CardBody>
      </Card>
    </div>
  );
}

export default PredictionResult;
