# Universal Plant Leaf Analysis

How PlantGuard AI analyses **any** plant leaf, not only the ten classes the
MobileNetV2 model was trained on.

---

## 1. The problem this solves

The trained classifier knows exactly ten PlantVillage classes across three
crops (tomato, potato, pepper). A softmax layer always produces an answer, so
feeding it a mango leaf returns a tomato disease with a confidence number
attached. That answer is not wrong by a little - it is meaningless, and the
confidence makes it look trustworthy.

The upgrade adds a second, independent analysis path that does not depend on
species at all, and a rule that decides which path applies.

---

## 2. Two layers, clearly separated

| | Trained classifier | Universal analysis |
|---|---|---|
| Method | MobileNetV2 CNN | OpenCV measurement + rule inference |
| Covers | 10 classes, 3 crops | Any plant |
| Output | A class with a softmax probability | Measured symptoms, and conditions consistent with them |
| Needs training | Yes | No |
| Identifies species | Within its 3 crops | No - see §4 |
| Used when | The plant is one it was trained on *and* it is confident | Always |

Both are always computed where possible. The analysis reports which ones
actually contributed, so a reader can see where the answer came from.

### The guard that matters

```python
def _classifier_applies(plant_name, species_key):
    """The classifier is consulted only for plants it was trained on."""
    if species_key in CLASSIFIER_SPECIES_MAP.values():   # tomato/potato/pepper
        return True
    ...
    return False
```

Without this, a mango leaf becomes a tomato diagnosis. With it, the classifier
stays silent and the universal layer answers. The response states the reason:

> *"The trained classifier was not used: it only covers pepper, potato, tomato,
> and this plant is outside that list."*

---

## 3. What the universal layer measures

`ml/leaf_analysis.py` is classical computer vision - deterministic, explainable,
and the same image always gives the same numbers.

**Segmentation.** A leaf is tissue with real chroma where red and/or green
clearly exceed blue. That holds for healthy green, chlorotic yellow, necrotic
brown and rust orange, and rejects grey desks, white paper, sky and shadow. The
largest connected component becomes the leaf; regions *enclosed* by it are
recovered separately, which is how pale powdery coating and dark lesions get
included without loosening the colour test.

Holes are told apart from surface patches by comparing each enclosed region
against the measured background colour. A gap shows the background; a mildew
patch does not. Without this, a hole over a dark desk reads as a black lesion.

**Measurements**, all as a fraction of leaf area:

| Measurement | What it indicates |
|---|---|
| Healthy green fraction | Remaining functional tissue |
| Chlorotic yellow fraction | Nutrient loss, virus, senescence |
| Necrotic brown fraction | Dead tissue |
| Dark spot fraction | Lesions, sunken anthracnose |
| Powdery white fraction | Surface coating |
| Rust-orange fraction | Pustules (separated from brown by brightness) |
| Lesion count, mean size, circularity | Many small round spots vs few large irregular patches |
| Margin vs interior necrosis | Edge scorch vs a spotting pathogen |
| Hole fraction | Insect feeding, tears |
| Mottling score | Mosaic-style patterning in green tissue |
| Solidity | Curling, rolling, lost margin |

Every reported symptom carries the measurement that produced it:

> *"4.2% of the leaf area is brown necrotic tissue, in 7 discrete lesions"*

That sentence is checkable against the image. "Septoria leaf spot, 87%
confidence" is not.

### Two corrections worth knowing about

Both were found by testing, and both matter on real photographs:

**Morphology order.** Opening must happen before closing. Sensor noise on a flat
background pushes a few percent of isolated pixels through the colour test;
closing first bridges them into one mass that swallows the frame. With the
original order a healthy leaf measured 96% coverage against a true 31% and
reported severe symptoms everywhere.

**Boundary inset.** The measurement region is eroded a few pixels inside the
leaf outline. JPEG compression rings at the high-contrast leaf/background edge,
and the leaf's own edge is a gradient, so a band of intermediate pixels hugs the
outline. Measured directly, every single JPEG reported "browning at the leaf
edges". Genuine marginal scorch extends well inside this band and is still
detected.

---

## 4. Plant species identification

This is the honest limitation. Colour histograms and blob geometry do not encode
species - a mango leaf and a guava leaf are both green ellipses. There are three
ways the system can know the plant, in descending reliability:

1. **The user selects it.** Always available, usually correct, and it outranks
   everything else. A grower looking at their own plant is more reliable than a
   classifier that knows three crops.
2. **An AI vision API tells us.** Optional, needs a key. See §5.
3. **The trained classifier**, for its three crops only.

If none applies, the plant is reported as **unidentified** and the care guidance
is generic. It is never guessed at.

15 species have a care profile: mango, neem, rose, hibiscus, banana, papaya,
guava, apple, grapevine, tomato, potato, pepper, corn, lemon, orange. Any other
plant is still analysed - symptoms do not depend on species - and receives
general plant-care guidance, with the UI saying so.

