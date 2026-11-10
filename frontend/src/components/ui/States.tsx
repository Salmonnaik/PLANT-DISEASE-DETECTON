import type { ReactNode } from 'react';
import { AlertOctagon, Inbox, RefreshCw, ServerCrash, Cpu } from 'lucide-react';
import { ApiClientError } from '@/services/api';
import { classNames } from '@/utils/format';
import { Spinner } from './Spinner';

/* ------------------------------------------------------------------ */
/* Empty state                                                         */
/* ------------------------------------------------------------------ */

interface EmptyStateProps {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ title, description, icon, action, className }: EmptyStateProps) {
  return (
    <div
      className={classNames(
        'flex flex-col items-center justify-center gap-3 px-6 py-14 text-center',
        className,
      )}
    >
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-leaf-50 text-leaf-500">
        {icon ?? <Inbox className="h-7 w-7" />}
      </span>
      <h3 className="text-base font-semibold text-bark-800">{title}</h3>
      {description && <p className="max-w-md text-sm leading-relaxed text-bark-500">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Error state                                                         */
/* ------------------------------------------------------------------ */

interface ErrorStateProps {
  error: ApiClientError | Error | string;
  onRetry?: () => void;
  isRetrying?: boolean;
  className?: string;
  compact?: boolean;
}

/**
 * Error panel that adapts its guidance to the failure.
 *
 * A dead backend, a missing model and a plain HTTP error need different next
 * steps, so the message and the icon change rather than showing one generic
 * "something went wrong".
 */
export function ErrorState({ error, onRetry, isRetrying, className, compact }: ErrorStateProps) {
  const apiError = error instanceof ApiClientError ? error : null;
  const message = typeof error === 'string' ? error : error.message;

  let Icon = AlertOctagon;
  let heading = 'Something went wrong';
  let guidance: ReactNode = null;

  if (apiError?.isBackendUnreachable) {
    Icon = ServerCrash;
    heading = 'Backend not reachable';
    guidance = (
      <>
        Start the API, then retry:
        <code className="mt-2 block rounded-lg bg-bark-900 px-3 py-2 text-left font-mono text-xs text-leaf-200">
          cd backend
          <br />
          python app.py
        </code>
      </>
    );
  } else if (apiError?.isModelUnavailable) {
    Icon = Cpu;
    heading = 'No model available';
    guidance = (
      <>
        Train a model, or create an explicitly untrained test model for pipeline checks:
        <code className="mt-2 block rounded-lg bg-bark-900 px-3 py-2 text-left font-mono text-xs text-leaf-200">
          python ml/train.py --dataset-dir ml/dataset
          <br />
          python ml/create_test_model.py
        </code>
      </>
    );
  } else if (apiError?.isDeviceUnreachable) {
    heading = 'ESP32-CAM not reachable';
  }

  if (compact) {
    return (
      <div
        className={classNames(
          'flex items-start gap-3 rounded-xl border border-blight-200 bg-blight-50 px-4 py-3',
          className,
        )}
        role="alert"
      >
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-blight-600" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-blight-800">{heading}</p>
          <p className="mt-0.5 whitespace-pre-line text-sm text-blight-700">{message}</p>
        </div>
        {onRetry && (
          <button type="button" onClick={onRetry} className="btn-ghost btn-sm text-blight-700">
            {isRetrying ? <Spinner /> : <RefreshCw className="h-3.5 w-3.5" />}
            Retry
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      className={classNames('flex flex-col items-center gap-3 px-6 py-12 text-center', className)}
      role="alert"
    >
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-blight-50 text-blight-500">
        <Icon className="h-7 w-7" />
      </span>
      <h3 className="text-base font-semibold text-bark-800">{heading}</h3>
      <p className="max-w-lg whitespace-pre-line text-sm leading-relaxed text-bark-600">{message}</p>
      {guidance && <div className="max-w-lg text-sm text-bark-500">{guidance}</div>}
      {apiError?.code && apiError.code !== 'UNKNOWN' && (
        <span className="chip font-mono text-2xs">{apiError.code}</span>
      )}
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn-secondary mt-2" disabled={isRetrying}>
          {isRetrying ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
          Try again
        </button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Inline notice                                                       */
/* ------------------------------------------------------------------ */

type NoticeTone = 'info' | 'warning' | 'danger' | 'success';

const NOTICE_TONES: Record<NoticeTone, string> = {
  info: 'border-sky-200 bg-sky-50 text-sky-900',
  warning: 'border-harvest-300 bg-harvest-50 text-harvest-700',
  danger: 'border-blight-200 bg-blight-50 text-blight-800',
  success: 'border-leaf-200 bg-leaf-50 text-leaf-800',
};

export function Notice({
  tone = 'info',
  icon,
  title,
  children,
  className,
}: {
  tone?: NoticeTone;
  icon?: ReactNode;
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={classNames(
        'flex items-start gap-3 rounded-xl border px-4 py-3',
        NOTICE_TONES[tone],
        className,
      )}
    >
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="min-w-0 flex-1 text-sm leading-relaxed">
        {title && <p className="font-semibold">{title}</p>}
        {children}
      </div>
    </div>
  );
}
