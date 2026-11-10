/**
 * useWebcam
 * =========
 * Laptop/USB webcam access through the browser's MediaDevices API.
 *
 * The backend plays no part in acquiring this image - the camera belongs to the
 * browser. The flow is: `getUserMedia` -> `<video>` preview -> draw the current
 * frame to a `<canvas>` -> `canvas.toBlob('image/jpeg')` -> POST to
 * `/api/predict`. From the POST onward it is byte-for-byte the same path an
 * ESP32-CAM frame takes.
 *
 * Browser constraints worth knowing, both handled here:
 *
 * * `navigator.mediaDevices` only exists in a **secure context**. `localhost`
 *   counts as secure; opening the dashboard over plain HTTP from another
 *   machine's LAN IP does not, and the API is simply absent rather than
 *   throwing something descriptive.
 * * Device *labels* are hidden until permission is granted, so the device list
 *   is re-enumerated after the stream starts to replace "Camera 1" with the
 *   real name.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export type WebcamPermission = 'unknown' | 'prompt' | 'granted' | 'denied';
export type WebcamStatus = 'idle' | 'starting' | 'live' | 'error' | 'unsupported';

export interface WebcamDevice {
  deviceId: string;
  label: string;
}

export interface CapturedFrame {
  file: File;
  previewUrl: string;
  width: number;
  height: number;
  sizeBytes: number;
}

export interface UseWebcamResult {
  videoRef: React.RefObject<HTMLVideoElement>;
  status: WebcamStatus;
  permission: WebcamPermission;
  error: string | null;
  isSupported: boolean;
  isSecureContext: boolean;
  devices: WebcamDevice[];
  activeDeviceId: string | null;
  resolution: { width: number; height: number } | null;
  start: (deviceId?: string) => Promise<void>;
  stop: () => void;
  capture: () => Promise<CapturedFrame | null>;
  refreshDevices: () => Promise<void>;
}

/** JPEG quality for the captured frame. 0.92 keeps leaf texture without bloating the upload. */
const CAPTURE_QUALITY = 0.92;

/**
 * Requested capture size.
 *
 * 1280x720 is requested rather than the maximum the sensor offers: the model
 * resizes to 224x224 anyway, so a larger frame only costs encode and upload
 * time. `ideal` (not `exact`) lets the browser fall back on cameras that cannot
 * deliver it instead of failing with OverconstrainedError.
 */
const VIDEO_CONSTRAINTS: MediaTrackConstraints = {
  width: { ideal: 1280 },
  height: { ideal: 720 },
  facingMode: 'environment',
};

function describeMediaError(error: unknown): string {
  if (!(error instanceof Error)) return 'The camera could not be started.';

  switch (error.name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
      return (
        'Camera permission was denied. Click the camera icon in the browser address bar, ' +
        'allow access to this site, then try again.'
      );
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return 'No camera was found on this computer. Connect a webcam and press Refresh.';
    case 'NotReadableError':
    case 'TrackStartError':
      return (
        'The camera is in use by another application. Close Zoom, Teams, OBS or any other ' +
        'app holding the camera, then try again.'
      );
    case 'OverconstrainedError':
      return 'This camera cannot provide the requested video format. Try a different camera.';
    case 'AbortError':
      return 'Starting the camera was interrupted. Try again.';
    case 'SecurityError':
      return 'The browser blocked camera access for this page because it is not a secure context.';
    default:
      return `The camera could not be started: ${error.message || error.name}`;
  }
}

