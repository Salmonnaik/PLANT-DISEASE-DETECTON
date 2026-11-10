"""
smoke_test.py
=============
End-to-end API verification against a running backend.

Checks every endpoint the dashboard depends on, including the failure paths
that matter: a corrupt file must be rejected, an unusable image must come back
as "unknown" rather than as a disease, and a bad filter value must return a 400
with a useful message.

Usage::

    python scripts/smoke_test.py
    python scripts/smoke_test.py --server http://192.168.1.10:5000
    python scripts/smoke_test.py --keep        # keep the records it creates

Exit code is 0 when every check passes, 1 otherwise, so it can be used in CI.

Note on the synthetic images: the shapes generated here exercise the *pipeline*
(validation, inference, storage, aggregation). They are not plant photographs,
so whatever class the model assigns them is meaningless - the assertions only
check structure and behaviour, never a specific disease.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    import numpy as np
    import requests
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    print(f"Missing dependency: {exc}\nInstall with: pip install -r backend/requirements.txt")
    raise SystemExit(2) from exc

sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_SERVER = "http://127.0.0.1:5000"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
GREY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"


class Results:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.failures: List[Tuple[str, str]] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.passed += 1
        print(f"  {GREEN}PASS{RESET}  {name}" + (f"  {GREY}{detail}{RESET}" if detail else ""))

    def fail(self, name: str, reason: str) -> None:
        self.failed += 1
        self.failures.append((name, reason))
        print(f"  {RED}FAIL{RESET}  {name}\n        {RED}{reason}{RESET}")

    def skip(self, name: str, reason: str) -> None:
        self.skipped += 1
        print(f"  {YELLOW}SKIP{RESET}  {name}  {GREY}{reason}{RESET}")

    def check(self, name: str, condition: bool, detail: str = "", reason: str = "") -> bool:
        if condition:
            self.ok(name, detail)
        else:
            self.fail(name, reason or "Condition was not met.")
        return condition


# --------------------------------------------------------------------------- #
# Test images
# --------------------------------------------------------------------------- #

def make_leaf_image(size: int = 360, seed: int = 11) -> bytes:
    """A textured green ellipse: passes the quality gate, reaches the model."""
    rng = np.random.default_rng(seed)
    grid_y, grid_x = np.mgrid[0:size, 0:size]
    centre = size / 2.0

    canvas = np.full((size, size, 3), 55.0, dtype=np.float32)
    leaf = ((grid_x - centre) ** 2 / (size * 0.36) ** 2 + (grid_y - centre) ** 2 / (size * 0.26) ** 2) < 1.0
    canvas[leaf] = [62.0, 150.0, 52.0]

    for offset in range(-size // 2, size // 2, 14):
        vein = np.abs((grid_y - centre) - 0.55 * (grid_x - centre - offset)) < 1.4
        canvas[vein & leaf] = [110.0, 185.0, 90.0]

    canvas += rng.normal(0.0, 9.0, canvas.shape)
    buffer = io.BytesIO()
    Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)).save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def make_blank_image() -> bytes:
    """A flat near-white frame: must fail the quality gate."""
    buffer = io.BytesIO()
    Image.new("RGB", (320, 320), (246, 246, 246)).save(buffer, "JPEG", quality=92)
    return buffer.getvalue()


def make_tiny_image() -> bytes:
    """8x8 pixels: must be rejected as too small."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (40, 120, 40)).save(buffer, "PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

class Client:
    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        return self.session.request(method, f"{self.base_url}{path}", **kwargs)

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("DELETE", path, **kwargs)


def envelope(response: requests.Response) -> Dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #

def check_health(client: Client, results: Results) -> Optional[Dict[str, Any]]:
    section("1. Health and configuration")

    try:
        response = client.get("/api/health", timeout=60)
    except requests.RequestException as exc:
        results.fail("GET /api/health", f"Backend unreachable at {client.base_url}: {exc}")
        return None

    results.check(
        "GET /api/health responds",
        response.status_code in (200, 503),
        f"HTTP {response.status_code}",
        f"Unexpected status {response.status_code}",
    )

    body = envelope(response)
    data = body.get("data") or {}
    if not data:
        results.fail("Health payload", "Response did not contain a data object.")
        return None

    results.check(
        "Database connected",
        bool(data.get("database", {}).get("connected")),
        f"{data['database'].get('detection_records')} detection records",
        f"Database error: {data.get('database', {}).get('error')}",
    )

    model = data.get("model") or {}
    results.check(
        "Model loaded",
        bool(model.get("loaded")),
        f"{model.get('num_classes')} classes, mode={model.get('mode')}",
        f"No model loaded: {model.get('error') or model.get('message')}",
    )

    if model.get("is_test_mode"):
        print(
            f"  {YELLOW}NOTE{RESET}  The backend is running an UNTRAINED model (test mode).\n"
            f"        Predictions below are pipeline checks only, not real diagnoses."
        )

    results.check(
        "Predictions permitted",
        bool(model.get("can_predict")),
        reason="can_predict is false; the server will refuse /api/predict.",
    )
    return data


def check_classes(client: Client, results: Results) -> None:
    section("2. Supported classes and reference data")

    response = client.get("/api/classes")
    data = envelope(response).get("data") or {}

    results.check(
        "GET /api/classes",
        response.status_code == 200 and data.get("num_classes", 0) >= 2,
        f"{data.get('num_classes')} classes across {len(data.get('plant_names', []))} plants",
        f"HTTP {response.status_code}",
    )

    classes = data.get("classes") or []
    results.check(
        "Class entries are fully parsed",
        bool(classes) and all(item.get("plant") and item.get("disease") for item in classes),
        f"e.g. {classes[0]['display']}" if classes else "",
        "One or more classes is missing a parsed plant or disease name.",
    )

    info = client.get("/api/disease-info")
    results.check(
        "GET /api/disease-info",
        info.status_code == 200 and (envelope(info).get("data") or {}).get("count", 0) > 0,
        f"{(envelope(info).get('data') or {}).get('count')} reference entries",
        f"HTTP {info.status_code}",
    )


