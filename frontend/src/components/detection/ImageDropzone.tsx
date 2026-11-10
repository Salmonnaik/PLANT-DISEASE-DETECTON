import { useCallback, useRef, useState, type DragEvent } from 'react';
import { ImageUp, Upload, X } from 'lucide-react';
import { classNames, formatBytes } from '@/utils/format';

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/bmp', 'image/webp'];
const ACCEPT_ATTRIBUTE = '.jpg,.jpeg,.png,.bmp,.webp';
const MAX_BYTES = 12 * 1024 * 1024;

interface ImageDropzoneProps {
  onSelect: (file: File) => void;
  onClear: () => void;
  selectedFile: File | null;
  previewUrl: string | null;
  disabled?: boolean;
}

/**
 * Drag-and-drop / click-to-browse image picker.
 *
 * Type and size are checked client-side purely as fast feedback; the backend
 * re-validates every byte (magic numbers, decodability, dimensions) because a
 * browser check is trivially bypassed and the firmware does not go through this
 * component at all.
 */
export function ImageDropzone({
  onSelect,
  onClear,
  selectedFile,
  previewUrl,
  disabled,
}: ImageDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const validateAndSelect = useCallback(
    (file: File) => {
      setLocalError(null);

      if (!ACCEPTED_TYPES.includes(file.type)) {
        setLocalError(
          `"${file.name}" is a ${file.type || 'unknown'} file. Choose a JPG, PNG, BMP or WebP image.`,
        );
        return;
      }
      if (file.size > MAX_BYTES) {
        setLocalError(
          `"${file.name}" is ${formatBytes(file.size)}; the limit is ${formatBytes(MAX_BYTES)}.`,
        );
        return;
      }
      onSelect(file);
    },
    [onSelect],
  );

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    if (disabled) return;
    const file = event.dataTransfer.files?.[0];
    if (file) validateAndSelect(file);
  };

  if (selectedFile && previewUrl) {
    return (
      <div className="space-y-3">
        <div className="relative overflow-hidden rounded-2xl border border-bark-200 bg-bark-900">
          <img
            src={previewUrl}
            alt={`Preview of ${selectedFile.name}`}
            className="mx-auto max-h-[22rem] w-auto object-contain"
          />
          <button
            type="button"
            onClick={onClear}
            disabled={disabled}
            className="absolute right-3 top-3 rounded-lg bg-bark-950/70 p-1.5 text-white backdrop-blur transition hover:bg-blight-600 disabled:opacity-50"
            aria-label="Remove selected image"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="min-w-0 truncate font-medium text-bark-700" title={selectedFile.name}>
            {selectedFile.name}
          </span>
          <span className="shrink-0 text-bark-400">{formatBytes(selectedFile.size)}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div
        role="button"
        tabIndex={0}
        aria-disabled={disabled}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(event) => {
          if (!disabled && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={classNames(
          'flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-all duration-200',
          disabled && 'cursor-not-allowed opacity-60',
          isDragging
            ? 'border-leaf-500 bg-leaf-50 scale-[1.01]'
            : 'border-bark-200 bg-bark-50/60 hover:border-leaf-400 hover:bg-leaf-50/50',
        )}
      >
        <span
          className={classNames(
            'flex h-14 w-14 items-center justify-center rounded-2xl transition-colors',
            isDragging ? 'bg-leaf-500 text-white' : 'bg-white text-leaf-600 shadow-card',
          )}
        >
          {isDragging ? <ImageUp className="h-7 w-7" /> : <Upload className="h-7 w-7" />}
        </span>
        <div>
          <p className="text-sm font-semibold text-bark-800">
            {isDragging ? 'Drop the image to load it' : 'Drag a leaf image here, or click to browse'}
          </p>
          <p className="mt-1 text-xs text-bark-500">
            JPG, PNG, BMP or WebP &middot; up to {formatBytes(MAX_BYTES)}
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_ATTRIBUTE}
          className="hidden"
          disabled={disabled}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) validateAndSelect(file);
            // Reset so selecting the same file twice still fires onChange.
            event.target.value = '';
          }}
        />
      </div>

      {localError && (
        <p className="rounded-lg bg-blight-50 px-3 py-2 text-sm text-blight-700" role="alert">
          {localError}
        </p>
      )}

      <p className="text-xs leading-relaxed text-bark-400">
        For the most reliable result: one leaf filling most of the frame, even lighting, plain
        background, and the camera held steady.
      </p>
    </div>
  );
}

export default ImageDropzone;
