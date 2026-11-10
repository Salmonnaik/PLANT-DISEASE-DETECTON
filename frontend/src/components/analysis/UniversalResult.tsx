import {
  Activity,
  AlertTriangle,
  Ban,
  Beaker,
  Bug,
  CheckCircle2,
  Droplets,
  Eye,
  FlaskConical,
  Image as ImageIcon,
  Info,
  Leaf,
  Lightbulb,
  ListChecks,
  Microscope,
  Mountain,
  ScrollText,
  Shield,
  ShieldAlert,
  Sparkles,
  Sprout,
  Sun,
  Thermometer,
} from 'lucide-react';
import type {
  ConditionCandidate,
  ConfidenceLevel,
  DetectedSymptom,
  DetectionResponse,
  SupportLevel,
  UniversalAnalysis,
} from '@/services/types';
import { imageUrl } from '@/services/api';
import { Card, CardBody, CardHeader, Notice } from '@/components/ui';
import { CameraSourceBadge } from '@/components/camera/CameraSourceBadge';
import { classNames, formatBytes } from '@/utils/format';

/* ------------------------------------------------------------------ */
/* Presentation maps                                                   */
/* ------------------------------------------------------------------ */

const CONFIDENCE_META: Record<
  ConfidenceLevel,
  { label: string; badge: string; bar: string; width: string; explanation: string }
> = {
  confident: {
    label: 'Confident',
    badge: 'badge-healthy',
    bar: 'bg-leaf-500',
    width: '100%',
    explanation:
      'The trained classifier recognised this plant and condition and was confident, and the measured symptoms agree.',
  },
  probable: {
    label: 'Probable',
    badge: 'badge-healthy',
    bar: 'bg-leaf-400',
    width: '72%',
    explanation:
      'The measured symptoms match this condition well, but a photograph alone cannot confirm the cause.',
  },
  possible: {
    label: 'Possible',
    badge: 'badge-uncertain',
    bar: 'bg-harvest-500',
    width: '45%',
    explanation:
      'Symptoms are present but several conditions would produce them. Treat this as a shortlist to investigate.',
  },
  insufficient: {
    label: 'Not enough evidence',
    badge: 'badge-neutral',
    bar: 'bg-bark-300',
    width: '18%',
    explanation:
      'The image does not carry enough information to narrow the cause down. Re-photograph the leaf and follow the checks below.',
  },
};

const SUPPORT_META: Record<SupportLevel, { label: string; className: string }> = {
  strong: { label: 'strong match', className: 'badge-healthy' },
  moderate: { label: 'moderate match', className: 'badge-uncertain' },
  weak: { label: 'weak match', className: 'badge-neutral' },
};

const CATEGORY_ICONS: Record<string, typeof Bug> = {
  fungal: Microscope,
  bacterial: Microscope,
  viral: ShieldAlert,
  pest: Bug,
  abiotic: Thermometer,
  none: CheckCircle2,
};

const SEVERITY_CLASS: Record<DetectedSymptom['severity'], string> = {
  mild: 'border-l-harvest-300 bg-harvest-50/60',
  moderate: 'border-l-harvest-500 bg-harvest-50',
  severe: 'border-l-blight-500 bg-blight-50',
};

/* ------------------------------------------------------------------ */
/* Sub-sections                                                        */
/* ------------------------------------------------------------------ */

function Bullets({ items, dot = 'bg-leaf-500' }: { items: string[]; dot?: string }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1.5">
      {items.map((item) => (
        <li key={item} className="flex gap-2 text-sm leading-relaxed text-bark-600">
          <span className={classNames('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full', dot)} />
          {item}
        </li>
      ))}
    </ul>
  );
}

