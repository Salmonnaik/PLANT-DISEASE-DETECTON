/**
 * TypeScript mirrors of the Flask API payloads.
 *
 * These are hand-maintained against backend/routes/* and the result dictionary
 * built in ml/predict.py. Keeping them in one file means a backend field rename
 * surfaces as a compile error here rather than as `undefined` in the UI.
 */

/* ------------------------------------------------------------------ */
/* Envelope                                                            */
/* ------------------------------------------------------------------ */

export interface ApiEnvelope<T> {
  success: boolean;
  data: T;
  message: string | null;
  timestamp: string;
  error?: ApiErrorBody;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
}

export interface Pagination {
  total: number;
  limit: number;
  offset: number;
  page: number;
  pages: number;
  has_more: boolean;
}

export interface PaginatedData<T> {
  items: T[];
  pagination: Pagination;
}

/* ------------------------------------------------------------------ */
/* Predictions                                                         */
/* ------------------------------------------------------------------ */

export type DetectionStatus = 'healthy' | 'diseased' | 'uncertain' | 'unknown';

/** Transport that delivered the bytes to the API. */
export type DetectionSource = 'upload' | 'esp32cam';

/**
 * Which camera actually took the picture.
 *
 * Distinct from `DetectionSource` because an HTTP upload can be either a
 * browser webcam frame or a file chosen from disk.
 */
export type CameraSource = 'laptop_webcam' | 'esp32_cam' | 'file_upload' | 'unknown';
export type ModelMode = 'trained' | 'test' | 'unavailable';
export type Severity = 'none' | 'mild' | 'moderate' | 'severe' | 'unknown';

export interface ClassProbability {
  class: string;
  plant: string;
  disease: string;
  is_healthy: boolean;
  probability: number;
  probability_percent: number;
}

export interface ImageQualityMetrics {
  width: number;
  height: number;
  sharpness: number;
  brightness: number;
  contrast: number;
  plant_pixel_ratio: number;
}

export interface ImageQuality {
  passed: boolean;
  issues: string[];
  metrics: ImageQualityMetrics;
}

export interface DiseaseInfo {
  class: string;
  matched: boolean;
  description: string;
  symptoms: string[];
  management: string[];
  severity: Severity;
}

export interface PredictionModelInfo {
  mode: ModelMode;
  trained: boolean;
  base_model: string | null;
  num_classes: number;
}

export interface Prediction {
  success: boolean;
  is_conclusive: boolean;
  /** True only when a genuinely trained model produced the result. */
  is_validated_prediction: boolean;
  plant_name: string;
  predicted_class: string | null;
  predicted_disease: string;
  display_label: string;
  detection_status: DetectionStatus;
  is_healthy: boolean | null;
  confidence: number;
  confidence_percent: number;
  confidence_threshold: number;
  reason: string | null;
  top_predictions: ClassProbability[];
  class_probabilities: ClassProbability[];
  disease_info: DiseaseInfo | null;
  image_quality: ImageQuality;
  model: PredictionModelInfo;
  inference_ms: number;
  warnings: string[];
}

export interface StoredImageInfo {
  url: string | null;
  path: string | null;
  filename: string | null;
  format: string;
  width: number;
  height: number;
  size_bytes: number;
  sha256: string;
  stored: boolean;
}

export interface CaptureInfo {
  transport: string;
  ip_address?: string | null;
  job_id?: string;
  device_name?: string;
  transfer_ms?: number;
  content_type?: string;
  led_used?: boolean;
  pull_error?: string | null;
}

export interface DetectionRecord {
  id: number;
  image_path: string;
  image_url: string | null;
  image_filename: string | null;
  image_size_bytes: number | null;
  plant_name: string;
  predicted_disease: string;
  predicted_class: string | null;
  confidence: number;
  confidence_percent: number;
  confidence_threshold: number | null;
  detection_status: DetectionStatus;
  is_healthy: boolean;
  is_conclusive: boolean;
  is_validated: boolean;
  model_mode: 'trained' | 'test';
  source: DetectionSource;
  camera_source: CameraSource;
  camera_source_label: string;
  device_name: string | null;
  inference_ms: number | null;
  probabilities: ClassProbability[];
  image_quality: ImageQuality | null;
  notes: string | null;
  created_at: string;
  /** Universal analysis fields; null on classifier-only records. */
  plant_species?: string | null;
  species_source?: SpeciesSource | null;
  analysis_mode?: 'classifier' | 'universal';
  confidence_level?: ConfidenceLevel | null;
  analysis?: UniversalAnalysis | null;
  symptoms?: DetectedSymptom[];
}

