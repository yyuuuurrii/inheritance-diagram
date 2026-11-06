"""図を出したあとに人が確認する項目（Markdown）を作る。"""
from __future__ import annotations

import datetime as dt

from .diagrams import relation
from .heirs import KIND_LABEL, Family, HeirResult, fmt_share
from .model import Case
from .wareki import to_wareki


def _date_issues(case: Case, fam: Family) -> list[str]:
    out = []
    for p in case.persons:
        if p.birth and p.death and p.death < p.birth:
            out.append(f"{p.name}: 死亡日（{to_wareki(p.death)}）が出生日（{to_wareki(p.birth)}）より前です。")
    for pc in case.parent_child:
        par, ch = fam.p[pc.parent], fam.p[pc.child]
        if pc.type == "biological" and par.birth and ch.birth:
            gap = (ch.birth - par.birth).days / 365.25
            if gap < 13:
                out.append(f"{par.name}（親）と{ch.name}（子）の年齢差が {gap:.0f} 歳です。生年月日・親子関係を確認してください。")
        if pc.type == "biological" and par.death and ch.birth and (ch.birth - par.death).days > 300:
            out.append(f"{ch.name} の出生が親 {par.name} の死亡から300日を超えています。親子関係を確認してください。")
        if pc.type == "adopted":
            if pc.date and par.death and pc.date > par.death:
                out.append(f"{par.name} の死亡後に養子縁組日（{to_wareki(pc.date)}）があります。")
            if pc.date and ch.birth and pc.date < ch.birth:
                out.append(f"{ch.name} の出生前に養子縁組日があります。")
            if par.birth and ch.birth and ch.birth <= par.birth:
                out.append(f"養子 {ch.name} が養親 {par.name} より年長または同日生まれです（尊属・年長者は養子にできない。民法793条）。")
    for m in case.marriages:
        a, b = fam.p[m.a], fam.p[m.b]
        for x in (a, b):
            if m.date and x.death and m.date > x.death:
                out.append(f"{a.name}・{b.name} の婚姻日が {x.name} の死亡後です。")
    return out


def _missing(case: Case, fam: Family, res: HeirResult) -> list[str]:
    out = []
    d = fam.p[case.decedent]
    for field, label in (("address", "最後の住所"), ("honseki", "最後の本籍"),
                         ("birth", "出生日"), ("death", "死亡日")):
        if getattr(d, field) in (None, ""):
            out.append(f"被相続人 {d.name} の{label}")
    for h in res.heirs:
        p = fam.p[h]
        if p.birth is None:
            out.append(f"{p.name} の出生日")
        if p.death is None and not p.address and case.options.show_heir_address:
            out.append(f"{p.name} の住所（一覧図に住所を書く設定のため）")
    if not case.creator.name:
        out.append("作成者の氏名")
    if not case.creator.address:
        out.append("作成者の住所")
    if case.created_date is None:
        out.append("作成日（未入力のため今日の日付を入れています）")
    if not any(fam.p[h].applicant for h in res.heirs):
        out.append("法定相続情報一覧図の申出人（どの相続人か）")
    return out


