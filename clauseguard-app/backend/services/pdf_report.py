"""Renders a FinalReport as an official-looking legal-style PDF (ReportLab).

Layout notes:
- Page chrome (navy header band, gold rule, footer disclaimer) is drawn
  directly on the canvas via the page template's onPage callback, since it
  must repeat identically on every page regardless of flowable content.
- "Page X / Y" needs the total page count, which isn't known until the whole
  document has been laid out. We use the standard ReportLab two-pass trick:
  a Canvas subclass buffers each page in showPage() and only stamps the
  page-number text once save() knows how many pages exist in total.
"""

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from models.schemas import FinalReport, ReportClause


def _find_logo_path() -> Optional[Path]:
    try:
        backend_dir = Path(__file__).resolve().parent.parent
        candidates = [
            backend_dir.parent / "frontend" / "public" / "clauseguard_logo.png",
            backend_dir.parent / "frontend" / "src" / "assets" / "clauseguard_logo.png",
            backend_dir / "public" / "clauseguard_logo.png",
            backend_dir / "src" / "assets" / "clauseguard_logo.png",
            backend_dir.parent / "public" / "clauseguard_logo.png",
            backend_dir.parent / "src" / "assets" / "clauseguard_logo.png",
        ]
        for p in candidates:
            if p.exists():
                return p
    except Exception:
        pass
    return None

PAGE_SIZE = A4
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE
MARGIN = 2 * cm
HEADER_HEIGHT = 1.6 * cm
FOOTER_HEIGHT = 1.3 * cm
GOLD_RULE_HEIGHT = 0.06 * cm

NAVY = colors.HexColor("#1E2A38")
GOLD = colors.HexColor("#C89B3C")
COLOR_VERT = colors.HexColor("#2E7D32")
COLOR_ORANGE = colors.HexColor("#F9A825")
COLOR_ROUGE = colors.HexColor("#C62828")
COLOR_UNKNOWN = colors.HexColor("#64748B")
TEXT_MUTED = colors.HexColor("#4B5563")
FOOTER_GRAY = colors.HexColor("#6B7280")
BORDER_GRAY = colors.HexColor("#D1D5DB")
BOX_BG = colors.HexColor("#F7F8FA")

RISK_COLORS = {
    "VERT": COLOR_VERT,
    "ORANGE": COLOR_ORANGE,
    "ROUGE": COLOR_ROUGE,
    "UNKNOWN": COLOR_UNKNOWN,
}

RISK_LABELS = {
    "VERT": "VERT",
    "ORANGE": "ORANGE",
    "ROUGE": "ROUGE",
    "UNKNOWN": "INCONNU",
}

DECISION_LABELS = {
    "approve": "Approuvé",
    "approved": "Approuvé",
    "reject": "Rejeté",
    "rejected": "Rejeté",
    "reclassify": "Reclassé",
    "downgraded": "Reclassé",
    "request_lawyer_review": "Avis avocat requis",
    "pending_human_validation": "En attente de validation",
    "ask_for_more_context": "Complément demandé",
}


def _styles() -> dict:
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "CGTitle",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            textColor=NAVY,
            spaceAfter=4,
        ),
        "meta": ParagraphStyle(
            "CGMeta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=TEXT_MUTED,
            leading=13,
        ),
        "meta_mono": ParagraphStyle(
            "CGMetaMono",
            parent=base["Normal"],
            fontName="Courier",
            fontSize=8,
            textColor=TEXT_MUTED,
            leading=12,
        ),
        "h2": ParagraphStyle(
            "CGH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=NAVY,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "CGBody",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=14,
            alignment=TA_JUSTIFY,
        ),
        "clause_subtitle": ParagraphStyle(
            "CGClauseSubtitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            textColor=NAVY,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "mono_small": ParagraphStyle(
            "CGMonoSmall",
            parent=base["Normal"],
            fontName="Courier",
            fontSize=8,
            textColor=TEXT_MUTED,
            leading=11,
        ),
        "rewrite_box": ParagraphStyle(
            "CGRewriteBox",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#1F2937"),
        ),
        "decision_line": ParagraphStyle(
            "CGDecisionLine",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=TEXT_MUTED,
            spaceBefore=4,
        ),
        "table_cell": ParagraphStyle(
            "CGTableCell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
        ),
        "table_header": ParagraphStyle(
            "CGTableHeader",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.white,
        ),
        "metric_value": ParagraphStyle(
            "CGMetricValue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=15,
            textColor=NAVY,
            alignment=TA_CENTER,
        ),
        "metric_label": ParagraphStyle(
            "CGMetricLabel",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            textColor=TEXT_MUTED,
            alignment=TA_CENTER,
            leading=10,
        ),
    }
    return styles