export interface DetectionResponse {
  detection_id: number | null;
  /** Classifier output. In universal mode this is a shim with confidence 0. */
  prediction: Prediction;
  detection: DetectionRecord | null;
  image: StoredImageInfo;
  capture: CaptureInfo | null;
  source: DetectionSource;
  camera_source: CameraSource;
  camera_source_label: string;
  model_mode: ModelMode;
  is_validated_prediction: boolean;
  /** 'universal' when /api/analyze-plant produced this result. */
  analysis_mode?: 'classifier' | 'universal';
  /** Present only in universal mode. */
  analysis?: UniversalAnalysis | null;
}

/* ------------------------------------------------------------------ */
/* Cameras                                                             */
/* ------------------------------------------------------------------ */

export interface CameraAddresses {
  dashboard: string | null;
  env: string | null;
  discovered: string | null;
  effective: string | null;
  effective_from: 'dashboard' | 'env' | 'heartbeat' | 'none';
}

export interface CameraInfo {
  id: CameraSource;
  label: string;
  description: string;
  /** 'backend' for the ESP32-CAM, 'browser' for the laptop webcam. */
  managed_by: 'backend' | 'browser';
  enabled: boolean;
  /** null when only the browser can determine availability. */
  available: boolean | null;
  status: 'online' | 'offline' | 'browser_managed';
  supports_led: boolean;
  supports_remote_capture: boolean;
  detections_recorded: number;
  capture_endpoint: string;
  requirements: string[];
  notes?: string;
  device?: DeviceStatus | null;
  addresses?: CameraAddresses;
  effective_address?: string | null;
  base_url?: string | null;
  push_fallback_enabled?: boolean;
  live_probe?: {
    reachable: boolean;
    ip_address: string | null;
    latency_ms?: number;
    reason?: string;
  } | null;
}

export interface SharedPipelineInfo {
  endpoint: string;
  model: string | null;
  model_mode: ModelMode;
  num_classes: number;
  image_size: number[];
  input_scaling: string;
  confidence_threshold: number;
  quality_gate_enabled: boolean;
}

export interface CamerasResponse {
  cameras: CameraInfo[];
  default_camera_source: CameraSource;
  valid_camera_sources: CameraSource[];
  file_upload: {
    id: CameraSource;
    label: string;
    description: string;
    enabled: boolean;
    detections_recorded: number;
    capture_endpoint: string;
  };
  shared_pipeline: SharedPipelineInfo;
}

export interface DeviceConfigResponse {
  device_name: string;
  addresses: CameraAddresses;
  port: number;
  base_url: string | null;
  capture_path: string;
  status_path: string;
  led_path: string;
}

/* ------------------------------------------------------------------ */
/* Universal plant analysis                                            */
/* ------------------------------------------------------------------ */

export type ConfidenceLevel = 'confident' | 'probable' | 'possible' | 'insufficient';
export type AssessmentKind =
  | 'healthy'
  | 'condition_identified'
  | 'symptoms_observed'
  | 'insufficient_evidence';
export type SymptomSeverity = 'mild' | 'moderate' | 'severe';
export type SupportLevel = 'strong' | 'moderate' | 'weak';
export type SpeciesSource =
  | 'user_declared'
  | 'ai_vision_api'
  | 'trained_classifier'
  | 'unidentified';

export interface DetectedSymptom {
  id: string;
  label: string;
  severity: SymptomSeverity;
  /** The measurement that triggered this symptom, in checkable terms. */
  evidence: string;
  metric: number;
  category: 'colour' | 'lesion' | 'structure' | 'surface';
}

