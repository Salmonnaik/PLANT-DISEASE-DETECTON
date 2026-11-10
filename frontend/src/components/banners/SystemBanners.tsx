import { AlertTriangle, FlaskConical, RefreshCw, ServerCrash } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { HealthResponse } from '@/services/types';
import { ApiClientError } from '@/services/api';
import { Spinner } from '@/components/ui';

interface SystemBannersProps {
  health: HealthResponse | null;
  error: ApiClientError | null;
  onRetry: () => void;
  isRetrying?: boolean;
}

/**
 * The honesty layer of the UI.
 *
 * Three conditions must never be silently hidden behind a normal-looking
 * dashboard, because each one changes how the numbers on screen should be read:
 *
 * 1. the backend is unreachable, so everything shown is stale or empty;
 * 2. the loaded model is untrained, so predictions are not real diagnoses;
 * 3. a model is present but cannot serve predictions at all.
 *
 * These banners are rendered on every page inside the dashboard layout.
 */
export function SystemBanners({ health, error, onRetry, isRetrying }: SystemBannersProps) {
  if (error?.isBackendUnreachable) {
    return (
      <div
        className="flex flex-col items-start gap-3 rounded-xl border border-blight-300 bg-blight-50 px-4 py-3 sm:flex-row sm:items-center"
        role="alert"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blight-100 text-blight-600">
          <ServerCrash className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-blight-800">Backend not reachable</p>
          <p className="text-sm text-blight-700">
            No data on this page is live. Start the API with{' '}
            <code className="rounded bg-blight-100 px-1.5 py-0.5 font-mono text-xs">python app.py</code>{' '}
            in the <code className="font-mono text-xs">backend</code> folder.
          </p>
        </div>
        <button type="button" onClick={onRetry} className="btn-secondary btn-sm shrink-0" disabled={isRetrying}>
          {isRetrying ? <Spinner /> : <RefreshCw className="h-3.5 w-3.5" />}
          Reconnect
        </button>
      </div>
    );
  }

  if (!health) return null;

  const model = health.model;

  if (model.is_test_mode) {
    return (
      <div
        className="flex flex-col items-start gap-3 rounded-xl border-2 border-harvest-300 bg-harvest-50 px-4 py-3 sm:flex-row sm:items-center"
        role="alert"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-harvest-100 text-harvest-700">
          <FlaskConical className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-bold uppercase tracking-wide text-harvest-700">
            Test mode - results are not real diagnoses
          </p>
          <p className="text-sm text-harvest-700">
            The loaded model is <strong>untrained</strong>: it has never seen a plant disease
            dataset, so its outputs are meaningless as diagnoses and are stored flagged as
            unvalidated. Train a real model with{' '}
            <code className="rounded bg-harvest-100 px-1.5 py-0.5 font-mono text-xs">
              python ml/train.py --dataset-dir ml/dataset
            </code>
            .
          </p>
        </div>
        <Link to="/about" className="btn-secondary btn-sm shrink-0 border-harvest-300 text-harvest-700">
          What this means
        </Link>
      </div>
    );
  }

  if (!model.can_predict) {
    return (
      <div
        className="flex flex-col items-start gap-3 rounded-xl border border-blight-300 bg-blight-50 px-4 py-3 sm:flex-row sm:items-center"
        role="alert"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blight-100 text-blight-600">
          <AlertTriangle className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-blight-800">Detection unavailable</p>
          <p className="whitespace-pre-line text-sm text-blight-700">{model.message}</p>
        </div>
      </div>
    );
  }

  return null;
}

export default SystemBanners;