class RiskPill(Flowable):
    """A small rounded, filled badge with a white bold label."""

    def __init__(self, label: str, risk_level: str, width: float = 3.6 * cm, height: float = 0.85 * cm):
        super().__init__()
        self.label = label
        self.fill_color = RISK_COLORS.get(risk_level, COLOR_UNKNOWN)
        self.width = width
        self.height = height

    def wrap(self, avail_width, avail_height):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.fill_color)
        c.roundRect(0, 0, self.width, self.height, radius=self.height / 2, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawCentredString(self.width / 2, self.height / 2 - 3.5, self.label)
        c.restoreState()


class _NumberedCanvas(pdfcanvas.Canvas):
    """Buffers pages so the footer can show 'Page X / Y' (total pages is only
    known once the whole document has been laid out)."""

    def __init__(self, *args, **kwargs):
        pdfcanvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_number(total_pages)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

    def _draw_page_number(self, total_pages: int) -> None:
        self.setFont("Helvetica", 7)
        self.setFillColor(FOOTER_GRAY)
        self.drawRightString(
            PAGE_WIDTH - MARGIN, FOOTER_HEIGHT / 2 - 2, f"Page {self._pageNumber} / {total_pages}"
        )


def _draw_chrome(canvas_obj: pdfcanvas.Canvas, _doc, disclaimer: str) -> None:
    canvas_obj.saveState()

    # Header navy band.
    canvas_obj.setFillColor(NAVY)
    canvas_obj.rect(0, PAGE_HEIGHT - HEADER_HEIGHT, PAGE_WIDTH, HEADER_HEIGHT, fill=1, stroke=0)
    canvas_obj.setFillColor(colors.white)

    logo_path = _find_logo_path()
    text_x = MARGIN
    if logo_path:
        try:
            img = ImageReader(str(logo_path))
            logo_height = 18.0
            logo_width = 18.0 * (316.0 / 298.0)
            logo_y = PAGE_HEIGHT - (HEADER_HEIGHT / 2) - (logo_height / 2)
            canvas_obj.drawImage(
                img,
                MARGIN,
                logo_y,
                width=logo_width,
                height=logo_height,
                mask="auto",
                preserveAspectRatio=True,
            )
            text_x = MARGIN + logo_width + 8
        except Exception:
            text_x = MARGIN

    canvas_obj.setFont("Helvetica-Bold", 13)
    canvas_obj.drawString(text_x, PAGE_HEIGHT - HEADER_HEIGHT / 2 - 4, "ClauseGuard")
    canvas_obj.setFont("Helvetica", 9)
    canvas_obj.drawRightString(
        PAGE_WIDTH - MARGIN, PAGE_HEIGHT - HEADER_HEIGHT / 2 - 3, "Rapport de pré-lecture contractuelle"
    )

    # Gold rule under the header band.
    canvas_obj.setFillColor(GOLD)
    canvas_obj.rect(0, PAGE_HEIGHT - HEADER_HEIGHT - GOLD_RULE_HEIGHT, PAGE_WIDTH, GOLD_RULE_HEIGHT, fill=1, stroke=0)

    # Footer disclaimer (page number is stamped later by _NumberedCanvas).
    canvas_obj.setFont("Helvetica", 7)
    canvas_obj.setFillColor(FOOTER_GRAY)
    canvas_obj.drawCentredString(PAGE_WIDTH / 2, FOOTER_HEIGHT / 2 - 2, disclaimer)

    canvas_obj.restoreState()


def _risk_pill_row(styles: dict, label: str, risk_level: str) -> Table:
    row = Table(
        [[Paragraph(label, styles["meta"]), RiskPill(RISK_LABELS.get(risk_level, risk_level), risk_level)]],
        colWidths=[6 * cm, 4 * cm],
    )
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return row


def _metric_box(styles: dict, value, label: str) -> Table:
    box = Table(
        [[Paragraph(str(value), styles["metric_value"])], [Paragraph(label, styles["metric_label"])]],
        colWidths=[4 * cm],
    )
    box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.75, BORDER_GRAY),
                ("BACKGROUND", (0, 0), (-1, -1), BOX_BG),
                ("TOPPADDING", (0, 0), (0, 0), 8),
                ("BOTTOMPADDING", (0, 0), (0, 0), 2),
                ("BOTTOMPADDING", (0, 1), (0, 1), 8),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    return box


