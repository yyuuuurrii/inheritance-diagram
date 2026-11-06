"""使い方:
    python -m souzoku_zu build case.json -o out/
    python -m souzoku_zu check case.json        # 判定だけ（図は作らない）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import checklist
from .diagrams import ichiranzu, setsumeizu
from .heirs import determine, fmt_share, secondary_decedents
from .model import Case
from .render import compose, to_pdf, to_png, to_pptx


def _safe(s: str) -> str:
    return re.sub(r"[\\/:*?\"<>|\s　]+", "", s)


def build(case: Case, out: Path, png: bool = True) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    font = case.options.font
    files: list[str] = []
    notes: list[str] = []

    # 法定相続情報一覧図（数次相続があれば被相続人ごとに作る）
    ichiran = []
    todo, done = [case.decedent], []
    while todo and len(done) < 6:
        did = todo.pop(0)
        if did in done:
            continue
        done.append(did)
        dia, res = ichiranzu(case, did)
        ichiran.append((dia, res))
        todo += secondary_decedents(case, res)

    def emit(dia, stem):
        page, pn = compose(dia, font)
        notes.extend(f"{dia.title}：{n}" for n in pn)
        pdf = out / f"{stem}.pdf"
        to_pdf(page, pdf, dia.title)
        to_pptx(page, out / f"{stem}.pptx")
        files.extend([pdf.name, f"{stem}.pptx"])
        if png and to_png(pdf, out / f"{stem}.png"):
            files.append(f"{stem}.png")

    for i, (dia, res) in enumerate(ichiran, 1):
        emit(dia, f"{i:02d}_法定相続情報一覧図_{_safe(case.person(res.decedent).name)}")

    sdia, sres = setsumeizu(case)
    emit(sdia, f"{len(ichiran) + 1:02d}_相続関係説明図_{_safe(case.person(case.decedent).name)}")

    files.append("確認チェックリスト.md")
    md = checklist.build(case, ichiran, (sdia, sres), notes, files)
    (out / "確認チェックリスト.md").write_text(md, encoding="utf-8")

    return {
        "out_dir": str(out),
        "files": files,
        "heirs": {case.person(h).name: fmt_share(s) for h, s in sres[0].shares.items()},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="souzoku_zu")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="図とチェックリストを作る")
    b.add_argument("case")
    b.add_argument("-o", "--out", default="output")
    b.add_argument("--no-png", action="store_true")
    c = sub.add_parser("check", help="相続人の判定結果だけを表示")
    c.add_argument("case")
    a = ap.parse_args(argv)

    case = Case.load(a.case)
    if a.cmd == "build":
        r = build(case, Path(a.out), png=not a.no_png)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        res = determine(case)
        print(json.dumps({
            "rank": res.rank,
            "heirs": {case.person(h).name: fmt_share(s) for h, s in res.shares.items()},
            "warnings": res.warnings,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
