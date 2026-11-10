import { Loader2 } from 'lucide-react';
import { classNames } from '@/utils/format';

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={classNames('h-4 w-4 animate-spin', className)} aria-hidden="true" />;
}

interface AnalysingOverlayProps {
  message?: string;
  detail?: string;
}

/**
 * Overlay shown while the model runs.
 *
 * The sweeping scan line is not decoration for its own sake: inference on a CPU
 * takes a noticeable moment, and a moving indicator tells the operator the
 * system is working rather than stuck.
 */
export function AnalysingOverlay({
  message = 'Analysing leaf image',
  detail = 'Running MobileNetV2 inference on the backend...',
}: AnalysingOverlayProps) {
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 rounded-2xl bg-bark-950/70 backdrop-blur-sm">
      <div className="relative h-20 w-20 overflow-hidden rounded-xl border-2 border-leaf-400/70">
        <div className="absolute inset-0 bg-leaf-500/10" />
        <div className="absolute left-0 h-0.5 w-full animate-scan-sweep bg-leaf-300 shadow-[0_0_12px_2px_rgba(134,239,172,0.8)]" />
      </div>
      <div className="text-center">
        <p className="flex items-center justify-center gap-2 text-sm font-semibold text-white">
          <Spinner className="text-leaf-300" />
          {message}
        </p>
        <p className="mt-1 text-xs text-leaf-100/70">{detail}</p>
      </div>
    </div>
  );
}

export default Spinner;
