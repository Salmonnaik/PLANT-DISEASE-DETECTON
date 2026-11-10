import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { PerClassMetric } from '@/services/types';
import { classNames } from '@/utils/format';
import { AXIS_STYLE, ChartTooltip, GRID_STYLE, TOOLTIP_CURSOR } from './ChartShell';

/* ------------------------------------------------------------------ */
/* Per-class precision / recall / F1                                   */
/* ------------------------------------------------------------------ */

/**
 * Per-class scores from ``ml/reports/metrics.json``.
 *
 * Precision, recall and F1 are grouped per class rather than averaged, because
 * a respectable macro F1 can still hide one class the model never gets right -
 * which is exactly what a project report needs to disclose.
 */
export function PerClassMetricsChart({
  data,
  height,
}: {
  data: PerClassMetric[];
  height?: number;
}) {
  const rows = data.map((item) => ({
    name: `${item.plant} - ${item.disease}`,
    precision: Number((item.precision * 100).toFixed(1)),
    recall: Number((item.recall * 100).toFixed(1)),
    f1: Number((item.f1_score * 100).toFixed(1)),
    support: item.support,
  }));

  return (
    <ResponsiveContainer width="100%" height={height ?? Math.max(300, rows.length * 56 + 48)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 0 }}>
        <CartesianGrid {...GRID_STYLE} horizontal={false} />
        <XAxis
          type="number"
          domain={[0, 100]}
          unit="%"
          tick={AXIS_STYLE.tick}
          stroke={AXIS_STYLE.stroke}
          tickLine={false}
        />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ ...AXIS_STYLE.tick, fontSize: 10 }}
          stroke={AXIS_STYLE.stroke}
          tickLine={false}
          width={160}
        />
        <Tooltip content={<ChartTooltip unit="%" />} cursor={TOOLTIP_CURSOR} />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: '#587055' }} />
        <Bar dataKey="precision" name="Precision" fill="#16a34a" radius={[0, 3, 3, 0]} maxBarSize={10} />
        <Bar dataKey="recall" name="Recall" fill="#0891b2" radius={[0, 3, 3, 0]} maxBarSize={10} />
        <Bar dataKey="f1" name="F1-score" fill="#7c3aed" radius={[0, 3, 3, 0]} maxBarSize={10} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/* ------------------------------------------------------------------ */
/* Training curves                                                     */
/* ------------------------------------------------------------------ */

export function TrainingHistoryChart({
  history,
  height = 288,
}: {
  history: Record<string, number[]>;
  height?: number;
}) {
  const epochs = history.accuracy?.length ?? history.loss?.length ?? 0;
  const rows = Array.from({ length: epochs }, (_, index) => ({
    epoch: index + 1,
    accuracy: history.accuracy ? Number((history.accuracy[index] * 100).toFixed(2)) : undefined,
    val_accuracy: history.val_accuracy
      ? Number((history.val_accuracy[index] * 100).toFixed(2))
      : undefined,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={rows} margin={{ top: 4, right: 12, left: -18, bottom: 0 }}>
        <CartesianGrid {...GRID_STYLE} vertical={false} />
        <XAxis
          dataKey="epoch"
          tick={AXIS_STYLE.tick}
          stroke={AXIS_STYLE.stroke}
          tickLine={false}
          label={{ value: 'Epoch', position: 'insideBottom', offset: -2, fill: '#75876f', fontSize: 11 }}
        />
        <YAxis
          unit="%"
          domain={[0, 100]}
          tick={AXIS_STYLE.tick}
          stroke={AXIS_STYLE.stroke}
          tickLine={false}
          width={52}
        />
        <Tooltip content={<ChartTooltip unit="%" />} />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, color: '#587055' }} />
        <Line
          type="monotone"
          dataKey="accuracy"
          name="Training accuracy"
          stroke="#16a34a"
          strokeWidth={2}
          dot={false}
        />
        <Line
          type="monotone"
          dataKey="val_accuracy"
          name="Validation accuracy"
          stroke="#065f46"
          strokeWidth={2}
          strokeDasharray="5 4"
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/* ------------------------------------------------------------------ */
/* Confusion matrix                                                    */
/* ------------------------------------------------------------------ */

interface ConfusionMatrixProps {
  matrix: number[][];
  classNames_: string[];
}

/**
 * Row-normalised confusion matrix rendered as an HTML grid.
 *
 * Deliberately not a charting-library heat map: a plain table gives readable
 * class names on both axes, keyboard-accessible cells with tooltips, and exact
 * counts on hover - all of which matter more here than visual polish.
 */
export function ConfusionMatrix({ matrix, classNames_: labels }: ConfusionMatrixProps) {
  if (!matrix.length) return null;

  const rowTotals = matrix.map((row) => row.reduce((sum, value) => sum + value, 0));

  const cellColour = (value: number, rowTotal: number) => {
    if (!rowTotal) return 'rgba(227, 232, 228, 0.5)';
    const ratio = value / rowTotal;
    if (ratio === 0) return 'transparent';
    return `rgba(22, 163, 74, ${Math.max(0.08, Math.min(1, ratio)).toFixed(3)})`;
  };

  const shortLabel = (label: string) => label.replace(/_+/g, ' ').replace(/\s+/g, ' ').trim();

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-separate border-spacing-0.5 text-2xs">
        <thead>
          <tr>
            <th className="sticky left-0 z-10 bg-white px-2 py-1 text-left font-semibold text-bark-500">
              True \ Predicted
            </th>
            {labels.map((label) => (
              <th
                key={label}
                className="h-24 w-9 px-0 py-1 align-bottom font-medium text-bark-500"
                title={label}
              >
                <span className="block origin-bottom-left translate-x-3 -rotate-[60deg] whitespace-nowrap">
                  {shortLabel(label)}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, rowIndex) => (
            <tr key={labels[rowIndex]}>
              <th
                className="sticky left-0 z-10 max-w-[180px] truncate bg-white px-2 py-1 text-left font-medium text-bark-600"
                title={labels[rowIndex]}
              >
                {shortLabel(labels[rowIndex])}
              </th>
              {row.map((value, columnIndex) => {
                const ratio = rowTotals[rowIndex] ? value / rowTotals[rowIndex] : 0;
                const isDiagonal = rowIndex === columnIndex;
                return (
                  <td
                    key={`${rowIndex}-${columnIndex}`}
                    className={classNames(
                      'h-8 w-9 rounded text-center font-semibold tabular-nums',
                      ratio > 0.55 ? 'text-white' : 'text-bark-700',
                      isDiagonal && 'ring-1 ring-inset ring-leaf-300',
                    )}
                    style={{ backgroundColor: cellColour(value, rowTotals[rowIndex]) }}
                    title={`True: ${labels[rowIndex]}\nPredicted: ${labels[columnIndex]}\nCount: ${value} (${(ratio * 100).toFixed(1)}% of this class)`}
                  >
                    {value || ''}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-bark-500">
        Each row is one true class; colour intensity is the share of that class predicted as the
        column label. A perfect model fills only the outlined diagonal. Hover a cell for exact counts.
      </p>
    </div>
  );
}
