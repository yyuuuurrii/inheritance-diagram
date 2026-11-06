import datetime as dt
from fractions import Fraction as F
from pathlib import Path

import pytest

from souzoku_zu.__main__ import build
from souzoku_zu.heirs import determine
from souzoku_zu.model import Case
from souzoku_zu.wareki import parse_date, to_wareki

EX = Path(__file__).parent.parent / "examples"


def names(case, res):
    return {case.person(h).name.replace("　", ""): s for h, s in res.shares.items()}


# ---------------------------------------------------------------- 和暦
@pytest.mark.parametrize("s,iso", [
    ("昭和20年1月1日", "1945-01-01"), ("令和元年5月1日", "2019-05-01"),
    ("H1.1.8", "1989-01-08"), ("S64.1.7", "1989-01-07"), ("R7.11.6", "2025-11-06"),
    ("２０２４－０３－０１", "2024-03-01"), ("T15.12.24", "1926-12-24"),
])
def test_parse(s, iso):
    assert parse_date(s) == dt.date.fromisoformat(iso)


def test_to_wareki():
    assert to_wareki(dt.date(2019, 5, 1)) == "令和元年5月1日"
    assert to_wareki(dt.date(1989, 1, 7)) == "昭和64年1月7日"
    assert to_wareki(dt.date(1989, 1, 8)) == "平成元年1月8日"


# ---------------------------------------------------------------- 例題
def test_basic():
    c = Case.load(EX / "01_basic.json")
    assert names(c, determine(c)) == {"法務花子": F(1, 2), "法務一郎": F(1, 4), "登記春子": F(1, 4)}


def test_complex_double_capacity_and_renounce():
    c = Case.load(EX / "02_complex.json")
    r = determine(c)
    assert names(c, r) == {"法務花子": F(1, 2), "法務次郎": F(3, 16), "法務さくら": F(1, 16),
                           "登記健司": F(1, 8), "登記春子": F(1, 8)}
    assert any("二重資格" in w for w in r.warnings)
    # 一覧図（放棄を反映しない）では夏男も相続人
    r0 = determine(c, respect_renunciation=False)
    assert "前田夏男" in names(c, r0)
    assert sum(r0.shares.values()) == 1


def test_siblings_half_blood_and_nephews():
    c = Case.load(EX / "03_siblings.json")
    assert names(c, determine(c)) == {"法務花子": F(3, 4), "雪野雪子": F(1, 10), "法務甥男": F(1, 20),
                                      "法務姪子": F(1, 20), "法務三郎": F(1, 20)}


def test_all_children_renounce_goes_to_parents():
    c = Case.load(EX / "04_renounce_to_parents.json")
    r = determine(c)
    assert r.rank == 2
    assert names(c, r) == {"相続舞": F(2, 3), "相続正": F(1, 6), "相続和子": F(1, 6)}
    assert determine(c, respect_renunciation=False).rank == 1


# ---------------------------------------------------------------- 個別ルール
def mk(persons, marriages=(), pcs=(), dec="d"):
    return Case.model_validate({"decedent": dec, "persons": persons,
                                "marriages": list(marriages), "parent_child": list(pcs)})


def P(i, **kw):
    return {"id": i, "name": i, **kw}


def test_adoptee_child_born_before_adoption_cannot_represent():
    c = mk([P("d", death="2020-01-01"), P("a", birth="1960-01-01", death="2010-01-01"),
            P("g1", birth="1985-01-01"), P("g2", birth="1995-01-01"), P("x")],
           pcs=[{"parent": "d", "child": "a", "type": "adopted", "date": "1990-01-01"},
                {"parent": "a", "child": "g1"}, {"parent": "a", "child": "g2"},
                {"parent": "d", "child": "x"}])
    r = determine(c)
    assert set(r.shares) == {"g2", "x"}
    assert r.shares["g2"] == F(1, 2)
    assert any("887条2項" in w for w in r.warnings)


def test_sibling_representation_is_one_generation_only():
    c = mk([P("d", death="2020-01-01"), P("f", death="2000-01-01"), P("m", death="2000-01-01"),
            P("s", death="2010-01-01"), P("n", death="2015-01-01"), P("gn"), P("s2")],
           marriages=[{"a": "f", "b": "m"}],
           pcs=[{"parent": "f", "child": "d"}, {"parent": "m", "child": "d"},
                {"parent": "f", "child": "s"}, {"parent": "m", "child": "s"},
                {"parent": "f", "child": "s2"}, {"parent": "m", "child": "s2"},
                {"parent": "s", "child": "n"}, {"parent": "n", "child": "gn"}])
    r = determine(c)
    assert set(r.shares) == {"s2"}


def test_renounced_child_has_no_representation():
    c = mk([P("d", death="2020-01-01"), P("c1", renounced=True), P("g"), P("c2")],
           pcs=[{"parent": "d", "child": "c1"}, {"parent": "c1", "child": "g"},
                {"parent": "d", "child": "c2"}])
    assert determine(c).shares == {"c2": F(1)}


def test_disinherited_child_is_represented():
    c = mk([P("d", death="2020-01-01"), P("c1", disinherited=True), P("g"), P("c2")],
           pcs=[{"parent": "d", "child": "c1"}, {"parent": "c1", "child": "g"},
                {"parent": "d", "child": "c2"}])
    assert determine(c).shares == {"g": F(1, 2), "c2": F(1, 2)}


def test_divorced_spouse_excluded_but_children_included():
    c = mk([P("d", death="2020-01-01"), P("ex", sex="F"), P("w", sex="F"), P("c")],
           marriages=[{"a": "d", "b": "ex", "divorced": "1990-01-01"}, {"a": "d", "b": "w"}],
           pcs=[{"parent": "d", "child": "c"}, {"parent": "ex", "child": "c"}])
    assert determine(c).shares == {"w": F(1, 2), "c": F(1, 2)}


def test_simultaneous_death_treated_as_predeceased():
    c = mk([P("d", death="2020-01-01"), P("c", death="2020-01-01"), P("g")],
           pcs=[{"parent": "d", "child": "c"}, {"parent": "c", "child": "g"}])
    r = determine(c)
    assert r.shares == {"g": F(1)}
    assert any("同時死亡" in w for w in r.warnings)


# ---------------------------------------------------------------- 出力
@pytest.mark.parametrize("ex", sorted(EX.glob("*.json")), ids=lambda p: p.stem)
def test_build_outputs(ex, tmp_path):
    c = Case.load(ex)
    r = build(c, tmp_path, png=False)
    for f in r["files"]:
        assert (tmp_path / f).exists(), f
    md = (tmp_path / "確認チェックリスト.md").read_text(encoding="utf-8")
    assert "判定結果" in md and "目視チェック" in md


def test_mukoyoshi_and_grandchildren_adopted_while_parent_alive():
    """婿養子＋孫2人を養子（実親Cは生存）: 子4人で各1/4、二重資格なし。説明図で参照は1回ずつ。"""
    from souzoku_zu.diagrams import setsumeizu
    c = Case.load(EX / "05_mukoyoshi_magoyoshi.json")
    r = determine(c)
    assert r.shares == {"F": F(1, 4), "C": F(1, 4), "D": F(1, 4), "E": F(1, 4)}
    assert not any("二重資格" in w for w in r.warnings)
    dia, _ = setsumeizu(c)
    refs = [b.pid for b in dia.drawing.boxes if b.ref]
    assert sorted(refs) == ["D", "E"]
    texts = " ".join(t.text for b in dia.drawing.boxes for t in b.lines)
    assert "二重資格" not in texts
