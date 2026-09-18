"""Generate the reviewed synthetic corpus; --check never writes files."""
from __future__ import annotations

import argparse
import io
import json
from html import escape
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle


FIXTURE_DIR = Path(__file__).resolve().parent
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 48
TEXT_WIDTH = PAGE_WIDTH - MARGIN * 2
BODY = ParagraphStyle("fixture-body", fontName="Helvetica", fontSize=10, leading=14)
LABEL = ParagraphStyle("fixture-label", fontName="Helvetica-Bold", fontSize=11, leading=15)


def load_manifest() -> dict:
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    # Longer agreements have separate readable sources instead of one huge file.
    for name in manifest.get("fixture_sources", []):
        if Path(name).name != name or not name.endswith(".json"):
            raise ValueError("Fixture source must be a JSON filename in sources")
        fixture = json.loads((FIXTURE_DIR / "sources" / name).read_text(encoding="utf-8"))
        manifest["fixtures"].append(fixture)
    names = [fixture["filename"] for fixture in manifest["fixtures"]]
    if len(names) != len(set(names)):
        raise ValueError("Fixture output filenames must be unique")
    return manifest


def paragraph(canvas: Canvas, text: str, top: float, style=BODY) -> float:
    item = Paragraph(escape(text), style)
    _, height = item.wrap(TEXT_WIDTH, top - 60)
    if top - height < 60:
        raise ValueError("Fixture content exceeds the explicit page boundary")
    item.drawOn(canvas, MARGIN, top - height)
    return top - height - 8


def sections(canvas: Canvas, values: list[dict], top: float) -> float:
    for section in values:
        top = paragraph(canvas, section["heading"], top, LABEL)
        top = paragraph(canvas, section["text"], top)
    return top


def text_page(canvas: Canvas, fixture: dict, page: dict, number: int, notice: str) -> None:
    canvas.setFillColor(colors.HexColor("#172635"))
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(MARGIN, PAGE_HEIGHT - 55, fixture["title"])
    top = paragraph(canvas, notice, PAGE_HEIGHT - 73)
    top = paragraph(canvas, page["heading"], top - 10, LABEL)
    top = sections(canvas, page["sections"], top - 6)
    if page.get("table"):
        table = Table(page["table"], colWidths=[TEXT_WIDTH * 0.44, TEXT_WIDTH * 0.34, TEXT_WIDTH * 0.22])
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7EDF2")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ABB8C2")),
        ]))
        _, height = table.wrap(TEXT_WIDTH, top - 60)
        if top - height < 60:
            raise ValueError("Fixture table exceeds the explicit page boundary")
        table.drawOn(canvas, MARGIN, top - height)
        top = sections(canvas, page.get("after_table", []), top - height - 20)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#516272"))
    canvas.drawString(MARGIN, 32, "ClauseIQ synthetic fixture | not a real agreement")
    canvas.drawRightString(PAGE_WIDTH - MARGIN, 32, f"Page {number} of {len(fixture['pages'])}")


def image_page(canvas: Canvas, fixture: dict, page: dict, notice: str) -> None:
    # Pillow's bundled font avoids dependence on machine-installed fonts.
    raster = Image.new("RGB", (1240, 1754), "white")
    drawing = ImageDraw.Draw(raster)
    body = ImageFont.load_default(size=26)
    label = ImageFont.load_default(size=36)
    y = 90

    def lines(value: str, font: ImageFont.FreeTypeFont, width: int, gap: int) -> None:
        nonlocal y
        for line in textwrap.wrap(value, width=width):
            drawing.text((85, y), line, font=font, fill="#172635")
            y += gap
        y += 24

    lines(fixture["title"], label, 45, 48)
    lines(notice, body, 68, 36)
    lines(page["heading"], label, 45, 48)
    for section in page["sections"]:
        lines(section["heading"], label, 45, 48)
        lines(section["text"], body, 68, 36)
    if y > 1600:
        raise ValueError("Fixture raster content exceeds the explicit page boundary")
    drawing.text((85, 1670), "Synthetic fixture | image only | page 1 of 1", font=body, fill="#516272")
    canvas.drawImage(ImageReader(raster), 0, 0, width=PAGE_WIDTH, height=PAGE_HEIGHT)


def render_fixture(fixture: dict, notice: str) -> bytes:
    output = io.BytesIO()
    canvas = Canvas(output, pagesize=A4, invariant=1, pageCompression=1)
    canvas.setTitle(fixture["title"])
    canvas.setAuthor("")
    canvas.setCreator("ClauseIQ synthetic fixture generator")
    canvas.setSubject("Invented software test content; not a real agreement or legal advice")
    canvas.setKeywords("synthetic,test,fixture")
    for number, page in enumerate(fixture["pages"], 1):
        if fixture["kind"] == "image_only":
            image_page(canvas, fixture, page, notice)
        else:
            text_page(canvas, fixture, page, number, notice)
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare committed PDFs with regenerated bytes without writing")
    options = parser.parse_args()
    manifest = load_manifest()
    mismatches = []
    for fixture in manifest["fixtures"]:
        filename = fixture["filename"]
        if Path(filename).name != filename or not filename.endswith(".pdf"):
            raise ValueError("Fixture output must be a PDF filename in this directory")
        target = FIXTURE_DIR / filename
        content = render_fixture(fixture, manifest["notice"])
        if options.check:
            if not target.is_file() or target.read_bytes() != content:
                mismatches.append(filename)
        else:
            target.write_bytes(content)
            print(f"Generated {filename}")
    if mismatches:
        print("Fixture bytes differ: " + ", ".join(mismatches))
        return 1
    if options.check:
        print(f"Verified {len(manifest['fixtures'])} reproducible synthetic PDFs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