Alias matching handles the spellings people actually type:

```
bell pepper      -> pepper
chilli           -> pepper
Mangifera indica -> mango
angoor           -> grapes
a rose leaf      -> rose
dragonfruit      -> None    (not guessed)
```

---

## 5. The optional AI vision API

Configure in `.env`:

```ini
VISION_API_ENABLED=true
VISION_API_PROVIDER=openai        # openai | gemini | anthropic | openai_compatible
VISION_API_KEY=sk-...
VISION_API_MODEL=gpt-4o-mini
VISION_API_BASE_URL=              # only for self-hosted / proxy endpoints
VISION_API_TIMEOUT=45
```

The model is prompted to return strict JSON, to answer `null` rather than guess
a species, to separate what it *sees* from what it *infers*, to include
non-pathogenic explanations, and never to state a dose.

Because a prompt is a request and not a guarantee, the reply is also sanitised
in code: any string matching a dosage pattern is dropped, fields are
length-capped, and a species name without stated certainty is downgraded to
unidentified. A reply that will not parse as JSON is discarded rather than
pattern-matched for fragments.

The vision reading can **raise** confidence when it independently agrees with
the local measurements. It cannot override them on its own.

When no key is configured, `/api/health`, `/api/plants` and the dashboard all
report it plainly:

> *"Disabled. Set VISION_API_ENABLED=true and VISION_API_KEY in .env to enable
> AI plant species identification."*

> **Not verified by me.** I had no API key available, so the provider request
> and response shapes are written from each provider's documented schema but
> have never been executed against a live endpoint. The no-key path - which is
> the default - is fully tested. Expect to debug the request shape on first use.

---

## 6. Conditions and the honesty rules

`ml/condition_rules.py` maps measured symptoms to possible conditions. Supported:

| Condition | Category |
|---|---|
| Healthy | none |
| Leaf spot | fungal/bacterial |
| Bacterial leaf spot | bacterial |
| Early blight | fungal |
| Late blight | fungal |
| Powdery mildew | fungal |
| Downy mildew | fungal |
| Rust | fungal |
| Anthracnose | fungal |
| Leaf scorch / marginal burn | **abiotic** |
| Mosaic-like symptoms | viral |
| Insect / pest feeding damage | **pest** |
| Nutrient deficiency / chlorosis | **abiotic** |
| Natural ageing | **abiotic** |

The four non-disease entries are the point. *Damage is not automatically
disease* - the most common cause of a damaged leaf is often water stress,
feeding, sun scorch or an insect. A rule set containing only diseases would find
a disease in every image.

Three rules govern the output:

**Possibilities, not a diagnosis.** Every candidate carries
`is_diagnosis: false` and `is_confirmed_diagnosis` is always false on the report.
Several conditions produce indistinguishable symptoms in one photograph.

**No invented numbers.** Support is `strong` / `moderate` / `weak`, derived from
how many rule criteria the measurements satisfied. There is no probability,
because a rule match is not a probability. The only numeric confidence anywhere
in the report is the trained classifier's softmax value, which is a real
measured quantity.

**Say what would settle it.** Every candidate lists `confirm_by` - what to look
at next to tell the shortlist apart:

> *"Try wiping the white film with a finger - powdery mildew rubs off, mineral
> deposits do not"*
> *"Examine the UNDERSIDE beneath the yellow patches for greyish-purple fuzz"*

---

## 7. Treatment guidance

Four tiers per condition: immediate actions, organic options, cultural controls,
and prevention. Plus chemical options, under strict conditions.

### Chemical options are withheld unless the assessment is confident

```python
treatment = get_treatment(condition_id, certain=(confidence_level == "confident"))
```

Anything less than `confident` returns the cultural and organic measures - which
are safe whether or not the diagnosis is right - plus an explanation:

> *"Chemical options are hidden because the assessment is not confident enough.
> Applying a treatment for the wrong cause wastes money, can damage the plant,
> and delays the right fix."*

### No product names and no dosages exist in the data

The knowledge base contains only documented active-ingredient **classes**
("copper-based fungicides", "potassium bicarbonate", "Bacillus thuringiensis").
Every chemical entry carries `requires_verification: true` and a disclaimer that
registration differs by country and only the label is authoritative. The test
suite asserts that no dosage pattern appears anywhere in a response, and the
vision-API sanitiser strips any that a model returns.

Abiotic conditions - leaf scorch, nutrient deficiency, senescence - and viral
ones have `chemical_options: null` outright, because a fungicide does not fix
drought or a virus.

---

## 8. API

### `POST /api/analyze-plant`

The endpoint behind the dashboard's **Analyse plant** button.

