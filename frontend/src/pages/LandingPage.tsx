import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BarChart3,
  Camera,
  Cpu,
  Database,
  Github,
  Layers,
  Leaf,
  Lightbulb,
  MonitorSmartphone,
  Network,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Target,
  Workflow,
} from 'lucide-react';
import { LogoWordmark } from '@/components/layout/Logo';

/* ------------------------------------------------------------------ */
/* Content                                                             */
/* ------------------------------------------------------------------ */

const OBJECTIVES = [
  {
    icon: Camera,
    title: 'Automated leaf imaging',
    body: 'Capture plant leaf images on demand with an ESP32-CAM and a white LED that gives consistent, repeatable illumination.',
  },
  {
    icon: Cpu,
    title: 'On-server deep learning',
    body: 'Classify each image with a MobileNetV2 transfer-learning model trained on the PlantVillage dataset.',
  },
  {
    icon: ShieldCheck,
    title: 'Honest, bounded answers',
    body: 'Report a disease only above a configurable confidence threshold; anything less is returned as uncertain rather than guessed.',
  },
  {
    icon: BarChart3,
    title: 'Traceable records',
    body: 'Persist every scan with its image, probabilities and timestamp in SQLite so results can be reviewed and audited later.',
  },
];

const PIPELINE = [
  {
    step: '01',
    icon: Lightbulb,
    title: 'Illuminate',
    body: 'The firmware switches on the white LED and lets the OV2640 sensor settle so exposure and white balance stabilise.',
  },
  {
    step: '02',
    icon: Camera,
    title: 'Capture',
    body: 'A JPEG frame is grabbed from the camera at the configured resolution and quality.',
  },
  {
    step: '03',
    icon: Network,
    title: 'Transmit',
    body: 'The frame travels over Wi-Fi to the Flask REST API by HTTP - either pulled by the server or pushed by the board.',
  },
  {
    step: '04',
    icon: ScanLine,
    title: 'Validate and classify',
    body: 'The backend checks sharpness, exposure and framing, then runs the trained CNN to obtain a probability per class.',
  },
  {
    step: '05',
    icon: Database,
    title: 'Record',
    body: 'The image, predicted class, confidence and full probability vector are written to SQLite.',
  },
  {
    step: '06',
    icon: MonitorSmartphone,
    title: 'Present',
    body: 'The React dashboard shows the diagnosis, reference agronomic guidance, and the statistics computed from stored records.',
  },
];

const TECH_STACK = [
  {
    group: 'Hardware',
    icon: Cpu,
    items: ['ESP32-CAM (AI Thinker)', 'OV2640 camera module', 'White LED + 220 Ω resistor', 'USB-to-TTL programmer'],
  },
  {
    group: 'Machine learning',
    icon: Layers,
    items: ['TensorFlow / Keras 3', 'MobileNetV2 transfer learning', 'OpenCV + NumPy', 'scikit-learn metrics'],
  },
  {
    group: 'Backend',
    icon: Workflow,
    items: ['Python 3 + Flask', 'Flask-CORS REST API', 'SQLite persistence', 'Pillow image validation'],
  },
  {
    group: 'Frontend',
    icon: MonitorSmartphone,
    items: ['React 18 + TypeScript', 'Vite build tooling', 'Tailwind CSS design system', 'Recharts visualisations'],
  },
];

