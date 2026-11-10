import { useState } from 'react';
import {
  Binary,
  BookOpen,
  Camera,
  CircuitBoard,
  Cpu,
  Database,
  FileText,
  FlaskConical,
  Layers,
  Lightbulb,
  ListChecks,
  Network,
  Rocket,
  Target,
  TriangleAlert,
} from 'lucide-react';
import { useSystemStatus } from '@/layouts/SystemStatusProvider';
import { useClasses } from '@/hooks';
import { Card, CardBody, CardHeader, Notice } from '@/components/ui';
import { classNames, formatFraction } from '@/utils/format';

/* ------------------------------------------------------------------ */
/* Static project documentation                                        */
/* ------------------------------------------------------------------ */

const HARDWARE = [
  {
    name: 'ESP32-CAM (AI Thinker)',
    detail:
      'Dual-core 240 MHz ESP32-S with 520 KB SRAM plus 4 MB PSRAM, integrated 802.11 b/g/n Wi-Fi, and a camera interface. The PSRAM is what makes VGA and larger JPEG frames possible.',
  },
  {
    name: 'OV2640 camera module',
    detail:
      '2 MP CMOS sensor with on-chip JPEG compression, delivering frames from 96x96 up to 1600x1200. Compressing on the sensor keeps the Wi-Fi transfer small.',
  },
  {
    name: 'White LED + 220 Ω resistor',
    detail:
      'Driven from GPIO 4 to give repeatable illumination. Controlled lighting is what makes two scans of the same leaf comparable; the resistor limits current to a safe ~15 mA.',
  },
  {
    name: 'USB-to-TTL programmer',
    detail:
      'The ESP32-CAM has no USB port, so a CP2102 or FT232 adapter supplies the serial link for flashing at 115200 baud.',
  },
];

const SOFTWARE_LAYERS = [
  {
    icon: Camera,
    title: 'Firmware (Arduino C++)',
    items: [
      'Joins Wi-Fi and reports telemetry by HTTP heartbeat',
      'Serves /capture, /status and /led endpoints',
      'Polls the backend for dashboard-triggered captures',
      'Drives the white LED around each frame grab',
    ],
  },
  {
    icon: Cpu,
    title: 'Backend (Python / Flask)',
    items: [
      'REST API with a single JSON envelope and error codes',
      'Multi-layer image validation before any inference',
      'SQLite persistence for detections and device state',
      'Pull and push capture transports with clear failures',
    ],
  },
  {
    icon: Layers,
    title: 'Machine learning (TensorFlow / Keras)',
    items: [
      'MobileNetV2 base pre-trained on ImageNet',
      'Two-stage transfer learning: head, then fine-tuning',
      'Augmentation, class weights, held-out test split',
      'Accuracy, precision, recall, F1 and confusion matrix',
    ],
  },
  {
    icon: Network,
    title: 'Frontend (React / TypeScript)',
    items: [
      'Seven pages over the same typed API client',
      'Recharts visualisations driven by live backend data',
      'Explicit empty, loading and error states throughout',
      'Permanent banner whenever the model is untrained',
    ],
  },
];

const FUTURE_SCOPE = [
  {
    title: 'On-device inference with TensorFlow Lite',
    detail:
      'Quantise the trained model to int8 and run it on the ESP32-S3, removing the Wi-Fi round-trip and the dependency on a server being up.',
  },
  {
    title: 'Severity estimation, not just classification',
    detail:
      'Add a segmentation head to measure the affected leaf area as a percentage, which is what actually drives a spraying decision.',
  },
  {
    title: 'Wider crop and disease coverage',
    detail:
      'Extend beyond the ten PlantVillage classes to locally relevant crops, with field-captured images rather than laboratory backgrounds.',
  },
  {
    title: 'Environmental sensor fusion',
    detail:
      'Combine the image prediction with temperature and humidity readings, since late blight risk is largely driven by sustained leaf wetness.',
  },
  {
    title: 'Solar power and LoRa backhaul',
    detail:
      'Replace mains power and Wi-Fi with a solar panel and LoRaWAN so nodes can sit in a field rather than near a router.',
  },
  {
    title: 'Mobile application and alerting',
    detail:
      'Push a notification when a severe disease is detected, so the grower does not have to be watching the dashboard.',
  },
];

