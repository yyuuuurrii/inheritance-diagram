"""法定相続人の判定と法定相続分の計算（民法 887〜890, 900, 901 条ベース）。

判定は「入力データに書かれた事実」だけで機械的に行い、
判断が必要だった箇所は warnings に理由付きで残す（チェックリストに出す）。

respect_renunciation=False で計算すると、相続放棄を無視した（＝戸籍上の）
相続人になる。法定相続情報一覧図は戸籍から作るので放棄は反映しない。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from fractions import Fraction

from .model import Case, Marriage, ParentChild, Person
from .wareki import to_wareki

KIND_LABEL = {
    "spouse": "配偶者",
    "child": "子",
    "daishu": "代襲相続人（直系卑属）",
    "ascendant": "直系尊属",
    "sibling": "兄弟姉妹",
    "sibling_daishu": "代襲相続人（兄弟姉妹の子）",
}


@dataclass
class Route:
    kind: str
    path: list[str]          # 被相続人から相続人までの経路（被相続人自身は含まない、末尾が相続人）
    share: Fraction
    half_blood: bool = False

    @property
    def heir(self) -> str:
        return self.path[-1]


@dataclass
class HeirResult:
    decedent: str
    date: dt.date | None
    respect_renunciation: bool
    rank: int = 0                       # 1:子 2:直系尊属 3:兄弟姉妹 0:血族相続人なし
    spouse: str | None = None
    shares: dict[str, Fraction] = field(default_factory=dict)
    routes: dict[str, list[Route]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    connectors: set[str] = field(default_factory=set)   # 図に必要な非相続人（父母など）
    route_edges: set[tuple[str, str]] = field(default_factory=set)  # (親, 子)

    @property
    def heirs(self) -> list[str]:
        return list(self.shares)

    def intermediates(self) -> set[str]:
        out: set[str] = set()
        for rs in self.routes.values():
            for r in rs:
                out.update(r.path[:-1])
        return out


class Family:
    """case 上の親族関係を引くためのヘルパ。"""

    def __init__(self, case: Case):
        self.case = case
        self.p = {x.id: x for x in case.persons}

    # ---- 時点つきの関係 ----
    @staticmethod
    def _active_link(pc: ParentChild, t: dt.date | None) -> bool:
        if pc.dissolved is True:
            return False
        if isinstance(pc.dissolved, dt.date) and (t is None or pc.dissolved <= t):
            return False
        return True

    def child_links(self, pid: str, t=None) -> list[ParentChild]:
        links = [pc for pc in self.case.parent_child
                 if pc.parent == pid and self._active_link(pc, t)]
        return sorted(links, key=lambda pc: self._birth_key(pc.child))

    def parent_links(self, pid: str, t=None) -> list[ParentChild]:
        return [pc for pc in self.case.parent_child
                if pc.child == pid and self._active_link(pc, t)]

    def parents(self, pid: str, t=None) -> list[str]:
        return [pc.parent for pc in self.parent_links(pid, t)]

    def marriages_of(self, pid: str) -> list[Marriage]:
        ms = [m for m in self.case.marriages if pid in (m.a, m.b)]
        return sorted(ms, key=lambda m: (m.date or dt.date.max))

    def _birth_key(self, pid: str):
        b = self.p[pid].birth
        return (b is None, b or dt.date.min)

    def link(self, parent: str, child: str) -> ParentChild | None:
        for pc in self.case.parent_child:
            if pc.parent == parent and pc.child == child:
                return pc
        return None


def determine(case: Case, decedent: str | None = None,
              respect_renunciation: bool = True) -> HeirResult:
    fam = Family(case)
    did = decedent or case.decedent
    d = fam.p[did]
    t = d.death
    res = HeirResult(did, t, respect_renunciation)
    W = res.warnings

    if t is None:
        W.append(f"被相続人 {d.name} の死亡日が未入力です。生存・先死亡の判定は『死亡日の入力がない人＝生存』として行いました。")

    def name(pid):
        return fam.p[pid].name

    def alive(pid) -> bool:
        x = fam.p[pid]
        if x.death is None:
            if t is not None and x.birth is not None and x.birth > t:
                W.append(f"{x.name} は被相続人の死亡後に出生しています（胎児として相続人に含めました。民法886条）。")
            return True
        if t is None:
            return True
        if x.death == t:
            W.append(f"{x.name} は被相続人と同日に死亡しています。同時死亡の推定（民法32条の2）により先に死亡したものとして扱いました。死亡時刻を確認してください。")
            return False
        return x.death > t

    def excluded(pid) -> bool:
        x = fam.p[pid]
        if x.disqualified:
            W.append(f"{x.name} は相続欠格として除外しました。欠格は戸籍に記載されないため、一覧図の作成可否・添付書面を確認してください。")
        return x.disinherited or x.disqualified

    def renounced(pid) -> bool:
        return respect_renunciation and fam.p[pid].renounced

    # ------------------------------------------------------------ 配偶者
    spouses = []
    for m in fam.marriages_of(did):
        s = m.partner(did)
        if m.divorced is True or (isinstance(m.divorced, dt.date) and (t is None or m.divorced <= t)):
            continue
        if alive(s) and not excluded(s) and not renounced(s):
            spouses.append(s)
    if len(spouses) > 1:
        W.append("婚姻中の配偶者が複数います（重婚の可能性）。離婚日を確認してください: "
                 + "、".join(name(s) for s in spouses))
    spouse = spouses[0] if spouses else None

    # ------------------------------------------------------------ 第1順位: 子・代襲
    def stirpe(pid: str, path: list[str], cut: dt.date | None, depth: int):
        """pid の系統が取得する相続人 [(heir, 割合, path)] を返す。空なら系統なし。"""
        x = fam.p[pid]
        if renounced(pid):
            return []
        if alive(pid) and not excluded(pid):
            return [(pid, Fraction(1), path)]
        subs = []
        for pc in fam.child_links(pid, t):
            c = fam.p[pc.child]
            if cut is not None and c.birth is not None and c.birth < cut:
                W.append(f"{c.name} は {x.name} の養子縁組（{to_wareki(cut)}）より前に出生しており、"
                         f"被相続人の直系卑属ではないため代襲相続人になりません（民法887条2項ただし書）。")
                continue
            ncut = cut
            if pc.type == "adopted":
                if pc.date is None:
                    W.append(f"{x.name}→{c.name} の養子縁組日が未入力です。代襲の可否に影響するため確認してください。")
                elif ncut is None or pc.date > ncut:
                    ncut = pc.date
            r = stirpe(pc.child, path + [pc.child], ncut, depth + 1)
            if r:
                subs.append(r)
        if not subs:
            return []
        n = len(subs)
        return [(h, s / n, p) for r in subs for (h, s, p) in r]

    lines = []
    for pc in fam.child_links(did, t):
        cut = pc.date if pc.type == "adopted" else None
        if pc.type == "adopted" and pc.date is None:
            W.append(f"養子 {name(pc.child)} の縁組日が未入力です（縁組前に生まれた養子の子は代襲できないため確認が必要）。")
        r = stirpe(pc.child, [pc.child], cut, 1)
        if r:
            lines.append(r)

    blood: list[tuple[str, Fraction, list[str], str, bool]] = []
    if lines:
        res.rank = 1
        n = len(lines)
        for r in lines:
            for h, s, p in r:
                blood.append((h, s / n, p, "child" if len(p) == 1 else "daishu", False))
        for r in lines:
            for _, _, p in r:
                prev = did
                for x in p:
                    res.route_edges.add((prev, x))
                    prev = x

    # ------------------------------------------------------------ 第2順位: 直系尊属
    if not blood:
        level = [(did, [])]
        seen = {did}
        while level:
            nxt = []
            for pid, chain in level:
                for q in fam.parents(pid, t):
                    if q not in seen:
                        seen.add(q)
                        nxt.append((q, chain + [q]))
            if not nxt:
                break
            hs = [(q, ch) for q, ch in nxt if alive(q) and not excluded(q) and not renounced(q)]
            if hs:
                res.rank = 2
                for q, ch in hs:
                    blood.append((q, Fraction(1, len(hs)), ch, "ascendant", False))
                    prev = did
                    for x in ch:
                        res.route_edges.add((x, prev))
                        prev = x
                    res.connectors.update(ch[:-1])
                break
            level = nxt

    # ------------------------------------------------------------ 第3順位: 兄弟姉妹
    if not blood:
        my_parents = set(fam.parents(did, t))
        sibs: dict[str, set[str]] = {}
        for q in my_parents:
            for pc in fam.child_links(q, t):
                if pc.child != did:
                    sibs.setdefault(pc.child, set()).add(q)
        if sibs and len(my_parents) < 2:
            W.append("被相続人の父母が2人とも入力されていないため、兄弟姉妹の全血・半血を判定できません。全血として計算しました。")
        stirpes = []
        for s, shared in sorted(sibs.items(), key=lambda kv: fam._birth_key(kv[0])):
            half = len(my_parents) >= 2 and len(shared) < 2
            if renounced(s):
                continue
            if alive(s) and not excluded(s):
                stirpes.append((s, half, [(s, Fraction(1), [s])], shared))
                continue
            kids = []
            for pc in fam.child_links(s, t):
                c = pc.child
                if renounced(c):
                    continue
                if alive(c) and not excluded(c):
                    kids.append(c)
                elif fam.child_links(c, t):
                    W.append(f"{name(c)}（兄弟姉妹の子）が先に死亡していますが、兄弟姉妹の代襲は一代限りのため、その子は相続人になりません（民法889条2項）。")
            if kids:
                stirpes.append((s, half, [(c, Fraction(1, len(kids)), [s, c]) for c in kids], shared))
        if stirpes:
            res.rank = 3
            total = sum(1 if half else 2 for _, half, _, _ in stirpes)
            for s, half, members, shared in stirpes:
                w = Fraction(1 if half else 2, total)
                for h, frac, p in members:
                    kind = "sibling" if len(p) == 1 else "sibling_daishu"
                    blood.append((h, w * frac, p, kind, half))
                for q in shared:
                    res.route_edges.add((q, s))
                for _, _, p in members:
                    if len(p) == 2:
                        res.route_edges.add((p[0], p[1]))
                if half:
                    W.append(f"{name(s)} は被相続人と父母の一方のみを同じくする兄弟姉妹（半血）です。相続分は全血の2分の1で計算しました（民法900条4号）。")
            for q in my_parents:
                res.route_edges.add((q, did))
            res.connectors.update(my_parents)

    # ------------------------------------------------------------ 相続分の合成
    spouse_share = {0: Fraction(1), 1: Fraction(1, 2), 2: Fraction(2, 3), 3: Fraction(3, 4)}[res.rank]
    blood_total = Fraction(1) - spouse_share if spouse else Fraction(1)
    if spouse:
        res.spouse = spouse
        res.shares[spouse] = spouse_share
        res.routes[spouse] = [Route("spouse", [spouse], spouse_share)]
    for h, s, p, kind, half in blood:
        share = s * blood_total
        res.shares[h] = res.shares.get(h, Fraction(0)) + share
        res.routes.setdefault(h, []).append(Route(kind, p, share, half))

    for h, rs in res.routes.items():
        if len(rs) > 1:
            W.append(f"{name(h)} は複数の資格で相続人になっています（二重資格: "
                     + "、".join(KIND_LABEL[r.kind] for r in rs)
                     + "）。相続分は各資格の合計で計算しました。実務上の取扱い（登記・税務）を確認してください。")
        if spouse and h == spouse and len(rs) > 1:
            W.append(f"{name(h)} は配偶者と血族相続人を兼ねています。配偶者と兄弟姉妹の二重資格は登記実務上認められない扱いがあるため確認してください。")

    if not res.shares:
        res.rank = 0
        W.append("相続人が見つかりませんでした（相続人不存在の可能性、または入力漏れ）。")

    res.warnings = list(dict.fromkeys(W))  # 重複除去（順序維持）
    return res


def secondary_decedents(case: Case, res: HeirResult) -> list[str]:
    """被相続人より後に死亡した相続人（数次相続の対象）。"""
    out = []
    for h in res.heirs:
        p = case.person(h)
        if p.death is not None and (res.date is None or p.death > res.date):
            out.append(h)
    return out


def fmt_share(f: Fraction) -> str:
    return "1" if f == 1 else f"{f.numerator}/{f.denominator}"
