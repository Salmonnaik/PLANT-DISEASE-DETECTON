import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  BarChart3,
  Brain,
  Gauge,
  Grid3x3,
  PieChart,
  RefreshCw,
  Sprout,
  Target,
  TrendingUp,
} from 'lucide-react';
import { useAnalytics } from '@/hooks';
import {
  ActivityChart,
  ChartCard,
  ConfidenceHistogram,
  ConfusionMatrix,
  DiseaseBarChart,
  DonutChart,
  PerClassMetricsChart,
  PlantDistributionChart,
  TrainingHistoryChart,
} from '@/components/charts';
import {
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Notice,
  Spinner,
  StatCard,
} from '@/components/ui';
import { classNames, formatDateTime, formatFraction, formatPercent } from '@/utils/format';

const WINDOW_OPTIONS = [7, 14, 30, 90];

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const { data, error, isLoading, isRefreshing, refresh } = useAnalytics(days);

  const evaluation = data?.model_evaluation;
  const metrics = evaluation?.metrics;
  const totals = data?.totals;

  if (error && !data) {
    return (
      <Card>
        <ErrorState error={error} onRetry={() => void refresh()} isRetrying={isRefreshing} />
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      {/* ---- Window selector ---- */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1 rounded-xl border border-bark-200 bg-white p-1">
          {WINDOW_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setDays(option)}
              className={classNames(
                'rounded-lg px-3 py-1.5 text-sm font-semibold transition-colors',
                days === option ? 'bg-leaf-600 text-white' : 'text-bark-600 hover:bg-bark-50',
              )}
            >
              {option} days
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          {data && (
            <p className="hidden text-xs text-bark-400 sm:block">
              Generated {formatDateTime(data.generated_at)}
            </p>
          )}
          <button type="button" onClick={() => void refresh()} className="btn-secondary btn-sm" disabled={isRefreshing}>
            {isRefreshing ? <Spinner /> : <RefreshCw className="h-3.5 w-3.5" />}
            Refresh
          </button>
        </div>
      </div>

      {totals?.test_mode_records ? (
        <Notice tone="warning" title="Some records came from an untrained model">
          {totals.test_mode_records} of {totals.total_detections} stored detections were produced in
          test mode and are not valid diagnoses. They are included in the counts below because they
          are real database rows, but they say nothing about disease prevalence.
        </Notice>
      ) : null}

      {/* ---- Detection statistics ---- */}
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total detections"
          value={totals?.total_detections}
          icon={<BarChart3 className="h-5 w-5" />}
          tone="leaf"
          isLoading={isLoading}
        />
        <StatCard
          label="Healthy / diseased"
          value={totals ? `${totals.healthy} / ${totals.diseased}` : undefined}
          icon={<Sprout className="h-5 w-5" />}
          tone="sky"
          isLoading={isLoading}
          animationDelayMs={60}
          footnote={
            totals && totals.total_detections > 0
              ? `${formatPercent((totals.diseased * 100) / totals.total_detections)} diseased`
              : undefined
          }
        />
        <StatCard
          label="Mean confidence"
          value={data ? formatPercent(data.confidence.average_percent) : undefined}
          icon={<Gauge className="h-5 w-5" />}
          tone="harvest"
          isLoading={isLoading}
          animationDelayMs={120}
          footnote={data ? `over ${data.confidence.samples} conclusive results` : undefined}
        />
        <StatCard
          label="Model test accuracy"
          value={metrics ? formatFraction(metrics.accuracy) : 'not evaluated'}
          icon={<Brain className="h-5 w-5" />}
          tone={metrics ? 'leaf' : 'bark'}
          isLoading={isLoading}
          animationDelayMs={180}
          footnote={metrics ? `${metrics.test_samples} held-out test images` : undefined}
          hint={metrics ? undefined : 'Run ml/train.py to generate metrics'}
        />
      </section>

      {/* ---- Distribution charts ---- */}
      <section className="grid gap-4 lg:grid-cols-5">
        <ChartCard
          title="Detection trend"
          subtitle={`Daily scans over the last ${days} days`}
          icon={<TrendingUp className="h-4 w-4" />}
          isLoading={isLoading}
          isEmpty={!data || data.activity.every((point) => point.total === 0)}
          className="lg:col-span-3"
        >
          <ActivityChart data={data?.activity ?? []} />
        </ChartCard>

        <ChartCard
          title="Healthy vs diseased"
          subtitle="Overall outcome split"
          icon={<PieChart className="h-4 w-4" />}
          isLoading={isLoading}
          isEmpty={!data || data.is_empty}
          className="lg:col-span-2"
        >
          <DonutChart
            data={data?.healthy_vs_diseased ?? []}
            centreValue={totals?.total_detections ?? 0}
            centreLabel="scans"
          />
        </ChartCard>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Disease distribution"
          subtitle="Detections per condition"
          icon={<BarChart3 className="h-4 w-4" />}
          isLoading={isLoading}
          isEmpty={!data || data.disease_distribution.length === 0}
          emptyTitle="No diseases detected yet"
        >
          <DiseaseBarChart data={data?.disease_distribution ?? []} />
        </ChartCard>

        <ChartCard
          title="Plant-wise statistics"
          subtitle="Outcome breakdown per crop"
          icon={<Sprout className="h-4 w-4" />}
          isLoading={isLoading}
          isEmpty={!data || data.plant_distribution.length === 0}
        >
          <PlantDistributionChart data={data?.plant_distribution ?? []} />
        </ChartCard>
      </section>

      <section className="grid gap-4 lg:grid-cols-5">
        <ChartCard
          title="Confidence distribution"
          subtitle="How certain the model has been on real scans"
          icon={<Gauge className="h-4 w-4" />}
          isLoading={isLoading}
          isEmpty={!data || data.confidence.samples === 0}
          className="lg:col-span-3"
        >
          <ConfidenceHistogram data={data?.confidence_distribution ?? []} />
        </ChartCard>

        <Card className="lg:col-span-2">
          <CardHeader
            title="Most frequent conditions"
            subtitle="Ranked by number of detections"
            icon={<Activity className="h-4 w-4" />}
          />
          {!data || data.top_conditions.length === 0 ? (
            <EmptyState title="Nothing to rank yet" description="Detected diseases will be listed here." />
          ) : (
            <CardBody className="space-y-2.5">
              {data.top_conditions.map((item, index) => (
                <div key={`${item.plant}-${item.disease}`} className="flex items-center gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-bark-100 text-xs font-bold text-bark-600">
                    {index + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-bark-800">
                      {item.plant} &middot; {item.disease}
                    </p>
                    <p className="text-xs text-bark-400">
                      avg confidence {formatFraction(item.avg_confidence)}
                    </p>
                  </div>
                  <span className="shrink-0 text-sm font-bold tabular-nums text-bark-700">
                    {item.count}
                  </span>
                </div>
              ))}
            </CardBody>
          )}
        </Card>
      </section>

      {/* ---- Model evaluation ---- */}
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-leaf-600" />
          <h2 className="text-lg font-semibold text-bark-900">Model evaluation</h2>
        </div>

        {!evaluation?.available || !metrics ? (
          <Card>
            <EmptyState
              icon={<Brain className="h-7 w-7" />}
              title="No evaluation report yet"
              description={
                <>
                  {evaluation?.reason ??
                    'Train the model to generate accuracy, precision, recall, F1 and the confusion matrix.'}
                  <code className="mt-3 block rounded-lg bg-bark-900 px-3 py-2 text-left font-mono text-xs text-leaf-200">
                    python ml/train.py --dataset-dir ml/dataset
                  </code>
                </>
              }
              action={
                <Link to="/about" className="btn-secondary btn-sm">
                  Read the methodology
                </Link>
              }
            />
          </Card>
        ) : (
          <>
            <Card>
              <CardHeader
                title="Held-out test set performance"
                subtitle={`${metrics.test_samples} images the model never saw during training, evaluated ${formatDateTime(metrics.evaluated_at)}`}
                icon={<Target className="h-4 w-4" />}
              />
              <CardBody>
                <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
                  {[
                    { label: 'Top-1 accuracy', value: formatFraction(metrics.accuracy), highlight: true },
                    { label: 'Top-3 accuracy', value: formatFraction(metrics.top3_accuracy) },
                    {
                      label: 'Healthy vs diseased',
                      value: formatFraction(metrics.healthy_vs_diseased_accuracy),
                    },
                    { label: 'Macro precision', value: metrics.macro.precision.toFixed(4) },
                    { label: 'Macro recall', value: metrics.macro.recall.toFixed(4) },
                    { label: 'Macro F1-score', value: metrics.macro.f1_score.toFixed(4), highlight: true },
                  ].map((item) => (
                    <div
                      key={item.label}
                      className={classNames(
                        'rounded-xl px-3.5 py-3',
                        item.highlight ? 'bg-leaf-50 ring-1 ring-leaf-200' : 'bg-bark-50',
                      )}
                    >
                      <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                        {item.label}
                      </dt>
                      <dd
                        className={classNames(
                          'mt-1 text-xl font-bold tabular-nums',
                          item.highlight ? 'text-leaf-800' : 'text-bark-800',
                        )}
                      >
                        {item.value}
                      </dd>
                    </div>
                  ))}
                </dl>

                <p className="mt-4 text-xs leading-relaxed text-bark-500">
                  Macro averages weight every class equally, so a rare disease the model fails on
                  cannot be hidden by a common class it handles well. Weighted F1 is{' '}
                  {metrics.weighted.f1_score.toFixed(4)}. Mean confidence on correct predictions was{' '}
                  {metrics.confidence.mean_when_correct !== null
                    ? formatFraction(metrics.confidence.mean_when_correct)
                    : 'not recorded'}
                  , against{' '}
                  {metrics.confidence.mean_when_wrong !== null
                    ? formatFraction(metrics.confidence.mean_when_wrong)
                    : 'not recorded'}{' '}
                  on incorrect ones.
                </p>
              </CardBody>
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <ChartCard
                title="Per-class precision, recall and F1"
                subtitle="From ml/reports/metrics.json"
                icon={<BarChart3 className="h-4 w-4" />}
                isEmpty={metrics.per_class.length === 0}
              >
                <PerClassMetricsChart data={metrics.per_class} />
              </ChartCard>

              <div className="space-y-4">
                {evaluation.training_history &&
                  Object.keys(evaluation.training_history).length > 0 && (
                    <ChartCard
                      title="Training history"
                      subtitle="Accuracy per epoch across both transfer-learning stages"
                      icon={<TrendingUp className="h-4 w-4" />}
                    >
                      <TrainingHistoryChart history={evaluation.training_history} />
                    </ChartCard>
                  )}

                <Card>
                  <CardHeader
                    title="Confusion matrix"
                    subtitle="Row-normalised, true class by predicted class"
                    icon={<Grid3x3 className="h-4 w-4" />}
                  />
                  <CardBody>
                    <ConfusionMatrix
                      matrix={metrics.confusion_matrix}
                      classNames_={metrics.class_names}
                    />
                  </CardBody>
                </Card>
              </div>
            </div>

            <Card>
              <CardHeader title="Per-class detail" subtitle="Support is the number of test images per class" />
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-bark-100 bg-bark-50 text-left">
                      {['Class', 'Plant', 'Condition', 'Precision', 'Recall', 'F1-score', 'Support'].map(
                        (heading) => (
                          <th
                            key={heading}
                            className="px-4 py-2.5 text-2xs font-bold uppercase tracking-wider text-bark-500"
                          >
                            {heading}
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-bark-50">
                    {metrics.per_class.map((item) => (
                      <tr key={item.class}>
                        <td className="px-4 py-2 font-mono text-xs text-bark-500">{item.class}</td>
                        <td className="px-4 py-2 font-medium text-bark-800">{item.plant}</td>
                        <td className="px-4 py-2 text-bark-600">{item.disease}</td>
                        <td className="px-4 py-2 tabular-nums text-bark-700">
                          {item.precision.toFixed(4)}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-bark-700">{item.recall.toFixed(4)}</td>
                        <td
                          className={classNames(
                            'px-4 py-2 font-semibold tabular-nums',
                            item.f1_score >= 0.9
                              ? 'text-leaf-700'
                              : item.f1_score >= 0.75
                                ? 'text-bark-700'
                                : 'text-blight-600',
                          )}
                        >
                          {item.f1_score.toFixed(4)}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-bark-500">{item.support}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}
      </section>
    </div>
  );
}
