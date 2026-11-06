"""ページ組版と出力（PDF / PPTX / PNG）。

PDF と PPTX は同じ座標データから描くので、見た目は一致する。
PPTX は人物ごとのテキストボックスと直線でできているので、
PowerPoint で文字の修正・移動がそのままできる（編集用）。
"""
from __future__ import annotations

import copy
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .diagrams import Diagram
from .fonts import PPTX_FONT, pdf_font, text_width_mm
from .layout import PT, Box, Drawing, Line, TextLine

PAGES = {"A4": (210.0, 297.0), "A3": (297.0, 420.0)}
MARGIN = 15.0


@dataclass
class Page:
    w: float
    h: float
    size_name: str
    drawing: Drawing
    scale: float
    font_kind: str


def _text_box(text: str, size: float, x: float, y: float, font: str) -> Box:
    w = text_width_mm(text, size, font) + 1
    lh = size * PT * 1.35
    return Box(x, y, w, lh, [TextLine(text, size, lh * 0.78)], lh / 2)


def compose(dia: Diagram, font: str = "mincho") -> tuple[Page, list[str]]:
    notes: list[str] = []
    x0, y0, x1, y1 = dia.drawing.bbox()
    cw, ch = x1 - x0, y1 - y0
    footer_h = len(dia.footer) * 11 * PT * 1.35 + 14

    top = MARGIN + 17

    def fit(size_name, landscape):
        pw, ph = PAGES[size_name]
        if landscape:
            pw, ph = ph, pw
        aw = pw - 2 * MARGIN
        ah = ph - top - MARGIN - footer_h - dia.reserve_bottom_mm
        return min(1.0, aw / cw if cw else 1, ah / ch if ch else 1), pw, ph, aw

    # 一覧図は A4 縦固定。説明図は縦横のうち縮小が少ないほうを選ぶ
    orients = [dia.landscape, not dia.landscape] if dia.kind == "setsumei" else [dia.landscape]
    for size_name in ("A4", "A3"):
        k, pw, ph, aw = max((fit(size_name, o) for o in orients), key=lambda t: t[0])
        if k >= 0.62 or size_name == "A3":
            break
    if k < 1.0:
        notes.append(f"図が大きいため {size_name} 用紙に {k:.0%} に縮小して配置しました。文字が小さすぎないか確認してください。")
    if size_name == "A3":
        notes.append("A4 に収まらないため A3 で出力しました。提出先が A4 指定の場合は分割（一覧図は複数枚に分ける）を検討してください。")

    dr = copy.deepcopy(dia.drawing)
    dr.shift(-x0, -y0).scale(k)
    left = MARGIN + (aw - cw * k) / 2
    dr.shift(left, top)

    # 題名
    tb = _text_box(dia.title, 14, 0, MARGIN, font)
    tb.x = (pw - tb.w) / 2
    dr.boxes.append(tb)

    yb = top + ch * k + 4
    if dia.trailing:
        t = _text_box(dia.trailing, 10, 0, yb, font)
        t.x = left + cw * k - t.w
        dr.boxes.append(t)
        yb += t.h
    yb += 6
    for line in dia.footer:
        b = _text_box(line, 10, max(MARGIN, left), yb, font)
        dr.boxes.append(b)
        yb += b.h
    return Page(pw, ph, size_name, dr, k, font), notes


# ---------------------------------------------------------------- PDF
def to_pdf(page: Page, path: Path, title: str = ""):
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    fname, _ = pdf_font(page.font_kind)
    c = canvas.Canvas(str(path), pagesize=(page.w * mm, page.h * mm))
    c.setTitle(title)
    H = page.h
    for ln in page.drawing.lines:
        c.setLineWidth(ln.width)
        c.line(ln.x1 * mm, (H - ln.y1) * mm, ln.x2 * mm, (H - ln.y2) * mm)
    for b in page.drawing.boxes:
        for t in b.lines:
            c.setFont(fname, t.size)
            c.drawString(b.x * mm, (H - b.y - t.y) * mm, t.text)
    c.showPage()
    c.save()


# ---------------------------------------------------------------- PPTX（編集用）
def to_pptx(page: Page, path: Path):
    from lxml import etree
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_CONNECTOR
    from pptx.enum.text import MSO_AUTO_SIZE
    from pptx.oxml.ns import qn
    from pptx.util import Mm, Pt

    font_name = PPTX_FONT.get(page.font_kind, "ＭＳ 明朝")
    prs = Presentation()
    prs.slide_width, prs.slide_height = Mm(page.w), Mm(page.h)
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    for ln in page.drawing.lines:
        cn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Mm(ln.x1), Mm(ln.y1), Mm(ln.x2), Mm(ln.y2))
        cn.line.width = Pt(ln.width)
        cn.line.color.rgb = RGBColor(0, 0, 0)

    for b in page.drawing.boxes:
        if not b.lines:
            continue
        first = b.lines[0]
        # 1行目のベースライン位置に合わせて箱の上端をずらす
        top = b.y + first.y - first.size * PT * 0.95
        tb = slide.shapes.add_textbox(Mm(b.x), Mm(top), Mm(b.w + 2), Mm(b.h + 2))
        tf = tb.text_frame
        tf.word_wrap = False
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        prev_y = None
        for i, t in enumerate(b.lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            run = para.add_run()
            run.text = t.text
            run.font.size = Pt(t.size)
            run.font.name = font_name
            rpr = run._r.get_or_add_rPr()
            ea = rpr.find(qn("a:ea"))
            if ea is None:
                ea = etree.SubElement(rpr, qn("a:ea"))
            ea.set("typeface", font_name)
            gap_mm = (t.y - prev_y) if prev_y is not None else t.size * PT * 1.35
            para.line_spacing = Pt(gap_mm / PT)
            prev_y = t.y
    prs.save(str(path))


# ---------------------------------------------------------------- PNG（確認用プレビュー）
def to_png(pdf_path: Path, png_path: Path, dpi: int = 110) -> bool:
    if not shutil.which("pdftoppm"):
        return False
    stem = png_path.with_suffix("")
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-singlefile", str(pdf_path), str(stem)],
                   check=True)
    return True