def check_prediction(client: Client, results: Results) -> List[int]:
    section("3. Prediction pipeline")
    created: List[int] = []

    # ---- a valid leaf-like image ----------------------------------------
    leaf = make_leaf_image()
    response = client.post(
        "/api/predict",
        files={"image": ("smoke_leaf.jpg", leaf, "image/jpeg")},
    )
    body = envelope(response)
    data = body.get("data") or {}
    prediction = data.get("prediction") or {}

    if not results.check(
        "POST /api/predict (valid image)",
        response.status_code == 200 and bool(prediction),
        f"status={prediction.get('detection_status')} "
        f"confidence={prediction.get('confidence_percent')}%",
        f"HTTP {response.status_code}: {body.get('error', {}).get('message', response.text[:160])}",
    ):
        return created

    if data.get("detection_id"):
        created.append(int(data["detection_id"]))

    probabilities = prediction.get("class_probabilities") or []
    total = sum(item["probability"] for item in probabilities)
    results.check(
        "Probability vector covers every class and sums to 1",
        len(probabilities) == prediction["model"]["num_classes"] and abs(total - 1.0) < 0.01,
        f"{len(probabilities)} classes, sum={total:.4f}",
        f"Got {len(probabilities)} probabilities summing to {total:.4f}.",
    )

    results.check(
        "Confidence is consistent with the reported status",
        (
            prediction["is_conclusive"]
            == (prediction["confidence"] >= prediction["confidence_threshold"])
        ),
        f"conclusive={prediction['is_conclusive']} "
        f"({prediction['confidence']:.3f} vs threshold {prediction['confidence_threshold']})",
        "is_conclusive does not match the confidence/threshold comparison.",
    )

    results.check(
        "Untrained results are flagged, trained results are not",
        prediction["is_validated_prediction"] == prediction["model"]["trained"],
        f"validated={prediction['is_validated_prediction']}",
        "is_validated_prediction disagrees with model.trained.",
    )

    results.check(
        "Image quality metrics returned",
        bool((prediction.get("image_quality") or {}).get("metrics")),
        reason="image_quality.metrics is missing.",
    )

    results.check(
        "Image stored and record created",
        bool(data.get("detection_id")) and bool((data.get("image") or {}).get("url")),
        f"record #{data.get('detection_id')} -> {(data.get('image') or {}).get('url')}",
        "No detection_id or image URL came back.",
    )

    image_url = (data.get("image") or {}).get("url")
    if image_url:
        served = client.get(image_url)
        results.check(
            "Stored image is served back",
            served.status_code == 200 and served.headers.get("Content-Type", "").startswith("image/"),
            f"{len(served.content)} bytes, {served.headers.get('Content-Type')}",
            f"HTTP {served.status_code} when fetching {image_url}",
        )

    # ---- quality gate ----------------------------------------------------
    blank = client.post("/api/predict", files={"image": ("blank.jpg", make_blank_image(), "image/jpeg")})
    blank_prediction = (envelope(blank).get("data") or {}).get("prediction") or {}
    if (envelope(blank).get("data") or {}).get("detection_id"):
        created.append(int(envelope(blank)["data"]["detection_id"]))

    results.check(
        "Flat/over-exposed image returns 'unknown', not a disease",
        blank.status_code == 200
        and blank_prediction.get("detection_status") == "unknown"
        and blank_prediction.get("is_conclusive") is False,
        f"status={blank_prediction.get('detection_status')}, "
        f"{len(blank_prediction.get('image_quality', {}).get('issues', []))} issues listed",
        f"Expected status 'unknown', got {blank_prediction.get('detection_status')!r}.",
    )

    # ---- threshold override ---------------------------------------------
    low = client.post(
        "/api/predict",
        files={"image": ("smoke_leaf2.jpg", leaf, "image/jpeg")},
        data={"threshold": "0.01", "save": "false"},
    )
    low_prediction = (envelope(low).get("data") or {}).get("prediction") or {}
    results.check(
        "Per-request threshold override is honoured",
        low.status_code == 200 and low_prediction.get("confidence_threshold") == 0.01,
        f"threshold={low_prediction.get('confidence_threshold')}, "
        f"conclusive={low_prediction.get('is_conclusive')}",
        f"Threshold came back as {low_prediction.get('confidence_threshold')}.",
    )
    results.check(
        "save=false does not create a record",
        (envelope(low).get("data") or {}).get("detection_id") is None,
        reason="A record was created even though save=false was sent.",
    )

    # ---- /api/analyze ----------------------------------------------------
    analyse = client.post("/api/analyze", files={"image": ("a.jpg", leaf, "image/jpeg")})
    results.check(
        "POST /api/analyze classifies without persisting",
        analyse.status_code == 200
        and (envelope(analyse).get("data") or {}).get("detection_id") is None,
        reason=f"HTTP {analyse.status_code}, detection_id was not null.",
    )

    return created


