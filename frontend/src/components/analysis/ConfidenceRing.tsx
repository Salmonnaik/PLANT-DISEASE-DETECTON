import type { ConfidenceLevel } from '@/services/types';
import { classNames } from '@/utils/format';

/**
 * Arc length per qualitative level.
 *
 * These are presentation values for the ring, not probabilities. A rule match
 * has no calibrated probability, so when there is no classifier percentage the
 * ring shows the level's *name* as the primary figure and the arc only conveys
 * "more" or "less". The caption says which is being shown, so the arc can
 * never be misread as a measured number.
 */
const LEVEL_ARC: Record<ConfidenceLevel, { fraction: number; colour: string; label: string }> = {
  confident: { fraction: 1.0, colour: '#16a34a', label: 'Confident' },
  probable: { fraction: 0.72, colour: '#22c55e', label: 'Probable' },
  possible: { fraction: 0.45, colour: '#f59e0b', label: 'Possible' },
  insufficient: { fraction: 0.16, colour: '#9faea3', label: 'Unclear' },
};

interface ConfidenceRingProps {
  level: ConfidenceLevel;
  /**
   * The trained classifier's softmax probability (0-1), when one applies.
   * This is the only genuinely numeric confidence in the system; omit it and
   * the ring falls back to the qualitative level.
   */
  percent?: number | null;
  size?: number;
  className?: string;
}

export function ConfidenceRing({ level, percent, size = 76, className }: ConfidenceRingProps) {
  const meta = LEVEL_ARC[level] ?? LEVEL_ARC.insufficient;
  const hasNumber = typeof percent === 'number' && Number.isFinite(percent);

  const fraction = hasNumber ? Math.max(0, Math.min(1, percent)) : meta.fraction;
  const colour = hasNumber
    ? fraction >= 0.85
      ? '#16a34a'
      : fraction >= 0.7
        ? '#22c55e'
        : '#f59e0b'
    : meta.colour;

  const stroke = 7;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = circumference * fraction;

  return (
    <div className={classNames('flex flex-col items-center gap-1', className)}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="#e3e8e4"
            strokeWidth={stroke}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={colour}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
            className="transition-[stroke-dasharray] duration-700 ease-spring"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          {hasNumber ? (
            <span className="text-lg font-bold tabular-nums text-bark-900">
              {(fraction * 100).toFixed(0)}%
            </span>
          ) : (
            <span
              className="px-1 text-center text-[11px] font-bold uppercase leading-tight tracking-tight"
              style={{ color: colour }}
            >
              {meta.label}
            </span>
          )}
        </div>
      </div>

      <p className="max-w-[9rem] text-center text-2xs leading-tight text-bark-400">
        {hasNumber
          ? 'Trained classifier probability'
          : 'Qualitative - no calibrated probability'}
      </p>
    </div>
  );
}

export default ConfidenceRing;
