"""
services/vision_service.py
==========================
Optional adapter for a configurable AI vision API.

Why this is optional and separate
---------------------------------
Plant *species* identification is the one requirement that local code cannot
honestly meet. Colour histograms and blob geometry do not encode species - a
mango leaf and a guava leaf are both green ellipses. So the system has exactly
three ways to know what plant it is looking at, in descending reliability:

    1. the user tells us            (always available, usually correct)
    2. a vision model tells us      (needs an API key; this module)
    3. the MobileNetV2 classifier   (only for its 10 trained classes)

If no key is configured this module reports ``available: False`` with a reason,
and the rest of the system carries on using local measurements plus whatever
the user declared. Nothing degrades silently and nothing is invented to fill
the gap.

Supported providers: ``openai``, ``gemini``, ``anthropic``, and
``openai_compatible`` for self-hosted or proxy endpoints that speak the OpenAI
chat-completions schema.

The model is prompted to return strict JSON, to answer ``"unknown"`` rather
than guess, to separate what it *sees* from what it *infers*, and never to
state a pesticide dose. Its output is additionally sanitised here, because a
prompt is a request, not a guarantee.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("openai", "gemini", "anthropic", "openai_compatible")

# Phrases that indicate a dosage or concentration. If the model returns one
# despite the instruction, the field is dropped rather than shown.
DOSAGE_PATTERN = re.compile(
    r"\b\d+\s*(?:ml|l|litre|liter|g|kg|mg|oz|gallon|tsp|tbsp|ppm|%)\b"
    r"|\bper\s+(?:litre|liter|gallon|acre|hectare)\b"
    r"|\b\d+\s*(?:ml|g)\s*/\s*(?:l|litre|liter|gal)",
    re.IGNORECASE,
)

PROMPT = """You are assisting a plant disease detection system. Analyse the attached photograph of a plant leaf.

Return ONLY a JSON object, with no markdown fencing and no commentary, in exactly this shape:

{
  "plant_species": "common name, or null if you cannot tell",
  "plant_species_scientific": "scientific name, or null",
  "plant_category": "e.g. Fruit tree, Vegetable, Ornamental shrub, or null",
  "species_certainty": "high" | "medium" | "low" | "unknown",
  "is_leaf_image": true | false,
  "observed_symptoms": ["short factual descriptions of what is VISIBLE, e.g. 'brown circular spots with yellow halos on the upper surface'"],
  "appears_healthy": true | false | null,
  "candidate_conditions": [
    {
      "name": "condition name",
      "reasoning": "which visible features point to this",
      "certainty": "high" | "medium" | "low"
    }
  ],
  "possible_causes": ["environmental, cultural or biological factors that could produce what is visible"],
  "recommended_next_steps": ["what the grower should look at or do next to narrow this down"],
  "uncertainty_notes": "what you cannot determine from this single image"
}

