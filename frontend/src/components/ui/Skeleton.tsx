import type { CSSProperties } from 'react';
import { classNames } from '@/utils/format';

export function Skeleton({ className, style }: { className?: string; style?: CSSProperties }) {
  return <div className={classNames('skeleton', className)} style={style} aria-hidden="true" />;
}

/** Placeholder matching the footprint of a chart card, to avoid layout shift. */
export function ChartSkeleton({ height = 280 }: { height?: number }) {
  return (
    <div className="space-y-3 p-5">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="w-full rounded-xl" style={{ height }} />
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-5">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="flex items-center gap-4">
          <Skeleton className="h-12 w-12 rounded-xl" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-24" />
        </div>
      ))}
    </div>
  );
}

export default Skeleton;
