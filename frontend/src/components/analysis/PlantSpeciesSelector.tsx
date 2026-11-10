import { useMemo, useState } from 'react';
import { Info, Leaf, Search, Sparkles, X } from 'lucide-react';
import { usePlants } from '@/hooks';
import { Notice } from '@/components/ui';
import { classNames } from '@/utils/format';

interface PlantSpeciesSelectorProps {
  value: string | null;
  onChange: (species: string | null) => void;
  disabled?: boolean;
}

/**
 * Plant species picker.
 *
 * Prominent by design. Declaring the species is the most reliable way the
 * system learns what plant it is looking at - more reliable than the ten-class
 * classifier and more reliable than an AI vision guess - and it is what turns
 * generic advice into species-specific care guidance.
 *
 * Deliberately optional, and free text is accepted. A plant that is not in the
 * knowledge base still gets analysed; it simply receives general care advice,
 * and the UI says so rather than silently substituting another plant's.
 */
export function PlantSpeciesSelector({ value, onChange, disabled }: PlantSpeciesSelectorProps) {
  const { data } = usePlants();
  const [query, setQuery] = useState('');
  const [showAll, setShowAll] = useState(false);

  const species = data?.species ?? [];

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return species;
    return species.filter(
      (item) =>
        item.common_name.toLowerCase().includes(term) ||
        (item.scientific_name ?? '').toLowerCase().includes(term) ||
        item.category.toLowerCase().includes(term),
    );
  }, [species, query]);

  const visible = showAll || query.trim() ? filtered : filtered.slice(0, 8);
  const isCustom = Boolean(value) && !species.some((item) => item.common_name === value);

  return (
    <div className="space-y-3">
      <div>
        <label className="label mb-1.5" htmlFor="species-search">
          <Leaf className="mr-1 inline h-3 w-3" />
          Which plant is this? <span className="font-normal normal-case text-bark-400">(optional, but improves the advice)</span>
        </label>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-bark-300" />
          <input
            id="species-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search 15 plants, or type any plant name below..."
            className="input pl-9"
            disabled={disabled}
          />
        </div>
      </div>

      {/* ---- Selected ---- */}
      {value && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-leaf-200 bg-leaf-50 px-3.5 py-2.5">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-leaf-900">{value}</p>
            <p className="text-xs text-leaf-700">
              {isCustom
                ? 'Not in the care database - general plant-care guidance will be shown'
                : 'Species-specific care and prevention guidance will be shown'}
            </p>
          </div>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="btn-ghost btn-sm shrink-0 text-leaf-700"
            disabled={disabled}
          >
            <X className="h-3.5 w-3.5" />
            Clear
          </button>
        </div>
      )}

      {/* ---- Grid ---- */}
      <div className="flex flex-wrap gap-1.5">
        {visible.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onChange(item.common_name === value ? null : item.common_name)}
            disabled={disabled}
            title={`${item.scientific_name ?? item.common_name} - ${item.category}`}
            className={classNames(
              'rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors',
              item.common_name === value
                ? 'border-leaf-500 bg-leaf-600 text-white'
                : 'border-bark-200 bg-white text-bark-600 hover:border-leaf-300 hover:bg-leaf-50 hover:text-leaf-800',
            )}
          >
            {item.common_name}
          </button>
        ))}

        {!showAll && !query.trim() && filtered.length > 8 && (
          <button
            type="button"
            onClick={() => setShowAll(true)}
            className="rounded-lg border border-dashed border-bark-300 px-2.5 py-1.5 text-xs font-medium text-bark-500 hover:border-leaf-300 hover:text-leaf-700"
          >
            +{filtered.length - 8} more
          </button>
        )}

        {query.trim() && filtered.length === 0 && (
          <button
            type="button"
            onClick={() => {
              onChange(query.trim());
              setQuery('');
            }}
            disabled={disabled}
            className="rounded-lg border border-leaf-300 bg-leaf-50 px-2.5 py-1.5 text-xs font-semibold text-leaf-800"
          >
            Use &ldquo;{query.trim()}&rdquo; anyway
          </button>
        )}
      </div>

      {/* ---- Capability note ---- */}
      {data && (
        <Notice tone="info" icon={<Info className="h-4 w-4" />}>
          <p>
            <strong>Any plant can be analysed.</strong> Symptoms are measured from the image
            itself, which does not depend on the species.
          </p>
          <p className="mt-1">
            The trained classifier only covers{' '}
            <strong>{data.classifier_species.join(', ')}</strong>. For every other plant the
            system measures visible symptoms and lists possible causes rather than forcing a
            classifier label onto it.
          </p>
          {!data.ai_vision.available && (
            <p className="mt-1 inline-flex items-start gap-1.5">
              <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Automatic species identification needs an AI vision API key, which is not
                configured. Selecting the plant above is the reliable alternative.
              </span>
            </p>
          )}
        </Notice>
      )}
    </div>
  );
}

export default PlantSpeciesSelector;
