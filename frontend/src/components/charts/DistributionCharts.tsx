import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { DistributionItem, PlantDistributionItem } from '@/services/types';
import { AXIS_STYLE, ChartTooltip, GRID_STYLE, TOOLTIP_CURSOR } from './ChartShell';

/* ------------------------------------------------------------------ */
/* Disease distribution (donut)                                        */
/* ------------------------------------------------------------------ */

interface DonutProps {
  data: { name: string; count: number; colour: string }[];
  height?: number;
  centreLabel?: string;
  centreValue?: string | number;
}

/**
 * Donut chart with the headline figure in the hole.
 *
 * The centre label carries the number the viewer actually wants (total scans,
 * or diseased count); the ring only shows how it splits.
 */
export function DonutChart({ data, height = 288, centreLabel, centreValue }: DonutProps) {
  const total = data.reduce((sum, item) => sum + item.count, 0);

  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie
            data={data}
            dataKey="count"
            nameKey="name"
            innerRadius="58%"
            outerRadius="84%"
            paddingAngle={data.length > 1 ? 2 : 0}
            strokeWidth={2}
            stroke="#ffffff"
          >
            {data.map((item) => (
              <Cell key={item.name} fill={item.colour} />
            ))}
          </Pie>
          <Tooltip content={<ChartTooltip />} />
          <Legend
            iconType="circle"
            iconSize={8}
            wrapperStyle={{ fontSize: 12, color: '#587055' }}
          />
        </PieChart>
      </ResponsiveContainer>

      {(centreValue !== undefined || centreLabel) && (
        <div
          className="pointer-events-none absolute inset-x-0 flex flex-col items-center justify-center"
          style={{ top: 0, height: height - 42 }}
        >
          <span className="text-2xl font-bold tabular-nums text-bark-900">
            {centreValue ?? total}
          </span>
          {centreLabel && (
            <span className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
              {centreLabel}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Disease distribution (horizontal bars)                              */
/* ------------------------------------------------------------------ */

/**
 * Horizontal bars for disease counts.
 *
 * Preferred over a pie when labels are long ("Tomato - Septoria Leaf Spot"):
 * the category axis has room for real text instead of a colour legend the
 * reader has to decode.
 */
export function DiseaseBarChart({ data, height = 288 }: { data: DistributionItem[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={Math.max(height, data.length * 38 + 40)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 0 }}>
        <CartesianGrid {...GRID_STYLE} horizontal={false} />
        <XAxis
          type="number"
          tick={AXIS_STYLE.tick}
          stroke={AXIS_STYLE.stroke}
          tickLine={false}
          allowDecimals={false}
        />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ ...AXIS_STYLE.tick, fontSize: 10 }}
          stroke={AXIS_STYLE.stroke}
          tickLine={false}
          width={150}
        />
        <Tooltip content={<ChartTooltip />} cursor={TOOLTIP_CURSOR} />
        <Bar dataKey="count" name="Detections" radius={[0, 6, 6, 0]} maxBarSize={26}>
          {data.map((item) => (
            <Cell key={item.name} fill={item.colour} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/* ------------------------------------------------------------------ */
/* Plant-wise stacked bars                                             */
/* ------------------------------------------------------------------ */

export function PlantDistributionChart({
  data,
  height = 288,
}: {
  data: PlantDistributionItem[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid {...GRID_STYLE} vertical={false} />
        <XAxis dataKey="plant" tick={AXIS_STYLE.tick} stroke={AXIS_STYLE.stroke} tickLine={false} />
        <YAxis
          tick={AXIS_STYLE.tick}
          stroke={AXIS_STYLE.stroke}
          tickLine={false}
          allowDecimals={false}
          width={46}
        />
        <Tooltip content={<ChartTooltip showTotal />} cursor={TOOLTIP_CURSOR} />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, paddingTop: 8, color: '#587055' }} />
        <Bar dataKey="healthy" name="Healthy" stackId="plant" fill="#16a34a" maxBarSize={56} />
        <Bar dataKey="diseased" name="Diseased" stackId="plant" fill="#dc2626" maxBarSize={56} />
        <Bar
          dataKey="inconclusive"
          name="Inconclusive"
          stackId="plant"
          fill="#f59e0b"
          radius={[6, 6, 0, 0]}
          maxBarSize={56}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

/* ------------------------------------------------------------------ */
/* Confidence histogram                                                */
/* ------------------------------------------------------------------ */

export function ConfidenceHistogram({
  data,
  height = 240,
}: {
  data: { range: string; count: number; colour: string }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
        <CartesianGrid {...GRID_STYLE} vertical={false} />
        <XAxis dataKey="range" tick={AXIS_STYLE.tick} stroke={AXIS_STYLE.stroke} tickLine={false} />
        <YAxis
          tick={AXIS_STYLE.tick}
          stroke={AXIS_STYLE.stroke}
          tickLine={false}
          allowDecimals={false}
          width={46}
        />
        <Tooltip content={<ChartTooltip />} cursor={TOOLTIP_CURSOR} />
        <Bar dataKey="count" name="Detections" radius={[6, 6, 0, 0]} maxBarSize={64}>
          {data.map((item) => (
            <Cell key={item.range} fill={item.colour} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