Rules you must follow:
- Describe only what is actually visible in THIS image. Do not describe a typical case of a disease.
- If you cannot identify the species, set plant_species to null and species_certainty to "unknown". Do not guess.
- Damage is not automatically disease. Include non-pathogenic explanations (water stress, nutrient deficiency, sun scorch, physical or insect damage, normal ageing) in candidate_conditions and possible_causes where they fit.
- If the image is not a plant leaf, set is_leaf_image to false and leave the symptom and condition lists empty.
- Never state a pesticide product name, a dose, a concentration or a mixing rate. Recommend categories of action only.
- Never claim certainty you do not have. "low" certainty is an acceptable and useful answer.
"""


class VisionService:
    """Thin, provider-agnostic client for an image-understanding API."""

    def __init__(self, config: Any) -> None:
        self._config = config
        self._session = requests.Session()
        self._last_error: Optional[str] = None
        self._calls = 0
        self._failures = 0

    # ------------------------------------------------------------------ #
    # Availability
    # ------------------------------------------------------------------ #

    @property
    def provider(self) -> str:
        return str(getattr(self._config, "VISION_API_PROVIDER", "openai")).lower().strip()

    @property
    def model(self) -> Optional[str]:
        return getattr(self._config, "VISION_API_MODEL", None)

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._config, "VISION_API_ENABLED", False))

    @property
    def api_key(self) -> Optional[str]:
        return getattr(self._config, "VISION_API_KEY", None)

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.api_key) and self.provider in SUPPORTED_PROVIDERS

    def status(self) -> Dict[str, Any]:
        """Reported by ``/api/health`` and shown on the dashboard."""
        if not self.enabled:
            reason = (
                "Disabled. Set VISION_API_ENABLED=true and VISION_API_KEY in .env to "
                "enable AI plant species identification."
            )
        elif not self.api_key:
            reason = "Enabled but VISION_API_KEY is not set, so no requests can be made."
        elif self.provider not in SUPPORTED_PROVIDERS:
            reason = (
                f"Unsupported VISION_API_PROVIDER '{self.provider}'. "
                f"Choose one of: {', '.join(SUPPORTED_PROVIDERS)}."
            )
        else:
            reason = f"Ready ({self.provider}, model {self.model})."

        return {
            "available": self.available,
            "enabled": self.enabled,
            "provider": self.provider if self.enabled else None,
            "model": self.model if self.available else None,
            "has_api_key": bool(self.api_key),
            "reason": reason,
            "calls": self._calls,
            "failures": self._failures,
            "last_error": self._last_error,
            "capability_note": (
                "When unavailable, plant species identification falls back to the species "
                "you select manually, and the local computer-vision symptom measurements "
                "are used on their own."
            ),
        }

    # ------------------------------------------------------------------ #
    # Request building
    # ------------------------------------------------------------------ #

    def _build_request(self, image_b64: str, mime: str, hint: Optional[str]) -> Dict[str, Any]:
        prompt = PROMPT
        if hint:
            # A hint is passed as context, not as an answer - the model is told
            # it may disagree, so a wrong hint does not silently propagate.
            prompt += (
                f"\nThe user believes this plant is '{hint}'. Treat that as a hint only: "
                "if the image clearly shows a different plant, say so and give your own "
                "identification."
            )

        timeout = float(getattr(self._config, "VISION_API_TIMEOUT", 45.0))
        base_url = getattr(self._config, "VISION_API_BASE_URL", None)
        model = self.model

        if self.provider in ("openai", "openai_compatible"):
            url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
            return {
                "url": url,
                "timeout": timeout,
                "headers": {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                "json": {
                    "model": model,
                    "max_tokens": 1200,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                                },
                            ],
                        }
                    ],
                },
            }

        if self.provider == "anthropic":
            url = (base_url or "https://api.anthropic.com/v1").rstrip("/") + "/messages"
            return {
                "url": url,
                "timeout": timeout,
                "headers": {
                    "x-api-key": str(self.api_key),
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                "json": {
                    "model": model,
                    "max_tokens": 1200,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime,
                                        "data": image_b64,
                                    },
                                },
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                },
            }

        # gemini
        base = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        url = f"{base}/models/{model}:generateContent"
        return {
            "url": url,
            "timeout": timeout,
            "headers": {"Content-Type": "application/json"},
            "params": {"key": self.api_key},
            "json": {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": mime, "data": image_b64}},
                        ]
                    }
                ],
                "generationConfig": {"maxOutputTokens": 1200, "temperature": 0.2},
            },
        }

    def _extract_text(self, payload: Dict[str, Any]) -> Optional[str]:
        """Pull the assistant's text out of a provider-shaped response."""
        try:
            if self.provider in ("openai", "openai_compatible"):
                return payload["choices"][0]["message"]["content"]
            if self.provider == "anthropic":
                blocks = payload.get("content") or []
                return "".join(block.get("text", "") for block in blocks if isinstance(block, dict))
            if self.provider == "gemini":
                parts = payload["candidates"][0]["content"]["parts"]
                return "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("Could not read the vision response shape: %s", exc)
        return None

    # ------------------------------------------------------------------ #
    # Parsing and sanitising
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_json(text: str) -> Optional[Dict[str, Any]]:
        """Parse JSON out of a model reply, tolerating markdown fences."""
        if not text:
            return None

        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

        # Fall back to the outermost brace pair.
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None

    @classmethod
    def _sanitise(cls, raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalise and filter the model's output.

        Two filters are applied because a prompt instruction is a request, not
        a guarantee: any string containing something that looks like a dose is
        dropped, and free-text fields are length-capped so a runaway response
        cannot flood the UI or the database.
        """
        def clean_list(value: Any, limit: int = 8) -> List[str]:
            if not isinstance(value, list):
                return []
            output: List[str] = []
            for item in value[:limit]:
                text = str(item).strip()
                if not text or len(text) > 400:
                    continue
                if DOSAGE_PATTERN.search(text):
                    logger.info("Dropped a vision-API line containing a dosage: %r", text[:80])
                    continue
                output.append(text)
            return output

        def clean_text(value: Any, limit: int = 600) -> Optional[str]:
            if value is None:
                return None
            text = str(value).strip()
            if not text or text.lower() in ("null", "none", "unknown", "n/a"):
                return None
            if DOSAGE_PATTERN.search(text):
                return None
            return text[:limit]

        certainty = str(raw.get("species_certainty", "unknown")).lower().strip()
        if certainty not in ("high", "medium", "low", "unknown"):
            certainty = "unknown"

        conditions: List[Dict[str, Any]] = []
        for item in (raw.get("candidate_conditions") or [])[:5]:
            if not isinstance(item, dict):
                continue
            name = clean_text(item.get("name"), 120)
            if not name:
                continue
            item_certainty = str(item.get("certainty", "low")).lower().strip()
            conditions.append(
                {
                    "name": name,
                    "reasoning": clean_text(item.get("reasoning"), 400) or "",
                    "certainty": item_certainty if item_certainty in ("high", "medium", "low") else "low",
                }
            )

        species = clean_text(raw.get("plant_species"), 120)
        appears_healthy = raw.get("appears_healthy")

        return {
            "plant_species": species,
            "plant_species_scientific": clean_text(raw.get("plant_species_scientific"), 160),
            "plant_category": clean_text(raw.get("plant_category"), 80),
            # A species name without certainty is meaningless, so an unknown
            # certainty downgrades the name to "unidentified".
            "species_certainty": certainty if species else "unknown",
            "is_leaf_image": bool(raw.get("is_leaf_image", True)),
            "observed_symptoms": clean_list(raw.get("observed_symptoms")),
            "appears_healthy": appears_healthy if isinstance(appears_healthy, bool) else None,
            "candidate_conditions": conditions,
            "possible_causes": clean_list(raw.get("possible_causes")),
            "recommended_next_steps": clean_list(raw.get("recommended_next_steps")),
            "uncertainty_notes": clean_text(raw.get("uncertainty_notes"), 600),
        }

    # ------------------------------------------------------------------ #
    # Public call
    # ------------------------------------------------------------------ #

    def analyse(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        species_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Ask the configured vision model to describe the leaf.

        Never raises: a failure returns ``{"available": False, "reason": ...}``
        so a dead or misconfigured API degrades the analysis rather than
        breaking the request.
        """
        if not self.available:
            return {"available": False, "attempted": False, **self.status()}

        request = self._build_request(
            base64.b64encode(image_bytes).decode("ascii"), mime_type, species_hint
        )
        self._calls += 1
        started = time.perf_counter()

        try:
            response = self._session.post(
                request["url"],
                headers=request["headers"],
                params=request.get("params"),
                json=request["json"],
                timeout=request["timeout"],
            )
        except requests.RequestException as exc:
            self._failures += 1
            self._last_error = str(exc)
            logger.warning("Vision API request failed: %s", exc)
            return {
                "available": False,
                "attempted": True,
                "provider": self.provider,
                "reason": f"The vision API could not be reached: {exc}",
            }

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        if response.status_code >= 400:
            self._failures += 1
            self._last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            logger.warning("Vision API returned HTTP %d: %s", response.status_code, response.text[:200])
            return {
                "available": False,
                "attempted": True,
                "provider": self.provider,
                "reason": (
                    f"The vision API returned HTTP {response.status_code}. "
                    "Check the API key, the model name, and your account quota."
                ),
                "status_code": response.status_code,
            }

        try:
            payload = response.json()
        except ValueError:
            self._failures += 1
            self._last_error = "Response was not JSON"
            return {
                "available": False,
                "attempted": True,
                "provider": self.provider,
                "reason": "The vision API response was not JSON.",
            }

        text = self._extract_text(payload)
        parsed = self._parse_json(text or "")

        if parsed is None:
            self._failures += 1
            self._last_error = "Could not parse the model's JSON"
            logger.warning("Vision model did not return parseable JSON: %r", (text or "")[:200])
            return {
                "available": False,
                "attempted": True,
                "provider": self.provider,
                "reason": (
                    "The vision model did not return valid JSON, so its answer was "
                    "discarded rather than guessed at."
                ),
                "raw_text": (text or "")[:500],
            }

        self._last_error = None
        result = self._sanitise(parsed)
        result.update(
            {
                "available": True,
                "attempted": True,
                "provider": self.provider,
                "model": self.model,
                "latency_ms": round(elapsed_ms, 1),
                "source": "ai_vision_api",
            }
        )
        logger.info(
            "Vision API identified species=%r (certainty %s) in %.0f ms",
            result.get("plant_species"),
            result.get("species_certainty"),
            elapsed_ms,
        )
        return result


# --------------------------------------------------------------------------- #
# Singleton
# --------------------------------------------------------------------------- #

_service: Optional[VisionService] = None


def init_vision_service(config: Any) -> VisionService:
    global _service
    _service = VisionService(config)
    status = _service.status()
    if status["available"]:
        logger.info("AI vision API enabled: %s (%s)", status["provider"], status["model"])
    else:
        logger.info("AI vision API not in use: %s", status["reason"])
    return _service


def get_vision_service() -> VisionService:
    if _service is None:
        raise RuntimeError(
            "VisionService has not been initialised. init_vision_service(config) must "
            "run inside create_app()."
        )
    return _service


__all__ = ["VisionService", "SUPPORTED_PROVIDERS", "init_vision_service", "get_vision_service"]