export function useWebcam(): UseWebcamResult {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  const [status, setStatus] = useState<WebcamStatus>('idle');
  const [permission, setPermission] = useState<WebcamPermission>('unknown');
  const [error, setError] = useState<string | null>(null);
  const [devices, setDevices] = useState<WebcamDevice[]>([]);
  const [activeDeviceId, setActiveDeviceId] = useState<string | null>(null);
  const [resolution, setResolution] = useState<{ width: number; height: number } | null>(null);

  const isSecureContext = typeof window !== 'undefined' && window.isSecureContext;
  const isSupported =
    typeof navigator !== 'undefined' &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof HTMLCanvasElement !== 'undefined';

  /* ---- device enumeration ------------------------------------------- */

  const refreshDevices = useCallback(async () => {
    if (!isSupported || !navigator.mediaDevices.enumerateDevices) return;
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      setDevices(
        all
          .filter((device) => device.kind === 'videoinput')
          .map((device, index) => ({
            deviceId: device.deviceId,
            // The label is empty until permission is granted.
            label: device.label || `Camera ${index + 1}`,
          })),
      );
    } catch {
      // Enumeration failing is not fatal: start() still works with the default
      // camera, so the picker is simply left empty.
    }
  }, [isSupported]);

  /* ---- permission state --------------------------------------------- */

  useEffect(() => {
    if (!isSupported) {
      setStatus('unsupported');
      return;
    }

    void refreshDevices();

    // The Permissions API does not support 'camera' in every browser (notably
    // Safari), so a failure here just leaves the state as 'unknown'.
    if (!navigator.permissions?.query) return;

    let permissionStatus: PermissionStatus | null = null;
    const handleChange = () => {
      if (permissionStatus) setPermission(permissionStatus.state as WebcamPermission);
    };

    navigator.permissions
      .query({ name: 'camera' as PermissionName })
      .then((result) => {
        permissionStatus = result;
        setPermission(result.state as WebcamPermission);
        result.addEventListener('change', handleChange);
      })
      .catch(() => {
        /* unsupported - leave as 'unknown' */
      });

    return () => {
      permissionStatus?.removeEventListener('change', handleChange);
    };
  }, [isSupported, refreshDevices]);

  /* ---- lifecycle ----------------------------------------------------- */

  const stop = useCallback(() => {
    // Every track must be stopped individually or the camera indicator light
    // stays on even after the preview is removed.
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setStatus('idle');
    setResolution(null);
  }, []);

  const start = useCallback(
    async (deviceId?: string) => {
      setError(null);

      if (!isSupported) {
        setStatus('unsupported');
        setError(
          isSecureContext
            ? 'This browser does not support the MediaDevices API needed for webcam capture.'
            : 'Webcam capture needs a secure context. Open the dashboard at http://localhost:5173 ' +
              'instead of a LAN IP address, or serve it over HTTPS.',
        );
        return;
      }

      // Release any existing stream first; two concurrent streams on the same
      // device fail with NotReadableError on Windows.
      stop();
      setStatus('starting');

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: deviceId ? { ...VIDEO_CONSTRAINTS, deviceId: { exact: deviceId } } : VIDEO_CONSTRAINTS,
          audio: false,
        });

        streamRef.current = stream;
        setPermission('granted');

        const video = videoRef.current;
        if (!video) {
          stop();
          setStatus('error');
          setError('The video preview element is not mounted.');
          return;
        }

        video.srcObject = stream;
        await video.play().catch(() => {
          /* Autoplay can reject; the stream is still attached and visible. */
        });

        const track = stream.getVideoTracks()[0];
        const settings = track?.getSettings();
        setActiveDeviceId(settings?.deviceId ?? deviceId ?? null);
        setResolution({
          width: settings?.width ?? video.videoWidth,
          height: settings?.height ?? video.videoHeight,
        });

        setStatus('live');

        // Labels become readable only after permission is granted.
        void refreshDevices();
      } catch (caught) {
        stop();
        setStatus('error');
        setError(describeMediaError(caught));
        if (caught instanceof Error && caught.name === 'NotAllowedError') {
          setPermission('denied');
        }
      }
    },
    [isSupported, isSecureContext, stop, refreshDevices],
  );

  /* ---- capture -------------------------------------------------------- */

  const capture = useCallback(async (): Promise<CapturedFrame | null> => {
    const video = videoRef.current;
    if (!video || status !== 'live') {
      setError('Start the camera before capturing an image.');
      return null;
    }

    const width = video.videoWidth;
    const height = video.videoHeight;

    // A zero-sized frame means the stream has not delivered one yet. Capturing
    // it would produce a blank image that the backend would correctly reject,
    // so it is caught here with a clearer message.
    if (!width || !height) {
      setError('The camera has not produced a frame yet. Wait a moment and capture again.');
      return null;
    }

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;

    const context = canvas.getContext('2d');
    if (!context) {
      setError('This browser could not create a canvas to capture the frame.');
      return null;
    }
    context.drawImage(video, 0, 0, width, height);

    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', CAPTURE_QUALITY);
    });

    if (!blob || blob.size === 0) {
      setError('Encoding the captured frame to JPEG failed. Try capturing again.');
      return null;
    }

    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    const previewUrl = URL.createObjectURL(blob);
    objectUrlRef.current = previewUrl;

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const file = new File([blob], `webcam-${timestamp}.jpg`, { type: 'image/jpeg' });

    setError(null);
    return { file, previewUrl, width, height, sizeBytes: blob.size };
  }, [status]);

  /* ---- cleanup -------------------------------------------------------- */

  useEffect(
    () => () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    },
    [],
  );

  return {
    videoRef,
    status,
    permission,
    error,
    isSupported,
    isSecureContext,
    devices,
    activeDeviceId,
    resolution,
    start,
    stop,
    capture,
    refreshDevices,
  };
}

export default useWebcam;
