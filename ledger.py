"""買い目の確定記録と検証集計。

方針（チャッピーと決めたルール）をコードで守る:
- 買い目は記録時刻つきで追記のみ。上書きしない
- 結果を取得した後に記録・変更した買い目は集計に入れない
- 変更するときは理由を必須にし、変更前の行も残す
- 払戻が確認できないレースは「未確認」として集計から外す
- 見送り・返還・不成立は別に数える
- 均等100円の検証収支と、実際の購入収支を分ける
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from autorace_api import PLACE_JA, finish_order, load_json, now_iso, trifecta_payouts

LEDGER = Path(__file__).parent / "data" / "picks.csv"
FIELDS = ["記録時刻", "日付", "場", "R", "種別", "本命", "対抗", "1点金額",
          "実購入額", "状態", "変更理由", "メモ", "ルール", "締切"]
# 種別: 裁量（映像を見た予想） / 数値（ルールだけの予想）。検証は分けて集計する
KINDS = ("裁量", "数値")
STATES = ("有効", "見送り")


def _norm(combos: str) -> list[str]:
    out = []
    for c in combos.replace("、", ",").replace(" ", ",").split(","):
        c = c.strip().replace("ー", "-").replace("－", "-")
        if c:
            parts = c.split("-")
            if len(parts) != 3 or len(set(parts)) != 3 or not all(p.isdigit() for p in parts):
                raise ValueError(f"3連単の形になっていない買い目: {c}")
            out.append(c)
    return out


def _rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    with LEDGER.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _append(row: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def add_pick(date, place, race, honmei, taikou="", kind="裁量", unit=100,
             actual="", state="有効", reason="", memo="", rule="", deadline="") -> dict:
    if kind not in KINDS:
        raise ValueError(f"種別は {KINDS} のどれか")
    if state not in STATES:
        raise ValueError(f"状態は {STATES} のどれか")
    if deadline and now_iso() >= deadline:
        raise PermissionError("締切を過ぎているので記録しない")
    if load_json("result", place, date, int(race)) is not None:
        raise PermissionError("このレースは結果を取得済み。結果を見た後の記録はできない")
    existing = [r for r in _rows() if (r["日付"], r["場"], r["R"], r["種別"]) ==
                (date, place, str(race), kind)]
    if existing and not reason:
        raise PermissionError("同じレースの買い目が記録済み。変更するなら変更理由を書く（追加する根拠と削る根拠）")
    h, t = _norm(honmei), _norm(taikou)
    if state == "有効" and not h:
        raise ValueError("買い目が空")
    if len(set(h + t)) != len(h + t):
        raise ValueError("本命と対抗で同じ買い目が重複している")
    row = {"記録時刻": now_iso(), "日付": date, "場": place, "R": str(race), "種別": kind,
           "本命": " ".join(h), "対抗": " ".join(t), "1点金額": str(unit),
           "実購入額": str(actual), "状態": state, "変更理由": reason, "メモ": memo,
           "ルール": rule, "締切": deadline}
    _append(row)
    return row


@dataclass
class RaceEval:
    date: str
    place: str
    race: int
    kind: str
    rule: str
    status: str          # 的中 / 不的中 / 見送り / 返還 / 結果未取得 / 払戻未確認 / 集計外
    points: int = 0
    stake: int = 0
    payout: int = 0
    hit_combo: str = ""
    result: str = ""
    note: str = ""


def final_picks() -> list[dict]:
    """各レース・種別ごとに、結果取得前に記録された最後の行を採用する。"""
    latest: dict[tuple, dict] = {}
    late: list[dict] = []
    for r in _rows():
        key = (r["日付"], r["場"], r["R"], r["種別"])
        res = load_json("result", r["場"], r["日付"], int(r["R"]))
        if res and r["記録時刻"] > res.get("_fetched_at", "9999"):
            late.append(r)
            continue
        latest[key] = r
    for r in late:
        r["_late"] = True
    return list(latest.values()) + late


def evaluate() -> list[RaceEval]:
    out = []
    for p in final_picks():
        race = int(p["R"])
        ev = RaceEval(p["日付"], p["場"], race, p["種別"], p.get("ルール") or "", "")
        if p.get("締切") and p["記録時刻"] >= p["締切"]:
            ev.status, ev.note = "集計外", "締切後に記録された行"
            out.append(ev)
            continue
        if p.get("_late"):
            ev.status, ev.note = "集計外", "結果取得後に記録された行"
            out.append(ev)
            continue
        if p["状態"] == "見送り":
            ev.status = "見送り"
            out.append(ev)
            continue
        combos = (p["本命"] + " " + p["対抗"]).split()
        unit = int(p["1点金額"] or 100)
        ev.points, ev.stake = len(combos), len(combos) * unit
        res = load_json("result", p["場"], p["日付"], race)
        if res is None:
            ev.status = "結果未取得"
            out.append(ev)
            continue
        order = finish_order(res)
        ev.result = "-".join(map(str, order[:3]))
        pays = trifecta_payouts(res)
        absent = (res.get("refundInfo") or {}).get("absent") or []
        if not pays:
            ev.status = "払戻未確認"
            out.append(ev)
            continue
        hits = [c for c in combos if c in pays]
        ev.payout = sum(pays[c] * unit // 100 for c in hits)
        ev.hit_combo = " ".join(hits)
        ev.status = "的中" if hits else "不的中"
        if absent:
            ev.note = f"欠車あり{absent}（返還分は未反映・要確認）"
        out.append(ev)
    return out


def summary(evals: list[RaceEval], kind: str | None = None, rule: str | None = None) -> dict:
    es = [e for e in evals if (kind is None or e.kind == kind) and (rule is None or e.rule == rule)]
    counted = [e for e in es if e.status in ("的中", "不的中")]
    stake = sum(e.stake for e in counted)
    payout = sum(e.payout for e in counted)
    hits = sum(e.status == "的中" for e in counted)
    return {
        "対象レース": len(counted), "的中": hits,
        "的中率%": round(hits / len(counted) * 100, 1) if counted else None,
        "投資": stake, "払戻": payout,
        "回収率%": round(payout / stake * 100, 1) if stake else None,
        "収支": payout - stake,
        "見送り": sum(e.status == "見送り" for e in es),
        "未集計（結果未取得・払戻未確認・集計外）":
            sum(e.status in ("結果未取得", "払戻未確認", "集計外") for e in es),
    }


def format_report(evals: list[RaceEval]) -> str:
    lines = []
    for e in sorted(evals, key=lambda e: (e.date, e.place, e.race)):
        name = f'{e.date} {PLACE_JA.get(e.place, e.place)}{e.race}R[{e.kind}{e.rule}]'
        if e.status in ("的中", "不的中"):
            pay = f" 払戻{e.payout:,}円" if e.payout else ""
            lines.append(f"{name} 結果{e.result} {e.status}{pay}（{e.points}点・{e.stake:,}円）")
        else:
            lines.append(f"{name} {e.status} {e.note}".rstrip())
    groups = sorted({(e.kind, e.rule) for e in evals})
    for k, r in groups:
        s = summary(evals, k, r)
        label = f"{k}予想" + (f"（ルール{r}）" if r else "")
        lines.append(f"\n■{label}の検証（記録した1点金額で計算・実際の購入収支とは別）")
        lines += [f"  {a}: {b}" for a, b in s.items()]
    return "\n".join(lines)
