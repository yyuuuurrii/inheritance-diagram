"""和暦 <-> 西暦の変換。

入力は次のどれでも受け付ける:
  - ISO 形式            "1945-01-01"
  - 和暦（漢字）        "昭和20年1月1日", "令和元年5月1日"
  - 和暦（略記）        "S20.1.1", "R1.5.1", "H元.1.8"
"""
from __future__ import annotations

import datetime as dt
import re

# (元号, 略号, 開始日)  新しい順
ERAS = [
    ("令和", "R", dt.date(2019, 5, 1)),
    ("平成", "H", dt.date(1989, 1, 8)),
    ("昭和", "S", dt.date(1926, 12, 25)),
    ("大正", "T", dt.date(1912, 7, 30)),
    ("明治", "M", dt.date(1868, 10, 23)),
]
_ERA_BY_NAME = {name: start for name, _, start in ERAS}
_ERA_BY_ABBR = {abbr: start for _, abbr, start in ERAS}

_ZEN2HAN = str.maketrans("０１２３４５６７８９．／－", "0123456789./-")


def parse_date(value: str | dt.date | None) -> dt.date | None:
    """日付文字列を date に変換する。解釈できなければ ValueError。"""
    if value is None or value == "":
        return None
    if isinstance(value, dt.date):
        return value
    s = str(value).strip().translate(_ZEN2HAN).replace(" ", "")

    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return dt.date(int(m[1]), int(m[2]), int(m[3]))

    m = re.fullmatch(r"(明治|大正|昭和|平成|令和)(元|\d{1,2})年(\d{1,2})月(\d{1,2})日", s)
    if m:
        return _from_era(_ERA_BY_NAME[m[1]], m[2], m[3], m[4])

    m = re.fullmatch(r"([MTSHRmtshr])(元|\d{1,2})[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
    if m:
        return _from_era(_ERA_BY_ABBR[m[1].upper()], m[2], m[3], m[4])

    raise ValueError(f"日付を解釈できません: {value!r}")


def _from_era(start: dt.date, year: str, month: str, day: str) -> dt.date:
    y = 1 if year == "元" else int(year)
    return dt.date(start.year + y - 1, int(month), int(day))


def to_wareki(d: dt.date | None, unknown: str = "（不明）") -> str:
    """date を「昭和20年1月1日」形式にする。"""
    if d is None:
        return unknown
    for name, _, start in ERAS:
        if d >= start:
            y = d.year - start.year + 1
            ys = "元" if y == 1 else str(y)
            return f"{name}{ys}年{d.month}月{d.day}日"
    return f"{d.year}年{d.month}月{d.day}日"
