# inheritance-diagram（相続関係図作成ツール）

司法書士業務の補助ツール。家族関係をテキストで伝えると、Claude Code が解釈して

- **法定相続情報一覧図**（数次相続があれば被相続人ごとに複数枚）
- **相続関係説明図**
- **確認チェックリスト**（判定結果・要判断箇所・入力不足・整合性・目視チェック項目）

を作ります。図は PDF（提出・印刷用）、PPTX（PowerPoint で編集用）、PNG（プレビュー）で出力します。

## 使い方（Claude Code）

このリポジトリを開いた Claude Code に、戸籍から読み取った内容を文章で伝えるだけです。
スキル `.claude/skills/souzoku-zu/SKILL.md` が読み込まれ、図とチェックリストが返ってきます。

> 被相続人は法務太郎（昭和15年1月1日生、令和6年3月1日死亡、最後の住所…）。妻は花子…。
> 長男一郎は平成30年に先に亡くなっていて、子が次郎とさくら。次郎は太郎夫婦の養子にもなっている…

修正は「一郎の続柄は二男」のように文章で伝えれば、作り直します。

## 対応している関係

配偶者・子・代襲（再代襲）・直系尊属・兄弟姉妹（全血／半血、甥姪の代襲）、前婚の子、婚外子、
養子（孫養子の二重資格、婿養子、縁組前に生まれた養子の子の代襲不可、離縁）、相続放棄（順位の移動を含む）、
廃除・欠格、同時死亡、数次相続。

## コマンドで直接使う場合

```bash
pip install -r requirements.txt
python -m souzoku_zu build examples/02_complex.json -o output/complex
python -m souzoku_zu check examples/02_complex.json   # 判定だけ
python -m pytest -q
```

明朝体で出すには `apt-get install -y fonts-ipafont-mincho`（ない場合はゴシック体）。

## 構成

| ファイル | 役割 |
|---|---|
| `souzoku_zu/model.py` | 入力データ（case.json）の定義 |
| `souzoku_zu/heirs.py` | 相続人の判定・法定相続分（民法 887〜890, 900, 901 条） |
| `souzoku_zu/diagrams.py` | 一覧図・説明図それぞれに載せる人と記載内容、続柄 |
| `souzoku_zu/layout.py` | 横型（左→右に世代）レイアウト、二重線、線の交差回避 |
| `souzoku_zu/render.py` | 用紙への配置（A4/A3、自動縮小）、PDF/PPTX/PNG 出力 |
| `souzoku_zu/checklist.py` | 確認チェックリスト |
| `examples/` | 架空の事例（基本／複雑／兄弟姉妹・半血／放棄で父母へ） |
| `docs/samples/` | 出力見本 |

## 注意

- 実案件のデータは `cases/` に置いてください（`.gitignore` 済みでコミットされません）。
- 相続人の判定は入力された事実に基づく機械的な計算です。最終判断は司法書士が行ってください。
- 一覧図の様式は法務局の記載例の項目に合わせていますが、法務局の原本ファイルとの照合はしていません。