def check_camera_sources(client: Client, results: Results) -> List[int]:
    """
    Verify that both camera sources share one pipeline and are recorded apart.

    The laptop webcam cannot be driven from a script - it lives in the browser -
    so what is tested here is the exact HTTP request the browser makes after
    `canvas.toBlob()`: a multipart POST to /api/predict carrying
    ``camera_source=laptop_webcam``. That is the entire server-side contract for
    the webcam path.
    """
    section("4. Camera sources")
    created: List[int] = []

    # ---- discovery ------------------------------------------------------
    response = client.get("/api/cameras")
    data = envelope(response).get("data") or {}
    cameras = {camera["id"]: camera for camera in (data.get("cameras") or [])}

    results.check(
        "GET /api/cameras lists both sources",
        response.status_code == 200 and "laptop_webcam" in cameras and "esp32_cam" in cameras,
        f"{', '.join(sorted(cameras))}",
        f"HTTP {response.status_code}, found {sorted(cameras)}",
    )

    results.check(
        "Webcam is reported as browser-managed",
        cameras.get("laptop_webcam", {}).get("managed_by") == "browser"
        and cameras.get("laptop_webcam", {}).get("available") is None,
        "availability is decided in the browser, not the backend",
        "The backend claims to know whether the webcam is available.",
    )

    results.check(
        "ESP32-CAM is reported as backend-managed",
        cameras.get("esp32_cam", {}).get("managed_by") == "backend",
        f"status={cameras.get('esp32_cam', {}).get('status')}",
        "ESP32-CAM is not marked as backend-managed.",
    )

    pipeline = data.get("shared_pipeline") or {}
    results.check(
        "Both sources advertise one shared pipeline",
        pipeline.get("endpoint") == "/api/predict" and pipeline.get("num_classes", 0) > 0,
        f"{pipeline.get('endpoint')}, {pipeline.get('num_classes')} classes, "
        f"threshold {pipeline.get('confidence_threshold')}",
        f"shared_pipeline looks wrong: {pipeline}",
    )

    # ---- webcam path ----------------------------------------------------
    leaf = make_leaf_image(seed=21)

    webcam_response = client.post(
        "/api/predict",
        files={"image": ("webcam-frame.jpg", leaf, "image/jpeg")},
        data={"camera_source": "laptop_webcam"},
    )
    webcam_body = envelope(webcam_response).get("data") or {}
    if webcam_body.get("detection_id"):
        created.append(int(webcam_body["detection_id"]))

    results.check(
        "Webcam frame is accepted and labelled laptop_webcam",
        webcam_response.status_code == 200
        and webcam_body.get("camera_source") == "laptop_webcam"
        and (webcam_body.get("detection") or {}).get("camera_source") == "laptop_webcam",
        f"record #{webcam_body.get('detection_id')} "
        f"stored as {(webcam_body.get('detection') or {}).get('camera_source')}",
        f"HTTP {webcam_response.status_code}, camera_source="
        f"{webcam_body.get('camera_source')}",
    )

    results.check(
        "Webcam image is stored with a webcam filename prefix",
        str((webcam_body.get("image") or {}).get("filename") or "").startswith("webcam"),
        (webcam_body.get("image") or {}).get("filename"),
        f"filename was {(webcam_body.get('image') or {}).get('filename')}",
    )

    # ---- file upload path ----------------------------------------------
    file_response = client.post(
        "/api/predict",
        files={"image": ("from-disk.jpg", leaf, "image/jpeg")},
        data={"camera_source": "file_upload"},
    )
    file_body = envelope(file_response).get("data") or {}
    if file_body.get("detection_id"):
        created.append(int(file_body["detection_id"]))

    results.check(
        "File upload is labelled file_upload",
        file_response.status_code == 200 and file_body.get("camera_source") == "file_upload",
        f"record #{file_body.get('detection_id')}",
        f"camera_source={file_body.get('camera_source')}",
    )

    # ---- identical treatment -------------------------------------------
    webcam_prediction = webcam_body.get("prediction") or {}
    file_prediction = file_body.get("prediction") or {}
    results.check(
        "The same image gives the same result from either source",
        webcam_prediction.get("predicted_class") == file_prediction.get("predicted_class")
        and abs(
            float(webcam_prediction.get("confidence", 0))
            - float(file_prediction.get("confidence", 0))
        )
        < 1e-6
        and webcam_prediction.get("confidence_threshold")
        == file_prediction.get("confidence_threshold"),
        f"both: {webcam_prediction.get('display_label')} at "
        f"{webcam_prediction.get('confidence_percent')}%",
        "Identical bytes produced different predictions depending on camera_source, "
        "which means the pipeline is not actually shared.",
    )

    # ---- invalid source --------------------------------------------------
    bogus = client.post(
        "/api/predict",
        files={"image": ("x.jpg", leaf, "image/jpeg")},
        data={"camera_source": "satellite", "save": "false"},
    )
    results.check(
        "Unknown camera_source is rejected",
        bogus.status_code == 400
        and (envelope(bogus).get("error") or {}).get("code") == "VALIDATION_ERROR",
        f"HTTP {bogus.status_code}",
        f"Expected 400, got HTTP {bogus.status_code}",
    )

    # ---- filtering -------------------------------------------------------
    filtered = client.get("/api/history?camera_source=laptop_webcam&limit=20")
    items = (envelope(filtered).get("data") or {}).get("items") or []
    results.check(
        "History filters by camera source",
        filtered.status_code == 200
        and len(items) > 0
        and all(item["camera_source"] == "laptop_webcam" for item in items),
        f"{len(items)} webcam record(s) returned",
        "The camera_source filter returned records from another camera.",
    )

    stats = envelope(client.get("/api/stats")).get("data") or {}
    camera_stats = {row["camera_source"]: row for row in (stats.get("camera_sources") or [])}
    results.check(
        "Statistics break down by camera source",
        "laptop_webcam" in camera_stats and "esp32_cam" in camera_stats,
        ", ".join(f"{key}={value['count']}" for key, value in camera_stats.items()),
        f"camera_sources was {list(camera_stats)}",
    )

    return created


