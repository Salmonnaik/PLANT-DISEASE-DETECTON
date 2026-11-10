import { Camera, FileImage, HelpCircle, Laptop } from 'lucide-react';
import type { CameraSource } from '@/services/types';
import { classNames } from '@/utils/format';

/**
 * Single source of truth for how each camera is presented.
 *
 * Every badge, legend and chart that mentions a camera reads from here, so the
 * laptop webcam is always cyan with a laptop icon and the ESP32-CAM always
 * green with a camera icon, wherever it appears.
 */
export const CAMERA_SOURCE_META: Record<
  CameraSource,
  { label: string; shortLabel: string; icon: typeof Camera; badgeClass: string; colour: string }
> = {
  laptop_webcam: {
    label: 'Laptop webcam',
    shortLabel: 'Webcam',
    icon: Laptop,
    badgeClass: 'bg-cyan-100 text-cyan-800',
    colour: '#0891b2',
  },
  esp32_cam: {
    label: 'ESP32-CAM',
    shortLabel: 'ESP32',
    icon: Camera,
    badgeClass: 'bg-leaf-100 text-leaf-800',
    colour: '#16a34a',
  },
  file_upload: {
    label: 'File upload',
    shortLabel: 'File',
    icon: FileImage,
    badgeClass: 'bg-violet-100 text-violet-800',
    colour: '#7c3aed',
  },
  unknown: {
    label: 'Unknown source',
    shortLabel: 'Unknown',
    icon: HelpCircle,
    badgeClass: 'bg-bark-100 text-bark-700',
    colour: '#75876f',
  },
};

export function cameraSourceMeta(source: CameraSource | string | null | undefined) {
  if (source && source in CAMERA_SOURCE_META) {
    return CAMERA_SOURCE_META[source as CameraSource];
  }
  return CAMERA_SOURCE_META.unknown;
}

interface CameraSourceBadgeProps {
  source: CameraSource | string | null | undefined;
  short?: boolean;
  showIcon?: boolean;
  className?: string;
}

export function CameraSourceBadge({
  source,
  short = false,
  showIcon = true,
  className,
}: CameraSourceBadgeProps) {
  const meta = cameraSourceMeta(source);
  const Icon = meta.icon;

  return (
    <span className={classNames('badge', meta.badgeClass, className)}>
      {showIcon && <Icon className="h-3.5 w-3.5" aria-hidden="true" />}
      {short ? meta.shortLabel : meta.label}
    </span>
  );
}

/** Compact icon-only variant for dense table cells. */
export function CameraSourceIcon({
  source,
  className,
}: {
  source: CameraSource | string | null | undefined;
  className?: string;
}) {
  const meta = cameraSourceMeta(source);
  const Icon = meta.icon;
  return (
    <span className={classNames('inline-flex items-center gap-1.5 text-bark-600', className)} title={meta.label}>
      <Icon className="h-3.5 w-3.5" style={{ color: meta.colour }} />
      {meta.shortLabel}
    </span>
  );
}

export default CameraSourceBadge;
