"""数値ルールで買い目を作る。ルールは rules/vN.json に版ごとに固定して置く。

考え方（v1）
  見込み競走T = 試走T + 偏差 × dev_weight / 1000
    （偏差は「良走路10走の平均試走Tと平均競走Tの差」。093 なら 0.093 秒）
  見込み走破時間 = (距離 + ハンデ) / 100 × 見込み競走T
  走破時間が短い順に A, B, C, D … とし、テンプレート（A-B-C など）を車番に置き換える
"""
from __future__ import annotations

import json
from pathlib import Path

RULES_DIR = Path(__file__).parent / "rules"


def current_rule() -> dict:
    """版番号が一番新しいルール（v1, v2 … の数字で比較）。"""
    files = sorted(RULES_DIR.glob("v*.json"), key=lambda p: int(p.stem[1:]))
    return json.loads(files[-1].read_text(encoding="utf-8"))


def load_rule(version: str) -> dict:
    return json.loads((RULES_DIR / f"{version}.json").read_text(encoding="utf-8"))


def avg_st(program: dict, player_code: str) -> float | None:
    """近10走の平均ST。記録が3走未満なら None。"""
    sts = []
    for x in (program.get("latest10List") or {}).get(player_code, []):
        try:
            v = float(x.get("stTime") or 0)
        except ValueError:
            continue
        if v > 0:
            sts.append(v)
    return round(sum(sts) / len(sts), 3) if len(sts) >= 3 else None


def all_rules() -> list[dict]:
    files = sorted(RULES_DIR.glob("v*.json"), key=lambda p: int(p.stem[1:]))
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def rank(program: dict, rule: dict, distance: int | None = None) -> list[dict]:
    dist = distance or rule["default_distance"]
    stw = rule.get("st_weight", 0.0)
    active = [p for p in program["playerList"] if not (p.get("absent") or p.get("retireFlag"))]
    st = {p["carNo"]: avg_st(program, p.get("playerCode", "")) for p in active}
    known = [v for v in st.values() if v is not None]
    st_mean = sum(known) / len(known) if known else 0.0
    rows = []
    for p in program["playerList"]:
        if p.get("absent") or p.get("retireFlag"):
            continue
        t = p.get("trialRunTime")
        if not t:
            raise ValueError(f'{p["carNo"]}号車の試走タイムがまだ出ていない')
        dev = p.get("raceDev")
        exp = float(t) + (float(dev) / 1000 * rule["dev_weight"] if dev else 0.0)
        s_avg = st[p["carNo"]] if st[p["carNo"]] is not None else st_mean
        total = (dist + p["handicap"]) / 100 * exp + stw * s_avg
        rows.append({"車": p["carNo"], "見込み競走T": round(exp, 3),
                     "見込み走破時間": round(total, 2), "偏差なし": not dev,
                     "平均ST": st[p["carNo"]]})
    return sorted(rows, key=lambda r: (r["見込み走破時間"], r["車"]))


def make_picks(program: dict, rule: dict, distance: int | None = None) -> dict:
    order = [r["車"] for r in rank(program, rule, distance)]
    letters = {chr(ord("A") + i): str(c) for i, c in enumerate(order)}

    def conv(templates):
        out = []
        for t in templates:
            parts = t.split("-")
            if all(x in letters for x in parts):
                out.append("-".join(letters[x] for x in parts))
        return out

    honmei = conv(rule["honmei"])
    taikou = [c for c in conv(rule["taikou"]) if c not in honmei]
    return {"本命": honmei, "対抗": taikou, "順位": order, "ルール": rule["version"]}
