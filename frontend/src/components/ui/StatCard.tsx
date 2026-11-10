import type { ReactNode } from 'react';
import { classNames, formatNumber } from '@/utils/format';
import { Skeleton } from './Skeleton';

export type StatTone = 'leaf' | 'blight' | 'harvest' | 'bark' | 'sky';

const TONES: Record<StatTone, { iconWrap: string; accent: string; value: string }> = {
  leaf: { iconWrap: 'bg-leaf-100 text-leaf-700', accent: 'from-leaf-400 to-leaf-600', value: 'text-leaf-900' },
  blight: { iconWrap: 'bg-blight-100 text-blight-700', accent: 'from-blight-300 to-blight-600', value: 'text-blight-800' },
  harvest: { iconWrap: 'bg-harvest-100 text-harvest-700', accent: 'from-harvest-300 to-harvest-600', value: 'text-harvest-700' },
  bark: { iconWrap: 'bg-bark-100 text-bark-700', accent: 'from-bark-300 to-bark-500', value: 'text-bark-900' },
  sky: { iconWrap: 'bg-sky-100 text-sky-700', accent: 'from-sky-300 to-sky-600', value: 'text-sky-800' },
};

interface StatCardProps {
  label: string;
  value: number | string | null | undefined;
  icon: ReactNode;
  tone?: StatTone;
  hint?: ReactNode;
  /** Secondary figure shown under the value, e.g. "62.5% of all scans". */
  footnote?: ReactNode;
  isLoading?: boolean;
  animationDelayMs?: number;
}

export function StatCard({
  label,
  value,
  icon,
  tone = 'leaf',
  hint,
  footnote,
  isLoading = false,
  animationDelayMs = 0,
}: StatCardProps) {
  const palette = TONES[tone];

  return (
    <div
      className="card-interactive animate-fade-in-up overflow-hidden"
      style={{ animationDelay: `${animationDelayMs}ms` }}
    >
      <div className={classNames('h-1 w-full bg-gradient-to-r', palette.accent)} />
      <div className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-xs font-semibold uppercase tracking-wider text-bark-500">
              {label}
            </p>
            {isLoading ? (
              <Skeleton className="mt-2 h-9 w-20" />
            ) : (
              <p className={classNames('stat-value mt-1', palette.value)}>
                {typeof value === 'number' ? formatNumber(value) : (value ?? '--')}
              </p>
            )}
          </div>
          <span
            className={classNames(
              'flex h-11 w-11 shrink-0 items-center justify-center rounded-xl',
              palette.iconWrap,
            )}
          >
            {icon}
          </span>
        </div>

        {footnote && !isLoading && (
          <p className="mt-3 text-sm font-medium text-bark-600">{footnote}</p>
        )}
        {hint && !isLoading && <p className="mt-1 text-xs text-bark-400">{hint}</p>}
      </div>
    </div>
  );
}

export default StatCard;
