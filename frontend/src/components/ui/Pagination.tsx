import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { Pagination as PaginationMeta } from '@/services/types';
import { classNames } from '@/utils/format';

interface PaginationProps {
  pagination: PaginationMeta;
  onPageChange: (page: number) => void;
  className?: string;
}

/** Page numbers around the current page, with ellipses for long ranges. */
function pageWindow(current: number, total: number): (number | 'gap')[] {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);

  const pages = new Set<number>([1, total, current, current - 1, current + 1]);
  const sorted = [...pages].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);

  const result: (number | 'gap')[] = [];
  sorted.forEach((page, index) => {
    if (index > 0 && page - (sorted[index - 1] as number) > 1) result.push('gap');
    result.push(page);
  });
  return result;
}

export function Pagination({ pagination, onPageChange, className }: PaginationProps) {
  const { page, pages, total, limit, offset } = pagination;
  if (total === 0) return null;

  const from = offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <div
      className={classNames(
        'flex flex-col items-center justify-between gap-3 border-t border-bark-100 px-5 py-3 sm:flex-row',
        className,
      )}
    >
      <p className="text-sm text-bark-500">
        Showing <span className="font-semibold text-bark-700">{from}</span>-
        <span className="font-semibold text-bark-700">{to}</span> of{' '}
        <span className="font-semibold text-bark-700">{total}</span> detections
      </p>

      {pages > 1 && (
        <nav className="flex items-center gap-1" aria-label="Pagination">
          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            aria-label="Previous page"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>

          {pageWindow(page, pages).map((item, index) =>
            item === 'gap' ? (
              <span key={`gap-${index}`} className="px-1.5 text-bark-300">
                &hellip;
              </span>
            ) : (
              <button
                key={item}
                type="button"
                onClick={() => onPageChange(item)}
                aria-current={item === page ? 'page' : undefined}
                className={classNames(
                  'h-8 min-w-8 rounded-lg px-2 text-sm font-semibold transition-colors',
                  item === page
                    ? 'bg-leaf-600 text-white'
                    : 'text-bark-600 hover:bg-bark-100 hover:text-bark-900',
                )}
              >
                {item}
              </button>
            ),
          )}

          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= pages}
            aria-label="Next page"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </nav>
      )}
    </div>
  );
}

export default Pagination;
