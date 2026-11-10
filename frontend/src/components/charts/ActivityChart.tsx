import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ActivityPoint } from '@/services/types';
import { AXIS_STYLE, ChartTooltip, GRID_STYLE } from './ChartShell';

interface ActivityChartProps {
  data: ActivityPoint[];
  height?: number;
}

/**
 * Detections per day, stacked by outcome.
 *
 * Stacking (rather than three separate lines) keeps the total scan volume
 * readable as the overall height while still showing the healthy/diseased split
 * that drives the whole system's purpose.
 */
export function ActivityChart({ data, height = 288 }: ActivityChartProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
        <defs>
          <linearGradient id="activityHealthy" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#16a34a" stopOpacity={0.55} />
            <stop offset="100%" stopColor="#16a34a" stopOpacity={0.05} />
          </linearGradient>
          <linearGradient id="activityDiseased" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#dc2626" stopOpacity={0.5} />
            <stop offset="100%" stopColor="#dc2626" stopOpacity={0.05} />
          </linearGradient>
          <linearGradient id="activityInconclusive" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.45} />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.05} />
          </linearGradient>
        </defs>

        <CartesianGrid {...GRID_STYLE} vertical={false} />
        <XAxis
          dataKey="label"
          tick={AXIS_STYLE.tick}
          stroke={AXIS_STYLE.stroke}
          tickLine={false}
          interval="preserveStartEnd"
          minTickGap={16}
        />
        <YAxis
          tick={AXIS_STYLE.tick}
          stroke={AXIS_STYLE.stroke}
          tickLine={false}
          allowDecimals={false}
          width={46}
        />
        <Tooltip content={<ChartTooltip showTotal />} />
        <Legend
          iconType="circle"
          iconSize={8}
          wrapperStyle={{ fontSize: 12, paddingTop: 8, color: '#587055' }}
        />

        <Area
          type="monotone"
          dataKey="healthy"
          name="Healthy"
          stackId="scans"
          stroke="#16a34a"
          strokeWidth={2}
          fill="url(#activityHealthy)"
        />
        <Area
          type="monotone"
          dataKey="diseased"
          name="Diseased"
          stackId="scans"
          stroke="#dc2626"
          strokeWidth={2}
          fill="url(#activityDiseased)"
        />
        <Area
          type="monotone"
          dataKey="inconclusive"
          name="Inconclusive"
          stackId="scans"
          stroke="#f59e0b"
          strokeWidth={2}
          fill="url(#activityInconclusive)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export default ActivityChart;
