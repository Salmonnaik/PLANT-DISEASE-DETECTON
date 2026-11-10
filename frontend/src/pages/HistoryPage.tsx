import { useCallback, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  FlaskConical,
  Grid3x3,
  History,
  Image as ImageIcon,
  List,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  X,
} from 'lucide-react';
import { historyApi, imageUrl } from '@/services/api';
import type { DetectionRecord, HistoryQuery } from '@/services/types';
import { useHistory, useHistoryFilters } from '@/hooks';
import { DetectionDetailModal } from '@/components/detection/DetectionDetailModal';
import { DetectionListItem } from '@/components/detection/DetectionListItem';
import { CameraSourceIcon } from '@/components/camera/CameraSourceBadge';
import {
  Card,
  CardBody,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Pagination,
  Spinner,
  StatusBadge,
  TableSkeleton,
} from '@/components/ui';
import { classNames, formatDateTime, formatRelative } from '@/utils/format';
import { statusMeta } from '@/utils/status';

const PAGE_SIZE = 12;

interface FilterState {
  search: string;
  status: string;
  plant: string;
  disease: string;
  cameraSource: string;
  dateFrom: string;
  dateTo: string;
  sortBy: string;
  sortDir: 'asc' | 'desc';
}

const INITIAL_FILTERS: FilterState = {
  search: '',
  status: 'all',
  plant: 'all',
  disease: 'all',
  cameraSource: 'all',
  dateFrom: '',
  dateTo: '',
  sortBy: 'created_at',
  sortDir: 'desc',
};

/* ------------------------------------------------------------------ */
/* Card grid                                                           */
/* ------------------------------------------------------------------ */