export interface ConditionCandidate {
  id: string;
  label: string;
  category: 'fungal' | 'bacterial' | 'viral' | 'pest' | 'abiotic' | 'none';
  support: SupportLevel;
  is_disease: boolean;
  matched_evidence: string[];
  conflicting_evidence: string[];
  possible_causes: string[];
  confirm_by: string[];
  /** Always false - this layer produces possibilities, not diagnoses. */
  is_diagnosis: boolean;
}

export interface ChemicalOptions {
  active_ingredient_classes: string[];
  requires_verification: boolean;
  /** Application and safety precautions for this condition. */
  precautions?: string[];
}

export interface SeverityEstimate {
  level: 'none' | 'mild' | 'moderate' | 'severe' | 'unknown';
  label: string;
  rank: number;
  guidance: string;
  /** Percentage of the leaf area measured as damaged. */
  damage_percent: number;
  /** Always true - severity is estimated from one leaf, not measured on the plant. */
  is_estimate: boolean;
  basis: string;
}

export interface CauseCategory {
  id: string;
  label: string;
  icon: string;
  reasons: string[];
}

export interface CauseBreakdown {
  categories: CauseCategory[];
  detailed: string[];
  note: string;
}

export interface TreatmentPlan {
  condition_id: string | null;
  matched: boolean;
  immediate_actions: string[];
  organic_options: string[];
  cultural_controls: string[];
  chemical_options: ChemicalOptions | null;
  prevention: string[];
  /** True when chemicals were hidden because the assessment is uncertain. */
  chemical_withheld: boolean;
  withheld_reason: string | null;
  chemical_disclaimer: string;
}

export interface PlantIdentification {
  name: string;
  declared_name: string | null;
  scientific_name: string | null;
  category: string;
  species_id: string | null;
  identified: boolean;
  identification_source: SpeciesSource;
  certainty: string;
  in_knowledge_base: boolean;
  common_issues: string[];
}

export interface AiVisionResult {
  available: boolean;
  attempted?: boolean;
  provider?: string | null;
  model?: string | null;
  reason?: string;
  plant_species?: string | null;
  species_certainty?: string;
  observed_symptoms?: string[];
  candidate_conditions?: { name: string; reasoning: string; certainty: string }[];
  possible_causes?: string[];
  uncertainty_notes?: string | null;
  latency_ms?: number;
}

export interface UniversalAnalysis {
  schema_version: number;
  assessment: AssessmentKind;
  confidence_level: ConfidenceLevel;
  basis: string;
  /** Always false. A confirmed diagnosis needs lab testing or expert inspection. */
  is_confirmed_diagnosis: boolean;
  plant: PlantIdentification;
  condition: {
    id: string | null;
    label: string;
    candidates: ConditionCandidate[];
    summary: string | null;
    /** Clinical reference text for the "Disease Information" panel. */
    description: string;
    references: string[];
    cause_categories: string[];
  };
  severity: SeverityEstimate;
  causes: CauseBreakdown;
  symptoms: {
    detected: DetectedSymptom[];
    appears_healthy: boolean | null;
    evidence_level: string;
    damage_fraction: number;
    leaf_detected: boolean;
    segmentation_quality: string;
    notes: string[];
    ai_described: string[];
  };
  treatment: TreatmentPlan;
  care: {
    watering: string | null;
    soil: string | null;
    light: string | null;
    feeding: string | null;
    pruning: string | null;
    prevention: string[];
  };
  next_steps: string[];
  limitations: string[];
  evidence_sources: {
    used: string[];
    local_cv: { used: boolean; metrics: Record<string, unknown>; method: string };
    ai_vision: AiVisionResult;
    classifier: {
      used: boolean;
      note: string | null;
      covers_species: string[];
      prediction: Record<string, unknown> | null;
      model_mode: string;
    };
  };
}

export interface PlantSpecies {
  id: string;
  common_name: string;
  scientific_name: string | null;
  category: string;
  common_issues: string[];
}

export interface PlantsResponse {
  count: number;
  species: PlantSpecies[];
  categories: string[];
  supports_unlisted: boolean;
  unlisted_note: string;
  classifier_species: string[];
  classifier_note: string;
  ai_vision: AiVisionResult & { capability_note?: string };
}

