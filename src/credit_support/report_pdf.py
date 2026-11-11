"""Paginated English/Spanish simulation reports with embedded Latin-script fonts."""

import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import reportlab
from pypdf import PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from credit_support.audit import canonical

fonts = Path(reportlab.__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("ReportVera", str(fonts / "Vera.ttf")))
pdfmetrics.registerFont(TTFont("ReportVeraBold", str(fonts / "VeraBd.ttf")))
pdfmetrics.registerFontFamily("ReportVera", normal="ReportVera", bold="ReportVeraBold")


def render_pdf(report: dict[str, Any]) -> bytes:
    es = report["locale"] == "es"

    def label(en: str, spanish: str) -> str:
        return spanish if es else en

    names = {
        "annual_revenue": ("Annual revenue", "Ingresos anuales"),
        "ebitda": ("EBITDA", "EBITDA"),
        "total_debt": ("Total debt", "Deuda total"),
        "debt_service": ("Debt service", "Servicio de deuda"),
        "available_cash_flow": ("Available cash flow", "Flujo de caja disponible"),
        "obligations": ("Obligations", "Obligaciones"),
    }
    terms = {
        **names,
        "PENDING": ("Pending review", "Revisión pendiente"),
        "APPROVED": ("Simulation approved", "Simulación aprobada"),
        "REJECTED": ("Simulation rejected", "Simulación rechazada"),
        "NEEDS_MORE_INFO": ("More information needed", "Se necesita información"),
        "extracted": ("Verified", "Verificado"),
        "missing": ("Missing", "Ausente"),
        "ambiguous": ("Conflicting evidence", "Evidencia contradictoria"),
        "invalid": ("Invalid input", "Entrada inválida"),
        "CALCULATED": ("Calculated", "Calculado"),
        "NOT_APPLICABLE": ("Not applicable", "No aplica"),
        "INVALID_INPUT": ("Invalid input", "Entrada inválida"),
        "MISSING_INPUT": ("Missing input", "Faltan datos"),
        "meets_rules": ("Meets the rules", "Cumple las reglas"),
        "exceptions": ("Policy exceptions", "Excepciones de política"),
        "insufficient_evidence": ("Insufficient evidence", "Evidencia insuficiente"),
        "PASS": ("Rule satisfied", "Regla cumplida"),
        "FAIL": ("Rule not satisfied", "Regla no cumplida"),
        "REQUIRES_REVIEW": ("Review required", "Requiere revisión"),
    }

    def display(value: str) -> str:
        return label(*terms[value]) if value in terms else value

    def finding(value: str) -> str:
        # Translate only complete known tokens in the presentation copy.
        return re.sub(
            r"\b(?:" + "|".join(map(re.escape, terms)) + r")\b",
            lambda match: display(match[0]),
            value,
        )

    def timestamp(value: str) -> str:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    styles = getSampleStyleSheet()
    for name, size, leading in [
        ("BodyText", 9, 13),
        ("Title", 23, 29),
        ("Heading1", 13, 19),
        ("Heading2", 10, 15),
    ]:
        styles[name].fontName = "ReportVeraBold" if name != "BodyText" else "ReportVera"
        styles[name].fontSize = size
        styles[name].leading = leading
        styles[name].textColor = colors.HexColor("#172c43")
        styles[name].alignment = TA_LEFT
    small = ParagraphStyle(
        "Small",
        parent=styles["BodyText"],
        fontSize=7,
        leading=10,
        textColor=colors.HexColor("#526577"),
        wordWrap="CJK",
    )

    def p(value: Any, style: str = "BodyText") -> Paragraph:
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style])

    def tiny(value: Any) -> Paragraph:
        return Paragraph(escape(str(value)), small)

    def table(rows: list[list[Any]], widths: list[float]) -> Table:
        cells = [[tiny(cell) for cell in row] for row in rows]
        result = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
        result.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eff5")),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#adc0d0")),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#e0e6ec")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        return result

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=(210 * mm, 297 * mm),
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=24 * mm,
        bottomMargin=22 * mm,
        title=label("Synthetic Credit Analysis", "Análisis crediticio sintético"),
        author="Credit Decision Support",
    )
    evaluation, review = report["evaluation"], report["review"]
    story: list[Any] = [
        p(report["marker"], "Heading2"),
        p(label("Credit analysis review", "Revisión de análisis crediticio"), "Title"),
        p(report["notice"]),
        Spacer(1, 5 * mm),
        table(
            [
                [label("Case", "Expediente"), report["case"]["id"]],
                [label("Evaluation", "Evaluación"), evaluation["evaluation_id"]],
                [
                    label("Cutoff / scope", "Fecha de corte / alcance"),
                    f"{report['case']['cutoff']} | {label('SME', 'PyME')} | USD | "
                    + label("Standalone statements", "Estados financieros individuales"),
                ],
                [
                    label("Current snapshot", "Evaluación actual"),
                    label("Yes", "Sí") if evaluation["current"] else label("No", "No"),
                ],
                [label("Human review", "Revisión humana"), display(review["state"])],
                [label("Exported at (UTC)", "Exportado (UTC)"), timestamp(report["generated_at"])],
            ],
            [45 * mm, 125 * mm],
        ),
        Spacer(1, 4 * mm),
    ]
    if review["record"]:
        record = review["record"]
        reviewer = record["reviewer_id"]
        if reviewer.startswith("guided:"):
            reviewer = label("Demo reviewer", "Revisor demo")
        story += [
            p(label("Human decision", "Decisión humana"), "Heading1"),
            p(f"{reviewer} | {display(record['decision'])} | {timestamp(record['created_at'])}"),
            p(record["reason"]),
            Spacer(1, 3 * mm),
        ]
    else:
        story += [
            p(
                label(
                    "Independent human review is pending.",
                    "La revisión humana independiente está pendiente.",
                )
            ),
            Spacer(1, 3 * mm),
        ]
    rows = [
        [
            label("Financial fact", "Dato financiero"),
            label("Value / USD", "Importe / USD"),
            label("Evidence status", "Estado de evidencia"),
        ]
    ]
    for fact in evaluation["facts"]:
        rows.append([label(*names[fact["key"]]), fact["value"] or "-", display(fact["status"])])
    story += [
        p(label("Financial facts", "Datos financieros"), "Heading1"),
        table(rows, [72 * mm, 48 * mm, 50 * mm]),
    ]
    calc = evaluation["calculations"][0]
    check = evaluation["policy_check"]
    story += [
        p(label("Calculation and policy", "Cálculo y política"), "Heading1"),
        p(f"DSCR: {calc['value'] or '-'} | {display(calc['status'])}"),
        p(f"{check['policy_version']} | {display(check['outcome'])}"),
        p(label("Verified draft findings", "Hallazgos verificados del borrador"), "Heading1"),
    ]
    for section in evaluation["ai_draft"]["section_order"]:
        for claim in evaluation["ai_draft"]["claims"]:
            if claim["section"] != section:
                continue
            group = [p(finding(claim["text_es" if es else "text_en"]))]
            refs = (
                claim["fact_ids"]
                + claim["evidence_ids"]
                + claim["calculation_ids"]
                + claim["policy_fragment_ids"]
            )
            if refs:
                group.append(tiny(f"{claim['id']}: " + "; ".join(refs)))
            group.append(Spacer(1, 2 * mm))
            story.append(KeepTogether(group))
    story.append(p(label("Source evidence", "Evidencia de fuentes"), "Heading1"))
    for evidence in evaluation["evidence"]:
        story.append(
            KeepTogether(
                [
                    tiny(evidence["id"]),
                    p(f"{evidence['excerpt']}"),
                    tiny(
                        f"{label('Document', 'Documento')}: {evidence['document_id']} | "
                        f"{evidence['locator']}"
                    ),
                    Spacer(1, 2 * mm),
                ]
            )
        )
    story.append(p(label("Policy citations", "Citas de política"), "Heading1"))
    for citation in check["citations"]:
        story += [
            p(citation["text_es" if es else "text_en"]),
            tiny(
                f"{citation['policy_version']} / {citation['fragment_id']} / {citation['sha256']}"
            ),
            Spacer(1, 2 * mm),
        ]
    story += [p(label("Source checksums", "Huellas de las fuentes"), "Heading1")]
    for source in report["documents"]:
        story += [
            tiny(f"{source['id']} | {source['media_type']} | {source['byte_size']} bytes"),
            tiny(source["sha256"]),
            Spacer(1, 2 * mm),
        ]
    story += [
        p(label("Audit and reconstruction", "Auditoría y reconstrucción"), "Heading1"),
        tiny(
            label("Technical codes", "Códigos técnicos")
            + ": "
            + f"{review['state']} | {calc['status']} | "
            + f"{calc['formula_version']} | {check['outcome']}"
        ),
        p(
            label(
                "Source checksums, locators, draft, policy, financial calculation, "
                "and audit chain verified.",
                "Huellas, localizadores, borrador, política, cálculo financiero "
                "y cadena de auditoría verificados.",
            )
        ),
        tiny(f"SHA-256: {report['integrity']['payload_sha256']}"),
        tiny(
            f"{label('Audit head', 'Último hash de auditoría')}: "
            f"{report['integrity']['audit_head']}"
        ),
        Spacer(1, 3 * mm),
    ]
    audit_rows = [["#", label("Event / actor", "Evento / actor"), "UTC"]]
    for event in report["audit_events"]:
        audit_rows.append(
            [str(event["sequence"]), f"{event['kind']} / {event['actor_id']}", event["created_at"]]
        )
    story.append(table(audit_rows, [10 * mm, 105 * mm, 55 * mm]))

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d5e0e9"))
        canvas.line(20 * mm, 18 * mm, 190 * mm, 18 * mm)
        canvas.setFont("ReportVera", 7)
        canvas.setFillColor(colors.HexColor("#526577"))
        canvas.drawString(20 * mm, 13 * mm, f"{report['marker']} | Credit Decision Support")
        canvas.drawRightString(190 * mm, 13 * mm, f"{doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    writer = PdfWriter(clone_from=BytesIO(output.getvalue()))
    writer.add_attachment("report.json", canonical(report).encode("utf-8"))
    bundled = BytesIO()
    writer.write(bundled)
    return bundled.getvalue()
