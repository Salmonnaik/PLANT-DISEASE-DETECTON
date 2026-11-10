import { useState } from 'react';
import {
  AlertTriangle,
  Ban,
  Beaker,
  Bug,
  CalendarDays,
  CheckCircle2,
  Droplets,
  Eye,
  FlaskConical,
  Info,
  Leaf,
  Microscope,
  Shield,
  ShieldAlert,
  Sparkles,
  Sprout,
  Stethoscope,
  Thermometer,
  TrendingUp,
} from 'lucide-react';
import type {
  ConditionCandidate,
  DetectionResponse,
  UniversalAnalysis,
} from '@/services/types';
import { Card, CardBody, CardHeader, Notice } from '@/components/ui';
import { classNames, formatDateTime } from '@/utils/format';
import { ConfidenceRing } from './ConfidenceRing';

/* ------------------------------------------------------------------ */
/* Maps                                                                */
/* ------------------------------------------------------------------ */

const CAUSE_ICONS: Record<string, typeof Bug> = {
  fungal: Microscope,
  bacterial: Microscope,
  viral: ShieldAlert,
  nutrient: Sprout,
  water: Droplets,
  environmental: Thermometer,
  pest: Bug,
  physiological: Leaf,
};

const SEVERITY_PILL: Record<string, string> = {
  none: 'badge-healthy',
  mild: 'badge-healthy',
  moderate: 'badge-uncertain',
  severe: 'badge-diseased',
  unknown: 'badge-neutral',
};

const SUPPORT_PILL: Record<string, string> = {
  strong: 'badge-healthy',
  moderate: 'badge-uncertain',
  weak: 'badge-neutral',
};

/* ------------------------------------------------------------------ */
/* Small pieces                                                        */
/* ------------------------------------------------------------------ */