def build(case: Case, ichiran: list[tuple], setsumei: tuple, page_notes: list[str],
          files: list[str]) -> str:
    fam = Family(case)
    main_kos = ichiran[0][1]
    sdia, sresults = setsumei
    main = sresults[0]
    d = fam.p[case.decedent]
    L: list[str] = []
    L.append(f"# 確認チェックリスト：被相続人 {d.name}")
    L.append("")
    L.append(f"作成：{dt.date.today().isoformat()}（ツールによる自動判定。最終判断は司法書士が行うこと）")
    L.append("")

    L.append("## 1. 判定結果（相続放棄を反映した、実際の相続人）")
    L.append("")
    rank_name = {0: "血族相続人なし", 1: "第1順位（子・代襲）", 2: "第2順位（直系尊属）", 3: "第3順位（兄弟姉妹）"}
    L.append(f"- 相続順位：**{rank_name[main.rank]}**" + ("／配偶者あり" if main.spouse else "／配偶者なし"))
    L.append("")
    L.append("| 氏名 | 続柄 | 資格 | 法定相続分 |")
    L.append("|---|---|---|---|")
    for h in main.heirs:
        lab, _ = relation(case, fam, case.decedent, h)
        kinds = "＋".join(KIND_LABEL[r.kind] + ("（半血）" if r.half_blood else "") for r in main.routes[h])
        L.append(f"| {fam.p[h].name} | {lab} | {kinds} | {fmt_share(main.shares[h])} |")
    total = sum(main.shares.values())
    L.append("")
    L.append(f"- 相続分の合計：{fmt_share(total)}" + ("" if total == 1 or not main.shares else "　⚠ 1になっていません"))
    if set(main_kos.heirs) != set(main.heirs):
        L.append(f"- ⚠ 法定相続情報一覧図（戸籍上の相続人）と顔ぶれが違います。一覧図には相続放棄が反映されないためです。"
                 f"一覧図に載る人：{'、'.join(fam.p[h].name for h in main_kos.heirs)}")
    for dia, r in ichiran[1:]:
        heirs = "、".join(f"{fam.p[h].name}（{fmt_share(r.shares[h])}）" for h in r.heirs)
        L.append(f"- 数次相続：{fam.p[r.decedent].name}（{to_wareki(fam.p[r.decedent].death)}死亡）の相続人 → {heirs or 'なし'}")
    L.append("")

    warn = []
    for r in [main] + [r for _, r in ichiran] + sresults[1:]:
        warn += r.warnings
    for dia, _ in ichiran:
        warn += dia.warnings
    warn += sdia.warnings + page_notes
    if len(ichiran) > 1:
        warn.append("被相続人より後に亡くなった相続人がいるため（数次相続）、法定相続情報一覧図を被相続人ごとに分けて作成しました。")
    renounced = [p.name for p in case.persons if p.renounced]
    if renounced:
        warn.append(f"相続放棄者（{'、'.join(renounced)}）は、一覧図には相続人として載り、説明図には「相続放棄」と表示しています。相続放棄申述受理証明書の添付を確認してください。")
    if case.options.child_relation_style == "child":
        warn.append("一覧図の子の続柄を「子」と記載しています。相続税の申告など、この書き方では使えない手続があります。")
    warn = list(dict.fromkeys(warn))
    L.append("## 2. 判断が必要だった箇所・要確認事項")
    L.append("")
    L += [f"- [ ] {w}" for w in warn] or ["- （なし）"]
    L.append("")

    L.append("## 3. テキストの解釈メモ（Claude が判断した点）")
    L.append("")
    L += [f"- [ ] {n}" for n in case.interpretation_notes] or ["- （なし）"]
    L.append("")

    L.append("## 4. 入力が不足している項目（図では「（未入力）」と表示）")
    L.append("")
    miss = _missing(case, fam, main_kos)
    autos = []
    for dia, _ in ichiran:
        autos += dia.auto_labels
    autos += sdia.auto_labels
    autos = list(dict.fromkeys(autos))
    L += [f"- [ ] {m}" for m in miss]
    if not miss and not autos:
        L.append("- （なし）")
    if autos:
        L.append("- [ ] 続柄を自動で入れた人（戸籍どおりの続柄、例：長男・二女 に直してください）")
        L += [f"    - {a}" for a in autos]
    L.append("")

    L.append("## 5. 日付・関係の整合性チェック")
    L.append("")
    L += [f"- [ ] {x}" for x in _date_issues(case, fam)] or ["- 自動チェックで矛盾は見つかりませんでした"]
    L.append("")

    L.append("## 6. 図の目視チェック（毎回確認）")
    L.append("")
    L += [
        "- [ ] 氏名の漢字が戸籍どおりか（旧字体・異体字。例：髙／高、﨑／崎、邊／辺）",
        "- [ ] 生年月日・死亡日が戸籍どおりか（和暦の年がずれていないか）",
        "- [ ] 被相続人の最後の住所が住民票の除票（または戸籍の附票）どおりか、最後の本籍が除籍謄本どおりか",
        "- [ ] 相続人の住所が住民票どおりか（番地・枝番・「丁目」「番」「号」の書き方）",
        "- [ ] 続柄が戸籍どおりか（長男／二男、長女／二女、養子／養女）",
        "- [ ] 配偶者が二重線、親子が一本線で、線のつながる相手が正しいか",
        "- [ ] 申出人の表示が正しいか（一覧図）",
        "- [ ] 作成日・作成者（住所・氏名・資格名）",
        "- [ ] 一覧図の下部に認証文用の余白が残っているか",
    ]
    L.append("")
    L.append("## 7. 出力ファイル")
    L.append("")
    L += [f"- {f}" for f in files]
    L.append("")
    L.append("修正がある場合は、修正内容をテキストで伝えてください（例：「一郎の続柄は二男」「花子の住所は〜」）。")
    return "\n".join(L) + "\n"