| Field | Notes |
|---|---|
| `image` | multipart file, raw `image/jpeg` body, or `image_base64` JSON |
| `plant_species` | optional, e.g. `"mango"`. Free text accepted |
| `camera_source` | `laptop_webcam` / `esp32_cam` / `file_upload` |
| `use_vision_api` | set `false` to skip the vision call for this request |
| `threshold` | classifier confidence threshold override |
| `save` | `false` to analyse without recording |

Response shape (abridged):

```jsonc
{
  "assessment": "symptoms_observed",
  "confidence_level": "possible",
  "basis": "Rule match against measured symptoms (moderate support, ...)",
  "is_confirmed_diagnosis": false,
  "plant":     { "name": "Mango", "category": "Fruit tree",
                 "identification_source": "user_declared", "in_knowledge_base": true },
  "condition": { "id": "leaf_spot", "label": "Leaf spot ...", "candidates": [ ... ] },
  "symptoms":  { "detected": [ { "id": "brown_necrosis", "severity": "mild",
                                 "evidence": "3.3% of the leaf area is brown ...",
                                 "metric": 0.033 } ] },
  "treatment": { "immediate_actions": [...], "organic_options": [...],
                 "chemical_options": null, "chemical_withheld": true,
                 "withheld_reason": "..." },
  "care":      { "watering": "...", "soil": "...", "prevention": [...] },
  "next_steps":   [...],
  "limitations":  [...],
  "evidence_sources": { "used": ["local_cv", "user_declared_species"],
                        "classifier": { "used": false, "note": "..." },
                        "ai_vision":  { "available": false, "reason": "..." } }
}
```

### `GET /api/plants`

Species with care profiles, what the classifier covers, and the vision API's
status.

`POST /api/predict` is unchanged and still classifier-only, so nothing built
against it breaks.

---

## 9. Database

Migration 004 adds, additively:

| Column | Contents |
|---|---|
| `plant_species` | Identified or declared species |
| `species_source` | `user_declared` / `ai_vision_api` / `trained_classifier` / `unidentified` |
| `analysis_mode` | `classifier` / `universal` |
| `confidence_level` | `confident` / `probable` / `possible` / `insufficient` |
| `analysis` | The full report, as JSON |
| `symptoms` | The measured symptom list, as JSON |

Existing rows are backfilled with `analysis_mode = 'classifier'` and are
otherwise untouched. The universal assessment is mapped onto the existing
`detection_status` vocabulary (`healthy` / `diseased` / `uncertain` / `unknown`)
so the column's CHECK constraint and every existing query keep working -
`symptoms_observed` becomes `uncertain`, because symptoms without a confirmed
cause is exactly what that means.

---

## 10. Testing

```bash
python scripts/test_leaf_analysis.py          # 10 assertions, CV discrimination
python scripts/smoke_test.py                  # 90 assertions, full API
```

`test_leaf_analysis.py` renders nine synthetic leaves - healthy, leaf spots,
large blight patches, yellowing, powdery coating, edge scorch, holes, rust, and
a blank wall - and asserts that each produces the right symptoms and the right
shortlist. Its most important check is the last one:

```
PASS  all 9 cases produced a distinct result (no canned response)
```

Measured results:

| Image | Symptoms measured | Top candidate |
|---|---|---|
| healthy | none | healthy |
| leaf_spots | brown_necrosis | leaf_spot |
| large_blight | brown_necrosis, dark_spots | late_blight |
| yellowing | yellowing | nutrient_deficiency |
| powdery | powdery_coating | powdery_mildew |
| edge_scorch | margin_necrosis, brown_necrosis | leaf_scorch |
| holes | holes_and_damage | pest_damage |
| rust | rust_coloured_pustules | rust |
| blank_wall | none | *insufficient evidence* |

The API suite additionally asserts that an out-of-class plant (Mango) is
analysed rather than rejected, that the classifier is not forced onto it, that a
clean leaf is not given a disease, that chemical advice is withheld while
uncertain, and that no dosage appears anywhere in a response.

### Not verified

* The AI vision API request/response path - no key was available.
* Accuracy on real photographs of real leaves. The synthetic tests verify the
  measurement and rule logic. Real-world accuracy needs field-captured images
  with known ground truth, and the honest expectation is that cluttered
  backgrounds and uneven light will degrade segmentation noticeably.

---

## 11. Honest summary of what this is

It is a **symptom measurement and triage tool**, not a diagnostic instrument.

What it does well: measures what is visible, repeatably and explainably; tells
you which conditions are consistent with those measurements and which are not;
tells you what to look at next; and refuses to name a chemical treatment for a
problem it has not pinned down.

What it cannot do: confirm a pathogen (that needs laboratory testing or expert
inspection), identify a species without being told or without a vision API, see
the leaf underside, or distinguish causes that look identical in a photograph -
marginal browning from drought, salt and root damage is the same brown.

Those limits are returned in every response under `limitations` and rendered as
a titled section in the UI, not a footnote.