def check_universal_analysis(client: Client, results: Results) -> List[int]:
    """
    Verify the universal, species-agnostic analysis.

    The important assertions are the ones about *scope* and *honesty*: that a
    plant outside the classifier's ten classes is analysed rather than rejected
    or force-fitted, that different images yield different findings, and that
    chemical treatment advice is withheld when the assessment is uncertain.
    """
    section("5. Universal plant analysis")
    created: List[int] = []

    # ---- species catalogue ---------------------------------------------
    response = client.get("/api/plants")
    data = envelope(response).get("data") or {}
    names = {str(item["common_name"]).lower() for item in (data.get("species") or [])}

    results.check(
        "GET /api/plants lists species beyond the trained classes",
        response.status_code == 200 and len(names) >= 10,
        f"{data.get('count')} species, classifier covers {data.get('classifier_species')}",
        f"HTTP {response.status_code}, {len(names)} species",
    )

    expected = {"mango", "neem", "rose", "hibiscus", "banana", "papaya", "guava",
                "apple", "grapevine", "tomato", "potato", "pepper", "corn", "lemon", "orange"}
    missing = expected - names
    results.check(
        "Requested plant species are all present",
        not missing,
        f"{len(expected - missing)}/{len(expected)} present",
        f"missing: {sorted(missing)}",
    )

    results.check(
        "Unlisted plants are explicitly supported",
        bool(data.get("supports_unlisted")),
        reason="The API does not advertise support for unlisted plants.",
    )

    # ---- a plant the classifier has never seen --------------------------
    leaf = make_leaf_image(seed=33)
    mango = client.post(
        "/api/analyze-plant",
        files={"image": ("mango.jpg", leaf, "image/jpeg")},
        data={"plant_species": "Mango", "camera_source": "laptop_webcam"},
    )
    mango_body = envelope(mango).get("data") or {}
    analysis = mango_body.get("analysis") or {}
    if mango_body.get("detection_id"):
        created.append(int(mango_body["detection_id"]))

    if not results.check(
        "An out-of-class plant (Mango) is analysed, not rejected",
        mango.status_code == 200 and bool(analysis),
        f"record #{mango_body.get('detection_id')}",
        f"HTTP {mango.status_code}: {mango.text[:200]}",
    ):
        return created

    plant = analysis.get("plant") or {}
    results.check(
        "The declared species is used and resolved to a care profile",
        plant.get("name", "").lower() == "mango"
        and plant.get("identification_source") == "user_declared"
        and plant.get("in_knowledge_base") is True,
        f"{plant.get('name')} ({plant.get('category')}), source={plant.get('identification_source')}",
        f"plant block was {plant}",
    )

    results.check(
        "The 10-class classifier was NOT forced onto an out-of-class plant",
        (analysis.get("evidence_sources", {}).get("classifier", {}).get("used") is False),
        analysis.get("evidence_sources", {}).get("classifier", {}).get("note", "")[:90],
        "The classifier was applied to a species it was never trained on.",
    )

    results.check(
        "Result is never presented as a confirmed diagnosis",
        analysis.get("is_confirmed_diagnosis") is False,
        reason="is_confirmed_diagnosis was not False.",
    )

    results.check(
        "Symptoms carry the measurement that triggered them",
        all(
            item.get("evidence") and item.get("metric") is not None
            for item in (analysis.get("symptoms", {}).get("detected") or [])
        ),
        f"{len(analysis.get('symptoms', {}).get('detected') or [])} symptom(s), each with evidence",
        "A reported symptom had no supporting measurement.",
    )

    candidates = (analysis.get("condition") or {}).get("candidates") or []
    results.check(
        "Candidate conditions are flagged as possibilities, not diagnoses",
        all(item.get("is_diagnosis") is False for item in candidates),
        f"{len(candidates)} candidate(s)",
        "A candidate condition claimed to be a diagnosis.",
    )

    results.check(
        "Non-disease explanations are included among the candidates",
        any(item.get("is_disease") is False for item in candidates) or not candidates,
        "damage is not assumed to be infection",
        "Every candidate was a disease; non-pathogenic causes were not considered.",
    )

    results.check(
        "Care guidance is species-specific when the plant is known",
        bool((analysis.get("care") or {}).get("watering")),
        reason="No watering guidance was returned for a known species.",
    )

    results.check(
        "Limitations are stated explicitly",
        len(analysis.get("limitations") or []) >= 2,
        f"{len(analysis.get('limitations') or [])} limitations listed",
        "Fewer than two limitations were disclosed.",
    )

    # ---- unknown species -------------------------------------------------
    unknown = client.post(
        "/api/analyze-plant",
        files={"image": ("unknown.jpg", leaf, "image/jpeg")},
        data={"save": "false"},
    )
    unknown_analysis = (envelope(unknown).get("data") or {}).get("analysis") or {}
    unknown_plant = unknown_analysis.get("plant") or {}
    results.check(
        "An undeclared, unidentifiable plant is reported as unidentified",
        unknown.status_code == 200
        and unknown_plant.get("identified") is False
        and unknown_plant.get("identification_source") == "unidentified",
        f"{unknown_plant.get('name')}",
        f"plant block was {unknown_plant}",
    )

    # ---- image-driven, not canned ---------------------------------------
    from test_leaf_analysis import render  # noqa: PLC0415

    import io as _io
    from PIL import Image as _Image

    def as_jpeg(kind: str, seed: int) -> bytes:
        buffer = _io.BytesIO()
        _Image.fromarray(render(kind, seed=seed)).save(buffer, "JPEG", quality=92)
        return buffer.getvalue()

    observed: Dict[str, Tuple] = {}
    for kind in ("healthy", "powdery", "holes", "rust", "edge_scorch"):
        reply = client.post(
            "/api/analyze-plant",
            files={"image": (f"{kind}.jpg", as_jpeg(kind, 700), "image/jpeg")},
            data={"plant_species": "Rose", "save": "false"},
        )
        body = (envelope(reply).get("data") or {}).get("analysis") or {}
        observed[kind] = (
            tuple(sorted(item["id"] for item in (body.get("symptoms", {}).get("detected") or []))),
            (body.get("condition") or {}).get("id"),
        )

    results.check(
        "Different images produce different findings (no hardcoded result)",
        len(set(observed.values())) == len(observed),
        " | ".join(f"{kind}->{value[1]}" for kind, value in observed.items()),
        f"only {len(set(observed.values()))} distinct results across {len(observed)} images",
    )

    results.check(
        "A clean leaf is reported as healthy, not given a disease",
        observed["healthy"][1] == "healthy" and observed["healthy"][0] == (),
        f"healthy -> {observed['healthy'][1]}",
        f"a clean leaf produced {observed['healthy']}",
    )

    # ---- chemical withholding -------------------------------------------
    uncertain_reply = client.post(
        "/api/analyze-plant",
        files={"image": ("spots.jpg", as_jpeg("leaf_spots", 701), "image/jpeg")},
        data={"plant_species": "Mango", "save": "false"},
    )
    uncertain = (envelope(uncertain_reply).get("data") or {}).get("analysis") or {}
    treatment = uncertain.get("treatment") or {}
    confidence = uncertain.get("confidence_level")

    results.check(
        "Chemical advice is withheld while the assessment is uncertain",
        confidence == "confident" or treatment.get("chemical_options") is None,
        f"confidence={confidence}, chemical_withheld={treatment.get('chemical_withheld')}",
        "Chemical treatments were offered for an unconfirmed assessment.",
    )

    results.check(
        "Safe cultural and organic guidance is still provided",
        len(treatment.get("organic_options") or []) > 0
        or len(treatment.get("cultural_controls") or []) > 0,
        f"{len(treatment.get('organic_options') or [])} organic, "
        f"{len(treatment.get('cultural_controls') or [])} cultural",
        "No safe alternative guidance was offered.",
    )

    # No dosage may appear anywhere in the response.
    import re as _re

    dosage = _re.compile(r"\b\d+\s*(?:ml|g|kg|mg|litre|liter|gallon|tsp|tbsp|ppm)\b", _re.I)
    results.check(
        "No dosages or application rates appear in the guidance",
        not dosage.search(json.dumps(uncertain)),
        reason="A dose or application rate was present in the treatment guidance.",
    )

    # ---- /api/diagnosis is the same handler as /api/analyze-plant --------
    aliased = client.post(
        "/api/diagnosis",
        files={"image": ("spots.jpg", as_jpeg("leaf_spots", 701), "image/jpeg")},
        data={"plant_species": "Mango", "save": "false"},
    )
    aliased_analysis = (envelope(aliased).get("data") or {}).get("analysis") or {}
    results.check(
        "POST /api/diagnosis and /api/analyze-plant give the same result",
        aliased.status_code == 200
        and (aliased_analysis.get("condition") or {}).get("id")
        == (uncertain.get("condition") or {}).get("id")
        and aliased_analysis.get("confidence_level") == uncertain.get("confidence_level"),
        f"both: {(aliased_analysis.get('condition') or {}).get('label')}",
        "The alias and the primary route diverged - the handler is duplicated.",
    )

    # ---- condition and treatment reference -------------------------------
    diseases_data = envelope(client.get("/api/diseases")).get("data") or {}
    diseases = diseases_data.get("diseases") or []
    results.check(
        "GET /api/diseases lists every condition with its description and causes",
        len(diseases) > 0
        and diseases_data.get("count") == len(diseases)
        and bool(diseases_data.get("severity_scale"))
        and bool(diseases_data.get("cause_categories"))
        and all(
            item.get("id")
            and item.get("display_name")
            and item.get("description")
            and item.get("severity")
            # "healthy" legitimately has no cause - nothing is wrong with the leaf.
            and (item.get("cause_categories") or item["severity"] == "none")
            for item in diseases
        ),
        f"{len(diseases)} condition(s), severity scale and cause categories included",
        "A condition entry was missing its id, name, description or cause categories.",
    )

    results.check(
        "The reference includes non-disease explanations",
        {"leaf_scorch", "nutrient_deficiency", "pest_damage", "senescence"}
        <= {item.get("id") for item in diseases},
        "scorch, nutrient deficiency, pest damage and senescence are all present",
        "Only diseases are listed - damage would always be read as infection.",
    )

    treatments_data = envelope(client.get("/api/treatments")).get("data") or {}
    treatments = treatments_data.get("treatments") or []
    results.check(
        "GET /api/treatments returns a plan per condition",
        len(treatments) == len(diseases)
        and all(item.get("condition_id") for item in treatments),
        f"{len(treatments)} plan(s) for {len(diseases)} condition(s)",
        "The treatment plans and the condition list do not line up.",
    )

    chemical_plans = [
        item for item in treatments if isinstance(item.get("chemical_options"), dict)
    ]
    results.check(
        "No dosages appear in the treatment reference, and chemicals need verifying",
        not dosage.search(json.dumps(treatments))
        and len(chemical_plans) > 0
        and all(
            item["chemical_options"].get("requires_verification") is True
            and item["chemical_options"].get("active_ingredient_classes")
            and item.get("chemical_disclaimer")
            for item in chemical_plans
        ),
        f"{len(chemical_plans)} plan(s) with chemicals, each an ingredient class "
        f"carrying requires_verification and the disclaimer",
        "A dosage was present, or a chemical entry was not flagged for verification.",
    )

    filtered = client.get("/api/treatments?condition=early_blight")
    filtered_items = (envelope(filtered).get("data") or {}).get("treatments") or []
    unknown_condition = client.get("/api/treatments?condition=not_a_condition")
    results.check(
        "GET /api/treatments filters by condition and 404s on an unknown one",
        filtered.status_code == 200
        and len(filtered_items) == 1
        and filtered_items[0].get("condition_id") == "early_blight"
        and unknown_condition.status_code == 404,
        f"filter returned 1 plan; unknown condition -> {unknown_condition.status_code}",
    )

    # ---- persistence -----------------------------------------------------
    if created:
        record = envelope(client.get(f"/api/history/{created[0]}")).get("data") or {}
        results.check(
            "The universal analysis is persisted with the record",
            record.get("analysis_mode") == "universal"
            and record.get("plant_species")
            and record.get("analysis") is not None,
            f"mode={record.get('analysis_mode')}, species={record.get('plant_species')}, "
            f"confidence={record.get('confidence_level')}",
            f"record fields were mode={record.get('analysis_mode')}, "
            f"species={record.get('plant_species')}",
        )

        # ---- PDF report --------------------------------------------------
        pdf_reply = client.get(f"/api/history/{created[0]}/report")
        disposition = pdf_reply.headers.get("Content-Disposition", "")
        results.check(
            "GET /api/history/<id>/report returns a valid PDF",
            pdf_reply.status_code == 200
            and pdf_reply.headers.get("Content-Type") == "application/pdf"
            and pdf_reply.content.startswith(b"%PDF-")
            and "attachment" in disposition
            and ".pdf" in disposition,
            f"{len(pdf_reply.content)} bytes, {disposition}",
            f"HTTP {pdf_reply.status_code}, type={pdf_reply.headers.get('Content-Type')}",
        )

        results.check(
            "GET /api/history/<id>/report 404s for a record that does not exist",
            client.get("/api/history/999999999/report").status_code == 404,
        )

    return created


