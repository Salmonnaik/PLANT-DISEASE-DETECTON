import { classNames } from '@/utils/format';

interface LogoProps {
  className?: string;
  /** Monochrome white mark, for the dark sidebar. */
  inverted?: boolean;
}

/** Inline SVG leaf-and-scan mark - no network request, scales crisply. */
export function LogoMark({ className, inverted = false }: LogoProps) {
  return (
    <svg
      viewBox="0 0 48 48"
      className={classNames('h-9 w-9', className)}
      role="img"
      aria-label="PlantGuard AI logo"
    >
      <defs>
        <linearGradient id="logoLeaf" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={inverted ? '#ffffff' : '#22c55e'} />
          <stop offset="100%" stopColor={inverted ? '#bbf7d0' : '#15803d'} />
        </linearGradient>
      </defs>
      <rect
        x="1"
        y="1"
        width="46"
        height="46"
        rx="13"
        fill={inverted ? 'rgba(255,255,255,0.12)' : 'url(#logoLeaf)'}
        stroke={inverted ? 'rgba(255,255,255,0.35)' : 'none'}
      />
      <path
        d="M24 38c0-10.5 4.6-16.5 13.5-19.5C36.8 30.5 31.6 36.5 24 38z"
        fill={inverted ? '#f0fdf4' : '#f0fdf4'}
        opacity="0.95"
      />
      <path
        d="M24 38c0-10.5-4.6-16.5-13.5-19.5C11.2 30.5 16.4 36.5 24 38z"
        fill={inverted ? '#86efac' : '#bbf7d0'}
        opacity="0.9"
      />
      <path d="M24 39.5V23" stroke="#f0fdf4" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="34" cy="13" r="3" fill="#fcd34d" />
    </svg>
  );
}

export function LogoWordmark({ inverted = false, compact = false }: LogoProps & { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark inverted={inverted} />
      {!compact && (
        <div className="leading-tight">
          <p className={classNames('text-base font-bold tracking-tight', inverted ? 'text-white' : 'text-bark-900')}>
            PlantGuard<span className={inverted ? 'text-leaf-300' : 'text-leaf-600'}> AI</span>
          </p>
          <p className={classNames('text-2xs font-medium', inverted ? 'text-leaf-200/70' : 'text-bark-400')}>
            ESP32-CAM Disease Detection
          </p>
        </div>
      )}
    </div>
  );
}

export default LogoWordmark;
