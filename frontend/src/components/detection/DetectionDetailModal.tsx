import { FlaskConical, Trash2 } from 'lucide-react';
import type { DetectionRecord } from '@/services/types';
import { imageUrl } from '@/services/api';
import { Modal, Notice, Spinner, StatusBadge } from '@/components/ui';
import { CameraSourceBadge } from '@/components/camera/CameraSourceBadge';
import { formatBytes, formatDateTime } from '@/utils/format';
import { statusMeta } from '@/utils/status';
import { ProbabilityList } from './ProbabilityList';

interface DetectionDetailModalProps {
  record: DetectionRecord | null;
  onClose: () => void;
  onDelete?: (record: DetectionRecord) => void;
  isDeleting?: boolean;
}

/** Full detail for one stored detection, opened from the history list. */
export function DetectionDetailModal({
  record,
  onClose,
  onDelete,
  isDeleting,
}: DetectionDetailModalProps) {
  if (!record) return null;

  const meta = statusMeta(record.detection_status);
  const source = imageUrl(record.image_url);

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={
        record.is_conclusive
          ? `${record.plant_name} - ${record.predicted_disease}`
          : `${record.plant_name} - ${meta.label}`
      }
      subtitle={formatDateTime(record.created_at)}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Close
          </button>
          {onDelete && (
            <button
              type="button"
              className="btn-danger"
              onClick={() => onDelete(record)}
              disabled={isDeleting}
            >
              {isDeleting ? <Spinner /> : <Trash2 className="h-4 w-4" />}
              Delete record
            </button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        {!record.is_validated && (
          <Notice tone="warning" icon={<FlaskConical className="h-4 w-4" />} title="Test-mode record">
            This result came from an untrained model and is not a valid diagnosis. It is kept in the
            history flagged as unvalidated so it can be told apart from real results.
          </Notice>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="overflow-hidden rounded-xl border border-bark-100 bg-bark-900">
            {source ? (
              <img
                src={source}
                alt={`${record.plant_name} - ${record.predicted_disease}`}
                className="h-full max-h-72 w-full object-contain"
              />
            ) : (
              <div className="flex h-48 items-center justify-center text-sm text-bark-400">
                Image file not available
              </div>
            )}
          </div>

          <dl className="space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-bark-500">Status</dt>
              <dd>
                <StatusBadge status={record.detection_status} />
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-bark-500">Confidence</dt>
              <dd className="font-semibold tabular-nums text-bark-800">
                {record.confidence_percent.toFixed(2)}%
                {record.confidence_threshold !== null && (
                  <span className="ml-1 text-xs font-normal text-bark-400">
                    (threshold {(record.confidence_threshold * 100).toFixed(0)}%)
                  </span>
                )}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-bark-500">Camera source</dt>
              <dd>
                <CameraSourceBadge source={record.camera_source} />
              </dd>
            </div>
            {record.device_name && (
              <div className="flex items-center justify-between gap-3">
                <dt className="text-bark-500">Device</dt>
                <dd className="font-mono text-xs text-bark-600">{record.device_name}</dd>
              </div>
            )}
            <div className="flex items-center justify-between gap-3">
              <dt className="text-bark-500">Dataset class</dt>
              <dd className="truncate font-mono text-xs text-bark-600" title={record.predicted_class ?? ''}>
                {record.predicted_class ?? '--'}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-bark-500">Inference time</dt>
              <dd className="font-medium text-bark-700">
                {record.inference_ms !== null ? `${record.inference_ms} ms` : '--'}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-bark-500">File size</dt>
              <dd className="font-medium text-bark-700">{formatBytes(record.image_size_bytes)}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-bark-500">Recorded at</dt>
              <dd className="font-medium text-bark-700">{formatDateTime(record.created_at)}</dd>
            </div>
          </dl>
        </div>

        {record.notes && (
          <div className="rounded-xl bg-bark-50 px-4 py-3">
            <p className="label">Note</p>
            <p className="text-sm leading-relaxed text-bark-600">{record.notes}</p>
          </div>
        )}

        <div>
          <p className="label">Top class probabilities</p>
          <ProbabilityList items={record.probabilities} selectedClass={record.predicted_class} />
        </div>

        {record.image_quality && (
          <div>
            <p className="label">Image quality at capture</p>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                { label: 'Sharpness', value: record.image_quality.metrics.sharpness },
                { label: 'Brightness', value: record.image_quality.metrics.brightness },
                { label: 'Contrast', value: record.image_quality.metrics.contrast },
                {
                  label: 'Leaf pixels',
                  value: `${(record.image_quality.metrics.plant_pixel_ratio * 100).toFixed(1)}%`,
                },
              ].map((metric) => (
                <div key={metric.label} className="rounded-lg bg-bark-50 px-3 py-2">
                  <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                    {metric.label}
                  </dt>
                  <dd className="text-sm font-semibold tabular-nums text-bark-800">{metric.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>
    </Modal>
  );
}

export default DetectionDetailModal;
