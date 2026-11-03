"""開催中の場を確認し、試走タイムが出揃ったレースの買い目を締切前に記録する。

GitHub Actions から数分おきに呼ばれる想定。1回の実行で各場の「今のレース」だけを見る。
- 試走タイムが揃っていなければ何もしない（次の実行で再確認）
- 締切を過ぎていたら記録しない
- 同じレースに数値予想の記録があれば何もしない
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import article
import ledger
import strategy
from autorace_api import BASE, PLACE_JA, AutoraceClient, now_iso, save_json


def race_date(h: dict) -> str:
    """開催初日＋開催日数−1 = そのレースの開催日（深夜開催で日付をまたいでもずれない）。"""
    d = date.fromisoformat(h["periodStartDate"]) + timedelta(days=int(h["paragraphday"]) - 1)
    return d.isoformat()


def deadline_iso(day: str, hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    d = datetime.fromisoformat(day) + timedelta(days=h // 24)
    return f"{d.date().isoformat()}T{h % 24:02d}:{m:02d}:00+09:00"


def already_picked(day, place, race) -> bool:
    return any((r["日付"], r["場"], r["R"], r["種別"]) == (day, place, str(race), "数値")
               for r in ledger._rows())


ARTICLES = Path(__file__).parent / "articles"


def write_article(day, place, race, program, picks) -> Path:
    path = ARTICLES / day / f"{place}_{race:02d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(article.build(place, race, program, picks) + "\n", encoding="utf-8")
    return path


def run() -> list[str]:
    cl = AutoraceClient(interval=1.0)
    hold = cl.s.get(f"{BASE}/race_info/XML/Hold/Today", timeout=20).json()["body"]
    rule = strategy.current_rule()
    logs = []
    for h in hold.get("today", []):
        place = h["placeKey"]
        if str(h.get("cancelFlg")) != "0" or place not in PLACE_JA:
            continue
        race, day = int(h["nowRaceNo"] or 0), race_date(h)
        name = f"{PLACE_JA[place]}{race}R"
        if race < 1 or not h.get("telvoteTime") or h.get("telvoteClose"):
            continue
        deadline = deadline_iso(day, h["telvoteTime"])
        if now_iso() >= deadline or already_picked(day, place, race):
            continue
        program = cl.program(place, day, race)
        try:
            picks = strategy.make_picks(program, rule, h.get("distance"))
        except ValueError as e:  # 試走前
            logs.append(f"{name}: 待機（{e}）")
            continue
        try:
            ledger.add_pick(day, place, race, ",".join(picks["本命"]), ",".join(picks["対抗"]),
                            kind="数値", rule=rule["version"], deadline=deadline,
                            memo=f'順位{"-".join(map(str, picks["順位"]))} 距離{h.get("distance")}m')
            logs.append(f'{name}: 記録 本命{picks["本命"]} 対抗{picks["対抗"]}（締切{h["telvoteTime"]}）')
            try:  # 記事で失敗しても買い目の記録は残す
                write_article(day, place, race, program, picks)
            except Exception as e:
                logs.append(f"{name}: 記事作成に失敗（{e}）")
        except PermissionError as e:
            logs.append(f"{name}: 記録せず（{e}）")
    save_json("hold", "all", hold["date"][:10], 0, hold)
    return logs


if __name__ == "__main__":
    for line in run() or ["対象なし"]:
        print(line)
