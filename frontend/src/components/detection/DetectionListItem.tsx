import { FlaskConical, Image as ImageIcon } from 'lucide-react';
import type { DetectionRecord } from '@/services/types';
import { imageUrl } from '@/services/api';
import { StatusBadge } from '@/components/ui';
import { CameraSourceIcon } from '@/components/camera/CameraSourceBadge';
import { classNames, formatRelative } from '@/utils/format';
import { statusMeta } from '@/utils/status';

interface DetectionListItemProps {
  record: DetectionRecord;
  onClick?: (record: DetectionRecord) => void;
  /** Compact variant used in the dashboard's "recent detections" list. */
  compact?: boolean;
}

/** Thumbnail with a graceful fallback - a stored file can be missing from disk. */
function Thumbnail({ record, size }: { record: DetectionRecord; size: string }) {
  const source = imageUrl(record.image_url);

  return (
    <div className={classNames('shrink-0 overflow-hidden rounded-xl border border-bark-100 bg-bark-100', size)}>
      {source ? (
        <img
          src={source}
          alt={`${record.plant_name} - ${record.predicted_disease}`}
          loading="lazy"
          className="h-full w-full object-cover"
          onError={(event) => {
            event.currentTarget.style.display = 'none';
          }}
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-bark-300">
          <ImageIcon className="h-5 w-5" />
        </div>
      )}
    </div>
  );
}

export function DetectionListItem({ record, onClick, compact = false }: DetectionListItemProps) {
  const meta = statusMeta(record.detection_status);
  const isInteractive = Boolean(onClick);

  return (
    <div
      role={isInteractive ? 'button' : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      onClick={() => onClick?.(record)}
      onKeyDown={(event) => {
        if (isInteractive && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          onClick?.(record);
        }
      }}
      className={classNames(
        'flex items-center gap-3 rounded-xl border border-transparent px-2 py-2 transition-colors',
        isInteractive && 'cursor-pointer hover:border-bark-100 hover:bg-bark-50',
      )}
    >
      <Thumbnail record={record} size={compact ? 'h-11 w-11' : 'h-14 w-14'} />

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-semibold text-bark-900">
            {record.plant_name}
            {record.is_conclusive && (
              <span className="font-normal text-bark-500"> &middot; {record.predicted_disease}</span>
            )}
          </p>
          {!record.is_validated && (
            <span
              className="shrink-0 text-harvest-600"
              title="Produced by an untrained model in test mode - not a real diagnosis"
            >
              <FlaskConical className="h-3.5 w-3.5" />
            </span>
          )}
        </div>

        <div className="mt-1 flex items-center gap-2 text-xs text-bark-400">
          <CameraSourceIcon source={record.camera_source} className="text-xs" />
          <span aria-hidden="true">&middot;</span>
          <time dateTime={record.created_at ?? undefined}>{formatRelative(record.created_at)}</time>
        </div>
      </div>

      <div className="shrink-0 text-right">
        <p className={classNames('text-sm font-bold tabular-nums', meta.textClass)}>
          {record.confidence_percent.toFixed(1)}%
        </p>
        <div className="mt-1">
          <StatusBadge status={record.detection_status} short showIcon={false} />
        </div>
      </div>
    </div>
  );
}

export default DetectionListItem;