def check_device_configuration(client: Client, results: Results) -> None:
    """The dashboard-driven ESP32-CAM address configuration."""
    section("6. ESP32-CAM configuration")

    original = (envelope(client.get("/api/device/config")).get("data") or {}).get("addresses", {})

    response = client.get("/api/device/config")
    data = envelope(response).get("data") or {}
    results.check(
        "GET /api/device/config reports the effective address",
        response.status_code == 200 and "addresses" in data,
        f"effective={data.get('addresses', {}).get('effective')} "
        f"(from {data.get('addresses', {}).get('effective_from')})",
        f"HTTP {response.status_code}",
    )

    saved = client.post("/api/device/config", json={"ip_address": "192.0.2.50"})
    saved_data = envelope(saved).get("data") or {}
    results.check(
        "POST /api/device/config saves an address",
        saved.status_code == 200
        and saved_data.get("ip_address") == "192.0.2.50"
        and saved_data.get("addresses", {}).get("effective") == "192.0.2.50"
        and saved_data.get("addresses", {}).get("effective_from") == "dashboard",
        "dashboard value overrides .env and discovery",
        f"HTTP {saved.status_code}: {saved.text[:200]}",
    )

    results.check(
        "An unreachable configured address is reported, not hidden",
        saved_data.get("live_probe", {}).get("reachable") is False,
        "probe result returned alongside the save",
        "The probe claimed a TEST-NET address was reachable.",
    )

    invalid = client.post("/api/device/config", json={"ip_address": "not a host!!"})
    results.check(
        "An invalid address is rejected",
        invalid.status_code == 400,
        f"HTTP {invalid.status_code}",
        f"Expected 400, got HTTP {invalid.status_code}",
    )

    # Restore whatever was configured before the test ran.
    client.post("/api/device/config", json={"ip_address": original.get("dashboard") or ""})
    restored = (envelope(client.get("/api/device/config")).get("data") or {}).get("addresses", {})
    results.check(
        "Original configuration restored",
        restored.get("dashboard") == original.get("dashboard"),
        f"dashboard={restored.get('dashboard')}",
        "Could not restore the original address setting.",
    )


