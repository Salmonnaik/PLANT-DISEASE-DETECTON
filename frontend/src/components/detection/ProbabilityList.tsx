import type { ClassProbability } from '@/services/types';
import { classNames } from '@/utils/format';

interface ProbabilityListProps {
  items: ClassProbability[];
  /** Highlight the row the model actually chose. */
  selectedClass?: string | null;
  threshold?: number;
  max?: number;
}

/**
 * The full softmax output, ranked.
 *
 * Shown because a single headline percentage hides the interesting part: a
 * 55/43 split between early and late blight is a very different situation from
 * 98/1, even though both would read as "Late Blight" at the top.
 */
export function ProbabilityList({ items, selectedClass, threshold, max }: ProbabilityListProps) {
  const rows = max ? items.slice(0, max) : items;
  if (rows.length === 0) {
    return (
      <p className="text-sm text-bark-500">
        No class probabilities are available: the image failed the quality check, so it was never
        passed to the model.
      </p>
    );
  }

  return (
    <ul className="space-y-2.5">
      {rows.map((item) => {
        const isSelected = selectedClass ? item.class === selectedClass : false;
        const meetsThreshold = threshold === undefined || item.probability >= threshold;

        return (
          <li key={item.class}>
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <span
                className={classNames(
                  'min-w-0 truncate text-sm',
                  isSelected ? 'font-semibold text-bark-900' : 'text-bark-600',
                )}
                title={item.class}
              >
                {item.plant} &middot; {item.disease}
              </span>
              <span
                className={classNames(
                  'shrink-0 text-sm font-semibold tabular-nums',
                  isSelected ? 'text-bark-900' : 'text-bark-500',
                )}
              >
                {item.probability_percent.toFixed(2)}%
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-bark-100">
              <div
                className="h-full animate-bar-grow rounded-full origin-left"
                style={{
                  width: `${Math.max(0.6, item.probability_percent)}%`,
                  backgroundColor: item.is_healthy
                    ? '#16a34a'
                    : meetsThreshold && isSelected
                      ? '#dc2626'
                      : '#9faea3',
                }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export default ProbabilityList;
