import type { ReactNode } from 'react';
import { BarChart3 } from 'lucide-react';
import { Card, CardBody, CardHeader, ChartSkeleton, EmptyState } from '@/components/ui';

/** Axis and grid styling shared by every chart, so they look like one family. */
export const AXIS_STYLE = {
  tick: { fill: '#587055', fontSize: 11 },
  stroke: '#c7d1c9',
} as const;

export const GRID_STYLE = {
  stroke: '#e3e8e4',
  strokeDasharray: '3 3',
} as const;

export const TOOLTIP_CURSOR = { fill: 'rgba(22, 163, 74, 0.06)' } as const;

interface TooltipRow {
  name?: string | number;
  value?: string | number;
  color?: string;
  dataKey?: string | number;
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: TooltipRow[];
  label?: string | number;
  /** Appended to every value, e.g. "%" or " scans". */
  unit?: string;
  /** Show the sum of all series, useful on stacked charts. */
  showTotal?: boolean;
}

/** Tooltip styled to match the dashboard cards rather than Recharts' default. */
export function ChartTooltip({ active, payload, label, unit = '', showTotal }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;

  const total = payload.reduce((sum, row) => sum + (Number(row.value) || 0), 0);

  return (
    <div className="rounded-xl border border-bark-100 bg-white/97 px-3 py-2 shadow-card backdrop-blur">
      {label !== undefined && label !== '' && (
        <p className="mb-1.5 text-xs font-semibold text-bark-700">{label}</p>
      )}
      <div className="space-y-1">
        {payload.map((row, index) => (
          <div key={`${row.dataKey ?? index}`} className="flex items-center gap-2 text-xs">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ backgroundColor: row.color ?? '#16a34a' }}
            />
            <span className="capitalize text-bark-500">{row.name}</span>
            <span className="ml-auto font-semibold tabular-nums text-bark-800">
              {row.value}
              {unit}
            </span>
          </div>
        ))}
      </div>
      {showTotal && payload.length > 1 && (
        <div className="mt-1.5 flex items-center justify-between gap-4 border-t border-bark-100 pt-1.5 text-xs">
          <span className="text-bark-500">Total</span>
          <span className="font-semibold tabular-nums text-bark-800">{total}</span>
        </div>
      )}
    </div>
  );
}

interface ChartCardProps {
  title: string;
  subtitle?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  isLoading?: boolean;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDescription?: ReactNode;
  height?: number;
  children: ReactNode;
  className?: string;
}

/**
 * Wrapper that gives every chart the same loading, empty and populated states.
 *
 * The empty state matters here: with no scans recorded, a chart component would
 * otherwise render blank axes that look like a bug. This says "no data yet" in
 * words instead.
 */
export function ChartCard({
  title,
  subtitle,
  icon,
  actions,
  isLoading,
  isEmpty,
  emptyTitle = 'No data yet',
  emptyDescription = 'Run a detection to populate this chart.',
  height = 288,
  children,
  className,
}: ChartCardProps) {
  return (
    <Card className={className}>
      <CardHeader title={title} subtitle={subtitle} icon={icon} actions={actions} />
      {isLoading ? (
        <ChartSkeleton height={height} />
      ) : isEmpty ? (
        <EmptyState
          icon={<BarChart3 className="h-7 w-7" />}
          title={emptyTitle}
          description={emptyDescription}
        />
      ) : (
        <CardBody className="pt-4">{children}</CardBody>
      )}
    </Card>
  );
}
