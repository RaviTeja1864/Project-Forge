import io
import re
import unicodedata
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.doctemplate import LayoutError

_METADATA_KEYS = {"generated_at", "specification_status", "input_artifacts", "validation_findings"}
_SECTION_LABELS = {
    "project": "Project overview",
    "objectives": "Objectives",
    "scope": "Scope",
    "target_users": "Target users and stakeholders",
    "research": "Research synthesis and evidence",
    "requirements": "Requirements",
    "technology": "Technology decisions and trade-offs",
    "architecture": "Architecture, API, and database design",
    "security_and_reliability": "Security and reliability",
    "constraints": "Constraints",
    "risks": "Risks",
    "assumptions": "Assumptions",
    "unresolved_information": "Unresolved information and research gaps",
    "tradeoffs": "Trade-offs",
}


class SpecificationExportError(Exception):
    pass


def _label(value):
    return str(value).replace("_", " ").strip().capitalize()


def _markdown_fence(value):
    longest = max((len(match.group()) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}mermaid\n{value}\n{fence}"


def _markdown_value(value, *, key=None, depth=0):
    if value is None:
        return "_Not specified._"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        if key and "diagram" in key:
            return _markdown_fence(value)
        return value.replace("\r\n", "\n")
    if isinstance(value, list):
        if not value:
            return "_None recorded._"
        rendered = []
        for item in value:
            text = _markdown_value(item, depth=depth + 1)
            if isinstance(item, (dict, list)):
                rendered.append(f"{'  ' * depth}-\n{text}")
            else:
                rendered.append(f"{'  ' * depth}- {text}")
        return "\n".join(rendered)
    if isinstance(value, dict):
        if not value:
            return "_None recorded._"
        return "\n".join(
            f"{'  ' * depth}**{_label(name)}**\n\n"
            f"{_markdown_value(item, key=name, depth=depth + 1)}"
            for name, item in value.items()
        )
    return str(value)


def _status_text(snapshot, outdated):
    status = snapshot.status.upper()
    if outdated:
        status += " — POTENTIALLY OUTDATED"
    elif snapshot.status != snapshot.Status.APPROVED:
        status += " — NOT APPROVED"
    return status


def _project_title(snapshot):
    content = snapshot.content if isinstance(snapshot.content, dict) else {}
    project = content.get("project")
    title = project.get("title") if isinstance(project, dict) else None
    return title if isinstance(title, str) and title.strip() else snapshot.workspace.name or "Engineering specification"


def specification_markdown(snapshot, *, outdated):
    content = snapshot.content
    title = _project_title(snapshot)
    lines = [
        f"# {title}",
        "",
        f"**Snapshot:** v{snapshot.version_number} (`{snapshot.pk}`)",
        f"**Status:** {_status_text(snapshot, outdated)}",
        f"**Generated:** {content.get('generated_at') or snapshot.created_at.isoformat()}",
        f"**Workspace:** {snapshot.workspace.name} (`{snapshot.workspace_id}`)",
        "",
        "## Input artifact versions",
        "",
    ]
    for item in content.get("input_artifacts", []):
        lines.append(
            f"- **{_label(item.get('kind', 'artifact'))}** v{item.get('version_number', 'unknown')} "
            f"— {str(item.get('status', 'unknown')).upper()} — "
            f"`{item.get('artifact_id', 'unknown')}`"
        )
    if not content.get("input_artifacts"):
        lines.append("_No input artifact versions were recorded._")

    for name, value in content.items():
        if name in _METADATA_KEYS:
            continue
        heading = _SECTION_LABELS.get(name, _label(name))
        lines.extend(["", f"## {heading}", "", _markdown_value(value, key=name), ""])
    return "\n".join(lines).rstrip() + "\n"


def specification_filename(snapshot, extension):
    title = _project_title(snapshot)
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", normalized).strip("-").lower()
    slug = slug[:64].strip("-") or f"specification-{str(snapshot.pk)[:8]}"
    return f"{slug}-v{snapshot.version_number}.{extension}"


def _pdf_styles():
    styles = getSampleStyleSheet()
    font_name = "Helvetica"
    font_bold = "Helvetica-Bold"
    try:
        from pathlib import Path

        from reportlab import __file__ as reportlab_path

        font_dir = Path(reportlab_path).parent / "fonts"
        regular_path = font_dir / "Vera.ttf"
        bold_path = font_dir / "VeraBd.ttf"
        if regular_path.exists() and bold_path.exists():
            if "ProjectForgeVera" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("ProjectForgeVera", str(regular_path)))
                pdfmetrics.registerFont(TTFont("ProjectForgeVera-Bold", str(bold_path)))
            font_name, font_bold = "ProjectForgeVera", "ProjectForgeVera-Bold"
    except (OSError, ValueError):
        pass
    styles.add(
        ParagraphStyle(
            "SpecTitle",
            parent=styles["Title"],
            fontName=font_bold,
            fontSize=22,
            leading=28,
            alignment=TA_CENTER,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            "SpecHeading1",
            parent=styles["Heading1"],
            fontName=font_bold,
            fontSize=15,
            leading=19,
            textColor=colors.HexColor("#25432f"),
            spaceBefore=12,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            "SpecHeading2",
            parent=styles["Heading2"],
            fontName=font_bold,
            fontSize=11,
            leading=14,
            spaceBefore=8,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            "SpecBody",
            parent=styles["BodyText"],
            fontName=font_name,
            fontSize=8.5,
            leading=12,
            wordWrap="CJK",
            splitLongWords=True,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            "SpecSmall",
            parent=styles["BodyText"],
            fontName=font_name,
            fontSize=7.5,
            leading=10,
            wordWrap="CJK",
            splitLongWords=True,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            "SpecCode",
            parent=styles["Code"],
            fontName=font_name,
            fontSize=7,
            leading=9,
            leftIndent=7,
            rightIndent=7,
            backColor=colors.HexColor("#f2f3ef"),
            borderPadding=5,
            spaceBefore=3,
            spaceAfter=6,
            splitLongWords=True,
        )
    )
    return styles


