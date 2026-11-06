"""法定相続情報一覧図・相続関係説明図の「中身」を組み立てる。

どちらも同じレイアウトエンジン（layout.py）を使い、違うのは
  - 誰を載せるか
  - 各人に何を書くか
  - 題名・末尾の記載
だけ。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .heirs import Family, HeirResult, determine, fmt_share, secondary_decedents
from .layout import Drawing, Spec, Style, layout
from .model import Case
from .wareki import to_wareki


@dataclass
class Diagram:
    kind: str                # "ichiran" | "setsumei"
    decedent: str
    title: str
    drawing: Drawing
    footer: list[str]
    landscape: bool
    reserve_bottom_mm: float = 0.0
    trailing: str = ""       # 「以下余白」
    warnings: list[str] = field(default_factory=list)
    auto_labels: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 続柄
def relation(case: Case, fam: Family, ctx: str, pid: str, *,
             child_style: str = "koseki", _depth: int = 0) -> tuple[str, bool]:
    """ctx（被相続人）から見た pid の続柄。(表示, 自動推定したか)"""
    p = fam.p[pid]
    c = fam.p[ctx]
    if ctx in p.relation_by:
        lab = p.relation_by[ctx]
        return ("子" if child_style == "child" and _is_child(fam, ctx, pid) else lab), False
    if ctx == case.decedent and p.relation:
        if child_style == "child" and _is_child(fam, ctx, pid):
            return "子", False
        return p.relation, False

    for m in fam.marriages_of(ctx):
        if m.partner(ctx) == pid:
            lab = {"F": "妻", "M": "夫"}.get(p.sex, "配偶者")
            if m.divorced:
                lab = "元" + lab
            return lab, p.sex is None
    pc = fam.link(ctx, pid)
    if pc:
        if child_style == "child":
            return "子", False
        if pc.type == "adopted":
            return {"F": "養女", "M": "養子"}.get(p.sex, "養子"), False
        return "子", True
    pc = fam.link(pid, ctx)
    if pc:
        base = {"M": "父", "F": "母"}.get(p.sex, "親")
        return ("養" + base if pc.type == "adopted" else base), p.sex is None
    for q in fam.parents(ctx):
        if fam.link(pid, q):
            return {"M": "祖父", "F": "祖母"}.get(p.sex, "祖父母"), p.sex is None
    for q in fam.parents(pid):
        if fam.link(ctx, q):
            return "孫", False
        for r in fam.parents(q):
            if fam.link(ctx, r):
                return "曾孫", False
    my_parents = set(fam.parents(ctx))
    if my_parents & set(fam.parents(pid)):
        if p.sex and p.birth and c.birth:
            older = p.birth < c.birth
            return {("M", True): "兄", ("M", False): "弟", ("F", True): "姉", ("F", False): "妹"}[(p.sex, older)], False
        return "兄弟姉妹", True
    for q in fam.parents(pid):
        if my_parents & set(fam.parents(q)):
            return {"M": "甥", "F": "姪"}.get(p.sex, "甥姪"), p.sex is None
    if _depth == 0:
        for m in fam.marriages_of(pid):
            o = m.partner(pid)
            if o == ctx:
                continue
            o_lab, o_auto = relation(case, fam, ctx, o, child_style="koseki", _depth=1)
            if o_lab != "続柄不明":
                wife = {"F": "妻", "M": "夫"}.get(p.sex, "配偶者")
                return f"{o_lab}{_compact(fam.p[o].name)}の{wife}", o_auto
    return "続柄不明", True


def _ref_lines(fam: Family, res: HeirResult, pid: str, role: str):
    """2か所目に出る人物の参照ボックス。"""
    p = fam.p[pid]
    if role == "spouse":
        lab = {"F": "妻", "M": "夫"}.get(p.sex, "配偶者")
        out = [(f"（{lab}）", "label")]
    else:
        parents = [x for x in role.partition(":")[2].split(",") if x]
        who = "・".join(_compact(fam.p[x].name) for x in parents)
        out = [(f"（{who}の子）" if who else "（子）", "label")]
    out += [(p.name, "name"), ("※前掲と同一人", "s")]
    if len(res.routes.get(pid, [])) > 1:
        out.append(("（二重資格）", "s"))
    return out


def _compact(name: str) -> str:
    return name.replace("　", "").replace(" ", "")


def _is_child(fam: Family, ctx: str, pid: str) -> bool:
    return fam.link(ctx, pid) is not None


# ---------------------------------------------------------------- 共通部品
def _date_line(label: str, d: dt.date | None) -> tuple[str, str]:
    return (f"{label}　{to_wareki(d, '（未入力）')}", "s")


def _creator_footer(case: Case, created: dt.date) -> list[str]:
    cr = case.creator
    lines = [f"作成日：{to_wareki(created)}"]
    who = "　".join(x for x in (cr.title, cr.name) if x) or "（未入力）"
    lines.append(f"作成者：住所　{cr.address or '（未入力）'}")
    lines.append(f"　　　　氏名　{who}")
    return lines


def _style(case: Case, landscape: bool = False) -> Style:
    return Style(font=case.options.font, avail_w=267.0 if landscape else 180.0)


def _marriage_pairs(fam: Family, shown: set[str], include_divorced: bool, at: dt.date | None):
    out = []
    for m in sorted(fam.case.marriages, key=lambda m: (m.date or dt.date.max)):
        if m.a in shown and m.b in shown:
            div = m.divorced is True or isinstance(m.divorced, dt.date)
            if div and not include_divorced:
                continue
            out.append((m.a, m.b))
    return out


def _root(fam: Family, ctx: str, shown: set[str]) -> str:
    cur = ctx
    for _ in range(6):
        ps = [q for q in fam.parents(cur) if q in shown]
        if not ps:
            break
        ps.sort(key=lambda q: (fam.p[q].sex != "M",))
        cur = ps[0]
    return cur


def _order(case: Case, shown: set[str]) -> list[str]:
    return [p.id for p in case.persons if p.id in shown]


# ---------------------------------------------------------------- 法定相続情報一覧図
def ichiranzu(case: Case, decedent: str | None = None) -> tuple[Diagram, HeirResult]:
    fam = Family(case)
    did = decedent or case.decedent
    res = determine(case, did, respect_renunciation=False)
    res_main = res
    d = fam.p[did]
    style = case.options.child_relation_style
    auto: list[str] = []

    shown = {did} | set(res.heirs) | res.intermediates() | res.connectors
    edges = sorted(res.route_edges)
    for pc in case.parent_child:   # 子の他方の親（配偶者）も線でつなぐ
        if pc.parent in shown and pc.child in shown and fam._active_link(pc, d.death):
            if (pc.parent, pc.child) not in res.route_edges and pc.parent == res.spouse:
                edges.append((pc.parent, pc.child))
    marriages = [(a, b) for a, b in _marriage_pairs(fam, shown, include_divorced=False, at=d.death)
                 if did in (a, b) or (a in res.connectors and b in res.connectors)]

    def lines_of(pid):
        p = fam.p[pid]
        if pid == did:
            return [(f"最後の住所　{p.address or '（未入力）'}", "s"),
                    (f"最後の本籍　{p.honseki or '（未入力）'}", "s"),
                    _date_line("出生", p.birth), _date_line("死亡", p.death),
                    ("（被相続人）", "label"), (p.name, "name")]
        lab, is_auto = relation(case, fam, did, pid, child_style=style)
        if is_auto:
            auto.append(f"{p.name}: {d.name}の一覧図で続柄を「{lab}」と自動設定"
                        f"（{d.name}から見た戸籍上の続柄を教えてください）")
        out = []
        if pid in res.shares and case.options.show_heir_address and p.death is None:
            out.append((f"住所　{p.address or '（未入力）'}", "s"))
        out.append(_date_line("出生", p.birth))
        if p.death:
            out.append(_date_line("死亡", p.death))
        out.append((f"（{lab}）", "label"))
        out.append((p.name + ("　（申出人）" if p.applicant else ""), "name"))
        return out

    def ref_lines_of(pid, role):
        return _ref_lines(fam, res_main, pid, role)

    spec = Spec(persons=_order(case, shown), marriages=marriages, edges=edges,
                root=_root(fam, did, shown), lines_of=lines_of, ref_lines_of=ref_lines_of,
                allow_ref=lambda a, b: (a, b) in res.route_edges,
                birth={p.id: p.birth for p in case.persons})
    drawing, lw = layout(spec, _style(case))
    created = case.created_date or dt.date.today()
    dia = Diagram("ichiran", did, f"被相続人　{d.name}　法定相続情報", drawing,
                  _creator_footer(case, created), landscape=False,
                  reserve_bottom_mm=50.0, trailing="以下余白", warnings=lw,
                  auto_labels=list(dict.fromkeys(auto)))
    return dia, res


# ---------------------------------------------------------------- 相続関係説明図
def setsumeizu(case: Case) -> tuple[Diagram, list[HeirResult]]:
    fam = Family(case)
    did = case.decedent
    d = fam.p[did]
    auto: list[str] = []

    results: list[HeirResult] = []
    shown: set[str] = set()
    status: dict[str, list[str]] = {}
    todo = [did]
    done = set()
    while todo and len(done) < 6:
        x = todo.pop(0)
        if x in done:
            continue
        done.add(x)
        r_real = determine(case, x, respect_renunciation=True)
        r_kos = determine(case, x, respect_renunciation=False)
        results.append(r_real)
        shown |= {x} | set(r_real.heirs) | r_real.intermediates() | r_real.connectors
        shown |= set(r_kos.heirs) | r_kos.intermediates() | r_kos.connectors
        for m in fam.marriages_of(x):
            shown.add(m.partner(x))
        for pc in fam.child_links(x):
            shown.add(pc.child)
        for r in (r_real, r_kos):
            if r.rank == 3:   # 兄弟姉妹の父母（後妻・後夫を含む）も載せて全血/半血がわかるように
                for rs in r.routes.values():
                    for rt in rs:
                        if rt.kind in ("sibling", "sibling_daishu"):
                            shown.update(fam.parents(rt.path[0]))
        for h in r_real.heirs:
            if x != did:
                status.setdefault(h, []).append(f"{_compact(fam.p[x].name)}の相続人")
        todo += secondary_decedents(case, r_kos)

    main = results[0]
    res_main = main
    edges = [(pc.parent, pc.child) for pc in case.parent_child
             if pc.parent in shown and pc.child in shown]
    marriages = _marriage_pairs(fam, shown, include_divorced=True, at=d.death)

    def lines_of(pid):
        p = fam.p[pid]
        if pid == did:
            out = [(f"本籍　{p.honseki or '（未入力）'}", "s"),
                   (f"最後の住所　{p.address or '（未入力）'}", "s")]
            if p.registered_address and p.registered_address != p.address:
                out.append((f"登記簿上の住所　{p.registered_address}", "s"))
            out += [_date_line("出生", p.birth), _date_line("死亡", p.death),
                    ("（被相続人）", "label"), (p.name, "name")]
            return out
        lab, is_auto = relation(case, fam, did, pid)
        if is_auto:
            auto.append(f"{p.name}: 説明図で続柄を「{lab}」と自動設定")
        out = []
        if p.death is None and p.address:
            out.append((f"住所　{p.address}", "s"))
        out.append(_date_line("出生", p.birth))
        if p.death:
            out.append(_date_line("死亡", p.death))
        for m in fam.marriages_of(pid):
            if did in (m.a, m.b) and isinstance(m.divorced, dt.date):
                out.append((f"離婚　{to_wareki(m.divorced)}", "s"))
        pc = fam.link(did, pid)
        if pc and pc.type == "adopted" and pc.date:
            out.append((f"養子縁組　{to_wareki(pc.date)}", "s"))
        tags = []
        if p.renounced:
            tags.append("相続放棄")
        if p.disinherited:
            tags.append("廃除")
        if p.disqualified:
            tags.append("相続欠格")
        if any(rt.half_blood for rt in main.routes.get(pid, [])):
            tags.append("半血")
        if p.death and pid in main.shares and p.death > (d.death or dt.date.min):
            tags.append("数次相続")
        tags += status.get(pid, [])
        if p.estate_note:
            tags.append(p.estate_note)
        if case.options.show_shares_in_explanation and pid in main.shares:
            tags.append(f"法定相続分 {fmt_share(main.shares[pid])}")
        out.append((f"（{lab}）", "label"))
        out.append((p.name, "name"))
        if tags:
            out.append(("【" + "・".join(tags) + "】", "s"))
        return out

    def ref_lines_of(pid, role):
        return _ref_lines(fam, res_main, pid, role)

    st = _style(case, landscape=True)
    spec = Spec(persons=_order(case, shown), marriages=marriages, edges=edges,
                root=_root(fam, did, shown), lines_of=lines_of, ref_lines_of=ref_lines_of,
                birth={p.id: p.birth for p in case.persons})
    drawing, lw = layout(spec, st)
    created = case.created_date or dt.date.today()
    dia = Diagram("setsumei", did, f"被相続人　{d.name}　相続関係説明図", drawing,
                  _creator_footer(case, created), landscape=True, warnings=lw,
                  auto_labels=list(dict.fromkeys(auto)))
    return dia, results
