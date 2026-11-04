"""AUTORACE.JP の出走表・レース結果を取得する。

公式ページが内部で使っている POST /race_info/Program と /race_info/RaceResult を呼ぶ。
パラメータ: placeCode（場コード）, raceDate（YYYY-MM-DD）, raceNo（R番号）
取得した生のJSONは data/ 以下に保存し、あとから何度でも集計できるようにする。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

BASE = "https://autorace.jp"
DATA_DIR = Path(__file__).parent / "data"

PLACES = {
    "funabashi": 1, "kawaguchi": 2, "isesaki": 3,
    "hamamatsu": 4, "iizuka": 5, "sanyou": 6,
}
PLACE_JA = {
    "kawaguchi": "川口", "isesaki": "伊勢崎", "hamamatsu": "浜松",
    "iizuka": "飯塚", "sanyou": "山陽", "funabashi": "船橋",
}
# 試走の服色（車番順）
COLORS = {1: "白", 2: "黒", 3: "赤", 4: "青", 5: "黄", 6: "緑", 7: "橙", 8: "桃"}


class AutoraceClient:
    def __init__(self, interval: float = 1.5):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "Mozilla/5.0 (autorace-yosou research)"})
        self.interval = interval  # 公式サイトに負荷をかけないための待ち時間
        self._token: str | None = None

    def _prepare(self, place: str, date: str, race: int, kind: str) -> None:
        """ページを一度開いてセッションとCSRFトークンを受け取る。"""
        page = "Program" if kind == "Program" else "RaceResult"
        r = self.s.get(f"{BASE}/race_info/{page}/{place}/{date}_{race}", timeout=20)
        r.raise_for_status()
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', r.text)
        self._token = m.group(1) if m else None

    def _post(self, kind: str, place: str, date: str, race: int) -> dict:
        self._prepare(place, date, race, kind)
        headers = {"X-Requested-With": "XMLHttpRequest",
                   "Referer": f"{BASE}/race_info/{kind}/{place}/{date}_{race}"}
        if self._token:
            headers["X-CSRF-TOKEN"] = self._token
        body = {"placeCode": PLACES[place], "raceDate": date, "raceNo": race}
        r = self.s.post(f"{BASE}/race_info/{kind}", json=body, headers=headers, timeout=20)
        r.raise_for_status()
        time.sleep(self.interval)
        data = r.json()
        if data.get("result") != "Success":
            raise RuntimeError(f"{kind} 取得失敗: {data.get('errors')}")
        return data["body"]

    def program(self, place: str, date: str, race: int, save: bool = True) -> dict:
        body = self._post("Program", place, date, race)
        if save:
            save_json("program", place, date, race, body)
        return body

    def result(self, place: str, date: str, race: int) -> dict:
        body = self._post("RaceResult", place, date, race)
        save_json("result", place, date, race, body)
        return body


def now_iso() -> str:
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")


def json_path(kind: str, place: str, date: str, race: int) -> Path:
    return DATA_DIR / kind / f"{date}_{place}_{race:02d}.json"


def save_json(kind, place, date, race, body) -> Path:
    p = json_path(kind, place, date, race)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = dict(body, _fetched_at=now_iso())
    p.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load_json(kind, place, date, race) -> dict | None:
    p = json_path(kind, place, date, race)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---------- 整形 ----------

def summarize_program(body: dict) -> list[dict]:
    """出走表を予想用の行にまとめる。"""
    rows = []
    for p in body["playerList"]:
        last3 = body.get("latest3List", {}).get(p["playerCode"], [])
        rows.append({
            "車": p["carNo"],
            "選手": p["playerName"].replace("　", " ").split()[0],  # 名字
            "フルネーム": p["playerName"].replace("　", " "),
            "所属": p["placeName"].replace("　", ""),
            "車級": f'{p["bikeClass"]}級',
            "ランク": p["rank"],
            "ハンデ": p["handicap"],
            "試走T": p.get("trialRunTime"),
            "再試走": bool(p.get("trialRetryCode")),
            "偏差": p.get("raceDev"),
            "2連率": p.get("rate2"),
            "3連率": p.get("rate3"),
            "欠車": bool(p.get("absent")),
            "直近3走": [
                {"日付": x["raceDate"], "場": x["placeName"].replace("　", ""),
                 "R": x["raceNo"], "着": x["order"], "競走T": x["raceTime"],
                 "試走T": x["trialTime"], "ST": x["stTime"],
                 "走路": x.get("situationCode")}
                for x in last3
            ],
        })
    return rows


def finish_order(body: dict) -> list[int]:
    return [r["carNo"] for r in sorted(
        (r for r in body["raceResult"] if r.get("order")), key=lambda r: r["order"])]


def trifecta_payouts(body: dict) -> dict[str, int]:
    """3連単の払戻（100円あたり）。同着などで複数ある場合もすべて返す。"""
    rt3 = (body.get("refundInfo") or {}).get("rt3") or {}
    out = {}
    for x in rt3.get("list", []):
        if x.get("refund") is None or not x.get("1thCarNo"):
            continue  # 中止・不成立などで払戻がない
        key = f'{x["1thCarNo"]}-{x["2thCarNo"]}-{x["3thCarNo"]}'
        out[key] = int(x["refund"])
    return out


def lap_positions(body: dict) -> list[dict]:
    """周回ごとの隊列（周回1が最初）。本走の追い上げ・前残りの記録用。"""
    laps = sorted(body.get("grandNoteList", []), key=lambda l: l["lapNo"])
    return [{"周回": l["lapNo"],
             "隊列": [int(r["carNo"]) for r in sorted(l["rankList"], key=lambda r: r["rank"])]}
            for l in laps]


def replay_urls(place: str, date: str, race: int) -> dict[str, str]:
    base = f"{BASE}/race_info/Ondemand/asx/{place}/{date}_{race}"
    return {"試走": base + "/1/1", "本走": base + "/0/1"}