const LIMITATIONS = [
  'PlantVillage images are captured on plain backgrounds in controlled lighting. Accuracy on cluttered field photographs is materially lower, and the published accuracy figure should not be read as field accuracy.',
  'The model can only output one of the classes it was trained on. An unseen crop or disease will be mapped to the nearest known class, which is why the confidence threshold and the uncertain outcome exist.',
  'Classification is per leaf, not per plant. Several leaves in one frame, or a whole-plant photograph, breaks the assumption the model was trained under.',
  'Inference runs on the server, so the system needs a reachable backend on the local network; the camera alone cannot diagnose anything.',
  'The ESP32-CAM browns out below roughly 5 V at 500 mA, which usually shows up as repeated camera init failures rather than an obvious power fault.',
];

const TESTING = [
  {
    stage: 'Unit level',
    detail:
      'Label parsing, image quality measurement and class-weight computation are exercised through the module self-checks (python ml/label_utils.py, python ml/preprocessing.py).',
  },
  {
    stage: 'Model level',
    detail:
      'evaluate.py scores the model on a held-out test split built with the same seed as training, producing accuracy, per-class precision/recall/F1 and the confusion matrix.',
  },
  {
    stage: 'API level',
    detail:
      'scripts/smoke_test.py exercises every endpoint against a running backend: health, classes, upload prediction, malformed input rejection, history pagination, statistics and device status.',
  },
  {
    stage: 'Protocol level',
    detail:
      'scripts/simulate_esp32cam.py speaks the real firmware protocol (heartbeat, command poll, image upload), which verifies the capture pipeline end-to-end without hardware.',
  },
  {
    stage: 'Hardware level',
    detail:
      'With the board flashed, the serial monitor at 115200 baud confirms Wi-Fi association, camera initialisation, LED switching and HTTP status codes for each upload.',
  },
];

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

type TabKey = 'overview' | 'architecture' | 'model' | 'testing' | 'future';

const TABS: { key: TabKey; label: string; icon: typeof BookOpen }[] = [
  { key: 'overview', label: 'Abstract & problem', icon: FileText },
  { key: 'architecture', label: 'Architecture & hardware', icon: CircuitBoard },
  { key: 'model', label: 'ML methodology', icon: Binary },
  { key: 'testing', label: 'Testing & limitations', icon: ListChecks },
  { key: 'future', label: 'Future scope', icon: Rocket },
];

