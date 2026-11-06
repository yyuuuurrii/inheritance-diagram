"""家系図のレイアウト（左→右に世代が進む、司法書士実務で一般的な横型）。

- 1人の「ユニット」= 本人 + 配偶者（縦に積む。配偶者とは二重線）
- 子は右の列に並べ、夫婦の二重線の中点（片親のみの子は本人の右端）から
  縦の「バス線」を引いて枝分かれさせる
- 同一人物が2か所に関係する場合（孫養子、婿養子など）は、2か所目を
  小さな「※前掲」参照ボックスにして線の交差を避ける
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .fonts import text_width_mm, wrap

PT = 25.4 / 72  # 1pt を mm に


# ---------------------------------------------------------------- 描画プリミティブ
@dataclass
class TextLine:
    text: str
    size: float          # pt
    y: float = 0.0       # ボックス上端からのベースライン位置(mm)


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float
    lines: list[TextLine]
    anchor_dy: float     # 線をつなぐ y（ボックス上端から）
    pid: str = ""
    ref: bool = False
    name_end: float = 0.0  # 氏名行の右端（ボックス左端から）

    @property
    def anchor(self) -> float:
        return self.y + self.anchor_dy


@dataclass
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0.5   # pt


@dataclass
class Drawing:
    boxes: list[Box] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)

    def shift(self, dx: float, dy: float) -> "Drawing":
        for b in self.boxes:
            b.x += dx
            b.y += dy
        for ln in self.lines:
            ln.x1 += dx
            ln.x2 += dx
            ln.y1 += dy
            ln.y2 += dy
        return self

    def extend(self, other: "Drawing"):
        self.boxes += other.boxes
        self.lines += other.lines

    def bbox(self):
        xs = [b.x for b in self.boxes] + [ln.x1 for ln in self.lines] + [ln.x2 for ln in self.lines]
        xe = [b.x + b.w for b in self.boxes] + xs
        ys = [b.y for b in self.boxes] + [ln.y1 for ln in self.lines] + [ln.y2 for ln in self.lines]
        ye = [b.y + b.h for b in self.boxes] + ys
        if not self.boxes:
            return 0, 0, 0, 0
        return min(xs), min(ys), max(xe), max(ye)

    def scale(self, k: float) -> "Drawing":
        for b in self.boxes:
            b.x, b.y, b.w, b.h, b.anchor_dy = b.x * k, b.y * k, b.w * k, b.h * k, b.anchor_dy * k
            b.name_end *= k
            for t in b.lines:
                t.size *= k
                t.y *= k
        for ln in self.lines:
            ln.x1, ln.y1, ln.x2, ln.y2 = ln.x1 * k, ln.y1 * k, ln.x2 * k, ln.y2 * k
        return self


# ---------------------------------------------------------------- 入力（図の中身）
@dataclass
class Style:
    box_w: float = 50.0       # 1人分の幅(mm)
    col_gap: float = 14.0     # 世代間の横の間隔
    sp_gap: float = 7.0       # 本人と配偶者の縦の間隔（ここに二重線）
    child_gap: float = 5.0    # 兄弟の縦の間隔
    small: float = 8.5        # 住所・日付の文字サイズ(pt)
    name: float = 11.0        # 氏名の文字サイズ(pt)
    leading: float = 1.35
    font: str = "mincho"
    dbl_dx: float = 9.0       # 二重線のボックス左端からの位置
    dbl_sep: float = 0.9      # 二重線の間隔
    avail_w: float | None = None   # 用紙の使える幅。指定すると列数に合わせて box_w を調整


@dataclass
class Spec:
    """レイアウトに渡す図の内容。"""
    persons: list[str]
    marriages: list[tuple[str, str]]                 # 表示する婚姻（日付順）
    edges: list[tuple[str, str]]                     # (親, 子)
    root: str
    lines_of: callable                               # pid -> [(text, kind)]  kind: s|label|name
    ref_lines_of: callable                           # (pid, role) -> [(text, kind)]  role: child|spouse
    allow_ref: callable = lambda parent, child: True
    birth: dict = field(default_factory=dict)        # pid -> date（並び順用）


# ---------------------------------------------------------------- ツリー構築
@dataclass
class Slot:
    pid: str
    ref: bool = False


@dataclass
class Unit:
    head: str
    spouses: list[Slot] = field(default_factory=list)
    groups: list[tuple[frozenset, list]] = field(default_factory=list)  # (親の集合, [Unit|Slot])
    parent: "Unit | None" = None
    gkey: frozenset = frozenset()
    sib_spouse: str | None = None   # 同じ親の下に並ぶ兄弟と婚姻（婿養子・嫁養子など）


def build_tree(spec: Spec) -> tuple[list[Unit], list[str]]:
    shown = set(spec.persons)
    marr = [(a, b) for a, b in spec.marriages if a in shown and b in shown]
    parents_of: dict[str, list[str]] = {}
    for p, c in spec.edges:
        if p in shown and c in shown:
            parents_of.setdefault(c, []).append(p)
    children_of: dict[str, list[str]] = {}
    for c, ps in parents_of.items():
        for p in ps:
            children_of.setdefault(p, []).append(c)

    def bkey(pid):
        b = spec.birth.get(pid)
        return (b is None, b or dt.date.min, spec.persons.index(pid))

    placed: dict[str, Unit] = {}
    roots: list[Unit] = []
    warnings: list[str] = []

    def bfs(root: str):
        u = Unit(root)
        placed[root] = u
        roots.append(u)
        queue = [u]
        while queue:
            u = queue.pop(0)
            members = {u.head}
            for a, b in marr:
                if u.head in (a, b):
                    s = b if a == u.head else a
                    su = placed.get(s)
                    if su is not None and su.head == s and su.parent is not None \
                            and su.parent is u.parent and su.gkey == u.gkey:
                        # 兄弟どうしの婚姻: 隣に並べて二重線で結ぶ（参照ボックスを作らない）
                        if su.sib_spouse != u.head:
                            u.sib_spouse = s
                        continue
                    if su is not None and any(sl.pid == u.head for sl in su.spouses):
                        continue  # 相手側ですでに描いている
                    if s in placed:
                        u.spouses.append(Slot(s, ref=True))
                    else:
                        u.spouses.append(Slot(s))
                        placed[s] = u
                    members.add(s)
            kids = set()
            for m in members:
                kids.update(children_of.get(m, []))
            groups: dict[frozenset, list] = {}
            for c in sorted(kids, key=bkey):
                key = frozenset(p for p in parents_of[c] if p in members)
                # 本人と無関係な配偶者側だけの子（配偶者が参照の場合）はスキップ
                if c in placed:
                    if placed[c] is u:
                        continue
                    if any(spec.allow_ref(p, c) for p in key):
                        groups.setdefault(key, []).append(Slot(c, ref=True))
                    continue
                cu = Unit(c, parent=u, gkey=key)
                placed[c] = cu
                groups.setdefault(key, []).append(cu)
                queue.append(cu)
            u.groups = list(groups.items())
        # 兄弟間で婚姻している2人を隣どうしに並べ替える（BFS 終了後に実施）

    def _pair_siblings(u: Unit):
        for gi, (key, members) in enumerate(u.groups):
            ms = list(members)
            for m in list(ms):
                if isinstance(m, Unit) and m.sib_spouse:
                    partner = next((x for x in ms if isinstance(x, Unit) and x.head == m.sib_spouse), None)
                    if partner is not None:
                        ms.remove(partner)
                        ms.insert(ms.index(m) + 1, partner)
            u.groups[gi] = (key, ms)
            for m in ms:
                if isinstance(m, Unit):
                    _pair_siblings(m)

    bfs(spec.root)
    for pid in spec.persons:
        if pid not in placed:
            warnings.append(f"{pid} は図の他の人物と線でつながらないため、図の下部に単独で配置しました。関係の入力漏れを確認してください。")
            bfs(pid)
    for r in roots:
        _pair_siblings(r)
    return roots, warnings


# ---------------------------------------------------------------- ボックス生成
def make_box(spec: Spec, st: Style, pid: str, ref: bool = False, role: str = "child") -> Box:
    raw = spec.ref_lines_of(pid, role) if ref else spec.lines_of(pid)
    w = st.box_w * (0.8 if ref else 1.0)
    lines: list[TextLine] = []
    y = 0.0
    anchor = None
    name_end = 0.0
    for text, kind in raw:
        size = st.name if kind == "name" else st.small
        if ref and kind == "name":
            size = st.small + 1
        lh = size * PT * st.leading
        indent = "　" if kind == "s" else ""
        for seg in wrap(text, w, size, st.font, indent=indent):
            y += lh
            lines.append(TextLine(seg, size, y - lh * 0.22))
            if kind == "name" and anchor is None:
                anchor = y - lh * 0.5
                name_end = text_width_mm(seg, size, st.font)
    if anchor is None:
        anchor = y / 2
        name_end = w
    return Box(0, 0, w, y + 0.8, lines, anchor, pid, ref, name_end)


# ---------------------------------------------------------------- レイアウト
def layout(spec: Spec, st: Style) -> tuple[Drawing, list[str]]:
    roots, warnings = build_tree(spec)
    if st.avail_w:
        cols = max(_depth(r) for r in roots) + 1
        w = (st.avail_w - (cols - 1) * st.col_gap) / cols
        st = Style(**{**st.__dict__, "box_w": max(44.0, min(62.0, w))})
    out = Drawing()
    y = 0.0
    for r in roots:
        d, h = _layout_unit(spec, st, r, 0)
        out.extend(d.shift(0, y))
        y += h + st.child_gap * 3
    return out, warnings


def _depth(u: Unit) -> int:
    ds = [_depth(m) + 1 for _, ms in u.groups for m in ms if isinstance(m, Unit)]
    ds += [1 for _, ms in u.groups for m in ms if not isinstance(m, Unit)]
    return max(ds, default=0)


def _layout_unit(spec: Spec, st: Style, u: Unit, depth: int) -> tuple[Drawing, float]:
    x0 = depth * (st.box_w + st.col_gap)
    d = Drawing()

    # --- 本人と配偶者を縦に積む（前婚の配偶者は上、後の配偶者は下）
    head = make_box(spec, st, u.head)
    sp_boxes = [make_box(spec, st, s.pid, ref=s.ref, role="spouse") for s in u.spouses]
    order: list[Box] = []
    above = sp_boxes[:1] if len(sp_boxes) >= 2 else []
    below = sp_boxes[1:] if len(sp_boxes) >= 2 else sp_boxes
    order = above + [head] + below
    yy = 0.0
    for b in order:
        b.x, b.y = x0, yy
        yy += b.h + st.sp_gap
    unit_h = yy - st.sp_gap
    d.boxes += order

    # 二重線と、子の線の起点（夫婦ごと）
    conn: dict[frozenset, tuple[float, float]] = {}
    hi = order.index(head)
    for k, sb in enumerate(sp_boxes):
        si = order.index(sb)
        lo, hi_ = sorted((hi, si))
        top_box, bot_box = order[lo], order[hi_]
        if hi_ - lo == 1:
            xa = x0 + st.dbl_dx
            y1, y2 = top_box.y + top_box.h, bot_box.y
            for dx in (0, st.dbl_sep):
                d.lines.append(Line(xa + dx, y1, xa + dx, y2, 0.6))
            cy = (y1 + y2) / 2
            cx = xa + st.dbl_sep
        else:
            # 隣り合わない配偶者（3人目以降）は左側に括弧状の二重線
            xa = x0 - 2.5 - 1.6 * k
            ya, yb = head.anchor, sb.anchor
            for dx in (0, st.dbl_sep):
                d.lines.append(Line(xa - dx, ya, xa - dx, yb, 0.6))
            for yv in (ya, yb):
                d.lines.append(Line(xa - st.dbl_sep, yv, x0, yv, 0.6))
            prev = order[si - 1]
            cy = (prev.y + prev.h + sb.y) / 2
            cx = xa
        conn[frozenset({u.head, u.spouses[k].pid})] = (cx, cy)
    conn[frozenset({u.head})] = (x0 + head.name_end + 1.5, head.anchor)
    for s, sb in zip(u.spouses, sp_boxes):
        conn.setdefault(frozenset({s.pid}), (x0 + sb.name_end + 1.5, sb.anchor))

    if not u.groups:
        return d, unit_h

    # --- 子のブロックを右の列に縦に並べる
    groups = sorted(u.groups, key=lambda g: conn.get(g[0], conn[frozenset({u.head})])[1])
    child_draw = Drawing()
    anchors: list[list[float]] = []
    cy_acc = 0.0
    xc = x0 + st.box_w + st.col_gap
    pending_pair: tuple[str, float] | None = None   # (配偶者pid, 二重線の上端y)
    for _, members in groups:
        al = []
        for m in members:
            if isinstance(m, Unit):
                cd, ch = _layout_unit(spec, st, m, depth + 1)
                head_box = next(b for b in cd.boxes if b.pid == m.head and not b.ref and b.x == xc)
                al.append(head_box.anchor + cy_acc)
                if pending_pair and pending_pair[0] == m.head:
                    xa = xc + st.dbl_dx
                    for dx in (0, st.dbl_sep):
                        child_draw.lines.append(Line(xa + dx, pending_pair[1], xa + dx, head_box.y + cy_acc, 0.6))
                    pending_pair = None
                if m.sib_spouse:
                    pending_pair = (m.sib_spouse, head_box.y + head_box.h + cy_acc)
            else:
                rb = make_box(spec, st, m.pid, ref=True, role="child")
                rb.x = xc
                cd, ch = Drawing([rb]), rb.h
                al.append(rb.anchor + cy_acc)
            child_draw.extend(cd.shift(0, cy_acc))
            cy_acc += ch + st.child_gap
        anchors.append(al)
    child_h = cy_acc - st.child_gap

    # --- 最初の夫婦の起点を、その子たちの中央にそろえる
    first_conn = conn.get(groups[0][0], conn[frozenset({u.head})])[1]
    target = (anchors[0][0] + anchors[0][-1]) / 2
    delta = target - first_conn
    unit_off, child_off = (delta, 0.0) if delta >= 0 else (0.0, -delta)
    d.shift(0, unit_off)
    child_draw.shift(0, child_off)
    d.extend(child_draw)

    # --- 線を引く
    n = len(groups)
    for gi, (key, members) in enumerate(groups):
        cx, cyc = conn.get(key, conn[frozenset({u.head})])
        cyc += unit_off
        # 下の夫婦の子ほど縦線を左（内側）に置くと、上下に並ぶ家族どうしで線が交差しない
        bus_x = x0 + st.box_w + st.col_gap * (n - gi) / (n + 1)
        ys = [a + child_off for a in anchors[gi]]
        d.lines.append(Line(cx, cyc, bus_x, cyc))
        top, bot = min(ys + [cyc]), max(ys + [cyc])
        if bot - top > 0.01:
            d.lines.append(Line(bus_x, top, bus_x, bot))
        for yv in ys:
            d.lines.append(Line(bus_x, yv, xc, yv))

    return d, max(unit_off + unit_h, child_off + child_h)