function DetectionCard({
  record,
  onOpen,
}: {
  record: DetectionRecord;
  onOpen: (record: DetectionRecord) => void;
}) {
  const meta = statusMeta(record.detection_status);
  const source = imageUrl(record.image_url);

  return (
    <button
      type="button"
      onClick={() => onOpen(record)}
      className="card-interactive group overflow-hidden text-left"
    >
      <div className="relative aspect-[4/3] overflow-hidden bg-bark-900">
        {source ? (
          <img
            src={source}
            alt={`${record.plant_name} - ${record.predicted_disease}`}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-500 ease-spring group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-bark-500">
            <ImageIcon className="h-8 w-8" />
          </div>
        )}

        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-bark-950/85 to-transparent px-3 pb-2.5 pt-8">
          <p className="truncate text-sm font-semibold text-white">{record.plant_name}</p>
          <p className="truncate text-xs text-leaf-100/85">
            {record.is_conclusive ? record.predicted_disease : meta.label}
          </p>
        </div>

        <div className="absolute left-2.5 top-2.5 flex items-center gap-1.5">
          <StatusBadge status={record.detection_status} short showIcon={false} />
          {!record.is_validated && (
            <span
              className="rounded-full bg-harvest-500 p-1 text-white"
              title="Test-mode record - not a real diagnosis"
            >
              <FlaskConical className="h-3 w-3" />
            </span>
          )}
        </div>

        <div className="absolute right-2.5 top-2.5 rounded-lg bg-bark-950/65 px-2 py-1 backdrop-blur">
          <span className="text-xs font-bold tabular-nums text-white">
            {record.confidence_percent.toFixed(0)}%
          </span>
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 px-3 py-2.5">
        <CameraSourceIcon source={record.camera_source} className="text-xs" />
        <time className="text-xs text-bark-400" dateTime={record.created_at ?? undefined}>
          {formatRelative(record.created_at)}
        </time>
      </div>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export default function HistoryPage() {
  const [filters, setFilters] = useState<FilterState>(INITIAL_FILTERS);
  const [page, setPage] = useState(1);
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [showFilters, setShowFilters] = useState(false);
  const [selected, setSelected] = useState<DetectionRecord | null>(null);
  const [pendingDelete, setPendingDelete] = useState<DetectionRecord | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [isMutating, setIsMutating] = useState(false);

  const query = useMemo<HistoryQuery>(
    () => ({
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
      status: filters.status,
      plant: filters.plant,
      disease: filters.disease,
      camera_source: filters.cameraSource,
      search: filters.search.trim() || undefined,
      date_from: filters.dateFrom || undefined,
      date_to: filters.dateTo || undefined,
      sort_by: filters.sortBy,
      sort_dir: filters.sortDir,
    }),
    [filters, page],
  );

  const { data, error, isLoading, isRefreshing, refresh } = useHistory(query);
  const { data: filterOptions, refresh: refreshFilters } = useHistoryFilters();

  const updateFilter = useCallback(<K extends keyof FilterState>(key: K, value: FilterState[K]) => {
    setFilters((previous) => ({ ...previous, [key]: value }));
    setPage(1);
  }, []);

  const resetFilters = useCallback(() => {
    setFilters(INITIAL_FILTERS);
    setPage(1);
  }, []);

  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (filters.search.trim()) count += 1;
    if (filters.status !== 'all') count += 1;
    if (filters.plant !== 'all') count += 1;
    if (filters.disease !== 'all') count += 1;
    if (filters.cameraSource !== 'all') count += 1;
    if (filters.dateFrom) count += 1;
    if (filters.dateTo) count += 1;
    return count;
  }, [filters]);

  const handleDelete = useCallback(async () => {
    if (!pendingDelete) return;
    setIsMutating(true);
    try {
      await historyApi.remove(pendingDelete.id);
      setPendingDelete(null);
      setSelected(null);
      await refresh();
      await refreshFilters();
    } finally {
      setIsMutating(false);
    }
  }, [pendingDelete, refresh, refreshFilters]);

  const handleClearAll = useCallback(async () => {
    setIsMutating(true);
    try {
      await historyApi.clear(true);
      setConfirmClear(false);
      setPage(1);
      await refresh();
      await refreshFilters();
    } finally {
      setIsMutating(false);
    }
  }, [refresh, refreshFilters]);

  const records = data?.items ?? [];
  const pagination = data?.pagination;

  return (
    <div className="space-y-5">
      {/* ---- Toolbar ---- */}
      <Card>
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-bark-300" />
              <input
                type="search"
                value={filters.search}
                onChange={(event) => updateFilter('search', event.target.value)}
                placeholder="Search by plant, disease, dataset class or device..."
                className="input pl-9"
                aria-label="Search detection history"
              />
            </div>

            <button
              type="button"
              onClick={() => setShowFilters((value) => !value)}
              className={classNames('btn-secondary', activeFilterCount > 0 && 'border-leaf-300 bg-leaf-50')}
            >
              <SlidersHorizontal className="h-4 w-4" />
              Filters
              {activeFilterCount > 0 && (
                <span className="rounded-full bg-leaf-600 px-1.5 text-2xs font-bold text-white">
                  {activeFilterCount}
                </span>
              )}
            </button>

            <div className="flex overflow-hidden rounded-xl border border-bark-200">
              <button
                type="button"
                onClick={() => setView('grid')}
                className={classNames(
                  'px-2.5 py-2 transition-colors',
                  view === 'grid' ? 'bg-leaf-600 text-white' : 'bg-white text-bark-500 hover:bg-bark-50',
                )}
                aria-label="Grid view"
                aria-pressed={view === 'grid'}
              >
                <Grid3x3 className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => setView('list')}
                className={classNames(
                  'px-2.5 py-2 transition-colors',
                  view === 'list' ? 'bg-leaf-600 text-white' : 'bg-white text-bark-500 hover:bg-bark-50',
                )}
                aria-label="List view"
                aria-pressed={view === 'list'}
              >
                <List className="h-4 w-4" />
              </button>
            </div>

            <button type="button" onClick={() => void refresh()} className="btn-secondary" disabled={isRefreshing}>
              {isRefreshing ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
              <span className="hidden sm:inline">Refresh</span>
            </button>

            {(pagination?.total ?? 0) > 0 && (
              <button type="button" onClick={() => setConfirmClear(true)} className="btn-ghost text-blight-600">
                <Trash2 className="h-4 w-4" />
                <span className="hidden sm:inline">Clear all</span>
              </button>
            )}
          </div>

          {showFilters && (
            <div className="animate-fade-in grid gap-3 rounded-xl border border-bark-100 bg-bark-50 p-4 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <label htmlFor="filter-status" className="label">
                  Outcome
                </label>
                <select
                  id="filter-status"
                  value={filters.status}
                  onChange={(event) => updateFilter('status', event.target.value)}
                  className="select"
                >
                  <option value="all">All outcomes</option>
                  <option value="healthy">Healthy</option>
                  <option value="diseased">Diseased</option>
                  <option value="inconclusive">Inconclusive (any)</option>
                  <option value="uncertain">Uncertain only</option>
                  <option value="unknown">Unusable image only</option>
                </select>
              </div>

              <div>
                <label htmlFor="filter-plant" className="label">
                  Plant
                </label>
                <select
                  id="filter-plant"
                  value={filters.plant}
                  onChange={(event) => updateFilter('plant', event.target.value)}
                  className="select"
                >
                  <option value="all">All plants</option>
                  {filterOptions?.plants.map((plant) => (
                    <option key={plant} value={plant}>
                      {plant}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="filter-disease" className="label">
                  Condition
                </label>
                <select
                  id="filter-disease"
                  value={filters.disease}
                  onChange={(event) => updateFilter('disease', event.target.value)}
                  className="select"
                >
                  <option value="all">All conditions</option>
                  {filterOptions?.diseases.map((disease) => (
                    <option key={disease} value={disease}>
                      {disease}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label htmlFor="filter-camera" className="label">
                  Camera source
                </label>
                <select
                  id="filter-camera"
                  value={filters.cameraSource}
                  onChange={(event) => updateFilter('cameraSource', event.target.value)}
                  className="select"
                >
                  <option value="all">All cameras</option>
                  <option value="laptop_webcam">Laptop webcam</option>
                  <option value="esp32_cam">ESP32-CAM</option>
                  <option value="file_upload">File upload</option>
                </select>
              </div>

              <div>
                <label htmlFor="filter-from" className="label">
                  From date
                </label>
                <input
                  id="filter-from"
                  type="date"
                  value={filters.dateFrom}
                  onChange={(event) => updateFilter('dateFrom', event.target.value)}
                  className="input"
                />
              </div>

              <div>
                <label htmlFor="filter-to" className="label">
                  To date
                </label>
                <input
                  id="filter-to"
                  type="date"
                  value={filters.dateTo}
                  onChange={(event) => updateFilter('dateTo', event.target.value)}
                  className="input"
                />
              </div>

              <div>
                <label htmlFor="filter-sort" className="label">
                  Sort by
                </label>
                <select
                  id="filter-sort"
                  value={filters.sortBy}
                  onChange={(event) => updateFilter('sortBy', event.target.value)}
                  className="select"
                >
                  <option value="created_at">Date</option>
                  <option value="confidence">Confidence</option>
                  <option value="plant_name">Plant name</option>
                  <option value="predicted_disease">Condition</option>
                </select>
              </div>

              <div>
                <label htmlFor="filter-dir" className="label">
                  Order
                </label>
                <select
                  id="filter-dir"
                  value={filters.sortDir}
                  onChange={(event) => updateFilter('sortDir', event.target.value as 'asc' | 'desc')}
                  className="select"
                >
                  <option value="desc">Newest / highest first</option>
                  <option value="asc">Oldest / lowest first</option>
                </select>
              </div>

              {activeFilterCount > 0 && (
                <div className="sm:col-span-2 lg:col-span-4">
                  <button type="button" onClick={resetFilters} className="btn-ghost btn-sm">
                    <X className="h-3.5 w-3.5" />
                    Clear all filters
                  </button>
                </div>
              )}
            </div>
          )}
        </CardBody>
      </Card>

      {/* ---- Results ---- */}
      {error && !data ? (
        <Card>
          <ErrorState error={error} onRetry={() => void refresh()} isRetrying={isRefreshing} />
        </Card>
      ) : isLoading ? (
        <Card>
          <TableSkeleton rows={6} />
        </Card>
      ) : records.length === 0 ? (
        <Card>
          <EmptyState
            icon={<History className="h-7 w-7" />}
            title={activeFilterCount > 0 ? 'No detections match these filters' : 'No detections recorded yet'}
            description={
              activeFilterCount > 0
                ? 'Try widening the date range or clearing the filters.'
                : 'Every scan you run is stored here with its image, confidence and timestamp.'
            }
            action={
              activeFilterCount > 0 ? (
                <button type="button" onClick={resetFilters} className="btn-secondary btn-sm">
                  Clear filters
                </button>
              ) : (
                <Link to="/detect" className="btn-primary btn-sm">
                  Run a detection
                </Link>
              )
            }
          />
        </Card>
      ) : view === 'grid' ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {records.map((record) => (
              <DetectionCard key={record.id} record={record} onOpen={setSelected} />
            ))}
          </div>
          {pagination && (
            <Card>
              <Pagination pagination={pagination} onPageChange={setPage} className="border-t-0" />
            </Card>
          )}
        </>
      ) : (
        <Card>
          <CardHeader
            title="Detection records"
            subtitle={`${pagination?.total ?? 0} total`}
            icon={<History className="h-4 w-4" />}
          />
          {/* Mobile: stacked rows. Desktop: a real table with column headers. */}
          <div className="divide-y divide-bark-50 px-3 sm:hidden">
            {records.map((record) => (
              <DetectionListItem key={record.id} record={record} onClick={setSelected} />
            ))}
          </div>

          <div className="hidden overflow-x-auto sm:block">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-bark-100 bg-bark-50 text-left">
                  {['Image', 'Plant', 'Condition', 'Confidence', 'Outcome', 'Camera', 'Recorded'].map(
                    (heading) => (
                      <th
                        key={heading}
                        className="px-4 py-2.5 text-2xs font-bold uppercase tracking-wider text-bark-500"
                      >
                        {heading}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-bark-50">
                {records.map((record) => (
                  <tr
                    key={record.id}
                    onClick={() => setSelected(record)}
                    className="cursor-pointer transition-colors hover:bg-leaf-50/50"
                  >
                    <td className="px-4 py-2.5">
                      <div className="h-11 w-11 overflow-hidden rounded-lg border border-bark-100 bg-bark-100">
                        {imageUrl(record.image_url) ? (
                          <img
                            src={imageUrl(record.image_url)}
                            alt=""
                            loading="lazy"
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-full items-center justify-center text-bark-300">
                            <ImageIcon className="h-4 w-4" />
                          </div>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="inline-flex items-center gap-1.5 font-medium text-bark-800">
                        {record.plant_name}
                        {!record.is_validated && (
                          <span
                            className="text-harvest-600"
                            title="Test-mode record - not a real diagnosis"
                          >
                            <FlaskConical className="h-3.5 w-3.5" />
                          </span>
                        )}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-bark-600">
                      {record.is_conclusive ? record.predicted_disease : '--'}
                    </td>
                    <td className="px-4 py-2.5 font-semibold tabular-nums text-bark-800">
                      {record.confidence_percent.toFixed(1)}%
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={record.detection_status} short />
                    </td>
                    <td className="px-4 py-2.5">
                      <CameraSourceIcon source={record.camera_source} />
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-bark-500">
                      {formatDateTime(record.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {pagination && <Pagination pagination={pagination} onPageChange={setPage} />}
        </Card>
      )}

      {/* ---- Dialogs ---- */}
      <DetectionDetailModal
        record={selected}
        onClose={() => setSelected(null)}
        onDelete={setPendingDelete}
        isDeleting={isMutating}
      />

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title="Delete this detection?"
        message={
          <>
            Record #{pendingDelete?.id} ({pendingDelete?.plant_name} -{' '}
            {pendingDelete?.predicted_disease}) and its stored image will be permanently removed.
          </>
        }
        confirmLabel="Delete"
        isWorking={isMutating}
        onConfirm={() => void handleDelete()}
        onCancel={() => setPendingDelete(null)}
      />

      <ConfirmDialog
        open={confirmClear}
        title="Clear the entire detection history?"
        message={
          <>
            All <strong>{pagination?.total ?? 0}</strong> records and their stored images will be
            deleted. Dashboard and analytics figures are computed from this table, so they will reset
            to zero. This cannot be undone.
          </>
        }
        confirmLabel="Delete everything"
        isWorking={isMutating}
        onConfirm={() => void handleClearAll()}
        onCancel={() => setConfirmClear(false)}
      />
    </div>
  );
}
