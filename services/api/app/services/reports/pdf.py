"""PDF rendering of a ReportBundle with ReportLab. Pure: bytes in, bytes out.

Layout follows docs/08 (header, overall evidence summary, tabs as sections) and the
docs/07 summary template. Levels are always spelled out in text; colour is only a
reinforcement. Nothing is rendered that is not in the bundle.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.providers.llm.base import SECTIONS
from app.services.reports.bundle import ReportBundle

PDF_VERSION = "v1"

LEVEL_COLOURS = {
    "VERIFIED": colors.HexColor("#d1fae5"),
    "STRONG": colors.HexColor("#ccfbf1"),
    "PROBABLE": colors.HexColor("#e0f2fe"),
    "POSSIBLE": colors.HexColor("#fef3c7"),
    "UNKNOWN": colors.HexColor("#f3f4f6"),
}

_styles = getSampleStyleSheet()
H1 = ParagraphStyle("vx-h1", parent=_styles["Heading1"], fontSize=18, spaceAfter=6)
H2 = ParagraphStyle("vx-h2", parent=_styles["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=4)
H3 = ParagraphStyle("vx-h3", parent=_styles["Heading3"], fontSize=10.5, spaceBefore=8, spaceAfter=2)
BODY = ParagraphStyle("vx-body", parent=_styles["BodyText"], fontSize=9, leading=12)
SMALL = ParagraphStyle(
    "vx-small", parent=BODY, fontSize=7.5, leading=10, textColor=colors.HexColor("#555555")
)
MONO = ParagraphStyle("vx-mono", parent=BODY, fontName="Courier", fontSize=7.5, leading=10)
CELL = ParagraphStyle("vx-cell", parent=BODY, fontSize=8, leading=10, alignment=TA_LEFT)


def _p(text: object, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(escape(str(text if text is not None else "—")), style)


def _fmt_dt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC")
    return str(value)


def _table(rows: Sequence[Sequence[Any]], widths: Sequence[float], *, header: bool = True) -> Table:
    t = Table([list(r) for r in rows], colWidths=list(widths), repeatRows=1 if header else 0)
    style: list[Any] = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d4d4d8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f4f5")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    t.setStyle(TableStyle(style))
    return t


def _yes_no(value: object) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "n/a"


def _level_cell(level: str) -> Paragraph:
    return Paragraph(f"<b>{escape(level)}</b>", CELL)


def _evidence_table(lines: Sequence[Any], width: float) -> Table | Paragraph:
    if not lines:
        return _p("None.", SMALL)
    rows: list[list[Any]] = [
        [_p("Level", CELL), _p("Claim", CELL), _p("Source", CELL), _p("Conf.", CELL)]
    ]
    for e in lines:
        body = escape(e.claim)
        if e.detail:
            body += f"<br/><font size='7' color='#555555'>{escape(e.detail)}</font>"
        if e.limitation:
            body += (
                "<br/><font size='7' color='#555555'><i>Limitation: "
                f"{escape(e.limitation)}</i></font>"
            )
        if e.conflicts_with:
            body += (
                "<br/><font size='7' color='#555555'>Conflicts: "
                f"{escape(' vs '.join(e.conflicts_with))}</font>"
            )
        rows.append(
            [
                _level_cell(e.level),
                Paragraph(body, CELL),
                _p(f"{e.source}\n{e.rule}", MONO),
                _p(f"{e.confidence:.2f}" if e.confidence is not None else "—", CELL),
            ]
        )
    t = _table(rows, [22 * mm, width - 22 * mm - 42 * mm - 14 * mm, 42 * mm, 14 * mm])
    for i, e in enumerate(lines, start=1):
        t.setStyle(
            TableStyle([("BACKGROUND", (0, i), (0, i), LEVEL_COLOURS.get(e.level, colors.white))])
        )
    return t


def _kv(pairs: Sequence[tuple[str, Any]], width: float) -> Table:
    rows = [[_p(k, SMALL), _p(v, CELL)] for k, v in pairs]
    return _table(rows, [45 * mm, width - 45 * mm], header=False)


def _image(png: bytes, max_w: float, max_h: float) -> Image | None:
    try:
        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(png)) as im:
            w, h = im.size
    except Exception:  # unreadable artifact: skip rather than fail the report
        return None
    scale = min(max_w / w, max_h / h, 1.0)
    img = Image(io.BytesIO(png), width=w * scale, height=h * scale)
    img.hAlign = "LEFT"
    return img


def render_pdf(b: ReportBundle) -> tuple[bytes, int]:
    """Return (pdf_bytes, page_count)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Verixa report {b.analysis_id}",
        author="Verixa",
        subject="Content forensics report",
    )
    width = A4[0] - doc.leftMargin - doc.rightMargin
    story: list[Any] = []
    o = b.overview

    # -- header -------------------------------------------------------------------------------
    story.append(_p("Verixa content forensics report", H1))
    story.append(
        _kv(
            [
                ("Title", b.title or "Untitled"),
                ("Analysis ID", b.analysis_id),
                ("Content type", b.analysis_type),
                ("Created", _fmt_dt(b.created_at)),
                ("Report generated", _fmt_dt(b.generated_at)),
                ("Status", b.status),
                (
                    "Evidence summary",
                    "  ".join(f"{lvl} {n}" for lvl, n in o.counts.items()),
                ),
                ("Synthesis confidence", f"{o.synthesis_confidence:.2f}"),
            ],
            width,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        _p(
            "This report separates what is directly verified from what is signalled, "
            "probabilistic, conflicting or unknown. Evidence levels are assigned only by "
            "deterministic rules; nothing here is a legal conclusion or a claim of authorship.",
            SMALL,
        )
    )
    if b.thumbnail_png:
        img = _image(b.thumbnail_png, 60 * mm, 45 * mm)
        if img is not None:
            story += [Spacer(1, 3 * mm), img, _p("Thumbnail of the stored original.", SMALL)]

    # -- file ---------------------------------------------------------------------------------
    story.append(_p("File", H2))
    f = b.file
    story.append(
        _kv(
            [
                ("Name", f.get("original_filename")),
                ("MIME type", f.get("mime_type")),
                ("Size (bytes)", f.get("size_bytes")),
                (
                    "Dimensions",
                    f"{f.get('width')} x {f.get('height')} px" if f.get("width") else "—",
                ),
                ("SHA-256", f.get("sha256")),
            ],
            width,
        )
    )

    # -- summary (docs/07 template) -------------------------------------------------------------
    story.append(_p("Summary", H2))
    if b.synthesis:
        s = b.synthesis
        story.append(
            _p(
                f"Interpretation by {s['provider']} ({s['model']}), grounded: "
                f"{'yes' if s['grounded'] else 'partly'}; "
                f"{len(s.get('warnings') or [])} warning(s). Written from the evidence records "
                "only; it cannot add evidence or change a level.",
                SMALL,
            )
        )
        for key, question in SECTIONS:
            sec = s["sections"].get(key) or {}
            story.append(_p(question, H3))
            story.append(_p(sec.get("text") or "—"))
            rules = sec.get("rules") or []
            if rules:
                story.append(_p("Cites: " + ", ".join(rules), MONO))
            if not sec.get("grounded", True):
                story.append(_p("This section makes statements without citing evidence.", SMALL))
        for w in s.get("warnings") or []:
            story.append(_p(f"Warning: {w}", SMALL))
    else:
        story.append(
            _p(
                "No language-model synthesis was generated; the evidence below stands on its own.",
                SMALL,
            )
        )

    for title, lines, hint in (
        (
            "Verified facts",
            o.verified,
            "Directly established by deterministic or cryptographic checks.",
        ),
        ("Strong evidence", o.strong, "Meaningful evidentiary value; still not proof on its own."),
        (
            "Probabilistic signals",
            o.probabilistic,
            "Detector scores, heuristics and recorded values worth weighing.",
        ),
        (
            "Conflicts",
            o.conflicts,
            "Evidence pointing in different directions; both sides retained.",
        ),
        ("Unknown", o.unknown, "What could not be established, and checks that found nothing."),
    ):
        story.append(_p(title, H3))
        story.append(_p(hint, SMALL))
        story.append(_evidence_table(_lines_for(b, lines), width))

    # -- sections ---------------------------------------------------------------------------------
    story.append(PageBreak())
    story.append(_p("Metadata", H2))
    if b.metadata:
        m = b.metadata
        cap = (m.get("captured_at") or {}).get("raw")
        mod = (m.get("modified_at") or {}).get("raw")
        story.append(
            _kv(
                [
                    ("Engine", f"{m.get('engine')} {m.get('engine_version')}"),
                    (
                        "Present",
                        ", ".join(
                            k[4:].upper()
                            for k in ("has_exif", "has_xmp", "has_iptc", "has_icc")
                            if m.get(k)
                        )
                        or "none",
                    ),
                    ("Software", m.get("software")),
                    (
                        "Camera",
                        " ".join(x for x in (m.get("camera_make"), m.get("camera_model")) if x)
                        or "—",
                    ),
                    ("Capture time (as recorded)", cap),
                    ("Modification time (as recorded)", mod),
                    ("GPS fields", "present" if m.get("gps_present") else "none"),
                    ("Generator markers", m.get("generator") or "none found"),
                    ("Digital source type (declared)", m.get("digital_source_type") or "—"),
                    (
                        "XMP edit history",
                        (
                            f"{len(m['edit_history'])} action(s): "
                            + ", ".join(
                                str(e.get("action")) + (f" ({e['when']})" if e.get("when") else "")
                                for e in m["edit_history"][:8]
                            )
                        )
                        if m.get("edit_history")
                        else "none recorded",
                    ),
                    *(
                        [
                            (
                                "GPS position (as recorded)",
                                f"{m['gps_latitude']:.6f}, {m['gps_longitude']:.6f}"
                                + (
                                    f" · altitude {m['gps_altitude_m']:.1f} m"
                                    if m.get("gps_altitude_m") is not None
                                    else ""
                                ),
                            ),
                            (
                                "GPS time (as recorded, UTC)",
                                (m.get("gps_time") or {}).get("raw") or "—",
                            ),
                        ]
                        if m.get("gps_latitude") is not None and m.get("gps_longitude") is not None
                        else []
                    ),
                ],
                width,
            )
        )
        story.append(
            _p(
                "Metadata values are recorded by software and can be edited; they are signals, "
                "not verified facts.",
                SMALL,
            )
        )
    else:
        story.append(
            _p(
                "Metadata was not extracted."
                if b.analysis_type == "image"
                else "Not applicable to text.",
                SMALL,
            )
        )

    story.append(_p("Provenance (C2PA)", H2))
    if b.provenance:
        p = b.provenance
        story.append(
            _kv(
                [
                    ("Engine", f"{p.get('engine')} {p.get('engine_version')}"),
                    ("Credentials present", "yes" if p.get("has_c2pa") else "no"),
                    ("Signature valid", _yes_no(p.get("valid_signature"))),
                    ("Signer (as stated)", p.get("signer")),
                    ("Signed at", p.get("signed_at")),
                    ("Claim generator", p.get("claim_generator")),
                ],
                width,
            )
        )
        story.append(
            _p(
                "Absence of credentials is UNKNOWN, not evidence of fraud. Validity shows the "
                "manifest is intact, not that its claims are true.",
                SMALL,
            )
        )
        for note in b.provenance_limitations:
            story.append(_p(note, SMALL))
    else:
        story.append(
            _p(
                "Content credentials were not inspected."
                if b.analysis_type == "image"
                else "Not applicable to text.",
                SMALL,
            )
        )

    story.append(_p("AI-generation signal", H2))
    if b.ai:
        a = b.ai
        story.append(
            _kv(
                [
                    (
                        "Provider / model",
                        f"{a.get('provider')} {a.get('model')}@{a.get('provider_version')}",
                    ),
                    ("Score", f"{a['score']:.2f}" if a.get("score") is not None else "none"),
                    ("Label", a.get("label")),
                    ("Calibrated", "yes" if a.get("calibrated") else "no"),
                    ("Evidence level", a.get("level")),
                ],
                width,
            )
        )
        story.append(
            _p(
                "A detector score is a probabilistic signal with known error rates; it is never "
                "proof of authorship.",
                SMALL,
            )
        )
    else:
        story.append(_p("No AI detector was configured; this signal is UNKNOWN.", SMALL))

    story.append(_p("Forensics", H2))
    if not b.forensics:
        story.append(
            _p(
                "Forensic analysis was not run."
                if b.analysis_type == "image"
                else "Not applicable to text.",
                SMALL,
            )
        )
    for meth in b.forensics:
        block: list[Any] = [_p(f"{meth.name}" + (f" ({meth.version})" if meth.version else ""), H3)]
        if not meth.applicable:
            block.append(_p(f"Not applicable: {meth.observation}", SMALL))
        else:
            block.append(
                _p(("SIGNAL (POSSIBLE at most): " if meth.flagged else "") + str(meth.observation))
            )
            block.append(_p(f"Method confidence: {meth.confidence}", SMALL))
            if meth.map_png:
                img = _image(meth.map_png, width, 70 * mm)
                if img is not None:
                    block.append(img)
            for lim in meth.limitations:
                block.append(_p(f"• {lim}", SMALL))
        story.append(KeepTogether(block))

    story.append(_p("Source matches", H2))
    if b.matches:
        mm_ = b.matches
        sm = mm_.get("summary") or {}
        story.append(
            _kv(
                [
                    ("Provider", f"{mm_.get('provider')}@{mm_.get('version')}"),
                    ("Searched", _fmt_dt(mm_.get("searched_at"))),
                    (
                        "Matches",
                        f"{sm.get('match_count', 0)} across {sm.get('domain_count', 0)} domain(s)",
                    ),
                    ("Earliest reported date", sm.get("earliest_published_at") or "none reported"),
                ],
                width,
            )
        )
        items = mm_.get("items") or []
        if items:
            rows: list[list[Any]] = [
                [
                    _p("#", CELL),
                    _p("Source", CELL),
                    _p("Sim.", CELL),
                    _p("Reported", CELL),
                    _p("Discovered", CELL),
                ]
            ]
            for it in items[:50]:
                rows.append(
                    [
                        _p(it.get("rank"), CELL),
                        Paragraph(
                            f"{escape(str(it.get('title') or ''))}<br/>"
                            f"<font size='7'>{escape(str(it.get('url')))}</font>",
                            CELL,
                        ),
                        _p(
                            f"{it['similarity']:.2f}" if it.get("similarity") is not None else "—",
                            CELL,
                        ),
                        _p(it.get("published_at") or "—", CELL),
                        _p(_fmt_dt(it.get("discovered_at")), CELL),
                    ]
                )
            story.append(
                _table(
                    rows,
                    [
                        8 * mm,
                        width - 8 * mm - 14 * mm - 26 * mm - 34 * mm,
                        14 * mm,
                        26 * mm,
                        34 * mm,
                    ],
                )
            )
        story.append(
            _p(
                "A match shows where similar content was found, not where it originated or "
                "which copy came first. Every match is POSSIBLE unless corroborated.",
                SMALL,
            )
        )
    else:
        story.append(_p("No source search was performed; this signal is UNKNOWN.", SMALL))

    story.append(_p("Timeline", H2))
    if b.timeline:
        rows = [[_p("Time", CELL), _p("Level", CELL), _p("Event", CELL), _p("Source", CELL)]]
        for e in b.timeline:
            when = (
                _fmt_dt(e.get("event_time"))
                if e.get("event_time")
                else f"unplaceable: {e.get('raw_time')}"
            )
            if e.get("event_time") and not e.get("tz_known"):
                when += " (tz not recorded)"
            rows.append(
                [
                    _p(when, CELL),
                    _level_cell(str(e.get("certainty"))),
                    _p(e.get("description"), CELL),
                    _p(e.get("source"), MONO),
                ]
            )
        story.append(_table(rows, [40 * mm, 20 * mm, width - 40 * mm - 20 * mm - 40 * mm, 40 * mm]))
        story.append(_p("Events are times some system recorded, never inferred.", SMALL))
    else:
        story.append(_p("No dated evidence was recorded.", SMALL))

    # -- methodology ------------------------------------------------------------------------
    story.append(PageBreak())
    story.append(_p("Methodology and limitations", H2))
    story.append(_p("Evidence levels", H3))
    story.append(_kv([(lvl, text) for lvl, text in o.level_definitions.items()], width))
    story.append(_p("Steps", H3))
    story.append(
        _table(
            [[_p("Step", CELL), _p("Status", CELL), _p("Duration", CELL), _p("Error", CELL)]]
            + [
                [
                    _p(s.name, MONO),
                    _p(s.status, CELL),
                    _p(f"{s.duration_ms} ms" if s.duration_ms is not None else "—", CELL),
                    _p(s.error_code or "—", MONO),
                ]
                for s in o.steps
            ],
            [45 * mm, 25 * mm, 25 * mm, width - 95 * mm],
        )
    )
    story.append(_p("Engines and providers", H3))
    if o.engines:
        story.append(
            _table(
                [
                    [
                        _p("Provider", CELL),
                        _p("Version", CELL),
                        _p("Operations", CELL),
                        _p("Calls", CELL),
                    ]
                ]
                + [
                    [
                        _p(e.provider, MONO),
                        _p(e.model_version or "—", MONO),
                        _p(", ".join(e.operations), CELL),
                        _p(f"{e.calls} ({e.cached} cached, {e.failed} failed)", CELL),
                    ]
                    for e in o.engines
                ],
                [30 * mm, 40 * mm, width - 30 * mm - 40 * mm - 35 * mm, 35 * mm],
            )
        )
    else:
        story.append(_p("No external engine or provider was called.", SMALL))
    story.append(_p("Thresholds in force", H3))
    th = o.thresholds
    story.append(
        _kv(
            [
                (
                    "AI score high / medium",
                    f"{th.get('ai_score_high')} / {th.get('ai_score_medium')}",
                ),
                ("pHash near (bits)", th.get("fingerprint_near_threshold")),
                ("Text near (Jaccard)", th.get("text_near_threshold")),
                ("Language PROBABLE", th.get("language_probable_confidence")),
                ("Forensic families for STRONG", th.get("forensic_families_for_strong")),
                (
                    "Default confidence",
                    " ".join(f"{k} {v}" for k, v in (th.get("confidence") or {}).items()),
                ),
                ("Conflict penalty", th.get("conflict_penalty")),
                ("Level overrides", th.get("level_overrides") or "none"),
            ],
            width,
        )
    )
    story.append(_p("Principles", H3))
    for note in o.methodology:
        story.append(_p(f"• {note}", SMALL))
    story.append(Spacer(1, 4 * mm))
    story.append(_p(f"Generated by Verixa {b.app_version}, report layout {PDF_VERSION}.", SMALL))

    def _footer(canvas: Any, doc_: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(
            doc_.leftMargin,
            10 * mm,
            f"Verixa report {b.analysis_id} - evidence-first; not a legal conclusion",
        )
        canvas.drawRightString(A4[0] - doc_.rightMargin, 10 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    data = buf.getvalue()
    return data, data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") + data.count(
        b"/Type/Page "
    )


def _lines_for(b: ReportBundle, rows: Sequence[Any]) -> list[Any]:
    """Match overview rows (ORM) to the bundle's evidence lines by rule + claim."""
    index = {(e.rule, e.claim): e for e in b.evidence}
    out = []
    for r in rows:
        rule = str((r.details or {}).get("rule") or "")
        line = index.get((rule, r.claim))
        if line is not None:
            out.append(line)
    return out
