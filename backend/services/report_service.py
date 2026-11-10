"""
services/report_service.py
==========================
Generates the downloadable PDF diagnosis report.

Built with ReportLab's platypus flowables rather than absolute positioning, so
content of any length paginates instead of overflowing a fixed canvas - symptom
and treatment lists vary a lot between diagnoses.

The report carries the same caveats as the dashboard, by design. A PDF gets
printed, forwarded and acted on away from the UI that produced it, so the
uncertainty has to travel with it: the confidence level, the "not a confirmed
diagnosis" statement, the limitations, and the chemical-verification notice all
appear in the document itself.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        HRFlowable,
        Image as RLImage,
        KeepTogether,
        ListFlowable,
        ListItem,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    REPORTLAB_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    REPORTLAB_AVAILABLE = False


LEAF_GREEN = "#16a34a"
DARK_GREEN = "#14532d"
INK = "#26332a"
MUTED = "#587055"
AMBER = "#b45309"
RED = "#b91c1c"

SEVERITY_COLOURS = {
    "none": LEAF_GREEN,
    "mild": "#65a30d",
    "moderate": AMBER,
    "severe": RED,
    "unknown": MUTED,
}


class ReportUnavailableError(RuntimeError):
    """Raised when ReportLab is not installed."""


def _styles() -> Dict[str, Any]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "RTitle", parent=base["Title"], fontSize=20, leading=24,
            textColor=colors.HexColor(DARK_GREEN), spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "RSubtitle", parent=base["Normal"], fontSize=9.5, leading=13,
            textColor=colors.HexColor(MUTED), spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "RH2", parent=base["Heading2"], fontSize=12.5, leading=16,
            textColor=colors.HexColor(DARK_GREEN), spaceBefore=12, spaceAfter=5,
        ),
        "h3": ParagraphStyle(
            "RH3", parent=base["Heading3"], fontSize=10.5, leading=14,
            textColor=colors.HexColor(INK), spaceBefore=8, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "RBody", parent=base["Normal"], fontSize=9.5, leading=13.5,
            textColor=colors.HexColor(INK), alignment=TA_LEFT,
        ),
        "small": ParagraphStyle(
            "RSmall", parent=base["Normal"], fontSize=8, leading=11,
            textColor=colors.HexColor(MUTED),
        ),
        "warn": ParagraphStyle(
            "RWarn", parent=base["Normal"], fontSize=8.5, leading=12,
            textColor=colors.HexColor(AMBER),
        ),
        "cell": ParagraphStyle(
            "RCell", parent=base["Normal"], fontSize=8.5, leading=11.5,
            textColor=colors.HexColor(INK),
        ),
        "cellHead": ParagraphStyle(
            "RCellHead", parent=base["Normal"], fontSize=7.5, leading=10,
            textColor=colors.HexColor(MUTED),
        ),
    }


def _bullets(items: List[str], style: Any, colour: str = LEAF_GREEN) -> Any:
    """A bulleted list, or a muted dash when empty."""
    cleaned = [str(item).strip() for item in items if str(item or "").strip()]
    if not cleaned:
        return Paragraph("<i>None recorded.</i>", style)
    return ListFlowable(
        [ListItem(Paragraph(item, style), leftIndent=10) for item in cleaned],
        bulletType="bullet",
        bulletColor=colors.HexColor(colour),
        bulletFontSize=6,
        leftIndent=12,
        spaceBefore=1,
        spaceAfter=1,
    )


def _panel(title: str, body: Any, styles: Dict[str, Any], tint: str = "#f6f7f6") -> Table:
    """A titled, tinted block that keeps its heading with its content."""
    table = Table(
        [[Paragraph(f"<b>{title}</b>", styles["h3"])], [body]],
        colWidths=[170 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(tint)),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e3e8e4")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def _header_footer(canvas: Any, doc: Any) -> None:
    """Brand bar on every page plus a page number."""
    canvas.saveState()
    width, height = A4

    canvas.setFillColor(colors.HexColor(DARK_GREEN))
    canvas.rect(0, height - 12 * mm, width, 12 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(15 * mm, height - 8 * mm, "PlantGuard AI  -  Plant Diagnosis Report")
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(
        width - 15 * mm, height - 8 * mm, "Advisory only - not a confirmed diagnosis"
    )

    canvas.setFillColor(colors.HexColor(MUTED))
    canvas.setFont("Helvetica", 7.5)
    canvas.drawCentredString(width / 2, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _image_flowable(image_path: Optional[Path], width_mm: float = 72.0) -> Optional[Any]:
    """Scale the leaf image to a fixed width, preserving aspect ratio."""
    if not image_path or not image_path.is_file():
        return None
    try:
        reader = ImageReader(str(image_path))
        source_width, source_height = reader.getSize()
        if not source_width or not source_height:
            return None
        width = width_mm * mm
        height = width * (source_height / source_width)
        return RLImage(str(image_path), width=width, height=height)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not embed %s in the report: %s", image_path, exc)
        return None


def build_diagnosis_report(
    record: Dict[str, Any],
    upload_folder: Path,
    app_version: str = "1.0.0",
) -> bytes:
    """
    Render a detection record as a PDF.

    ``record`` is a row from ``models.detection.get_detection`` - including its
    ``analysis`` block when the record came from the universal diagnosis path.
    Records produced by the classifier-only path still render; the sections
    that need analysis data are simply omitted.
    """
    if not REPORTLAB_AVAILABLE:
        raise ReportUnavailableError(
            "PDF generation needs ReportLab. Install it with:\n"
            "    pip install -r backend/requirements.txt"
        )

    styles = _styles()
    story: List[Any] = []

    analysis: Dict[str, Any] = record.get("analysis") or {}
    plant: Dict[str, Any] = analysis.get("plant") or {}
    condition: Dict[str, Any] = analysis.get("condition") or {}
    symptoms: Dict[str, Any] = analysis.get("symptoms") or {}
    severity: Dict[str, Any] = analysis.get("severity") or {}
    causes: Dict[str, Any] = analysis.get("causes") or {}
    treatment: Dict[str, Any] = analysis.get("treatment") or {}
    care: Dict[str, Any] = analysis.get("care") or {}

    plant_name = plant.get("name") or record.get("plant_name") or "Unidentified plant"
    disease_name = condition.get("label") or record.get("predicted_disease") or "No assessment"

    # ---- title ----------------------------------------------------------
    story.append(Paragraph("Plant Diagnosis Report", styles["title"]))
    story.append(
        Paragraph(
            f"Record #{record.get('id')} &nbsp;|&nbsp; "
            f"Generated {datetime.now().astimezone().strftime('%d %b %Y, %H:%M %Z')} "
            f"&nbsp;|&nbsp; PlantGuard AI v{app_version}",
            styles["subtitle"],
        )
    )
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor(LEAF_GREEN)))
    story.append(Spacer(1, 7))

    # ---- summary: image beside the key findings -------------------------
    image = _image_flowable(
        (Path(upload_folder) / record["image_path"]) if record.get("image_path") else None
    )

    confidence_text = (
        f"{record.get('confidence_percent', 0):.1f}% (trained classifier)"
        if record.get("is_validated")
        else str(analysis.get("confidence_level") or record.get("confidence_level") or "not stated").title()
    )
    severity_level = str(severity.get("level", "unknown"))

    summary_rows = [
        ["Plant identified", plant_name],
        ["Plant species", plant.get("scientific_name") or "Not determined"],
        ["Plant category", plant.get("category") or "Unknown"],
        ["Identified by", str(plant.get("identification_source") or "unknown").replace("_", " ")],
        ["Status", str(record.get("detection_status") or "unknown").title()],
        ["Possible condition", disease_name],
        ["Confidence", confidence_text],
        ["Severity (estimated)", severity.get("label", "Unknown")],
        ["Camera source", record.get("camera_source_label") or record.get("camera_source") or "-"],
        ["Detected on", record.get("created_at") or "-"],
    ]

    details = Table(
        [
            [Paragraph(label, styles["cellHead"]), Paragraph(f"<b>{value}</b>", styles["cell"])]
            for label, value in summary_rows
        ],
        colWidths=[32 * mm, 62 * mm],
    )
    details.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e3e8e4")),
            ]
        )
    )

    header = Table(
        [[image or Paragraph("<i>Image not available.</i>", styles["small"]), details]],
        colWidths=[74 * mm, 96 * mm],
    )
    header.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0)])
    )
    story.append(header)
    story.append(Spacer(1, 6))

    # ---- the caveat, stated prominently and early -----------------------
    caveat = Table(
        [[Paragraph(
            "<b>This is an advisory assessment, not a confirmed diagnosis.</b> It is based on "
            "visible features of a single leaf image. Several conditions produce similar "
            "symptoms, and confirming a pathogen requires laboratory testing or inspection by "
            "a qualified plant health professional. Verify before applying any treatment.",
            styles["warn"],
        )]],
        colWidths=[170 * mm],
    )
    caveat.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffbeb")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#fcd34d")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(caveat)

    # ---- disease information --------------------------------------------
    if condition.get("description"):
        story.append(Paragraph("1. Condition information", styles["h2"]))
        story.append(_panel(disease_name, Paragraph(condition["description"], styles["body"]), styles))

        if severity.get("basis"):
            story.append(Spacer(1, 4))
            story.append(
                Paragraph(
                    f"<b>Severity estimate: {severity.get('label')}</b> &nbsp;-&nbsp; "
                    f"{severity.get('guidance', '')}",
                    styles["body"],
                )
            )
            story.append(Paragraph(severity["basis"], styles["small"]))

    # ---- symptoms --------------------------------------------------------
    detected = symptoms.get("detected") or []
    story.append(Paragraph("2. Symptoms observed in this image", styles["h2"]))
    if detected:
        rows = [
            [
                Paragraph("Symptom", styles["cellHead"]),
                Paragraph("Severity", styles["cellHead"]),
                Paragraph("Measured evidence", styles["cellHead"]),
            ]
        ]
        for symptom in detected:
            rows.append(
                [
                    Paragraph(str(symptom.get("label", "")), styles["cell"]),
                    Paragraph(str(symptom.get("severity", "")).title(), styles["cell"]),
                    Paragraph(str(symptom.get("evidence", "")), styles["cell"]),
                ]
            )
        table = Table(rows, colWidths=[42 * mm, 20 * mm, 108 * mm], repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0fdf4")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3e8e4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)
    else:
        story.append(
            Paragraph(
                "No symptoms exceeded the reporting threshold. This describes the visible leaf "
                "surface only - early infection and underside symptoms would not appear.",
                styles["body"],
            )
        )

    if symptoms.get("ai_described"):
        story.append(Spacer(1, 4))
        story.append(Paragraph("AI vision reading", styles["h3"]))
        story.append(_bullets(symptoms["ai_described"], styles["body"], "#0891b2"))

    # ---- possible causes -------------------------------------------------
    story.append(Paragraph("3. Possible causes", styles["h2"]))
    category_labels = [item.get("label", "") for item in (causes.get("categories") or [])]
    if category_labels:
        story.append(
            Paragraph(
                "Categories consistent with the observations: <b>"
                + ", ".join(category_labels)
                + "</b>",
                styles["body"],
            )
        )
        story.append(Spacer(1, 3))
    story.append(_bullets(causes.get("detailed") or [], styles["body"], MUTED))
    if causes.get("note"):
        story.append(Paragraph(causes["note"], styles["small"]))

    # ---- candidate conditions -------------------------------------------
    candidates = condition.get("candidates") or []
    if candidates:
        story.append(Paragraph("4. Conditions consistent with the evidence", styles["h2"]))
        story.append(
            Paragraph(
                "Ranked by how well each fits the measurements. This is a shortlist to "
                "investigate, not a ranked set of diagnoses.",
                styles["small"],
            )
        )
        story.append(Spacer(1, 3))
        for index, candidate in enumerate(candidates[:4], start=1):
            block: List[Any] = [
                Paragraph(
                    f"<b>{index}. {candidate.get('label', '')}</b> "
                    f"<font size=8 color='{MUTED}'>({candidate.get('support', '')} match, "
                    f"{candidate.get('category', '')})</font>",
                    styles["body"],
                )
            ]
            if candidate.get("matched_evidence"):
                block.append(Paragraph("Evidence for:", styles["small"]))
                block.append(_bullets(candidate["matched_evidence"], styles["small"], LEAF_GREEN))
            if candidate.get("conflicting_evidence"):
                block.append(Paragraph("Evidence against:", styles["small"]))
                block.append(_bullets(candidate["conflicting_evidence"], styles["small"], AMBER))
            if candidate.get("confirm_by"):
                block.append(Paragraph("What to check next:", styles["small"]))
                block.append(_bullets(candidate["confirm_by"], styles["small"], "#0891b2"))
            block.append(Spacer(1, 5))
            story.append(KeepTogether(block))

    story.append(PageBreak())

    # ---- treatment -------------------------------------------------------
    story.append(Paragraph("5. Treatment recommendations", styles["h2"]))

    if treatment.get("chemical_withheld") and treatment.get("withheld_reason"):
        withheld = Table(
            [[Paragraph(f"<b>Chemical treatment withheld.</b> {treatment['withheld_reason']}", styles["warn"])]],
            colWidths=[170 * mm],
        )
        withheld.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffbeb")),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#fcd34d")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(withheld)
        story.append(Spacer(1, 5))

    if treatment.get("immediate_actions"):
        story.append(Paragraph("Immediate actions", styles["h3"]))
        story.append(_bullets(treatment["immediate_actions"], styles["body"], AMBER))

    organic_block: List[Any] = [Paragraph("<b>Organic / eco-friendly</b>", styles["h3"])]
    organic_block.append(_bullets(treatment.get("organic_options") or [], styles["cell"], LEAF_GREEN))

    chemical = treatment.get("chemical_options")
    chemical_block: List[Any] = [Paragraph("<b>Chemical control</b>", styles["h3"])]
    if isinstance(chemical, dict):
        chemical_block.append(
            Paragraph("Documented active ingredient classes:", styles["small"])
        )
        chemical_block.append(
            _bullets(chemical.get("active_ingredient_classes") or [], styles["cell"], RED)
        )
        if chemical.get("precautions"):
            chemical_block.append(Paragraph("Precautions:", styles["small"]))
            chemical_block.append(_bullets(chemical["precautions"], styles["cell"], AMBER))
    else:
        chemical_block.append(
            Paragraph(
                "<i>No chemical treatment is listed for this condition.</i>", styles["cell"]
            )
        )

    columns = Table(
        [[organic_block, chemical_block]],
        colWidths=[84 * mm, 86 * mm],
    )
    columns.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#f0fdf4")),
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#fef2f2")),
                ("BOX", (0, 0), (0, 0), 0.5, colors.HexColor("#bbf7d0")),
                ("BOX", (1, 0), (1, 0), 0.5, colors.HexColor("#fecaca")),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(Spacer(1, 4))
    story.append(columns)

    if treatment.get("cultural_controls"):
        story.append(Paragraph("Cultural and agricultural controls", styles["h3"]))
        story.append(_bullets(treatment["cultural_controls"], styles["body"], "#0891b2"))

    if treatment.get("chemical_disclaimer"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(treatment["chemical_disclaimer"], styles["warn"]))

    # ---- prevention ------------------------------------------------------
    story.append(Paragraph("6. Prevention and management", styles["h2"]))
    story.append(_bullets(treatment.get("prevention") or [], styles["body"], LEAF_GREEN))

    if care.get("prevention"):
        story.append(Paragraph(f"Specific to {plant_name}", styles["h3"]))
        story.append(_bullets(care["prevention"], styles["body"], LEAF_GREEN))

    # ---- plant care ------------------------------------------------------
    care_rows = [
        (label, care.get(key))
        for label, key in (
            ("Watering", "watering"),
            ("Soil", "soil"),
            ("Light", "light"),
            ("Feeding", "feeding"),
            ("Pruning", "pruning"),
        )
        if care.get(key)
    ]
    if care_rows:
        story.append(Paragraph("7. Plant care", styles["h2"]))
        table = Table(
            [
                [Paragraph(f"<b>{label}</b>", styles["cell"]), Paragraph(str(value), styles["cell"])]
                for label, value in care_rows
            ],
            colWidths=[26 * mm, 144 * mm],
        )
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e3e8e4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f6f7f6")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)

    # ---- next steps and limitations --------------------------------------
    if analysis.get("next_steps"):
        story.append(Paragraph("8. Recommended next steps", styles["h2"]))
        story.append(_bullets(analysis["next_steps"], styles["body"], "#0891b2"))

    story.append(Paragraph("9. Limitations of this assessment", styles["h2"]))
    limitations = list(analysis.get("limitations") or [])
    if not limitations:
        limitations = [
            "This assessment is based on a single leaf image and is advisory only.",
            "Confirming a pathogen requires laboratory testing or expert inspection.",
        ]
    story.append(_bullets(limitations, styles["body"], AMBER))

    # ---- evidence provenance ---------------------------------------------
    sources = analysis.get("evidence_sources") or {}
    classifier = sources.get("classifier") or {}
    vision = sources.get("ai_vision") or {}
    story.append(Paragraph("10. How this assessment was produced", styles["h2"]))
    provenance = [
        f"<b>Computer-vision measurement:</b> used. Evidence level "
        f"{symptoms.get('evidence_level', 'unknown')}, leaf segmentation "
        f"{symptoms.get('segmentation_quality', 'unknown')}.",
        f"<b>Trained MobileNetV2 classifier:</b> "
        + (
            "used."
            if classifier.get("used")
            else (classifier.get("note") or "not used.")
        ),
        f"<b>AI vision model:</b> "
        + (
            f"used ({vision.get('provider')}, {vision.get('model')})."
            if vision.get("available")
            else (vision.get("reason") or "not configured.")
        ),
    ]
    story.append(_bullets(provenance, styles["small"], MUTED))

    if condition.get("references"):
        story.append(Paragraph("Reference sources", styles["h3"]))
        story.append(_bullets(condition["references"], styles["small"], MUTED))

    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e3e8e4")))
    story.append(
        Paragraph(
            "Generated by PlantGuard AI. Treatment guidance names categories of active "
            "ingredient only and contains no dosages. Always confirm a product is registered "
            "for your crop in your country and follow its label.",
            styles["small"],
        )
    )

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=f"PlantGuard AI diagnosis report #{record.get('id')}",
        author="PlantGuard AI",
        subject=f"{plant_name} - {disease_name}",
    )
    document.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)

    pdf = buffer.getvalue()
    logger.info("Generated a %.1f KB PDF report for record #%s", len(pdf) / 1024, record.get("id"))
    return pdf


def report_filename(record: Dict[str, Any]) -> str:
    """A descriptive, filesystem-safe download name."""
    import re

    plant = str(
        (record.get("analysis") or {}).get("plant", {}).get("name")
        or record.get("plant_name")
        or "plant"
    )
    safe = re.sub(r"[^A-Za-z0-9]+", "-", plant).strip("-").lower() or "plant"
    stamp = datetime.now().strftime("%Y%m%d")
    return f"plantguard-diagnosis-{safe}-{record.get('id')}-{stamp}.pdf"


__all__ = [
    "REPORTLAB_AVAILABLE",
    "ReportUnavailableError",
    "build_diagnosis_report",
    "report_filename",
]