function CandidateCard({ candidate, rank }: { candidate: ConditionCandidate; rank: number }) {
  const Icon = CATEGORY_ICONS[candidate.category] ?? Microscope;
  const support = SUPPORT_META[candidate.support];

  return (
    <div
      className={classNames(
        'rounded-xl border p-4',
        rank === 0 ? 'border-leaf-300 bg-leaf-50/40' : 'border-bark-100',
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-bark-600 shadow-card">
            <Icon className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-bark-900">{candidate.label}</p>
            <p className="mt-0.5 text-xs capitalize text-bark-500">
              {candidate.category === 'none' ? 'no pathogen' : candidate.category}
              {!candidate.is_disease && candidate.category !== 'none' && ' - not an infection'}
            </p>
          </div>
        </div>
        <span className={support.className}>{support.label}</span>
      </div>

      {candidate.matched_evidence.length > 0 && (
        <div className="mt-3">
          <p className="text-2xs font-bold uppercase tracking-wider text-leaf-700">
            Evidence in this image
          </p>
          <Bullets items={candidate.matched_evidence} dot="bg-leaf-500" />
        </div>
      )}

      {candidate.conflicting_evidence.length > 0 && (
        <div className="mt-2.5">
          <p className="text-2xs font-bold uppercase tracking-wider text-harvest-700">
            Evidence against
          </p>
          <Bullets items={candidate.conflicting_evidence} dot="bg-harvest-500" />
        </div>
      )}

      {candidate.possible_causes.length > 0 && (
        <div className="mt-2.5">
          <p className="text-2xs font-bold uppercase tracking-wider text-bark-500">
            Possible causes
          </p>
          <Bullets items={candidate.possible_causes} dot="bg-bark-400" />
        </div>
      )}

      {candidate.confirm_by.length > 0 && (
        <div className="mt-2.5 rounded-lg bg-white px-3 py-2.5">
          <p className="inline-flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-sky-700">
            <Eye className="h-3 w-3" />
            What to check next
          </p>
          <Bullets items={candidate.confirm_by} dot="bg-sky-400" />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */

interface UniversalResultProps {
  result: DetectionResponse;
  analysis: UniversalAnalysis;
  localPreviewUrl?: string | null;
}

/**
 * The universal analysis result.
 *
 * Laid out in the order an operator needs it: what plant, what might be wrong
 * and how sure, what to do, then the supporting evidence and the limits of the
 * answer. The limits are not a footnote - they are a titled section, because a
 * shortlist presented as a diagnosis is the main way a tool like this causes
 * harm.
 */
export function UniversalResult({ result, analysis, localPreviewUrl }: UniversalResultProps) {
  const { plant, condition, symptoms, treatment, care } = analysis;
  const confidence = CONFIDENCE_META[analysis.confidence_level] ?? CONFIDENCE_META.insufficient;
  const preview = imageUrl(result.image.url) ?? localPreviewUrl ?? undefined;
  const isHealthy = analysis.assessment === 'healthy';
  const vision = analysis.evidence_sources.ai_vision;

  return (
    <div className="space-y-4">
      {/* ================= 1. PLANT IDENTIFICATION ================= */}
      <Card className="overflow-hidden">
        <CardHeader
          title="Plant identification"
          subtitle="What was analysed"
          icon={<Leaf className="h-4 w-4" />}
          actions={<CameraSourceBadge source={result.camera_source} short />}
        />
        <CardBody className="grid gap-5 sm:grid-cols-[minmax(0,14rem)_1fr]">
          <div className="overflow-hidden rounded-xl border border-bark-100 bg-bark-900">
            {preview ? (
              <img
                src={preview}
                alt={`Analysed leaf: ${plant.name}`}
                className="h-48 w-full object-cover"
              />
            ) : (
              <div className="flex h-48 items-center justify-center text-bark-500">
                <ImageIcon className="h-8 w-8" />
              </div>
            )}
          </div>

          <div>
            <h2 className="text-2xl font-bold tracking-tight text-bark-900">{plant.name}</h2>
            {plant.scientific_name && (
              <p className="mt-0.5 text-sm italic text-bark-500">{plant.scientific_name}</p>
            )}

            <dl className="mt-4 grid grid-cols-2 gap-x-5 gap-y-3 text-sm">
              <div>
                <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                  Category
                </dt>
                <dd className="mt-0.5 font-medium text-bark-700">{plant.category}</dd>
              </div>
              <div>
                <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                  Identified by
                </dt>
                <dd className="mt-0.5 font-medium text-bark-700">
                  {plant.identification_source === 'user_declared' && 'Your selection'}
                  {plant.identification_source === 'ai_vision_api' && 'AI vision model'}
                  {plant.identification_source === 'trained_classifier' && 'Trained classifier'}
                  {plant.identification_source === 'unidentified' && 'Not identified'}
                </dd>
              </div>
              <div>
                <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                  Image
                </dt>
                <dd className="mt-0.5 font-medium text-bark-700">
                  {result.image.width}&times;{result.image.height} &middot;{' '}
                  {formatBytes(result.image.size_bytes)}
                </dd>
              </div>
              <div>
                <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                  Care profile
                </dt>
                <dd className="mt-0.5 font-medium text-bark-700">
                  {plant.in_knowledge_base ? 'Species-specific' : 'General guidance'}
                </dd>
              </div>
            </dl>

            {!plant.identified && (
              <Notice tone="info" className="mt-4" icon={<Info className="h-4 w-4" />}>
                The plant species was not identified. Select it above and re-analyse to get
                species-specific care and prevention advice.
              </Notice>
            )}

            {plant.common_issues.length > 0 && (
              <div className="mt-4">
                <p className="label mb-1.5">Conditions commonly seen on this plant</p>
                <div className="flex flex-wrap gap-1.5">
                  {plant.common_issues.map((issue) => (
                    <span key={issue} className="chip capitalize">
                      {issue.replace(/_/g, ' ')}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      {/* ================= 2. DISEASE ANALYSIS ================= */}
      <Card className={classNames('overflow-hidden border-2', isHealthy ? 'border-leaf-200' : 'border-harvest-200')}>
        <div className={classNames('px-5 py-4', isHealthy ? 'bg-leaf-50' : 'bg-harvest-50')}>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className={confidence.badge}>{confidence.label}</span>
                {!analysis.is_confirmed_diagnosis && (
                  <span className="badge-neutral">
                    <Ban className="h-3.5 w-3.5" />
                    Not a confirmed diagnosis
                  </span>
                )}
              </div>
              <h2 className="mt-3 text-2xl font-bold tracking-tight text-bark-900">
                {condition.label}
              </h2>
              <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-bark-600">
                {analysis.basis}
              </p>
            </div>

            <div className="w-full max-w-[13rem] shrink-0">
              <p className="text-2xs font-bold uppercase tracking-wider text-bark-400">
                Certainty
              </p>
              <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-white/70">
                <div
                  className={classNames('h-full rounded-full', confidence.bar)}
                  style={{ width: confidence.width }}
                />
              </div>
              <p className="mt-1.5 text-xs leading-snug text-bark-500">{confidence.explanation}</p>
            </div>
          </div>
        </div>

        <CardBody className="space-y-4">
          {condition.summary && (
            <p className="text-sm leading-relaxed text-bark-700">{condition.summary}</p>
          )}

          {/* ---- Detected symptoms ---- */}
          <div>
            <p className="label inline-flex items-center gap-1.5">
              <Activity className="h-3 w-3" />
              Symptoms measured in this image
            </p>
            {symptoms.detected.length === 0 ? (
              <Notice tone="success" icon={<CheckCircle2 className="h-4 w-4" />}>
                No symptoms exceeded the reporting threshold. This describes the visible leaf
                surface only - early infections and underside symptoms will not show up.
              </Notice>
            ) : (
              <div className="space-y-2">
                {symptoms.detected.map((symptom) => (
                  <div
                    key={symptom.id}
                    className={classNames(
                      'rounded-r-xl border-l-4 px-3.5 py-2.5',
                      SEVERITY_CLASS[symptom.severity],
                    )}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-semibold text-bark-800">{symptom.label}</p>
                      <span className="text-2xs font-bold uppercase tracking-wider text-bark-500">
                        {symptom.severity}
                      </span>
                    </div>
                    {/* The measurement, so the user can check it against the image. */}
                    <p className="mt-0.5 text-xs leading-relaxed text-bark-600">
                      {symptom.evidence}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {symptoms.notes.length > 0 && (
              <div className="mt-2 space-y-1">
                {symptoms.notes.map((note) => (
                  <p key={note} className="text-xs text-bark-500">
                    {note}
                  </p>
                ))}
              </div>
            )}
          </div>

          {/* ---- AI vision description ---- */}
          {vision.available && (vision.observed_symptoms?.length ?? 0) > 0 && (
            <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3">
              <p className="inline-flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-sky-800">
                <Sparkles className="h-3 w-3" />
                AI vision reading ({vision.provider})
              </p>
              <Bullets items={vision.observed_symptoms ?? []} dot="bg-sky-400" />
              {vision.uncertainty_notes && (
                <p className="mt-2 text-xs italic text-sky-800">{vision.uncertainty_notes}</p>
              )}
            </div>
          )}

          {/* ---- Candidates ---- */}
          {condition.candidates.length > 0 && (
            <div>
              <p className="label inline-flex items-center gap-1.5">
                <ListChecks className="h-3 w-3" />
                Possible causes, ranked by how well they fit the evidence
              </p>
              <div className="space-y-2.5">
                {condition.candidates.map((candidate, index) => (
                  <CandidateCard key={candidate.id} candidate={candidate} rank={index} />
                ))}
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {/* ================= 3. TREATMENT ================= */}
      <Card>
        <CardHeader
          title="Treatment recommendations"
          subtitle={
            plant.in_knowledge_base
              ? `Matched to ${plant.name} and the condition above`
              : 'General guidance - identify the plant for species-specific advice'
          }
          icon={<Shield className="h-4 w-4" />}
        />
        <CardBody className="space-y-5">
          {treatment.chemical_withheld && treatment.withheld_reason && (
            <Notice
              tone="warning"
              icon={<AlertTriangle className="h-4 w-4" />}
              title="Chemical treatment options are not shown"
            >
              {treatment.withheld_reason}
            </Notice>
          )}

          {treatment.immediate_actions.length > 0 && (
            <div>
              <p className="label inline-flex items-center gap-1.5">
                <Lightbulb className="h-3 w-3 text-harvest-500" />
                Immediate actions
              </p>
              <Bullets items={treatment.immediate_actions} dot="bg-harvest-500" />
            </div>
          )}

          <div className="grid gap-5 sm:grid-cols-2">
            {treatment.organic_options.length > 0 && (
              <div>
                <p className="label inline-flex items-center gap-1.5">
                  <Sprout className="h-3 w-3 text-leaf-600" />
                  Organic options
                </p>
                <Bullets items={treatment.organic_options} dot="bg-leaf-500" />
              </div>
            )}

            {treatment.cultural_controls.length > 0 && (
              <div>
                <p className="label inline-flex items-center gap-1.5">
                  <ScrollText className="h-3 w-3 text-sky-600" />
                  Cultural and agricultural controls
                </p>
                <Bullets items={treatment.cultural_controls} dot="bg-sky-400" />
              </div>
            )}
          </div>

          {/* Chemical options carry a mandatory verification notice. No product
              names and no dosages exist anywhere in the knowledge base. */}
          {treatment.chemical_options && (
            <div className="rounded-xl border-2 border-blight-200 bg-blight-50 px-4 py-3.5">
              <p className="inline-flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-blight-800">
                <Beaker className="h-3 w-3" />
                Chemical control - verification required
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {treatment.chemical_options.active_ingredient_classes.map((item) => (
                  <span key={item} className="chip border-blight-200 bg-white text-blight-800">
                    {item}
                  </span>
                ))}
              </div>
              <p className="mt-2.5 text-xs leading-relaxed text-blight-800">
                {treatment.chemical_disclaimer}
              </p>
            </div>
          )}

          {treatment.prevention.length > 0 && (
            <div>
              <p className="label inline-flex items-center gap-1.5">
                <Shield className="h-3 w-3 text-leaf-600" />
                Prevention
              </p>
              <Bullets items={treatment.prevention} dot="bg-leaf-400" />
            </div>
          )}
        </CardBody>
      </Card>

      {/* ================= 4. ADDITIONAL INFORMATION ================= */}
      <Card>
        <CardHeader
          title="Plant care and prevention"
          subtitle={
            plant.in_knowledge_base
              ? `Care profile for ${plant.name}`
              : 'General plant-care guidance'
          }
          icon={<Sprout className="h-4 w-4" />}
        />
        <CardBody className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {[
              { icon: Droplets, label: 'Watering', value: care.watering, tone: 'text-sky-600' },
              { icon: Mountain, label: 'Soil', value: care.soil, tone: 'text-amber-700' },
              { icon: Sun, label: 'Light', value: care.light, tone: 'text-harvest-600' },
              { icon: Sprout, label: 'Feeding', value: care.feeding, tone: 'text-leaf-600' },
              { icon: ScrollText, label: 'Pruning', value: care.pruning, tone: 'text-bark-600' },
            ]
              .filter((item) => Boolean(item.value))
              .map((item) => (
                <div key={item.label} className="rounded-xl bg-bark-50 px-4 py-3">
                  <p className="inline-flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-bark-500">
                    <item.icon className={classNames('h-3 w-3', item.tone)} />
                    {item.label}
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-bark-600">{item.value}</p>
                </div>
              ))}
          </div>

          {care.prevention.length > 0 && (
            <div>
              <p className="label">Prevention for this plant</p>
              <Bullets items={care.prevention} dot="bg-leaf-500" />
            </div>
          )}
        </CardBody>
      </Card>

      {/* ================= 5. NEXT STEPS ================= */}
      {analysis.next_steps.length > 0 && (
        <Card>
          <CardHeader
            title="Recommended next steps"
            subtitle="How to narrow this down"
            icon={<ListChecks className="h-4 w-4" />}
          />
          <CardBody>
            <ol className="space-y-2.5">
              {analysis.next_steps.map((step, index) => (
                <li key={step} className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-leaf-600 text-xs font-bold text-white">
                    {index + 1}
                  </span>
                  <span className="text-sm leading-relaxed text-bark-600">{step}</span>
                </li>
              ))}
            </ol>
          </CardBody>
        </Card>
      )}

      {/* ================= 6. LIMITS AND EVIDENCE ================= */}
      <Card>
        <CardHeader
          title="What this analysis can and cannot tell you"
          subtitle="Stated plainly, because a shortlist is not a diagnosis"
          icon={<Info className="h-4 w-4" />}
        />
        <CardBody className="space-y-4">
          <Bullets items={analysis.limitations} dot="bg-harvest-500" />

          <div className="divider" />

          <div>
            <p className="label">Evidence sources used</p>
            <div className="space-y-2">
              <div className="flex items-start gap-2.5 rounded-xl bg-bark-50 px-3.5 py-2.5">
                <Microscope className="mt-0.5 h-4 w-4 shrink-0 text-leaf-600" />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-bark-800">
                    Computer-vision symptom measurement
                  </p>
                  <p className="text-xs text-bark-500">
                    Used. Species-agnostic measurements taken from this image - evidence level{' '}
                    {symptoms.evidence_level}, leaf segmentation {symptoms.segmentation_quality}.
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-2.5 rounded-xl bg-bark-50 px-3.5 py-2.5">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-sky-600" />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-bark-800">AI vision model</p>
                  <p className="text-xs text-bark-500">
                    {vision.available
                      ? `Used (${vision.provider}, ${vision.model}) in ${vision.latency_ms} ms.`
                      : (vision.reason ?? 'Not configured.')}
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-2.5 rounded-xl bg-bark-50 px-3.5 py-2.5">
                <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-violet-600" />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-bark-800">
                    Trained MobileNetV2 classifier
                  </p>
                  <p className="text-xs text-bark-500">
                    {analysis.evidence_sources.classifier.used
                      ? 'Used - this plant is one of its trained classes and it was confident.'
                      : (analysis.evidence_sources.classifier.note ??
                        `Not used. It covers only ${analysis.evidence_sources.classifier.covers_species.join(', ')}.`)}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

export default UniversalResult;