def check_validation(client: Client, results: Results) -> None:
    section("7. Input validation and error handling")

    cases: Sequence[Tuple[str, Callable[[], requests.Response], int, Optional[str]]] = (
        (
            "Non-image bytes are rejected",
            lambda: client.post("/api/predict", files={"image": ("x.jpg", b"this is not a jpeg", "image/jpeg")}),
            400,
            "INVALID_IMAGE",
        ),
        (
            "Missing file part is rejected",
            lambda: client.post("/api/predict", files={}),
            400,
            "VALIDATION_ERROR",
        ),
        (
            "Empty body is rejected",
            lambda: client.post("/api/predict", data=b"", headers={"Content-Type": "image/jpeg"}),
            400,
            None,
        ),
        (
            "Tiny image is rejected",
            lambda: client.post("/api/predict", files={"image": ("t.png", make_tiny_image(), "image/png")}),
            400,
            "INVALID_IMAGE",
        ),
        (
            "Invalid history filter is rejected",
            lambda: client.get("/api/history?status=not_a_status"),
            400,
            "VALIDATION_ERROR",
        ),
        (
            "Invalid limit is rejected",
            lambda: client.get("/api/history?limit=999999"),
            400,
            "VALIDATION_ERROR",
        ),
        (
            "Unknown route returns a JSON 404",
            lambda: client.get("/api/does-not-exist"),
            404,
            None,
        ),
        (
            "Clearing history without confirmation is refused",
            lambda: client.delete("/api/history"),
            400,
            "VALIDATION_ERROR",
        ),
        # The device upload path, which is the one the firmware uses. An empty
        # body and a truncated JPEG are both real device faults and must be
        # refused rather than stored as a successful detection.
        (
            "Empty device upload is refused",
            lambda: client.post(
                "/api/device/upload?device=smoke-test-device",
                data=b"",
                headers={"Content-Type": "image/jpeg"},
            ),
            400,
            "INVALID_IMAGE",
        ),
        (
            "Truncated device JPEG is refused",
            lambda: client.post(
                "/api/device/upload?device=smoke-test-device",
                # Valid SOI marker and plausible length, but no EOI: exactly
                # what a Wi-Fi transfer cut short looks like.
                data=b"\xff\xd8\xff\xe0" + b"\x00" * 4000,
                headers={"Content-Type": "image/jpeg"},
            ),
            400,
            "INVALID_IMAGE",
        ),
        (
            "Unsupported device Content-Type is refused",
            lambda: client.post(
                "/api/device/upload?device=smoke-test-device",
                data=b"hello",
                headers={"Content-Type": "text/plain"},
            ),
            400,
            "VALIDATION_ERROR",
        ),
    )

    for name, call, expected_status, expected_code in cases:
        try:
            response = call()
        except requests.RequestException as exc:
            results.fail(name, f"Request error: {exc}")
            continue

        body = envelope(response)
        code = (body.get("error") or {}).get("code")
        status_ok = response.status_code == expected_status
        code_ok = expected_code is None or code == expected_code

        results.check(
            name,
            status_ok and code_ok and body.get("success") is False,
            f"HTTP {response.status_code} {code}",
            f"Expected HTTP {expected_status}"
            + (f" with code {expected_code}" if expected_code else "")
            + f", got HTTP {response.status_code} with code {code}.",
        )