export interface CameraSourceStat {
  camera_source: CameraSource;
  label: string;
  count: number;
  healthy: number;
  diseased: number;
  avg_confidence: number;
  last_used: string | null;
  colour: string;
}

/* ------------------------------------------------------------------ */
/* Health, model and classes                                           */
/* ------------------------------------------------------------------ */

export interface ModelMetrics {
  accuracy?: number;
  top3_accuracy?: number;
  healthy_vs_diseased_accuracy?: number;
  macro_precision?: number;
  macro_recall?: number;
  macro_f1?: number;
  weighted_f1?: number;
  test_samples?: number;
}

export interface ModelStatus {
  loaded: boolean;
  trained: boolean;
  mode: ModelMode;
  is_test_mode: boolean;
  can_predict: boolean;
  allow_test_mode_model: boolean;
  model_path: string;
  model_file_exists: boolean;
  labels_path: string;
  labels_file_exists: boolean;
  num_classes: number;
  class_names: string[];
  image_size: number[];
  input_scaling: string;
  confidence_threshold: number;
  base_model: string | null;
  trained_at: string | null;
  tensorflow_version: string | null;
  metrics: ModelMetrics;
  error: string | null;
  message: string;
}

export interface HealthResponse {
  status: 'healthy' | 'degraded';
  problems: string[];
  app: {
    name: string;
    version: string;
    uptime_seconds: number;
    python_version: string;
    platform: string;
    debug: boolean;
  };
  database: {
    connected: boolean;
    path: string;
    detection_records: number | null;
    device_records: number | null;
    error: string | null;
  };
  model: ModelStatus;
  device: {
    configured_ip: string | null;
    configured_name: string;
    resolved_ip: string | null;
    primary: DeviceStatus | null;
    is_online: boolean;
  };
  storage: {
    upload_folder: string;
    files: number;
    total_bytes: number;
    total_mb: number;
  };
  config: Record<string, unknown>;
  universal_analysis?: {
    enabled: boolean;
    method: string;
    species_agnostic: boolean;
    note: string;
  };
  ai_vision?: AiVisionResult & { capability_note?: string };
}

export interface ParsedClass {
  raw: string;
  plant: string;
  disease: string;
  display: string;
  is_healthy: boolean;
  status: 'healthy' | 'diseased';
}

export interface ClassesResponse {
  num_classes: number;
  classes: ParsedClass[];
  plants: Record<
    string,
    { index: number; class: string; disease: string; is_healthy: boolean; severity: Severity }[]
  >;
  plant_names: string[];
  reference_entries: string[];
  confidence_threshold: number;
  model_mode: ModelMode;
}

/* ------------------------------------------------------------------ */
/* Statistics                                                          */
/* ------------------------------------------------------------------ */

export interface DistributionItem {
  name: string;
  disease: string;
  plant: string;
  count: number;
  percentage: number;
  avg_confidence: number;
  colour: string;
}

export interface PlantDistributionItem {
  plant: string;
  total: number;
  healthy: number;
  diseased: number;
  inconclusive: number;
  avg_confidence: number;
  colour: string;
}

export interface ActivityPoint {
  date: string;
  label: string;
  total: number;
  healthy: number;
  diseased: number;
  inconclusive: number;
}

export interface ConfidenceSummary {
  samples: number;
  average: number;
  minimum: number;
  maximum: number;
  average_percent: number;
}

export interface StatsResponse {
  totals: {
    total_detections: number;
    healthy: number;
    diseased: number;
    uncertain: number;
    unknown: number;
    inconclusive: number;
    today: number;
    test_mode_records: number;
  };
  rates: {
    healthy_percent: number;
    diseased_percent: number;
    inconclusive_percent: number;
  };
  confidence: ConfidenceSummary;
  sources: Record<string, number>;
  camera_sources: CameraSourceStat[];
  disease_distribution: DistributionItem[];
  plant_distribution: PlantDistributionItem[];
  activity: ActivityPoint[];
  recent_detections: DetectionRecord[];
  last_detection_at: string | null;
  is_empty: boolean;
}

export interface PerClassMetric {
  class: string;
  plant: string;
  disease: string;
  precision: number;
  recall: number;
  f1_score: number;
  support: number;
}

