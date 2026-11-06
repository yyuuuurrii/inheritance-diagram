"""入力データ（case.json）のモデル。

Claude がユーザーのテキストを解釈してこの形に落とし込み、
以降の判定・描画はすべてこのデータだけを元に機械的に行う。
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

from .wareki import parse_date

Date = Optional[dt.date]


def _date(v):
    return parse_date(v)


class Person(BaseModel):
    id: str
    name: str = Field(description="戸籍上の氏名。旧字体はそのまま")
    sex: Optional[Literal["M", "F"]] = None
    birth: Date = None
    death: Date = None
    address: Optional[str] = Field(None, description="住所（被相続人は最後の住所）")
    honseki: Optional[str] = Field(None, description="本籍（被相続人は最後の本籍）")
    registered_address: Optional[str] = Field(
        None, description="登記簿上の住所（最後の住所と異なる場合、説明図に併記）")
    relation: Optional[str] = Field(
        None, description="主たる被相続人から見た戸籍上の続柄（長男、二女、養子 など）")
    relation_by: dict[str, str] = Field(
        default_factory=dict, description="被相続人ID→続柄。数次相続の2次相続などで使う")
    renounced: bool = Field(False, description="相続放棄（家庭裁判所で受理済み）")
    disinherited: bool = Field(False, description="推定相続人の廃除（戸籍に記載あり）")
    disqualified: bool = Field(False, description="相続欠格（戸籍には載らない）")
    applicant: bool = Field(False, description="法定相続情報一覧図の申出人")
    estate_note: Optional[str] = Field(
        None, description="説明図に付ける注記（『相続』『分割』など）")
    note: Optional[str] = None

    _v_birth = field_validator("birth", "death", mode="before")(_date)


class Marriage(BaseModel):
    a: str
    b: str
    date: Date = None
    divorced: Optional[dt.date | bool] = Field(
        None, description="離婚日（日付不明なら true）")

    _v = field_validator("date", mode="before")(_date)

    @field_validator("divorced", mode="before")
    @classmethod
    def _v_div(cls, v):
        if v is None or isinstance(v, bool):
            return v
        return parse_date(v)

    def partner(self, pid: str) -> str:
        return self.b if self.a == pid else self.a


class ParentChild(BaseModel):
    parent: str
    child: str
    type: Literal["biological", "adopted"] = "biological"
    date: Date = Field(None, description="養子縁組日")
    dissolved: Optional[dt.date | bool] = Field(
        None, description="離縁日（日付不明なら true）")

    _v = field_validator("date", mode="before")(_date)

    @field_validator("dissolved", mode="before")
    @classmethod
    def _v_dis(cls, v):
        if v is None or isinstance(v, bool):
            return v
        return parse_date(v)


class Creator(BaseModel):
    name: str = ""
    address: str = ""
    title: str = Field("", description="資格名（司法書士 など）")


class Options(BaseModel):
    child_relation_style: Literal["koseki", "child"] = Field(
        "koseki", description="一覧図の子の続柄を戸籍どおり（koseki）にするか『子』にするか")
    show_heir_address: bool = Field(True, description="一覧図に相続人の住所を書くか")
    show_shares_in_explanation: bool = Field(False, description="説明図に法定相続分を書くか")
    font: Literal["mincho", "gothic"] = "mincho"


class Case(BaseModel):
    decedent: str = Field(description="被相続人の person id")
    persons: list[Person]
    marriages: list[Marriage] = Field(default_factory=list)
    parent_child: list[ParentChild] = Field(default_factory=list)
    created_date: Date = None
    creator: Creator = Field(default_factory=Creator)
    options: Options = Field(default_factory=Options)
    interpretation_notes: list[str] = Field(
        default_factory=list, description="Claude がテキストを解釈した際の判断メモ")

    _v = field_validator("created_date", mode="before")(_date)
    _idx: Optional[dict] = PrivateAttr(default=None)

    @model_validator(mode="after")
    def _check_refs(self):
        ids = [p.id for p in self.persons]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"person id が重複しています: {sorted(dup)}")
        known = set(ids)
        if self.decedent not in known:
            raise ValueError(f"decedent '{self.decedent}' が persons にありません")
        for m in self.marriages:
            for x in (m.a, m.b):
                if x not in known:
                    raise ValueError(f"marriages に未定義の id: {x}")
        for pc in self.parent_child:
            for x in (pc.parent, pc.child):
                if x not in known:
                    raise ValueError(f"parent_child に未定義の id: {x}")
        return self

    # ---- 参照ヘルパ ----
    def person(self, pid: str) -> Person:
        return self._index()[pid]

    def _index(self) -> dict[str, Person]:
        if self._idx is None:
            self._idx = {p.id: p for p in self.persons}
        return self._idx

    @classmethod
    def load(cls, path: str | Path) -> "Case":
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