export default function AboutPage() {
  const [tab, setTab] = useState<TabKey>('overview');
  const { health } = useSystemStatus();
  const { data: classes } = useClasses();

  const model = health?.model;
  const metrics = model?.metrics;

  return (
    <div className="space-y-5">
      {/* ---- Title ---- */}
      <Card className="overflow-hidden">
        <div className="bg-leaf-gradient px-6 py-7 text-white">
          <span className="badge bg-white/15 text-leaf-50">Major project documentation</span>
          <h1 className="mt-3 text-2xl font-bold tracking-tight text-white sm:text-3xl">
            AI-Based Smart Plant Disease Detection and Classification Using ESP32-CAM and Deep
            Learning
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-leaf-50/90">
            An end-to-end IoT and machine learning system: an ESP32-CAM with controlled white-LED
            illumination acquires leaf images, a Flask service validates and classifies them with a
            MobileNetV2 convolutional network, and a React dashboard presents the diagnosis together
            with the confidence and evidence behind it.
          </p>
        </div>
      </Card>

      {/* ---- Tabs ---- */}
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            className={classNames(
              'inline-flex shrink-0 items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors',
              tab === item.key
                ? 'bg-leaf-600 text-white shadow-glow-leaf'
                : 'border border-bark-200 bg-white text-bark-600 hover:border-leaf-300 hover:text-leaf-700',
            )}
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </button>
        ))}
      </div>

      {/* ---- Overview ---- */}
      {tab === 'overview' && (
        <div className="animate-fade-in space-y-5">
          <Card>
            <CardHeader title="Abstract" icon={<FileText className="h-4 w-4" />} />
            <CardBody className="prose-doc">
              <p>
                Plant disease is one of the largest controllable causes of crop loss, and most
                infections are visible on the leaf well before yield is affected. The practical
                barrier is not treatment but <strong>timely diagnosis</strong>: identifying a
                specific pathogen from leaf symptoms requires training that is unavailable on most
                smallholdings, and manual scouting across a field is slow and inconsistent.
              </p>
              <p>
                This project implements a complete diagnostic loop from two hardware components. An
                ESP32-CAM module with an OV2640 sensor captures a leaf image under a white LED that
                provides consistent illumination; the JPEG is transferred over Wi-Fi by HTTP to a
                Python Flask service; a MobileNetV2 convolutional neural network, adapted by
                transfer learning from ImageNet to the PlantVillage dataset, produces a probability
                distribution over the trained disease classes; and the result, with its confidence
                and full probability vector, is stored in SQLite and presented in a React dashboard.
              </p>
              <p>
                The design priority is <strong>calibrated honesty</strong> rather than headline
                accuracy. Images are gated on sharpness, exposure, contrast and leaf coverage before
                inference, and a frame that fails is reported as unusable instead of being
                classified. A prediction below a configurable confidence threshold is returned as
                uncertain, naming no disease. When the loaded model has not been trained, every API
                response is flagged and the dashboard displays a permanent warning. The intent is
                that no screen in this system can mislead a user into acting on a result the model
                cannot support.
              </p>
            </CardBody>
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader title="Problem statement" icon={<TriangleAlert className="h-4 w-4" />} />
              <CardBody className="prose-doc">
                <p>
                  Existing approaches to plant disease identification fall into two groups, and
                  neither closes the loop:
                </p>
                <ul className="list-inside list-disc space-y-1.5">
                  <li>
                    <strong>Manual expert inspection</strong> is accurate but does not scale.
                    It depends on scarce expertise, is subjective between inspectors, and cannot
                    cover a field frequently enough to catch a fast pathogen such as late blight.
                  </li>
                  <li>
                    <strong>Phone-based classifier apps</strong> scale but depend on a person
                    deciding to photograph the right leaf at the right time, with no record of what
                    was scanned, when, or how confident the model was.
                  </li>
                </ul>
                <p>
                  What is missing is an inexpensive, fixed-position imaging node that captures under
                  repeatable lighting, classifies automatically, and keeps an auditable history -
                  while being explicit about the cases it cannot decide.
                </p>
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Proposed solution" icon={<Target className="h-4 w-4" />} />
              <CardBody className="prose-doc">
                <p>A four-layer system in which each layer can be developed and tested alone:</p>
                <ol className="list-inside list-decimal space-y-1.5">
                  <li>
                    <strong>Acquisition.</strong> ESP32-CAM firmware controls the white LED, grabs a
                    JPEG frame, and moves it to the server by HTTP - either pulled by the backend or
                    pushed by the board when direct access is blocked.
                  </li>
                  <li>
                    <strong>Validation and inference.</strong> Flask verifies the bytes really are a
                    decodable image, measures quality, and runs the trained CNN.
                  </li>
                  <li>
                    <strong>Persistence.</strong> Every outcome - including uncertain and unusable -
                    is written to SQLite with its image, probabilities and timestamp.
                  </li>
                  <li>
                    <strong>Presentation.</strong> The dashboard renders live statistics computed
                    from those records, never from sample data.
                  </li>
                </ol>
              </CardBody>
            </Card>
          </div>

          <Card>
            <CardHeader title="Objectives" icon={<ListChecks className="h-4 w-4" />} />
            <CardBody>
              <ol className="grid gap-3 sm:grid-cols-2">
                {[
                  'Build an ESP32-CAM imaging node with white-LED illumination controllable from both the board and the dashboard.',
                  'Transfer captured images reliably to a Flask REST API over a local Wi-Fi network.',
                  'Train a MobileNetV2 transfer-learning classifier on PlantVillage and evaluate it on a held-out test split.',
                  'Report accuracy, precision, recall, F1-score and a confusion matrix rather than accuracy alone.',
                  'Reject unusable images and refuse to name a disease below a configurable confidence threshold.',
                  'Persist every detection in SQLite so results are reviewable and statistics are derived, not invented.',
                  'Present the system through a responsive dashboard covering detection, history, analytics and device management.',
                  'Keep the untrained-model case visible at every layer so test runs cannot be mistaken for real diagnoses.',
                ].map((objective, index) => (
                  <li key={objective} className="flex gap-3 rounded-xl bg-bark-50 px-3.5 py-3">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-leaf-600 text-xs font-bold text-white">
                      {index + 1}
                    </span>
                    <span className="text-sm leading-relaxed text-bark-600">{objective}</span>
                  </li>
                ))}
              </ol>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Literature review outline"
              subtitle="The work this project builds on"
              icon={<BookOpen className="h-4 w-4" />}
            />
            <CardBody className="prose-doc">
              <ul className="list-inside list-disc space-y-2">
                <li>
                  <strong>Deep learning for plant disease classification.</strong> Mohanty, Hughes
                  and Salathé (2016) established the PlantVillage benchmark, reporting above 99%
                  accuracy with AlexNet and GoogLeNet on 54,306 laboratory images - and noted the
                  sharp drop on field imagery that motivates this project's caution about reporting
                  accuracy.
                </li>
                <li>
                  <strong>Efficient architectures for constrained hardware.</strong> Sandler et al.
                  (2018) introduced MobileNetV2 with inverted residuals and linear bottlenecks,
                  reaching competitive ImageNet accuracy at roughly 3.4 M parameters - the property
                  that lets this system run inference on a laptop CPU.
                </li>
                <li>
                  <strong>Transfer learning.</strong> Yosinski et al. (2014) quantified how
                  transferable ImageNet features are, supporting the two-stage strategy used here:
                  train the new head first, then fine-tune the upper convolutional blocks.
                </li>
                <li>
                  <strong>IoT imaging nodes in agriculture.</strong> A body of work pairs ESP32-class
                  microcontrollers with cameras for crop monitoring, consistently finding that
                  controlled illumination and a fixed working distance matter more to accuracy than
                  sensor resolution.
                </li>
                <li>
                  <strong>Calibration and selective prediction.</strong> Guo et al. (2017) showed
                  modern networks are systematically overconfident, which is the direct justification
                  for the confidence threshold and the uncertain outcome in this system rather than
                  always returning a top-1 label.
                </li>
              </ul>
            </CardBody>
          </Card>
        </div>
      )}

      {/* ---- Architecture ---- */}
      {tab === 'architecture' && (
        <div className="animate-fade-in space-y-5">
          <Card>
            <CardHeader
              title="System architecture"
              subtitle="Data flow from leaf to dashboard"
              icon={<Network className="h-4 w-4" />}
            />
            <CardBody>
              <div className="space-y-2">
                {[
                  { label: 'Plant leaf', detail: 'Subject, illuminated by the white LED', icon: Lightbulb },
                  { label: 'OV2640 sensor', detail: 'JPEG frame captured on the ESP32-CAM', icon: Camera },
                  { label: 'Wi-Fi 802.11 b/g/n', detail: 'HTTP transport on the local network', icon: Network },
                  { label: 'Flask REST API', detail: 'Validation, orchestration, error handling', icon: Cpu },
                  { label: 'MobileNetV2 classifier', detail: 'Softmax probability per trained class', icon: Layers },
                  { label: 'SQLite database', detail: 'detection_history and device_status tables', icon: Database },
                  { label: 'React dashboard', detail: 'Results, history, analytics, device control', icon: Binary },
                ].map((node, index, array) => (
                  <div key={node.label}>
                    <div className="flex items-center gap-3 rounded-xl border border-bark-100 bg-white px-4 py-3">
                      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-leaf-50 text-leaf-700">
                        <node.icon className="h-[18px] w-[18px]" />
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-bark-800">{node.label}</p>
                        <p className="text-xs text-bark-500">{node.detail}</p>
                      </div>
                      <span className="ml-auto font-mono text-2xs text-bark-300">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                    </div>
                    {index < array.length - 1 && (
                      <div className="ml-[35px] h-3 w-0.5 bg-leaf-200" aria-hidden="true" />
                    )}
                  </div>
                ))}
              </div>
              <p className="mt-4 text-xs leading-relaxed text-bark-500">
                A full diagram with both capture transports is in{' '}
                <code className="font-mono">docs/architecture.md</code>; the wiring diagram is in{' '}
                <code className="font-mono">docs/circuit_diagram.md</code>.
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Hardware details" icon={<CircuitBoard className="h-4 w-4" />} />
            <CardBody className="space-y-3">
              {HARDWARE.map((item) => (
                <div key={item.name} className="rounded-xl bg-bark-50 px-4 py-3">
                  <p className="text-sm font-semibold text-bark-800">{item.name}</p>
                  <p className="mt-1 text-sm leading-relaxed text-bark-600">{item.detail}</p>
                </div>
              ))}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Software details" icon={<Layers className="h-4 w-4" />} />
            <CardBody>
              <div className="grid gap-4 sm:grid-cols-2">
                {SOFTWARE_LAYERS.map((layer) => (
                  <div key={layer.title} className="rounded-xl border border-bark-100 p-4">
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-leaf-50 text-leaf-700">
                      <layer.icon className="h-[18px] w-[18px]" />
                    </span>
                    <h3 className="mt-3 text-sm font-semibold text-bark-800">{layer.title}</h3>
                    <ul className="mt-2 space-y-1.5">
                      {layer.items.map((item) => (
                        <li key={item} className="flex gap-2 text-sm text-bark-600">
                          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-leaf-400" />
                          {item}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Database design"
              subtitle="Two tables, both written by the backend"
              icon={<Database className="h-4 w-4" />}
            />
            <CardBody>
              <div className="grid gap-4 lg:grid-cols-2">
                {[
                  {
                    table: 'detection_history',
                    purpose: 'One row per prediction the model produced.',
                    columns: [
                      ['id', 'INTEGER PK', 'Autoincrement identifier'],
                      ['image_path', 'TEXT', 'Stored image, relative to uploads/'],
                      ['plant_name', 'TEXT', 'e.g. Tomato'],
                      ['predicted_disease', 'TEXT', 'e.g. Early Blight'],
                      ['confidence', 'REAL', 'Softmax probability, 0-1'],
                      ['detection_status', 'TEXT', 'healthy / diseased / uncertain / unknown'],
                      ['created_at', 'TEXT', 'UTC timestamp'],
                      ['model_mode', 'TEXT', 'trained or test'],
                      ['is_validated', 'INTEGER', '0 for untrained-model results'],
                      ['probabilities', 'TEXT', 'JSON of the top classes'],
                    ],
                  },
                  {
                    table: 'device_status',
                    purpose: 'One row per ESP32-CAM, updated by heartbeats.',
                    columns: [
                      ['id', 'INTEGER PK', 'Autoincrement identifier'],
                      ['device_name', 'TEXT UNIQUE', 'Logical camera name'],
                      ['ip_address', 'TEXT', 'Last reported address'],
                      ['connection_status', 'TEXT', 'online / offline / error'],
                      ['last_seen', 'TEXT', 'Last heartbeat, UTC'],
                      ['wifi_rssi', 'INTEGER', 'Signal strength in dBm'],
                      ['led_state', 'TEXT', 'on or off'],
                      ['free_heap', 'INTEGER', 'Bytes of free SRAM'],
                      ['last_capture_at', 'TEXT', 'Most recent frame delivered'],
                      ['total_captures', 'INTEGER', 'Lifetime capture count'],
                    ],
                  },
                ].map((spec) => (
                  <div key={spec.table}>
                    <p className="font-mono text-sm font-semibold text-leaf-700">{spec.table}</p>
                    <p className="mt-0.5 text-xs text-bark-500">{spec.purpose}</p>
                    <div className="mt-2 overflow-x-auto">
                      <table className="min-w-full text-xs">
                        <tbody className="divide-y divide-bark-50">
                          {spec.columns.map(([column, type, note]) => (
                            <tr key={column}>
                              <td className="py-1.5 pr-3 font-mono text-bark-700">{column}</td>
                              <td className="py-1.5 pr-3 font-mono text-2xs text-bark-400">{type}</td>
                              <td className="py-1.5 text-bark-600">{note}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-4 text-xs leading-relaxed text-bark-500">
                Online status is <em>derived</em> from heartbeat age rather than trusted from the
                stored column: a board that loses power cannot report its own death, so a persisted
                "online" flag would stay wrong indefinitely.
              </p>
            </CardBody>
          </Card>
        </div>
      )}

      {/* ---- Model ---- */}
      {tab === 'model' && (
        <div className="animate-fade-in space-y-5">
          {model?.is_test_mode && (
            <Notice tone="warning" icon={<FlaskConical className="h-4 w-4" />} title="Currently running an untrained model">
              The figures below describe the <em>methodology</em>. The model loaded right now has not
              been trained, so it has no evaluation metrics. Run{' '}
              <code className="font-mono text-xs">python ml/train.py --dataset-dir ml/dataset</code>{' '}
              to produce a real one.
            </Notice>
          )}

          <Card>
            <CardHeader
              title="Machine learning methodology"
              subtitle="Dataset, preprocessing, architecture, training, evaluation"
              icon={<Binary className="h-4 w-4" />}
            />
            <CardBody className="prose-doc">
              <h3 className="text-sm font-bold uppercase tracking-wider text-bark-700">1. Dataset</h3>
              <p>
                PlantVillage, organised one directory per class using the{' '}
                <code className="font-mono text-xs">Plant___Condition</code> convention. The folder
                names are the single source of truth for the label set: training writes them to{' '}
                <code className="font-mono text-xs">class_labels.json</code>, and the API serves that
                file, so the dashboard's class list cannot drift from what the network can output.
                Validation refuses to start training on an empty or single-class directory and warns
                about classes with too few images.
              </p>

              <h3 className="text-sm font-bold uppercase tracking-wider text-bark-700">
                2. Preprocessing
              </h3>
              <p>
                Images are decoded with EXIF orientation applied, converted to 3-channel RGB and
                resized to 224x224 bilinearly. Normalisation to the [-1, 1] range MobileNetV2
                expects happens in a <code className="font-mono text-xs">Rescaling</code> layer{' '}
                <em>inside</em> the saved model, which structurally eliminates the most common
                train/serve bug: applying different scaling at inference than during training.
              </p>

              <h3 className="text-sm font-bold uppercase tracking-wider text-bark-700">
                3. Augmentation
              </h3>
              <p>
                Applied to the training split only: horizontal and vertical flips, rotation up to
                25%, zoom and translation, plus contrast and brightness jitter. Flips and rotations
                are valid here because a leaf photograph has no canonical orientation; the
                brightness and contrast jitter specifically models the variation the white LED
                produces at different working distances.
              </p>

              <h3 className="text-sm font-bold uppercase tracking-wider text-bark-700">
                4. Architecture
              </h3>
              <p>
                MobileNetV2 pre-trained on ImageNet with the classifier head removed, followed by
                global average pooling, dropout, and a softmax dense layer sized to the number of
                classes. At roughly 2.3 M parameters it trains on a CPU in a practical amount of time
                and is small enough for a single Flask worker to hold in memory.
              </p>

              <h3 className="text-sm font-bold uppercase tracking-wider text-bark-700">
                5. Two-stage training
              </h3>
              <p>
                <strong>Stage one</strong> freezes the convolutional base and trains only the new
                head at a 1e-3 learning rate, so the large random gradients of an untrained head
                cannot damage the pre-trained features. <strong>Stage two</strong> unfreezes the top
                40 layers and continues at 1e-4. BatchNormalization layers stay frozen throughout
                fine-tuning: updating their running statistics on small batches is the usual cause of
                a sudden accuracy collapse at the start of stage two. Class weights compensate for
                PlantVillage's class imbalance, and early stopping with checkpoint restoration keeps
                the best epoch rather than the last.
              </p>

              <h3 className="text-sm font-bold uppercase tracking-wider text-bark-700">
                6. Evaluation
              </h3>
              <p>
                Scoring happens on a test split the model never saw, rebuilt deterministically from
                the same random seed. Reported metrics are top-1 and top-3 accuracy, macro and
                weighted precision/recall/F1, per-class scores, the confusion matrix, and the
                separate healthy-versus-diseased accuracy - which is the binary decision a grower
                actually acts on. Macro averaging is quoted alongside weighted so a rare class the
                model fails on cannot be hidden by a common class it handles well.
              </p>

              <h3 className="text-sm font-bold uppercase tracking-wider text-bark-700">
                7. Selective prediction
              </h3>
              <p>
                Inference is deliberately allowed to abstain. The quality gate rejects frames that
                are too small, blurred, under- or over-exposed, flat, or contain no leaf-like region,
                returning <strong>unknown</strong> without running the model. A prediction whose top
                probability falls below the threshold returns <strong>uncertain</strong> with the
                candidate classes listed but no disease named. Both outcomes are stored, because
                "the system could not decide" is information the operator needs.
              </p>
            </CardBody>
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader title="Loaded model" subtitle="Live values from the running backend" />
              <CardBody>
                <dl className="space-y-2.5 text-sm">
                  {[
                    { label: 'Base architecture', value: model?.base_model ?? '--' },
                    { label: 'Mode', value: model?.mode ?? '--' },
                    { label: 'Classes', value: model?.num_classes ?? '--' },
                    {
                      label: 'Input size',
                      value: model?.image_size ? `${model.image_size[0]}\u00d7${model.image_size[1]}` : '--',
                    },
                    { label: 'Input scaling', value: model?.input_scaling ?? '--' },
                    {
                      label: 'Confidence threshold',
                      value: model ? `${(model.confidence_threshold * 100).toFixed(0)}%` : '--',
                    },
                    { label: 'Trained at', value: model?.trained_at ?? 'not trained' },
                    { label: 'TensorFlow', value: model?.tensorflow_version ?? '--' },
                  ].map((row) => (
                    <div key={row.label} className="flex items-center justify-between gap-3">
                      <dt className="text-bark-500">{row.label}</dt>
                      <dd className="truncate font-medium text-bark-800">{String(row.value)}</dd>
                    </div>
                  ))}
                </dl>

                {metrics?.accuracy !== undefined && (
                  <div className="mt-4 grid grid-cols-2 gap-3">
                    {[
                      { label: 'Test accuracy', value: formatFraction(metrics.accuracy) },
                      {
                        label: 'Macro F1',
                        value: metrics.macro_f1 !== undefined ? metrics.macro_f1.toFixed(4) : '--',
                      },
                    ].map((item) => (
                      <div key={item.label} className="rounded-xl bg-leaf-50 px-3.5 py-3">
                        <p className="text-2xs font-semibold uppercase tracking-wider text-leaf-700">
                          {item.label}
                        </p>
                        <p className="mt-0.5 text-xl font-bold tabular-nums text-leaf-800">
                          {item.value}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader
                title="Supported classes"
                subtitle="Read from the trained model, not hardcoded"
              />
              <CardBody>
                {classes ? (
                  <div className="space-y-4">
                    {classes.plant_names.map((plant) => (
                      <div key={plant}>
                        <p className="text-sm font-semibold text-bark-800">{plant}</p>
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                          {classes.plants[plant].map((entry) => (
                            <span
                              key={entry.class}
                              className={entry.is_healthy ? 'badge-healthy' : 'badge-diseased'}
                            >
                              {entry.disease}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-bark-500">
                    The class list is unavailable because no model is loaded.
                  </p>
                )}
              </CardBody>
            </Card>
          </div>
        </div>
      )}

      {/* ---- Testing ---- */}
      {tab === 'testing' && (
        <div className="animate-fade-in space-y-5">
          <Card>
            <CardHeader
              title="Testing methodology"
              subtitle="Five levels, each independently runnable"
              icon={<ListChecks className="h-4 w-4" />}
            />
            <CardBody className="space-y-3">
              {TESTING.map((item, index) => (
                <div key={item.stage} className="flex gap-3 rounded-xl bg-bark-50 px-4 py-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-leaf-600 text-xs font-bold text-white">
                    {index + 1}
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-bark-800">{item.stage}</p>
                    <p className="mt-0.5 text-sm leading-relaxed text-bark-600">{item.detail}</p>
                  </div>
                </div>
              ))}
            </CardBody>
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader title="Advantages" />
              <CardBody>
                <ul className="space-y-2">
                  {[
                    'Low hardware cost: two main components, both widely available.',
                    'Repeatable imaging conditions thanks to controlled LED illumination.',
                    'Runs entirely on a local network - no cloud service or subscription.',
                    'Every detection is stored with its image and probabilities, so results are auditable.',
                    'Abstains rather than guessing on poor images or low-confidence cases.',
                    'The model is replaceable: retrain, reload, and the dashboard picks up the new class list.',
                  ].map((item) => (
                    <li key={item} className="flex gap-2 text-sm text-bark-600">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-leaf-500" />
                      {item}
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>

            <Card>
              <CardHeader title="Limitations" subtitle="Stated plainly, because they bound the claims" />
              <CardBody>
                <ul className="space-y-2">
                  {LIMITATIONS.map((item) => (
                    <li key={item} className="flex gap-2 text-sm text-bark-600">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-harvest-500" />
                      {item}
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          </div>

          <Card>
            <CardHeader title="Results and discussion" />
            <CardBody className="prose-doc">
              {metrics?.accuracy !== undefined ? (
                <>
                  <p>
                    On the held-out test split the trained model reaches{' '}
                    <strong>{formatFraction(metrics.accuracy)}</strong> top-1 accuracy across{' '}
                    {model?.num_classes} classes
                    {metrics.macro_f1 !== undefined && (
                      <>
                        , with a macro F1-score of <strong>{metrics.macro_f1.toFixed(4)}</strong>
                      </>
                    )}
                    . The per-class table and confusion matrix on the{' '}
                    <strong>Analytics</strong> page show where the remaining error sits.
                  </p>
                  <p>
                    Confusions concentrate between visually similar conditions - early and late
                    blight on both tomato and potato share dark necrotic lesions, and distinguishing
                    them depends on lesion margin and ring structure that a 224x224 crop may not
                    resolve. This is also why top-3 accuracy (
                    {metrics.top3_accuracy !== undefined ? formatFraction(metrics.top3_accuracy) : 'see Analytics'}
                    ) exceeds top-1 by a useful margin, and why the dashboard shows the full
                    probability vector rather than a single label.
                  </p>
                  <p>
                    The accuracy figure above is measured on PlantVillage-style images: a single leaf,
                    plain background, even lighting. It should be read as an upper bound for field
                    conditions, not as field accuracy.
                  </p>
                </>
              ) : (
                <>
                  <p>
                    No evaluation results are available yet because the loaded model has not been
                    trained. Once <code className="font-mono text-xs">ml/train.py</code> completes it
                    writes <code className="font-mono text-xs">ml/reports/metrics.json</code>, and
                    this section plus the Analytics page populate from that file.
                  </p>
                  <p>
                    For reference, published work on PlantVillage with transfer learning on these
                    classes typically reports 95-99% test accuracy under laboratory imaging
                    conditions, with the bulk of residual error between early and late blight.
                  </p>
                </>
              )}
            </CardBody>
          </Card>
        </div>
      )}

      {/* ---- Future scope ---- */}
      {tab === 'future' && (
        <div className="animate-fade-in space-y-5">
          <Card>
            <CardHeader
              title="Future scope"
              subtitle="Where this system would go next"
              icon={<Rocket className="h-4 w-4" />}
            />
            <CardBody>
              <div className="grid gap-4 sm:grid-cols-2">
                {FUTURE_SCOPE.map((item, index) => (
                  <div key={item.title} className="rounded-xl border border-bark-100 p-4">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-leaf-gradient text-xs font-bold text-white">
                      {index + 1}
                    </span>
                    <h3 className="mt-3 text-sm font-semibold text-bark-800">{item.title}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-bark-600">{item.detail}</p>
                  </div>
                ))}
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Conclusion" />
            <CardBody className="prose-doc">
              <p>
                The system demonstrates that a complete plant disease diagnostic loop - controlled
                image acquisition, deep learning inference, persistent records and an operator
                dashboard - can be built from an ESP32-CAM, a white LED and open-source software,
                with no cloud dependency and no recurring cost.
              </p>
              <p>
                The engineering contribution is less the accuracy number than the discipline around
                it. Images are validated before they reach the model; predictions below the
                confidence threshold name no disease; inconclusive outcomes are stored rather than
                discarded; and an untrained model is impossible to mistake for a trained one at any
                layer of the stack. A diagnostic tool that is occasionally silent is far more useful
                than one that is confidently wrong.
              </p>
              <p>
                The clearest path forward is narrowing the laboratory-to-field gap: training on
                images captured by this hardware in real conditions, and moving inference onto the
                device so a node can work without a server.
              </p>
            </CardBody>
          </Card>
        </div>
      )}
    </div>
  );
}