export interface EvaluationMetrics {
  evaluated_at: string;
  num_classes: number;
  test_samples: number;
  accuracy: number;
  top3_accuracy: number;
  healthy_vs_diseased_accuracy: number;
  macro: { precision: number; recall: number; f1_score: number };
  weighted: { precision: number; recall: number; f1_score: number };
  confidence: {
    mean: number;
    mean_when_correct: number | null;
    mean_when_wrong: number | null;
  };
  per_class: PerClassMetric[];
  confusion_matrix: number[][];
  class_names: string[];
  suggested_confidence_threshold?: number;
}

export interface ModelEvaluation {
  available: boolean;
  reason?: string;
  reports_dir: string;
  metrics?: EvaluationMetrics;
  training_history?: Record<string, number[]>;
  artefacts?: Record<string, boolean>;
}

export interface AnalyticsResponse {
  window_days: number;
  totals: {
    total_detections: number;
    healthy: number;
    diseased: number;
    inconclusive: number;
    test_mode_records: number;
  };
  healthy_vs_diseased: { name: string; count: number; colour: string }[];
  disease_distribution: DistributionItem[];
  disease_distribution_with_healthy: DistributionItem[];
  plant_distribution: PlantDistributionItem[];
  activity: ActivityPoint[];
  confidence_distribution: { range: string; count: number; colour: string }[];
  confidence: ConfidenceSummary;
  sources: Record<string, number>;
  camera_sources: CameraSourceStat[];
  top_conditions: {
    plant: string;
    disease: string;
    count: number;
    avg_confidence: number;
    last_seen: string | null;
  }[];
  model_evaluation: ModelEvaluation;
  model_status: ModelStatus;
  is_empty: boolean;
  generated_at: string;
}

/* ------------------------------------------------------------------ */
/* Device                                                              */
/* ------------------------------------------------------------------ */

export interface DeviceStatus {
  id: number | null;
  device_name: string;
  ip_address: string | null;
  connection_status: 'online' | 'offline' | 'error';
  is_online: boolean;
  last_seen: string | null;
  seconds_since_last_seen: number | null;
  offline_after_seconds: number;
  mac_address: string | null;
  wifi_ssid: string | null;
  wifi_rssi: number | null;
  wifi_signal_quality: 'excellent' | 'good' | 'fair' | 'weak' | null;
  firmware_version: string | null;
  camera_model: string | null;
  led_state: 'on' | 'off';
  free_heap: number | null;
  uptime_seconds: number | null;
  last_capture_at: string | null;
  seconds_since_last_capture: number | null;
  total_captures: number;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TroubleshootingItem {
  severity: 'ok' | 'info' | 'warning' | 'error';
  title: string;
  detail: string;
}

export interface CaptureJobSnapshot {
  job_id: string;
  device_name: string;
  led: boolean;
  status: 'pending' | 'dispatched' | 'completed' | 'failed';
  age_seconds: number;
  error: string | null;
  image_bytes: number;
}

export interface DeviceStatusResponse {
  device: DeviceStatus | null;
  is_online: boolean;
  configured: {
    device_name: string;
    static_ip: string | null;
    resolved_ip: string | null;
    capture_path: string;
    status_path: string;
    led_path: string;
    offline_after_seconds: number;
    push_fallback_enabled: boolean;
    device_key_required: boolean;
  };
  live_probe: {
    reachable: boolean;
    ip_address: string | null;
    latency_ms?: number;
    reason?: string;
    device_report?: Record<string, unknown>;
  } | null;
  pending_capture_jobs: CaptureJobSnapshot[];
  troubleshooting: TroubleshootingItem[];
}

export interface HistoryFilters {
  plants: string[];
  diseases: string[];
  sources: string[];
  statuses: string[];
  camera_sources: { value: CameraSource; label: string; count: number }[];
  camera_source_options: { value: CameraSource; label: string }[];
  total_records: number;
}

export interface HistoryQuery {
  limit?: number;
  offset?: number;
  status?: string;
  plant?: string;
  disease?: string;
  source?: string;
  camera_source?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
}
