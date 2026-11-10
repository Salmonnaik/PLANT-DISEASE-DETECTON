import { classNames } from '@/utils/format';

interface ProgressBarProps {
  /** 0 - 1. */
  value: number;
  colour?: string;
  className?: string;
  trackClassName?: string;
  /** Animate the bar growing in on mount. */
  animate?: boolean;
  label?: string;
}

export function ProgressBar({
  value,
  colour = '#16a34a',
  className,
  trackClassName,
  animate = true,
  label,
}: ProgressBarProps) {
  const percent = Math.max(0, Math.min(100, value * 100));

  return (
    <div
      className={classNames('h-2 w-full overflow-hidden rounded-full bg-bark-100', trackClassName)}
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div
        className={classNames(
          'h-full rounded-full origin-left transition-[width] duration-700 ease-spring',
          animate && 'animate-bar-grow',
          className,
        )}
        style={{ width: `${percent}%`, backgroundColor: colour }}
      />
    </div>
  );
}

/**
 * Confidence meter with the decision threshold drawn on the track.
 *
 * Showing where the cut-off sits is the point: "68%" means nothing on its own,
 * but "68% against a 70% threshold" explains why the result came back as
 * uncertain.
 */
export function ConfidenceMeter({
  confidence,
  threshold,
  colour,
}: {
  confidence: number;
  threshold: number;
  colour: string;
}) {
  const percent = Math.max(0, Math.min(100, confidence * 100));
  const thresholdPercent = Math.max(0, Math.min(100, threshold * 100));

  return (
    <div className="space-y-1.5">
      <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-bark-100">
        <div
          className="h-full animate-bar-grow rounded-full origin-left"
          style={{ width: `${percent}%`, backgroundColor: colour }}
        />
        <div
          className="absolute top-0 h-full w-0.5 bg-bark-700"
          style={{ left: `${thresholdPercent}%` }}
          title={`Confidence threshold: ${thresholdPercent.toFixed(0)}%`}
        />
      </div>
      <div className="flex justify-between text-2xs font-medium text-bark-400">
        <span>0%</span>
        <span className="text-bark-600">threshold {thresholdPercent.toFixed(0)}%</span>
        <span>100%</span>
      </div>
    </div>
  );
}

export default ProgressBar;
