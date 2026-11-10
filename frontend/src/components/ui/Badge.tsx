import { AlertTriangle, CheckCircle2, HelpCircle, ShieldAlert } from 'lucide-react';
import type { DetectionStatus } from '@/services/types';
import { classNames } from '@/utils/format';
import { statusMeta } from '@/utils/status';

interface StatusBadgeProps {
  status: DetectionStatus | string | null | undefined;
  /** Use the shorter wording, for table cells and tight spaces. */
  short?: boolean;
  showIcon?: boolean;
  className?: string;
}

const ICONS: Record<DetectionStatus, typeof CheckCircle2> = {
  healthy: CheckCircle2,
  diseased: ShieldAlert,
  uncertain: AlertTriangle,
  unknown: HelpCircle,
};

export function StatusBadge({ status, short = false, showIcon = true, className }: StatusBadgeProps) {
  const meta = statusMeta(status);
  const key = (status && status in ICONS ? status : 'unknown') as DetectionStatus;
  const Icon = ICONS[key];

  return (
    <span className={classNames(meta.badgeClass, className)}>
      {showIcon && <Icon className="h-3.5 w-3.5" aria-hidden="true" />}
      {short ? meta.shortLabel : meta.label}
    </span>
  );
}

interface LiveDotProps {
  online: boolean;
  label?: string;
  className?: string;
}

/** Pulsing presence indicator for the ESP32-CAM connection. */
export function LiveDot({ online, label, className }: LiveDotProps) {
  return (
    <span className={classNames('inline-flex items-center gap-2', className)}>
      <span className="relative flex h-2.5 w-2.5">
        {online && (
          <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-leaf-400" />
        )}
        <span
          className={classNames(
            'relative inline-flex h-2.5 w-2.5 rounded-full',
            online ? 'bg-leaf-500' : 'bg-bark-300',
          )}
        />
      </span>
      {label && (
        <span className={classNames('text-xs font-semibold', online ? 'text-leaf-700' : 'text-bark-500')}>
          {label}
        </span>
      )}
    </span>
  );
}

export default StatusBadge;