const SUPPORTED_CROPS = [
  { plant: 'Tomato', conditions: ['Healthy', 'Early Blight', 'Late Blight', 'Leaf Mould', 'Septoria Leaf Spot'] },
  { plant: 'Potato', conditions: ['Healthy', 'Early Blight', 'Late Blight'] },
  { plant: 'Bell Pepper', conditions: ['Healthy', 'Bacterial Spot'] },
];

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export default function LandingPage() {
  return (
    <div className="min-h-full bg-white">
      {/* ---- Navigation ---- */}
      <header className="sticky top-0 z-30 border-b border-bark-100 bg-white/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3.5 sm:px-6">
          <LogoWordmark />
          <nav className="flex items-center gap-2">
            <a href="#how-it-works" className="btn-ghost btn-sm hidden sm:inline-flex">
              How it works
            </a>
            <a href="#stack" className="btn-ghost btn-sm hidden sm:inline-flex">
              Technology
            </a>
            <a href="#about" className="btn-ghost btn-sm hidden sm:inline-flex">
              About
            </a>
            <Link to="/dashboard" className="btn-primary btn-sm">
              Open dashboard
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </nav>
        </div>
      </header>

      {/* ---- Hero ---- */}
      <section className="relative overflow-hidden bg-hero-mesh">
        <div className="absolute inset-0 bg-grid-faint bg-grid-24 opacity-60" aria-hidden="true" />
        <div className="relative mx-auto max-w-7xl px-4 py-16 sm:px-6 sm:py-24">
          <div className="grid items-center gap-12 lg:grid-cols-2">
            <div className="animate-fade-in-up">
              <span className="badge-healthy">
                <Sparkles className="h-3.5 w-3.5" />
                IoT + Deep Learning Major Project
              </span>

              <h1 className="mt-5 text-pretty text-4xl font-extrabold leading-[1.1] tracking-tight text-bark-900 sm:text-5xl lg:text-[3.4rem]">
                AI-Based Smart{' '}
                <span className="bg-gradient-to-r from-leaf-600 to-leaf-800 bg-clip-text text-transparent">
                  Plant Disease
                </span>{' '}
                Detection and Classification
              </h1>

              <p className="mt-5 max-w-xl text-lg leading-relaxed text-bark-600">
                An ESP32-CAM captures a leaf under controlled white-LED lighting, streams it over
                Wi-Fi to a Flask server, and a MobileNetV2 convolutional network identifies the
                disease - with the confidence behind every answer shown, not hidden.
              </p>

              <div className="mt-8 flex flex-wrap items-center gap-3">
                <Link to="/detect" className="btn-primary btn-lg">
                  <ScanLine className="h-5 w-5" />
                  Get started
                </Link>
                <Link to="/dashboard" className="btn-secondary btn-lg">
                  <BarChart3 className="h-5 w-5" />
                  View dashboard
                </Link>
              </div>

              <dl className="mt-10 grid max-w-lg grid-cols-3 gap-4">
                {[
                  { label: 'Hardware components', value: '2' },
                  { label: 'Disease categories', value: '10' },
                  { label: 'Model parameters', value: '2.3 M' },
                ].map((item) => (
                  <div key={item.label}>
                    <dt className="text-2xs font-semibold uppercase tracking-wider text-bark-400">
                      {item.label}
                    </dt>
                    <dd className="mt-1 text-2xl font-bold text-bark-900">{item.value}</dd>
                  </div>
                ))}
              </dl>
            </div>

            {/* Architecture illustration */}
            <div className="animate-fade-in-up [animation-delay:150ms]">
              <div className="card overflow-hidden">
                <div className="flex items-center gap-2 border-b border-bark-100 bg-bark-50 px-4 py-2.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-blight-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-harvest-300" />
                  <span className="h-2.5 w-2.5 rounded-full bg-leaf-400" />
                  <span className="ml-2 font-mono text-xs text-bark-400">system-architecture</span>
                </div>
                <div className="space-y-3 p-5">
                  {[
                    { icon: Camera, label: 'ESP32-CAM + white LED', detail: 'OV2640 · JPEG capture', tone: 'bg-leaf-50 text-leaf-700' },
                    { icon: Network, label: 'Wi-Fi · HTTP POST', detail: 'Local network transport', tone: 'bg-sky-50 text-sky-700' },
                    { icon: Cpu, label: 'Flask REST API', detail: 'Validation · inference · storage', tone: 'bg-harvest-50 text-harvest-700' },
                    { icon: Layers, label: 'MobileNetV2 CNN', detail: 'Softmax over trained classes', tone: 'bg-violet-50 text-violet-700' },
                    { icon: Database, label: 'SQLite', detail: 'detection_history · device_status', tone: 'bg-bark-100 text-bark-700' },
                    { icon: MonitorSmartphone, label: 'React dashboard', detail: 'Live results and analytics', tone: 'bg-leaf-50 text-leaf-700' },
                  ].map((node, index, array) => (
                    <div key={node.label}>
                      <div className="flex items-center gap-3 rounded-xl border border-bark-100 bg-white px-3.5 py-3">
                        <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${node.tone}`}>
                          <node.icon className="h-[18px] w-[18px]" />
                        </span>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-bark-800">{node.label}</p>
                          <p className="truncate text-xs text-bark-500">{node.detail}</p>
                        </div>
                      </div>
                      {index < array.length - 1 && (
                        <div className="ml-[31px] h-3 w-0.5 bg-leaf-200" aria-hidden="true" />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---- Objectives ---- */}
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
        <div className="max-w-2xl">
          <span className="badge-neutral">
            <Target className="h-3.5 w-3.5" />
            Objectives
          </span>
          <h2 className="mt-4 text-3xl font-bold tracking-tight text-bark-900">
            What the system sets out to do
          </h2>
          <p className="mt-3 text-base leading-relaxed text-bark-600">
            Manual scouting for plant disease is slow, subjective, and needs expertise that is not
            available on every farm. This project automates the imaging and the diagnosis while
            keeping the uncertainty visible.
          </p>
        </div>

        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {OBJECTIVES.map((objective, index) => (
            <div
              key={objective.title}
              className="card-interactive animate-fade-in-up p-5"
              style={{ animationDelay: `${index * 80}ms` }}
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-leaf-gradient text-white shadow-glow-leaf">
                <objective.icon className="h-5 w-5" />
              </span>
              <h3 className="mt-4 text-base font-semibold text-bark-900">{objective.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-bark-600">{objective.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ---- How it works ---- */}
      <section id="how-it-works" className="bg-bark-50 py-16">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="max-w-2xl">
            <span className="badge-healthy">
              <Workflow className="h-3.5 w-3.5" />
              How the system works
            </span>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-bark-900">
              From leaf to diagnosis in six steps
            </h2>
            <p className="mt-3 text-base leading-relaxed text-bark-600">
              Each stage is a real component in this repository: the Arduino sketch, the Flask
              routes, the Keras model and the React pages.
            </p>
          </div>

          <ol className="mt-10 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {PIPELINE.map((stage, index) => (
              <li
                key={stage.step}
                className="card animate-fade-in-up relative overflow-hidden p-5"
                style={{ animationDelay: `${index * 70}ms` }}
              >
                <span className="absolute -right-2 -top-3 text-6xl font-black text-leaf-50">
                  {stage.step}
                </span>
                <span className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-leaf-100 text-leaf-700">
                  <stage.icon className="h-5 w-5" />
                </span>
                <h3 className="relative mt-4 text-base font-semibold text-bark-900">{stage.title}</h3>
                <p className="relative mt-2 text-sm leading-relaxed text-bark-600">{stage.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ---- Supported crops ---- */}
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-[1fr_1.1fr] lg:items-center">
          <div>
            <span className="badge-neutral">
              <Leaf className="h-3.5 w-3.5" />
              Scope
            </span>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-bark-900">
              Crops and conditions in the trained class list
            </h2>
            <p className="mt-3 text-base leading-relaxed text-bark-600">
              The model can only predict classes it was trained on, so the dashboard shows that list
              explicitly and reads it from the saved model rather than hardcoding it. Adding a crop
              means adding its images to the dataset and retraining - the UI then picks it up
              automatically.
            </p>
            <Link to="/about" className="link mt-4 inline-flex items-center gap-1.5 text-sm">
              Read the methodology
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            {SUPPORTED_CROPS.map((crop) => (
              <div key={crop.plant} className="card p-5">
                <h3 className="text-base font-semibold text-bark-900">{crop.plant}</h3>
                <ul className="mt-3 space-y-1.5">
                  {crop.conditions.map((condition) => (
                    <li key={condition} className="flex items-center gap-2 text-sm text-bark-600">
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          condition === 'Healthy' ? 'bg-leaf-500' : 'bg-blight-400'
                        }`}
                      />
                      {condition}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---- Technology stack ---- */}
      <section id="stack" className="bg-bark-900 py-16 text-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="max-w-2xl">
            <span className="badge bg-white/10 text-leaf-200">
              <Layers className="h-3.5 w-3.5" />
              Technology stack
            </span>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-white">
              Built from four cooperating layers
            </h2>
            <p className="mt-3 text-base leading-relaxed text-bark-200">
              Each layer is independently runnable and testable: train the model without the
              hardware, run the API without the dashboard, develop the dashboard against the API.
            </p>
          </div>

          <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {TECH_STACK.map((layer, index) => (
              <div
                key={layer.group}
                className="animate-fade-in-up rounded-2xl border border-white/10 bg-white/5 p-5 backdrop-blur"
                style={{ animationDelay: `${index * 80}ms` }}
              >
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-leaf-500/20 text-leaf-300">
                  <layer.icon className="h-5 w-5" />
                </span>
                <h3 className="mt-4 text-base font-semibold text-white">{layer.group}</h3>
                <ul className="mt-3 space-y-1.5">
                  {layer.items.map((item) => (
                    <li key={item} className="text-sm text-bark-200">
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---- About ---- */}
      <section id="about" className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
        <div className="grid gap-10 lg:grid-cols-[1.2fr_1fr]">
          <div>
            <span className="badge-neutral">About the project</span>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-bark-900">
              Why build this
            </h2>
            <div className="prose-doc mt-4 max-w-2xl text-base">
              <p>
                Plant disease costs a large share of global crop yield every year, and most of that
                loss is avoidable: early-stage symptoms are visible on the leaf long before the crop
                is lost. The barrier is access to diagnosis, not the existence of a cure.
              </p>
              <p>
                This project puts a diagnostic loop on a desk: a ten-dollar camera module, a white
                LED for repeatable lighting, and a convolutional network small enough to run on a
                laptop CPU. The camera handles acquisition, the server handles inference, and the
                dashboard turns a probability vector into something a grower can act on.
              </p>
              <p>
                The engineering emphasis is on <strong>not overclaiming</strong>. Images that are
                blurred, dark or do not contain a leaf are rejected instead of classified.
                Predictions below the confidence threshold are reported as uncertain. If the loaded
                model has not been trained, every response and every screen says so.
              </p>
            </div>
          </div>

          <div className="card h-fit p-6">
            <h3 className="text-base font-semibold text-bark-900">Run it yourself</h3>
            <p className="mt-2 text-sm text-bark-600">
              Three terminals, in this order:
            </p>
            <ol className="mt-4 space-y-3 text-sm">
              {[
                { label: 'Train the model', code: 'cd ml\npython train.py --dataset-dir dataset' },
                { label: 'Start the API', code: 'cd backend\npython app.py' },
                { label: 'Start the dashboard', code: 'cd frontend\nnpm install\nnpm run dev' },
              ].map((item, index) => (
                <li key={item.label}>
                  <p className="font-semibold text-bark-700">
                    {index + 1}. {item.label}
                  </p>
                  <pre className="mt-1.5 overflow-x-auto rounded-lg bg-bark-900 px-3 py-2 font-mono text-xs leading-relaxed text-leaf-200">
                    {item.code}
                  </pre>
                </li>
              ))}
            </ol>
            <p className="mt-4 text-xs leading-relaxed text-bark-500">
              Flash <code className="font-mono">esp32cam/plant_disease_camera.ino</code> with the
              Arduino IDE and set your Wi-Fi credentials plus the server IP printed in the backend
              banner. Full steps are in <code className="font-mono">docs/installation.md</code>.
            </p>
          </div>
        </div>
      </section>

      {/* ---- CTA ---- */}
      <section className="bg-leaf-gradient py-14">
        <div className="mx-auto flex max-w-7xl flex-col items-center gap-5 px-4 text-center sm:px-6">
          <h2 className="text-balance text-3xl font-bold tracking-tight text-white">
            Ready to scan a leaf?
          </h2>
          <p className="max-w-2xl text-base text-leaf-50/90">
            Trigger a capture on the ESP32-CAM, or upload a photograph from your device. Either way
            the same model and the same validation rules apply.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Link
              to="/detect"
              className="btn btn-lg bg-white text-leaf-800 shadow-card hover:bg-leaf-50"
            >
              <ScanLine className="h-5 w-5" />
              Start detection
            </Link>
            <Link
              to="/device"
              className="btn btn-lg border border-white/35 text-white hover:bg-white/10"
            >
              <Cpu className="h-5 w-5" />
              Check the camera
            </Link>
          </div>
        </div>
      </section>

      {/* ---- Footer ---- */}
      <footer className="border-t border-bark-100 bg-white py-8">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 sm:flex-row sm:px-6">
          <LogoWordmark />
          <p className="text-center text-xs text-bark-400 sm:text-right">
            AI-Based Smart Plant Disease Detection and Classification
            <br />
            ESP32-CAM &middot; TensorFlow/Keras &middot; Flask &middot; React &middot; SQLite
          </p>
          <a
            href="#about"
            className="btn-ghost btn-sm text-bark-500"
            aria-label="Project documentation"
          >
            <Github className="h-4 w-4" />
            Documentation in /docs
          </a>
        </div>
      </footer>
    </div>
  );
}
