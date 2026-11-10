import { Check, FileImage } from 'lucide-react';
import type { CameraSource } from '@/services/types';
import { classNames } from '@/utils/format';
import { cameraSourceMeta } from './CameraSourceBadge';

export interface CameraOption {
  id: CameraSource;
  label: string;
  description: string;
  /** null when availability is only knowable in the browser (the webcam). */
  available: boolean | null;
  statusText: string;
  enabled: boolean;
}

interface CameraSourceSelectorProps {
  options: CameraOption[];
  value: CameraSource;
  onChange: (source: CameraSource) => void;
  className?: string;
}

/**
 * Camera source picker.
 *
 * Shown as full cards rather than a dropdown because each option carries state
 * the operator needs before choosing: whether that camera is reachable, and why
 * not if it isn't. A select element would hide exactly the information that
 * makes the choice.
 *
 * An offline camera stays selectable on purpose - the backend will still try a
 * capture (the board may be reachable even without a recent heartbeat), and the
 * resulting error is more informative than a disabled button.
 */
export function CameraSourceSelector({
  options,
  value,
  onChange,
  className,
}: CameraSourceSelectorProps) {
  return (
    <div
      className={classNames('grid gap-3 sm:grid-cols-3', className)}
      role="radiogroup"
      aria-label="Camera source"
    >
      {options.map((option) => {
        const meta = cameraSourceMeta(option.id);
        const Icon = option.id === 'file_upload' ? FileImage : meta.icon;
        const isSelected = value === option.id;

        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={isSelected}
            onClick={() => onChange(option.id)}
            disabled={!option.enabled}
            className={classNames(
              'group relative rounded-2xl border-2 p-4 text-left transition-all duration-200 ease-spring',
              'disabled:cursor-not-allowed disabled:opacity-50',
              isSelected
                ? 'border-leaf-500 bg-leaf-50 shadow-glow-leaf'
                : 'border-bark-200 bg-white hover:-translate-y-0.5 hover:border-leaf-300 hover:shadow-card-hover',
            )}
          >
            {isSelected && (
              <span className="absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-full bg-leaf-600 text-white">
                <Check className="h-3 w-3" strokeWidth={3} />
              </span>
            )}

            <span
              className={classNames(
                'flex h-11 w-11 items-center justify-center rounded-xl transition-colors',
                isSelected ? 'bg-leaf-600 text-white' : 'bg-bark-100 text-bark-600 group-hover:bg-leaf-100 group-hover:text-leaf-700',
              )}
            >
              <Icon className="h-5 w-5" />
            </span>

            <h3
              className={classNames(
                'mt-3 text-sm font-semibold',
                isSelected ? 'text-leaf-900' : 'text-bark-900',
              )}
            >
              {option.label}
            </h3>
            <p className="mt-1 text-xs leading-relaxed text-bark-500">{option.description}</p>

            <div className="mt-2.5 flex items-center gap-1.5">
              <span
                className={classNames(
                  'h-1.5 w-1.5 rounded-full',
                  option.available === true
                    ? 'bg-leaf-500'
                    : option.available === false
                      ? 'bg-bark-300'
                      : 'bg-sky-400',
                )}
              />
              <span className="text-2xs font-medium text-bark-500">{option.statusText}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

export default CameraSourceSelector;