def check_history(client: Client, results: Results) -> None:
    section("8. Detection history")

    response = client.get("/api/history?limit=5")
    data = envelope(response).get("data") or {}
    pagination = data.get("pagination") or {}

    results.check(
        "GET /api/history is paginated",
        response.status_code == 200 and "items" in data and "total" in pagination,
        f"{len(data.get('items', []))} of {pagination.get('total')} records, page {pagination.get('page')}/{pagination.get('pages')}",
        f"HTTP {response.status_code}",
    )

    items = data.get("items") or []
    if items:
        required = {
            "id", "image_url", "plant_name", "predicted_disease", "confidence",
            "detection_status", "created_at", "source", "model_mode", "is_validated",
        }
        missing = required - set(items[0].keys())
        results.check(
            "History records carry every required field",
            not missing,
            f"{len(items[0])} fields present",
            f"Missing fields: {sorted(missing)}",
        )

        single = client.get(f"/api/history/{items[0]['id']}")
        results.check(
            "GET /api/history/<id>",
            single.status_code == 200,
            f"record #{items[0]['id']}",
            f"HTTP {single.status_code}",
        )

        absent = client.get("/api/history/99999999")
        results.check(
            "Unknown record id returns 404",
            absent.status_code == 404,
            reason=f"HTTP {absent.status_code}",
        )
    else:
        results.skip("History record fields", "no records in the database")

    filters = client.get("/api/history/filters")
    results.check(
        "GET /api/history/filters",
        filters.status_code == 200 and "plants" in (envelope(filters).get("data") or {}),
        reason=f"HTTP {filters.status_code}",
    )

    filtered = client.get("/api/history?status=healthy&limit=5")
    results.check(
        "Status filter is applied",
        filtered.status_code == 200
        and all(
            item["detection_status"] == "healthy"
            for item in ((envelope(filtered).get("data") or {}).get("items") or [])
        ),
        reason="A non-healthy record came back from a status=healthy query.",
    )


def check_statistics(client: Client, results: Results) -> None:
    section("9. Statistics and analytics")

    stats_response = client.get("/api/stats")
    stats = envelope(stats_response).get("data") or {}
    totals = stats.get("totals") or {}

    results.check(
        "GET /api/stats",
        stats_response.status_code == 200 and "totals" in stats,
        f"{totals.get('total_detections')} detections, {totals.get('today')} today",
        f"HTTP {stats_response.status_code}",
    )

    component_sum = (
        totals.get("healthy", 0)
        + totals.get("diseased", 0)
        + totals.get("uncertain", 0)
        + totals.get("unknown", 0)
    )
    results.check(
        "Status counts add up to the total",
        component_sum == totals.get("total_detections"),
        f"{component_sum} == {totals.get('total_detections')}",
        f"Components sum to {component_sum} but total is {totals.get('total_detections')}.",
    )

    results.check(
        "Activity series is continuous and zero-filled",
        len(stats.get("activity") or []) == 14,
        f"{len(stats.get('activity') or [])} daily points",
        f"Expected 14 daily points, got {len(stats.get('activity') or [])}.",
    )

    history = client.get("/api/history?limit=1")
    history_total = ((envelope(history).get("data") or {}).get("pagination") or {}).get("total")
    results.check(
        "Statistics agree with the history table",
        history_total == totals.get("total_detections"),
        f"both report {history_total}",
        f"/api/stats says {totals.get('total_detections')}, /api/history says {history_total}.",
    )

    analytics_response = client.get("/api/analytics?days=30")
    analytics = envelope(analytics_response).get("data") or {}
    results.check(
        "GET /api/analytics",
        analytics_response.status_code == 200 and "model_evaluation" in analytics,
        f"evaluation available: {analytics.get('model_evaluation', {}).get('available')}",
        f"HTTP {analytics_response.status_code}",
    )

    if not analytics.get("model_evaluation", {}).get("available"):
        print(
            f"  {YELLOW}NOTE{RESET}  No evaluation report yet - run "
            f"`python ml/train.py --dataset-dir ml/dataset` to populate model metrics."
        )


