import { NavLink } from 'react-router-dom';
import {
  BarChart3,
  Cpu,
  FlaskConical,
  History,
  Home,
  Info,
  LayoutDashboard,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Video,
  X,
} from 'lucide-react';
import { useSystemStatus } from '@/layouts/SystemStatusProvider';
import { usePlants } from '@/hooks';
import { LiveDot } from '@/components/ui';
import { classNames, formatFraction } from '@/utils/format';
import { LogoWordmark } from './Logo';

export interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  description: string;
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, description: 'Overview and recent activity' },
  { to: '/detect', label: 'Disease Detection', icon: ScanLine, description: 'Capture or upload a leaf image' },
  { to: '/cameras', label: 'Camera Management', icon: Video, description: 'Laptop webcam and ESP32-CAM' },
  { to: '/history', label: 'Detection History', icon: History, description: 'Every past scan' },
  { to: '/analytics', label: 'Analytics', icon: BarChart3, description: 'Trends and model metrics' },
  { to: '/device', label: 'Device Management', icon: Cpu, description: 'ESP32-CAM status and control' },
  { to: '/about', label: 'About Project', icon: Info, description: 'Abstract, architecture, methodology' },
];

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

/** Model state panel at the foot of the sidebar - always visible, never buried. */
function ModelStatusPanel() {
  const { health, isBackendOnline, isTestMode } = useSystemStatus();
  const model = health?.model;
  const accuracy = model?.metrics?.accuracy;

  if (!isBackendOnline) {
    return (
      <div className="rounded-xl border border-white/10 bg-white/5 p-3">
        <p className="text-2xs font-semibold uppercase tracking-wider text-leaf-200/60">Model</p>
        <p className="mt-1 text-xs text-leaf-100/70">Backend offline</p>
      </div>
    );
  }

  if (isTestMode) {
    return (
      <div className="rounded-xl border border-harvest-400/40 bg-harvest-500/15 p-3">
        <p className="flex items-center gap-1.5 text-2xs font-bold uppercase tracking-wider text-harvest-300">
          <FlaskConical className="h-3.5 w-3.5" />
          Test mode
        </p>
        <p className="mt-1 text-xs leading-snug text-harvest-100/90">
          Untrained model - results are not real diagnoses.
        </p>
      </div>
    );
  }

  if (!model?.can_predict) {
    return (
      <div className="rounded-xl border border-blight-400/40 bg-blight-500/15 p-3">
        <p className="text-2xs font-bold uppercase tracking-wider text-blight-200">No model</p>
        <p className="mt-1 text-xs leading-snug text-blight-100/90">Run ml/train.py to enable detection.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
      <p className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-leaf-200/70">
        <ShieldCheck className="h-3.5 w-3.5" />
        Model Status
      </p>
      <p className="mt-1 text-xs font-semibold text-leaf-300">Trained &amp; Ready</p>
      <p className="mt-0.5 text-xs text-leaf-100/80">
        {model.base_model ?? 'MobileNetV2'} &middot; {model.num_classes} classes
      </p>
      {accuracy !== undefined && (
        <p className="mt-0.5 text-xs font-semibold text-leaf-300">
          {formatFraction(accuracy)} test accuracy
        </p>
      )}
    </div>
  );
}

/**
 * Universal analysis capability.
 *
 * Shown separately from the classifier because the two cover different things:
 * the classifier handles a few crops precisely, while this layer handles any
 * plant approximately. Conflating them into one "supports N species" figure
 * would overstate what the trained model actually knows.
 */
function CapabilityPanel() {
  const { data } = usePlants();
  const { health } = useSystemStatus();

  if (!data) return null;

  const visionReady = Boolean(data.ai_vision?.available);

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
      <p className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-leaf-200/70">
        <Sparkles className="h-3.5 w-3.5" />
        Analysis coverage
      </p>
      <p className="mt-1 text-xs text-leaf-100/80">
        Any plant &middot; {data.count} care profiles
      </p>
      <p className="mt-0.5 text-xs text-leaf-200/60">
        {health?.universal_analysis?.enabled === false
          ? 'Universal analysis disabled'
          : 'Symptom measurement + rule inference'}
      </p>
      <p className="mt-0.5 text-2xs text-leaf-200/50">
        AI species ID: {visionReady ? 'enabled' : 'not configured'}
      </p>
    </div>
  );
}

export function Sidebar({ isOpen, onClose }: SidebarProps) {
  const { health, isDeviceOnline } = useSystemStatus();
  const device = health?.device.primary;

  return (
    <>
      {/* Mobile scrim */}
      {isOpen && (
        <div
          className="fixed inset-0 z-30 animate-fade-in bg-bark-950/50 backdrop-blur-sm lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={classNames(
          'fixed inset-y-0 left-0 z-40 flex w-72 flex-col bg-leaf-gradient shadow-panel transition-transform duration-300 ease-spring',
          'lg:translate-x-0',
          isOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-2 px-5 py-5">
          <NavLink to="/" aria-label="PlantGuard AI home">
            <LogoWordmark inverted />
          </NavLink>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-leaf-100 hover:bg-white/10 lg:hidden"
            aria-label="Close navigation"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="mx-5 h-px bg-white/10" />

        {/* Navigation */}
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          <p className="px-3 pb-2 text-2xs font-bold uppercase tracking-widest text-leaf-200/50">
            Workspace
          </p>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={onClose}
              className={({ isActive }) =>
                classNames('nav-link group', isActive && 'nav-link-active')
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span className="absolute left-0 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full bg-leaf-300" />
                  )}
                  <item.icon className="h-[18px] w-[18px] shrink-0" />
                  <span className="truncate">{item.label}</span>
                </>
              )}
            </NavLink>
          ))}

          <p className="px-3 pb-2 pt-5 text-2xs font-bold uppercase tracking-widest text-leaf-200/50">
            Project
          </p>
          <NavLink to="/" onClick={onClose} className="nav-link">
            <Home className="h-[18px] w-[18px] shrink-0" />
            <span>Landing page</span>
          </NavLink>
        </nav>

        {/* Footer: device + model state */}
        <div className="space-y-2 px-3 pb-4">
          <div className="rounded-xl border border-white/10 bg-white/5 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-2xs font-semibold uppercase tracking-wider text-leaf-200/70">
                ESP32-CAM
              </p>
              <LiveDot online={isDeviceOnline} label={isDeviceOnline ? 'Online' : 'Offline'} />
            </div>
            <p className="mt-1 truncate font-mono text-xs text-leaf-100/80">
              {device?.ip_address ?? 'No IP registered'}
            </p>
          </div>

          <ModelStatusPanel />
          <CapabilityPanel />

          <p className="px-1 pt-1 text-2xs leading-relaxed text-leaf-200/45">
            MobileNetV2 transfer learning &middot; Flask REST API &middot; SQLite
          </p>
        </div>
      </aside>
    </>
  );
}

export default Sidebar;