def _pdf_text(value):
    text = "".join(
        character
        for character in str(value)
        if character in "\t\n\r"
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
        or 0x10000 <= ord(character) <= 0x10FFFF
    )
    return escape(text).replace("\n", "<br/>")


def _pdf_value(value, story, styles, *, key=None, depth=0):
    if value is None:
        story.append(Paragraph("Not specified.", styles["Italic"]))
    elif isinstance(value, (str, int, float, bool)):
        text = str(value)
        if isinstance(value, bool):
            text = "Yes" if value else "No"
        if key and "diagram" in key and isinstance(value, str):
            story.append(Paragraph(f"<b>{_pdf_text(_label(key))} (Mermaid source)</b>", styles["SpecSmall"]))
            for line in value.splitlines() or [""]:
                story.append(Paragraph(_pdf_text(line) or "&#160;", styles["SpecCode"]))
        else:
            story.append(Paragraph(_pdf_text(text), styles["SpecBody"]))
    elif isinstance(value, list):
        if not value:
            story.append(Paragraph("None recorded.", styles["SpecSmall"]))
            return
        for item in value:
            if isinstance(item, (dict, list)):
                story.append(Paragraph("•", styles["SpecBody"]))
                _pdf_value(item, story, styles, depth=depth + 1)
            else:
                story.append(Paragraph(f"• {_pdf_text(item)}", styles["SpecBody"]))
    elif isinstance(value, dict):
        if not value:
            story.append(Paragraph("None recorded.", styles["SpecSmall"]))
            return
        for name, item in value.items():
            story.append(
                Paragraph(f"<b>{_pdf_text(_label(name))}</b>", styles["SpecSmall"])
            )
            _pdf_value(item, story, styles, key=name, depth=depth + 1)
    else:
        story.append(Paragraph(_pdf_text(value), styles["SpecBody"]))


class _NumberedDocument(BaseDocTemplate):
    def __init__(self, buffer, **kwargs):
        super().__init__(buffer, **kwargs)
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="content",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(
            [
                PageTemplate(
                    id="numbered",
                    frames=[frame],
                    onPage=self._draw_page_number,
                )
            ]
        )

    @staticmethod
    def _draw_page_number(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#6b7169"))
        canvas.drawCentredString(A4[0] / 2, 12 * mm, str(document.page))
        canvas.restoreState()


def specification_pdf(snapshot, *, outdated):
    buffer = io.BytesIO()
    styles = _pdf_styles()
    content = snapshot.content
    title = _project_title(snapshot)
    document = _NumberedDocument(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title=title,
        author="ProjectForge",
    )
    story = [
        Spacer(1, 20 * mm),
        Paragraph(_pdf_text(title), styles["SpecTitle"]),
        Paragraph(
            _pdf_text(
                f"Specification snapshot v{snapshot.version_number} · "
                f"{_status_text(snapshot, outdated)}"
            ),
            styles["SpecBody"],
        ),
        Paragraph(
            _pdf_text(
                f"Generated {content.get('generated_at') or snapshot.created_at.isoformat()}"
            ),
            styles["SpecBody"],
        ),
        Paragraph(
            _pdf_text(f"Snapshot ID: {snapshot.pk} · Workspace: {snapshot.workspace.name}"),
            styles["SpecSmall"],
        ),
        Spacer(1, 8 * mm),
        Paragraph("Contents", styles["SpecHeading1"]),
    ]
    section_keys = [key for key in content if key not in _METADATA_KEYS]
    for index, name in enumerate(section_keys, start=1):
        story.append(
            Paragraph(
                _pdf_text(f"{index}. {_SECTION_LABELS.get(name, _label(name))}"),
                styles["SpecBody"],
            )
        )
    story.append(Paragraph("Input artifact versions", styles["SpecHeading1"]))
    input_rows = [["Type", "Version", "Status", "Artifact ID"]]
    for item in content.get("input_artifacts", []):
        input_rows.append(
            [
                _pdf_text(_label(item.get("kind", "artifact"))),
                _pdf_text(item.get("version_number", "unknown")),
                _pdf_text(str(item.get("status", "unknown")).upper()),
                _pdf_text(item.get("artifact_id", "unknown")),
            ]
        )
    if len(input_rows) == 1:
        input_rows.append(["No input versions recorded.", "", "", ""])
    input_table = Table(input_rows, colWidths=[34 * mm, 20 * mm, 25 * mm, 95 * mm], repeatRows=1)
    input_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7ebe3")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("LEADING", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b9c0b4")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("WORDWRAP", (0, 0), (-1, -1), "CJK"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([input_table, Spacer(1, 6 * mm)])

    for index, name in enumerate(section_keys, start=1):
        heading = _SECTION_LABELS.get(name, _label(name))
        story.append(Paragraph(f"{index}. {_pdf_text(heading)}", styles["SpecHeading1"]))
        _pdf_value(content[name], story, styles, key=name)
    try:
        document.build(story)
    except (LayoutError, OSError, ValueError) as error:
        raise SpecificationExportError from error
    return buffer.getvalue()