function TickList({ items, tone = 'leaf' }: { items: string[]; tone?: 'leaf' | 'amber' | 'red' | 'sky' }) {
  const colour = {
    leaf: 'text-leaf-600',
    amber: 'text-harvest-600',
    red: 'text-blight-600',
    sky: 'text-sky-600',
  }[tone];

  if (!items.length) {
    return <p className="text-sm italic text-bark-400">None recorded.</p>;
  }

  return (
    <ul className="space-y-1.5">
      {items.map((item) => (
        <li key={item} className="flex gap-2 text-sm leading-relaxed text-bark-600">
          <CheckCircle2 className={classNames('mt-0.5 h-3.5 w-3.5 shrink-0', colour)} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function DotList({ items }: { items: string[] }) {
  if (!items.length) return <p className="text-sm italic text-bark-400">None recorded.</p>;
  return (
    <ul className="space-y-1.5">
      {items.map((item) => (
        <li key={item} className="flex gap-2 text-sm leading-relaxed text-bark-600">
          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-bark-400" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function CandidateRow({ candidate }: { candidate: ConditionCandidate }) {
  const [open, setOpen] = useState(false);
  const Icon = CAUSE_ICONS[candidate.category] ?? Microscope;

  return (
    <div className="rounded-xl border border-bark-100">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left"
      >
        <Icon className="h-4 w-4 shrink-0 text-bark-500" />
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-bark-800">
          {candidate.label}
        </span>
        <span className={SUPPORT_PILL[candidate.support] ?? 'badge-neutral'}>
          {candidate.support}
        </span>
      </button>

      {open && (
        <div className="space-y-2.5 border-t border-bark-100 px-3.5 py-3">
          {candidate.matched_evidence.length > 0 && (
            <div>
              <p className="text-2xs font-bold uppercase tracking-wider text-leaf-700">
                Evidence for
              </p>
              <DotList items={candidate.matched_evidence} />
            </div>
          )}
          {candidate.conflicting_evidence.length > 0 && (
            <div>
              <p className="text-2xs font-bold uppercase tracking-wider text-harvest-700">
                Evidence against
              </p>
              <DotList items={candidate.conflicting_evidence} />
            </div>
          )}
          {candidate.confirm_by.length > 0 && (
            <div className="rounded-lg bg-sky-50 px-3 py-2">
              <p className="inline-flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-sky-800">
                <Eye className="h-3 w-3" />
                What to check next
              </p>
              <DotList items={candidate.confirm_by} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main                                                                */
/* ------------------------------------------------------------------ */

interface DiagnosisDashboardProps {
  result: DetectionResponse;
  analysis: UniversalAnalysis;
}

/**
 * The diagnosis result dashboard.
 *
 * Section order follows what an operator needs: what plant, what might be
 * wrong and how sure, why, what to do, how to prevent it. The "how sure" part
 * is never a decoration - the confidence ring shows a real classifier
 * probability when one exists and a named qualitative level when it does not,
 * and the two are visually distinguishable.
 */
export function DiagnosisDashboard({ result, analysis }: DiagnosisDashboardProps) {
  const { plant, condition, symptoms, severity, causes, treatment, care } = analysis;
  const [treatmentTab, setTreatmentTab] = useState<'organic' | 'chemical'>('organic');

  const isHealthy = analysis.assessment === 'healthy';
  // Only a genuinely trained, applied classifier contributes a numeric value.
  const classifierPercent =
    result.prediction?.is_validated_prediction && analysis.evidence_sources.classifier.used
      ? result.prediction.confidence
      : null;
  const vision = analysis.evidence_sources.ai_vision;

  return (
    <div className="space-y-4">
      {/* ===== Analysis result header ===== */}
      <Card className="overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-bark-100 bg-leaf-50 px-5 py-2.5">
          <h2 className="inline-flex items-center gap-2 text-sm font-bold text-leaf-900">
            <Stethoscope className="h-4 w-4" />
            Analysis Result
          </h2>
          <p className="inline-flex items-center gap-1.5 text-xs text-bark-500">
            <CalendarDays className="h-3.5 w-3.5" />
            {formatDateTime(result.detection?.created_at ?? new Date().toISOString())}
          </p>
        </div>

        {/* ---- three-up summary ---- */}
        <div className="grid divide-bark-100 sm:grid-cols-3 sm:divide-x">
          <div className="flex items-center gap-3 px-5 py-4">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-leaf-100 text-leaf-700">
              <Leaf className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <p className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                Plant identified
              </p>
              <p className="truncate text-lg font-bold text-bark-900">{plant.name}</p>
              <p className="truncate text-2xs text-bark-400">
                {plant.identified
                  ? `${plant.category} - via ${String(plant.identification_source).replace(/_/g, ' ')}`
                  : 'Select the species for specific advice'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 px-5 py-4">
            <span
              className={classNames(
                'flex h-11 w-11 shrink-0 items-center justify-center rounded-xl',
                isHealthy ? 'bg-leaf-100 text-leaf-700' : 'bg-blight-100 text-blight-700',
              )}
            >
              {isHealthy ? <CheckCircle2 className="h-5 w-5" /> : <Leaf className="h-5 w-5" />}
            </span>
            <div className="min-w-0">
              <p className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                {isHealthy ? 'Assessment' : 'Possible condition'}
              </p>
              <p
                className={classNames(
                  'truncate text-lg font-bold',
                  isHealthy ? 'text-leaf-700' : 'text-blight-700',
                )}
                title={condition.label}
              >
                {condition.label}
              </p>
              <p className="truncate text-2xs text-bark-400">
                {condition.candidates.length > 1
                  ? `${condition.candidates.length} possibilities shortlisted`
                  : 'Shortlisted from measured symptoms'}
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between gap-3 px-5 py-4">
            <ConfidenceRing level={analysis.confidence_level} percent={classifierPercent} />
            <div className="flex flex-col items-end gap-1.5">
              <span className={isHealthy ? 'badge-healthy' : 'badge-diseased'}>
                {isHealthy ? 'Healthy' : 'Diseased'}
              </span>
              <span className={SEVERITY_PILL[severity.level] ?? 'badge-neutral'}>
                {severity.label}
              </span>
            </div>
          </div>
        </div>

        {/* ---- honesty strip ---- */}
        <div className="flex flex-wrap items-center gap-2 border-t border-bark-100 bg-bark-50 px-5 py-2.5">
          <span className="badge-neutral">
            <Ban className="h-3.5 w-3.5" />
            Not a confirmed diagnosis
          </span>
          <p className="min-w-0 flex-1 text-xs leading-relaxed text-bark-500">{analysis.basis}</p>
        </div>
      </Card>

      {/* ===== Disease info / symptoms / causes ===== */}
      <div className="grid gap-4 lg:grid-cols-3">
        {/* Disease information */}
        <Card>
          <CardHeader
            title="Disease Information"
            icon={<Info className="h-4 w-4" />}
            subtitle={severity.label !== 'Unknown' ? `Severity: ${severity.label}` : undefined}
          />
          <CardBody className="space-y-3">
            {condition.description ? (
              <p className="text-sm leading-relaxed text-bark-600">{condition.description}</p>
            ) : (
              <p className="text-sm italic text-bark-400">
                No reference description is available for this outcome.
              </p>
            )}

            {severity.basis && (
              <div className="rounded-xl bg-bark-50 px-3.5 py-2.5">
                <p className="inline-flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-bark-500">
                  <TrendingUp className="h-3 w-3" />
                  Severity estimate
                </p>
                <p className="mt-1 text-xs leading-relaxed text-bark-600">{severity.basis}</p>
              </div>
            )}

            {condition.references.length > 0 && (
              <div>
                <p className="label mb-1">Reference sources</p>
                <ul className="space-y-1">
                  {condition.references.map((item) => (
                    <li key={item} className="text-2xs leading-snug text-bark-400">
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardBody>
        </Card>

        {/* Detected symptoms */}
        <Card>
          <CardHeader
            title="Detected Symptoms"
            icon={<Sprout className="h-4 w-4" />}
            subtitle="Measured from this image"
          />
          <CardBody className="space-y-3">
            {symptoms.detected.length === 0 ? (
              <Notice tone="success" icon={<CheckCircle2 className="h-4 w-4" />}>
                No symptoms exceeded the reporting threshold. This covers the visible leaf
                surface only.
              </Notice>
            ) : (
              <ul className="space-y-2">
                {symptoms.detected.map((symptom) => (
                  <li key={symptom.id} className="flex gap-2">
                    <CheckCircle2
                      className={classNames(
                        'mt-0.5 h-3.5 w-3.5 shrink-0',
                        symptom.severity === 'severe'
                          ? 'text-blight-600'
                          : symptom.severity === 'moderate'
                            ? 'text-harvest-600'
                            : 'text-leaf-600',
                      )}
                    />
                    <span className="min-w-0">
                      <span className="text-sm font-medium text-bark-800">{symptom.label}</span>
                      {/* The measurement, so it can be checked against the image. */}
                      <span className="block text-2xs leading-snug text-bark-400">
                        {symptom.evidence}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {vision.available && (vision.observed_symptoms?.length ?? 0) > 0 && (
              <div className="rounded-xl bg-sky-50 px-3.5 py-2.5">
                <p className="inline-flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-sky-800">
                  <Sparkles className="h-3 w-3" />
                  AI vision reading
                </p>
                <DotList items={vision.observed_symptoms ?? []} />
              </div>
            )}

            <p className="text-2xs leading-snug text-bark-400">
              Evidence level: {symptoms.evidence_level}. Leaf segmentation:{' '}
              {symptoms.segmentation_quality}. Damage measured on{' '}
              {severity.damage_percent}% of the leaf.
            </p>
          </CardBody>
        </Card>

        {/* Possible causes */}
        <Card>
          <CardHeader
            title="Possible Causes"
            icon={<AlertTriangle className="h-4 w-4" />}
            subtitle="Only those the evidence supports"
          />
          <CardBody className="space-y-3">
            {causes.categories.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {causes.categories.map((category) => {
                  const Icon = CAUSE_ICONS[category.id] ?? Bug;
                  return (
                    <span key={category.id} className="chip" title={category.reasons.join(', ')}>
                      <Icon className="h-3 w-3" />
                      {category.label}
                    </span>
                  );
                })}
              </div>
            )}

            {causes.detailed.length > 0 ? (
              <DotList items={causes.detailed} />
            ) : (
              <p className="text-sm italic text-bark-400">
                No specific causes could be attributed from this image.
              </p>
            )}

            <p className="text-2xs leading-snug text-bark-400">{causes.note}</p>
          </CardBody>
        </Card>
      </div>

      {/* ===== Shortlist ===== */}
      {condition.candidates.length > 0 && (
        <Card>
          <CardHeader
            title="Conditions consistent with the evidence"
            subtitle="Ranked by fit. Expand any row for the evidence for and against it."
            icon={<Microscope className="h-4 w-4" />}
          />
          <CardBody className="space-y-2">
            {condition.candidates.map((candidate) => (
              <CandidateRow key={candidate.id} candidate={candidate} />
            ))}
          </CardBody>
        </Card>
      )}

      {/* ===== Treatment + Prevention ===== */}
      <div className="grid gap-4 lg:grid-cols-5">
        {/* Treatment */}
        <Card className="lg:col-span-3">
          <CardHeader
            title="Treatment & Recommended Medicines"
            icon={<Beaker className="h-4 w-4" />}
            subtitle={
              plant.in_knowledge_base
                ? `Matched to ${plant.name}`
                : 'General guidance - identify the plant for specific advice'
            }
          />
          <CardBody className="space-y-4">
            {/* tabs */}
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setTreatmentTab('organic')}
                className={classNames(
                  'inline-flex items-center justify-center gap-2 rounded-xl border-2 px-3 py-2.5 text-sm font-semibold transition-colors',
                  treatmentTab === 'organic'
                    ? 'border-leaf-400 bg-leaf-50 text-leaf-800'
                    : 'border-bark-200 bg-white text-bark-500 hover:border-leaf-300',
                )}
              >
                <Sprout className="h-4 w-4" />
                Organic (eco-friendly)
              </button>
              <button
                type="button"
                onClick={() => setTreatmentTab('chemical')}
                className={classNames(
                  'inline-flex items-center justify-center gap-2 rounded-xl border-2 px-3 py-2.5 text-sm font-semibold transition-colors',
                  treatmentTab === 'chemical'
                    ? 'border-blight-300 bg-blight-50 text-blight-800'
                    : 'border-bark-200 bg-white text-bark-500 hover:border-blight-200',
                )}
              >
                <Beaker className="h-4 w-4" />
                Chemical (fungicide)
              </button>
            </div>

            {treatmentTab === 'organic' ? (
              <div className="space-y-3">
                {treatment.immediate_actions.length > 0 && (
                  <div>
                    <p className="label">Immediate actions</p>
                    <TickList items={treatment.immediate_actions} tone="amber" />
                  </div>
                )}
                <div>
                  <p className="label">Organic management</p>
                  <TickList items={treatment.organic_options} tone="leaf" />
                </div>
                {treatment.cultural_controls.length > 0 && (
                  <div>
                    <p className="label">Cultural and agricultural controls</p>
                    <TickList items={treatment.cultural_controls} tone="sky" />
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                {treatment.chemical_withheld ? (
                  <Notice
                    tone="warning"
                    icon={<AlertTriangle className="h-4 w-4" />}
                    title="Chemical treatment is not recommended yet"
                  >
                    {treatment.withheld_reason}
                  </Notice>
                ) : treatment.chemical_options ? (
                  <>
                    <p className="text-sm leading-relaxed text-bark-600">
                      Use fungicides with these active ingredients, following local
                      agricultural guidelines:
                    </p>
                    <ul className="space-y-1.5">
                      {treatment.chemical_options.active_ingredient_classes.map((item) => (
                        <li
                          key={item}
                          className="flex items-center gap-2 rounded-lg border border-blight-100 bg-blight-50 px-3 py-2 text-sm font-medium text-blight-900"
                        >
                          <Beaker className="h-3.5 w-3.5 shrink-0 text-blight-600" />
                          {item}
                        </li>
                      ))}
                    </ul>

                    {treatment.chemical_options.precautions && (
                      <div>
                        <p className="label">Precautions</p>
                        <TickList items={treatment.chemical_options.precautions} tone="red" />
                      </div>
                    )}

                    <Notice tone="warning" icon={<AlertTriangle className="h-4 w-4" />}>
                      {treatment.chemical_disclaimer}
                    </Notice>
                  </>
                ) : (
                  <Notice tone="info" icon={<Info className="h-4 w-4" />}>
                    No chemical treatment applies to this condition. Abiotic problems such as
                    scorch and nutrient deficiency, and viral infections, are not treatable with
                    a fungicide.
                  </Notice>
                )}
              </div>
            )}
          </CardBody>
        </Card>

        {/* Prevention */}
        <Card className="lg:col-span-2">
          <CardHeader
            title="Prevention & Management"
            icon={<Shield className="h-4 w-4" />}
            subtitle="Reduces recurrence and spread"
          />
          <CardBody className="space-y-4">
            <TickList items={treatment.prevention} tone="leaf" />

            {care.prevention.length > 0 && (
              <div>
                <p className="label">Specific to {plant.name}</p>
                <TickList items={care.prevention} tone="leaf" />
              </div>
            )}

            {(care.watering || care.soil) && (
              <div className="space-y-2.5 border-t border-bark-100 pt-3">
                {care.watering && (
                  <div>
                    <p className="inline-flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-bark-500">
                      <Droplets className="h-3 w-3 text-sky-600" />
                      Watering
                    </p>
                    <p className="mt-0.5 text-xs leading-relaxed text-bark-600">{care.watering}</p>
                  </div>
                )}
                {care.soil && (
                  <div>
                    <p className="inline-flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-bark-500">
                      <Sprout className="h-3 w-3 text-amber-700" />
                      Soil
                    </p>
                    <p className="mt-0.5 text-xs leading-relaxed text-bark-600">{care.soil}</p>
                  </div>
                )}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* ===== Next steps + limits ===== */}
      <div className="grid gap-4 lg:grid-cols-2">
        {analysis.next_steps.length > 0 && (
          <Card>
            <CardHeader title="Recommended next steps" icon={<Eye className="h-4 w-4" />} />
            <CardBody>
              <ol className="space-y-2">
                {analysis.next_steps.map((step, index) => (
                  <li key={step} className="flex gap-2.5">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-leaf-600 text-2xs font-bold text-white">
                      {index + 1}
                    </span>
                    <span className="text-sm leading-relaxed text-bark-600">{step}</span>
                  </li>
                ))}
              </ol>
            </CardBody>
          </Card>
        )}

        <Card>
          <CardHeader
            title="What this cannot tell you"
            icon={<FlaskConical className="h-4 w-4" />}
            subtitle="Limits of a single-image assessment"
          />
          <CardBody>
            <DotList items={analysis.limitations} />
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

export default DiagnosisDashboard;
