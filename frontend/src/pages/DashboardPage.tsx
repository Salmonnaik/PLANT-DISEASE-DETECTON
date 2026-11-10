import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  Camera,
  Cpu,
  Gauge,
  Leaf,
  PieChart,
  ScanLine,
  ShieldAlert,
  Signal,
  Sprout,
} from 'lucide-react';
import { useStats } from '@/hooks';
import { useSystemStatus } from '@/layouts/SystemStatusProvider';
import { ActivityChart, ChartCard, DonutChart } from '@/components/charts';
import { DetectionListItem } from '@/components/detection/DetectionListItem';
import { DetectionDetailModal } from '@/components/detection/DetectionDetailModal';
import {
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  LiveDot,
  StatCard,
  TableSkeleton,
} from '@/components/ui';
import type { DetectionRecord } from '@/services/types';
import { formatFraction, formatPercent, formatRelative } from '@/utils/format';
import { signalMeta } from '@/utils/status';

export default function DashboardPage() {
  const { data: stats, error, isLoading, refresh } = useStats(14, 6);
  const { health, isDeviceOnline } = useSystemStatus();
  const [selected, setSelected] = useState<DetectionRecord | null>(null);

  const device = health?.device.primary ?? null;
  const totals = stats?.totals;
  const signal = signalMeta(device?.wifi_signal_quality);

  if (error && !stats) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refresh()} />
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      {/* ---- Headline statistics ---- */}
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total plant scans"
          value={totals?.total_detections}
          icon={<ScanLine className="h-5 w-5" />}
          tone="leaf"
          isLoading={isLoading}
          footnote={
            totals ? `${totals.today} today` : undefined
          }
          hint={
            stats?.last_detection_at
              ? `Last scan ${formatRelative(stats.last_detection_at)}`
              : 'No scans recorded yet'
          }
        />
        <StatCard
          label="Healthy leaves"
          value={totals?.healthy}
          icon={<Sprout className="h-5 w-5" />}
          tone="leaf"
          isLoading={isLoading}
          animationDelayMs={60}
          footnote={stats ? `${formatPercent(stats.rates.healthy_percent)} of all scans` : undefined}
        />
        <StatCard
          label="Diseased leaves"
          value={totals?.diseased}
          icon={<ShieldAlert className="h-5 w-5" />}
          tone="blight"
          isLoading={isLoading}
          animationDelayMs={120}
          footnote={stats ? `${formatPercent(stats.rates.diseased_percent)} of all scans` : undefined}
        />
        <StatCard
          label="Inconclusive"
          value={totals?.inconclusive}
          icon={<Gauge className="h-5 w-5" />}
          tone="harvest"
          isLoading={isLoading}
          animationDelayMs={180}
          footnote={
            totals ? `${totals.uncertain} low confidence, ${totals.unknown} unusable` : undefined
          }
          hint="Reported as uncertain rather than guessed"
        />
      </section>

      {/* ---- Device + quick actions ---- */}
      <section className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="ESP32-CAM status"
            subtitle="Live connection state reported by the camera's heartbeat"
            icon={<Cpu className="h-4 w-4" />}
            actions={
              <Link to="/device" className="btn-ghost btn-sm">
                Manage
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            }
          />
          <CardBody>
            <div className="grid gap-4 sm:grid-cols-4">
              <div>
                <p className="label">Connection</p>
                <LiveDot online={isDeviceOnline} label={isDeviceOnline ? 'Online' : 'Offline'} />
              </div>
              <div>
                <p className="label">IP address</p>
                <p className="font-mono text-sm text-bark-700">
                  {device?.ip_address ?? 'not registered'}
                </p>
              </div>
              <div>
                <p className="label">Wi-Fi signal</p>
                <p className={`inline-flex items-center gap-1.5 text-sm font-medium ${signal.textClass}`}>
                  <Signal className="h-4 w-4" />
                  {device?.wifi_rssi !== null && device?.wifi_rssi !== undefined
                    ? `${signal.label} (${device.wifi_rssi} dBm)`
                    : signal.label}
                </p>
              </div>
              <div>
                <p className="label">Last capture</p>
                <p className="text-sm text-bark-700">{formatRelative(device?.last_capture_at)}</p>
              </div>
            </div>

            {!isDeviceOnline && (
              <p className="mt-4 rounded-xl bg-harvest-50 px-3.5 py-2.5 text-sm text-harvest-700">
                No heartbeat from the camera. You can still analyse images by uploading them from
                this computer - open{' '}
                <Link to="/detect" className="link">
                  Disease Detection
                </Link>
                .
              </p>
            )}
          </CardBody>
        </Card>

        <Card className="bg-leaf-gradient text-white">
          <div className="p-5">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/15">
              <Camera className="h-5 w-5" />
            </span>
            <h3 className="mt-4 text-lg font-semibold text-white">Run a new scan</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-leaf-50/85">
              Trigger the ESP32-CAM with the white LED, or upload a leaf photograph from this device.
            </p>
            <Link
              to="/detect"
              className="btn mt-5 w-full bg-white text-leaf-800 hover:bg-leaf-50"
            >
              <ScanLine className="h-4 w-4" />
              Open detection
            </Link>
          </div>
        </Card>
      </section>

      {/* ---- Charts ---- */}
      <section className="grid gap-4 lg:grid-cols-5">
        <ChartCard
          title="Detection activity"
          subtitle="Scans per day, stacked by outcome"
          icon={<Activity className="h-4 w-4" />}
          isLoading={isLoading}
          isEmpty={!stats || stats.activity.every((point) => point.total === 0)}
          emptyTitle="No scans in the last 14 days"
          emptyDescription="Run a detection and this chart will populate from the database."
          className="lg:col-span-3"
        >
          <ActivityChart data={stats?.activity ?? []} />
        </ChartCard>

        <ChartCard
          title="Disease distribution"
          subtitle="Share of each detected condition"
          icon={<PieChart className="h-4 w-4" />}
          isLoading={isLoading}
          isEmpty={!stats || stats.disease_distribution.length === 0}
          emptyTitle="No diseases detected yet"
          emptyDescription="Only scans classified as diseased appear here."
          className="lg:col-span-2"
        >
          <DonutChart
            data={stats?.disease_distribution ?? []}
            centreValue={totals?.diseased ?? 0}
            centreLabel="diseased"
          />
        </ChartCard>
      </section>

      {/* ---- Recent detections + plant summary ---- */}
      <section className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader
            title="Recent detections"
            subtitle="Newest scans from the database"
            icon={<Leaf className="h-4 w-4" />}
            actions={
              <Link to="/history" className="btn-ghost btn-sm">
                View all
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            }
          />
          {isLoading ? (
            <TableSkeleton rows={4} />
          ) : !stats || stats.recent_detections.length === 0 ? (
            <EmptyState
              icon={<ScanLine className="h-7 w-7" />}
              title="No detections yet"
              description="Capture an image with the ESP32-CAM or upload one to create the first record."
              action={
                <Link to="/detect" className="btn-primary btn-sm">
                  Run first scan
                </Link>
              }
            />
          ) : (
            <CardBody className="space-y-1 p-3">
              {stats.recent_detections.map((record) => (
                <DetectionListItem
                  key={record.id}
                  record={record}
                  compact
                  onClick={setSelected}
                />
              ))}
            </CardBody>
          )}
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader
            title="By plant"
            subtitle="Outcome split per crop"
            icon={<Sprout className="h-4 w-4" />}
          />
          {isLoading ? (
            <TableSkeleton rows={3} />
          ) : !stats || stats.plant_distribution.length === 0 ? (
            <EmptyState title="No plant data yet" description="Scan a leaf to populate this summary." />
          ) : (
            <CardBody className="space-y-4">
              {stats.plant_distribution.map((plant) => {
                const total = Math.max(1, plant.total);
                return (
                  <div key={plant.plant}>
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="text-sm font-semibold text-bark-800">{plant.plant}</p>
                      <p className="text-sm tabular-nums text-bark-500">{plant.total} scans</p>
                    </div>
                    <div className="mt-1.5 flex h-2 overflow-hidden rounded-full bg-bark-100">
                      <div
                        className="h-full bg-leaf-500"
                        style={{ width: `${(plant.healthy / total) * 100}%` }}
                        title={`${plant.healthy} healthy`}
                      />
                      <div
                        className="h-full bg-blight-500"
                        style={{ width: `${(plant.diseased / total) * 100}%` }}
                        title={`${plant.diseased} diseased`}
                      />
                      <div
                        className="h-full bg-harvest-500"
                        style={{ width: `${(plant.inconclusive / total) * 100}%` }}
                        title={`${plant.inconclusive} inconclusive`}
                      />
                    </div>
                    <p className="mt-1 text-xs text-bark-400">
                      {plant.healthy} healthy &middot; {plant.diseased} diseased &middot;{' '}
                      {plant.inconclusive} inconclusive &middot; avg confidence{' '}
                      {formatFraction(plant.avg_confidence)}
                    </p>
                  </div>
                );
              })}
            </CardBody>
          )}
        </Card>
      </section>

      <DetectionDetailModal record={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
