/**
 * Status presentation map.
 *
 * Every place a detection status, severity or Wi-Fi signal is displayed looks up
 * its colours and wording here. Centralising it is what guarantees "uncertain"
 * is amber in the result card, the history table and the sidebar alike - and it
 * keeps the semantics honest: an inconclusive result never borrows the green of
 * a healthy leaf or the red of a confirmed disease.
 */

import type { DetectionStatus, Severity } from '@/services/types';

export interface StatusMeta {
  label: string;
  shortLabel: string;
  badgeClass: string;
  dotClass: string;
  textClass: string;
  borderClass: string;
  softBgClass: string;
  chartColour: string;
  description: string;
}

export const STATUS_META: Record<DetectionStatus, StatusMeta> = {
  healthy: {
    label: 'Healthy',
    shortLabel: 'Healthy',
    badgeClass: 'badge-healthy',
    dotClass: 'bg-leaf-500',
    textClass: 'text-leaf-700',
    borderClass: 'border-leaf-200',
    softBgClass: 'bg-leaf-50',
    chartColour: '#16a34a',
    description: 'No disease symptoms were detected in this leaf.',
  },
  diseased: {
    label: 'Disease detected',
    shortLabel: 'Diseased',
    badgeClass: 'badge-diseased',
    dotClass: 'bg-blight-500',
    textClass: 'text-blight-700',
    borderClass: 'border-blight-200',
    softBgClass: 'bg-blight-50',
    chartColour: '#dc2626',
    description: 'The model identified a disease above the confidence threshold.',
  },
  uncertain: {
    label: 'Uncertain',
    shortLabel: 'Uncertain',
    badgeClass: 'badge-uncertain',
    dotClass: 'bg-harvest-500',
    textClass: 'text-harvest-700',
    borderClass: 'border-harvest-300',
    softBgClass: 'bg-harvest-50',
    chartColour: '#f59e0b',
    description:
      'Confidence fell below the threshold, so no diagnosis is reported. Re-capture the leaf.',
  },
  unknown: {
    label: 'Unusable image',
    shortLabel: 'Unknown',
    badgeClass: 'badge-neutral',
    dotClass: 'bg-bark-400',
    textClass: 'text-bark-600',
    borderClass: 'border-bark-200',
    softBgClass: 'bg-bark-50',
    chartColour: '#75876f',
    description:
      'The image failed the quality check, so it was not classified at all.',
  },
};

export function statusMeta(status: DetectionStatus | string | null | undefined): StatusMeta {
  if (status && status in STATUS_META) {
    return STATUS_META[status as DetectionStatus];
  }
  return STATUS_META.unknown;
}

export interface SeverityMeta {
  label: string;
  badgeClass: string;
  chartColour: string;
}

export const SEVERITY_META: Record<Severity, SeverityMeta> = {
  none: { label: 'No action needed', badgeClass: 'badge-healthy', chartColour: '#16a34a' },
  mild: { label: 'Mild', badgeClass: 'badge-uncertain', chartColour: '#fcd34d' },
  moderate: { label: 'Moderate - treat soon', badgeClass: 'badge-uncertain', chartColour: '#f59e0b' },
  severe: { label: 'Severe - act immediately', badgeClass: 'badge-diseased', chartColour: '#dc2626' },
  unknown: { label: 'Unclassified severity', badgeClass: 'badge-neutral', chartColour: '#75876f' },
};

export function severityMeta(severity: Severity | string | null | undefined): SeverityMeta {
  if (severity && severity in SEVERITY_META) {
    return SEVERITY_META[severity as Severity];
  }
  return SEVERITY_META.unknown;
}

export interface SignalMeta {
  label: string;
  textClass: string;
  bars: number;
}

export function signalMeta(quality: string | null | undefined): SignalMeta {
  switch (quality) {
    case 'excellent':
      return { label: 'Excellent', textClass: 'text-leaf-600', bars: 4 };
    case 'good':
      return { label: 'Good', textClass: 'text-leaf-600', bars: 3 };
    case 'fair':
      return { label: 'Fair', textClass: 'text-harvest-600', bars: 2 };
    case 'weak':
      return { label: 'Weak', textClass: 'text-blight-600', bars: 1 };
    default:
      return { label: 'Unknown', textClass: 'text-bark-400', bars: 0 };
  }
}

/** Colour for a confidence value, used by progress bars and result headers. */
export function confidenceColour(confidence: number, threshold: number): string {
  if (confidence < threshold) return '#f59e0b';
  if (confidence >= 0.9) return '#16a34a';
  if (confidence >= 0.75) return '#22c55e';
  return '#65a30d';
}

export function sourceLabel(source: string | null | undefined): string {
  if (source === 'esp32cam') return 'ESP32-CAM';
  if (source === 'upload') return 'Manual upload';
  return 'Unknown source';
}