def _metrics_strip(styles: dict, report: FinalReport) -> Table:
    metrics = report.dashboard_metrics
    citation_pct = f"{round(metrics.citation_rate * 100)} %" if metrics.citation_rate is not None else "—"
    boxes = [
        _metric_box(styles, metrics.total_clauses_processed, "Clauses analysées"),
        _metric_box(styles, metrics.orange_red_detection_count, "Orange / Rouge détectées"),
        _metric_box(styles, citation_pct, "Taux de citation"),
        _metric_box(styles, metrics.human_validation_pending_count, "En attente de validation"),
    ]
    strip = Table([boxes], colWidths=[4.2 * cm] * 4)
    strip.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return strip


def _clause_table(styles: dict, clauses: list[ReportClause]) -> Table:
    header = [
        Paragraph("Référence", styles["table_header"]),
        Paragraph("Type", styles["table_header"]),
        Paragraph("Risque", styles["table_header"]),
        Paragraph("Décision humaine", styles["table_header"]),
    ]
    rows = [header]
    for clause in clauses:
        risk_color = RISK_COLORS.get(clause.risk_level, COLOR_UNKNOWN)
        risk_style = ParagraphStyle(
            f"risk_{clause.clause_id}", parent=styles["table_cell"], textColor=risk_color, fontName="Helvetica-Bold"
        )
        rows.append(
            [
                Paragraph(clause.reference, styles["table_cell"]),
                Paragraph(clause.type, styles["table_cell"]),
                Paragraph(RISK_LABELS.get(clause.risk_level, clause.risk_level), risk_style),
                Paragraph(
                    DECISION_LABELS.get(clause.human_decision, clause.human_decision or "—"), styles["table_cell"]
                ),
            ]
        )
    table = Table(rows, colWidths=[4.5 * cm, 4 * cm, 2.5 * cm, 4 * cm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER_GRAY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BOX_BG]),
            ]
        )
    )
    return table