def check_device(client: Client, results: Results) -> None:
    section("10. Device endpoints")

    response = client.get("/api/device/status")
    data = envelope(response).get("data") or {}

    results.check(
        "GET /api/device/status",
        response.status_code == 200 and "configured" in data,
        f"online={data.get('is_online')}, resolved ip={data.get('configured', {}).get('resolved_ip')}",
        f"HTTP {response.status_code}",
    )

    results.check(
        "Troubleshooting guidance is generated",
        bool(data.get("troubleshooting")),
        f"{len(data.get('troubleshooting', []))} checks",
        "The troubleshooting list was empty.",
    )

    devices = client.get("/api/devices")
    results.check(
        "GET /api/devices",
        devices.status_code == 200,
        f"{(envelope(devices).get('data') or {}).get('count')} registered",
        f"HTTP {devices.status_code}",
    )

    # Heartbeat: the exact call the firmware makes on boot.
    heartbeat = client.post(
        "/api/device/register",
        json={
            "device_name": "smoke-test-device",
            "ip_address": "10.0.0.123",
            "wifi_ssid": "SMOKE-TEST",
            "wifi_rssi": -58,
            "firmware_version": "smoke-test",
            "camera_model": "SMOKE TEST (no hardware)",
            "led_state": "off",
            "free_heap": 150000,
            "uptime_seconds": 42,
        },
        headers={"X-Device-Name": "smoke-test-device"},
    )
    heartbeat_data = envelope(heartbeat).get("data") or {}
    results.check(
        "POST /api/device/register accepts a heartbeat",
        heartbeat.status_code == 200 and (heartbeat_data.get("device") or {}).get("is_online") is True,
        f"command={heartbeat_data.get('command', {}).get('action')}",
        f"HTTP {heartbeat.status_code}: {heartbeat.text[:160]}",
    )

    command = client.get("/api/device/command?device=smoke-test-device")
    results.check(
        "GET /api/device/command returns 'none' when idle",
        command.status_code == 200
        and (envelope(command).get("data") or {}).get("action") == "none",
        reason=f"HTTP {command.status_code}: {command.text[:160]}",
    )

    empty_upload = client.post(
        "/api/device/upload?device=smoke-test-device",
        data=b"",
        headers={"Content-Type": "image/jpeg"},
    )
    results.check(
        "Empty device upload is rejected",
        empty_upload.status_code == 400,
        reason=f"HTTP {empty_upload.status_code}",
    )

    # Clean up the fake device so it does not linger on the Device page.
    client.delete("/api/device/smoke-test-device")


def cleanup(client: Client, results: Results, record_ids: List[int]) -> None:
    section("11. Cleanup")
    if not record_ids:
        results.skip("Delete test records", "nothing was created")
        return

    removed = 0
    for record_id in record_ids:
        if client.delete(f"/api/history/{record_id}").status_code == 200:
            removed += 1

    results.check(
        "Test records deleted",
        removed == len(record_ids),
        f"{removed} of {len(record_ids)} removed",
        f"Only {removed} of {len(record_ids)} test records could be deleted.",
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify every backend endpoint against a running server.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--server", default=DEFAULT_SERVER, help="Backend base URL")
    parser.add_argument("--keep", action="store_true", help="Keep the detection records created by the test")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout in seconds")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    client = Client(args.server, args.timeout)
    results = Results()

    print(f"{BOLD}Plant Disease Detection - API smoke test{RESET}")
    print(f"{GREY}Target: {client.base_url}{RESET}")

    health = check_health(client, results)
    if health is None:
        print(f"\n{RED}The backend is not reachable. Start it with:{RESET}")
        print("    cd backend")
        print("    python app.py")
        return 1

    check_classes(client, results)

    created: List[int] = []
    if health.get("model", {}).get("can_predict"):
        created = check_prediction(client, results)
    else:
        section("3. Prediction pipeline")
        results.skip("Prediction checks", "the backend reports it cannot predict")

    if health.get("model", {}).get("can_predict"):
        created += check_camera_sources(client, results)
    else:
        section("4. Camera sources")
        results.skip("Camera source checks", "the backend reports it cannot predict")

    if health.get("universal_analysis", {}).get("enabled", True):
        created += check_universal_analysis(client, results)
    else:
        section("5. Universal plant analysis")
        results.skip("Universal analysis checks", "disabled on this server")

    check_device_configuration(client, results)
    check_validation(client, results)
    check_history(client, results)
    check_statistics(client, results)
    check_device(client, results)

    if args.keep:
        section("11. Cleanup")
        results.skip("Delete test records", "--keep was passed")
    else:
        cleanup(client, results, created)

    # ---- summary ---------------------------------------------------------
    total = results.passed + results.failed
    print(f"\n{BOLD}{'=' * 62}{RESET}")
    print(
        f"{BOLD}Summary:{RESET} {GREEN}{results.passed} passed{RESET}, "
        f"{RED if results.failed else GREY}{results.failed} failed{RESET}, "
        f"{YELLOW if results.skipped else GREY}{results.skipped} skipped{RESET}"
        f"  ({total} assertions)"
    )

    if results.failures:
        print(f"\n{RED}Failures:{RESET}")
        for name, reason in results.failures:
            print(f"  - {name}: {reason}")
        print(f"{BOLD}{'=' * 62}{RESET}")
        return 1

    print(f"{GREEN}All checks passed.{RESET}")
    print(f"{BOLD}{'=' * 62}{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
