"""フォントの検出・登録と文字幅の計測。"""
from __future__ import annotations

import functools
import shutil
import subprocess
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

CANDIDATES = {
    "mincho": ["/usr/share/fonts/opentype/ipafont-mincho/ipam.ttf",
               "/usr/share/fonts/truetype/fonts-japanese-mincho.ttf"],
    "gothic": ["/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
               "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"],
}
FC_QUERY = {"mincho": "IPAMincho", "gothic": "IPAGothic"}
# PowerPoint 側で指定するフォント名（Windows/Mac の Office で一般的なもの）
PPTX_FONT = {"mincho": "ＭＳ 明朝", "gothic": "ＭＳ ゴシック"}


def _find(kind: str) -> str | None:
    for c in CANDIDATES[kind]:
        if Path(c).exists():
            return c
    if shutil.which("fc-match"):
        out = subprocess.run(["fc-match", "-f", "%{file}", FC_QUERY[kind]],
                             capture_output=True, text=True).stdout.strip()
        if out.endswith((".ttf", ".otf")) and Path(out).exists():
            return out
    return None


@functools.lru_cache(maxsize=None)
def pdf_font(kind: str = "mincho") -> tuple[str, str]:
    """(reportlab のフォント名, 実際に使った種類) を返す。明朝がなければゴシックに落とす。"""
    for k in ([kind, "gothic"] if kind == "mincho" else [kind, "mincho"]):
        path = _find(k)
        if path:
            name = f"JP-{k}"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, path))
            return name, k
    raise RuntimeError(
        "日本語フォントが見つかりません。`apt-get install -y fonts-ipafont-mincho fonts-ipafont-gothic` を実行してください。")


def text_width_mm(text: str, size_pt: float, kind: str = "mincho") -> float:
    name, _ = pdf_font(kind)
    return pdfmetrics.stringWidth(text, name, size_pt) * 25.4 / 72


def wrap(text: str, width_mm: float, size_pt: float, kind: str = "mincho",
         indent: str = "") -> list[str]:
    """文字単位で折り返す（日本語なので単語境界は見ない）。2行目以降は indent を付ける。"""
    lines: list[str] = []
    cur = ""
    for ch in text:
        trial = cur + ch
        if cur and text_width_mm(trial, size_pt, kind) > width_mm:
            lines.append(cur)
            cur = indent + ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]