def _clause_block(styles: dict, clause: ReportClause) -> list:
    flow: list = []
    subtitle_row = Table(
        [
            [
                Paragraph(f"{clause.reference} — {clause.type}", styles["clause_subtitle"]),
                RiskPill(RISK_LABELS.get(clause.risk_level, clause.risk_level), clause.risk_level, width=3 * cm, height=0.7 * cm),
            ]
        ],
        colWidths=[12 * cm, 3 * cm],
    )
    subtitle_row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    flow.append(subtitle_row)
    flow.append(Paragraph(clause.finding, styles["body"]))

    if clause.sources:
        flow.append(Spacer(1, 3))
        flow.append(Paragraph("Sources : " + ", ".join(clause.sources), styles["mono_small"]))

    if clause.proposed_rewrite:
        flow.append(Spacer(1, 5))
        rewrite_box = Table(
            [[Paragraph("<b>Reformulation proposée</b><br/>" + clause.proposed_rewrite, styles["rewrite_box"])]],
            colWidths=[16.5 * cm],
        )
        rewrite_box.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), BOX_BG),
                    ("LINEBEFORE", (0, 0), (0, -1), 2.2, GOLD),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ]
            )
        )
        flow.append(rewrite_box)

    decision_label = DECISION_LABELS.get(clause.human_decision, clause.human_decision or "—")
    decision_text = f"Décision humaine : <b>{decision_label}</b> — statut d'audit : {clause.audit_status}"
    flow.append(Paragraph(decision_text, styles["decision_line"]))
    flow.append(Spacer(1, 8))
    return flow


def build_pdf(report: FinalReport, filename: str, validated_by: Optional[str] = None) -> bytes:
    """Render `report` as an official-looking PDF and return the raw bytes.

    `filename` isn't embedded in the PDF content itself (it's used by the
    caller for the Content-Disposition header) but is accepted here to keep
    the call site self-descriptive and to allow future title-page use.
    """
    styles = _styles()
    buffer = io.BytesIO()

    doc = BaseDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        title=filename,
        author="ClauseGuard",
    )
    frame = Frame(
        MARGIN,
        FOOTER_HEIGHT + 0.3 * cm,
        PAGE_WIDTH - 2 * MARGIN,
        PAGE_HEIGHT - HEADER_HEIGHT - FOOTER_HEIGHT - 0.6 * cm,
        id="main",
    )
    template = PageTemplate(
        id="cg",
        frames=[frame],
        onPage=lambda c, d: _draw_chrome(c, d, report.disclaimer),
    )
    doc.addPageTemplates([template])

    story: list = []

    logo_path = _find_logo_path()
    if logo_path:
        try:
            logo_w = 100.0
            logo_h = 100.0 * (298.0 / 316.0)
            cover_logo = Image(str(logo_path), width=logo_w, height=logo_h)
            cover_logo.hAlign = "CENTER"
            story.append(cover_logo)
            story.append(Spacer(1, 10))
        except Exception:
            pass

    story.append(Paragraph(filename.replace("_", " ").replace(".pdf", ""), styles["title"]))
    story.append(Paragraph(f"Date d'analyse : {report.analysis_date}", styles["meta"]))
    contract_id_short = report.contract_id[:8] if report.contract_id else "—"
    story.append(
        Paragraph(
            f"Référence dossier : {contract_id_short} — request_id : {report.request_id or '—'}",
            styles["meta_mono"],
        )
    )
    story.append(Spacer(1, 10))
    story.append(_risk_pill_row(styles, "Niveau de risque global", report.overall_risk))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Synthèse exécutive", styles["h2"]))
    story.append(Paragraph(report.executive_summary, styles["body"]))
    story.append(Spacer(1, 12))

    story.append(_metrics_strip(styles, report))
    story.append(Spacer(1, 16))

    story.append(Paragraph("Détail des clauses", styles["h2"]))
    story.append(_clause_table(styles, report.clauses))

    flagged_clauses = [c for c in report.clauses if c.risk_level in ("ORANGE", "ROUGE")]
    if flagged_clauses:
        story.append(Spacer(1, 10))
        for clause in flagged_clauses:
            story.extend(_clause_block(styles, clause))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Traçabilité", styles["h2"]))
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    traceability_lines = [
        f"Généré le : {generated_at}",
        f"Request ID : {report.request_id or '—'}",
        f"Mode de livraison : {report.delivery}",
        "Modèles utilisés : Groq llama-3.3-70b, Gemini",
    ]
    if validated_by:
        traceability_lines.append(f"Validé par : {validated_by}")
    story.append(Paragraph("<br/>".join(traceability_lines), styles["meta_mono"]))

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buffer.getvalue()
