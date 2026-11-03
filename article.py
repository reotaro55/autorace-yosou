"""数値ルールの買い目から予想記事を作る。

型（チャッピーの記事を参考）
  🏁 タイトル（場名R＋短い中立的な言葉）
  🎯 中心：頭の選手と勝ち筋（ハンデ配置と試走T）
  🔥 相手：2・3着の主な相手と、その条件
  🔸 3着：残りの拾い目
  ⚠️ 懸念材料：本線が崩れる条件
  ✅ 本命 / 🔄 対抗 / ハッシュタグ

守ること
- 文章は買い目から作るので、記事で「拾う」と書いた選手は必ず買い目に入る
- 映像やコース取りなど、データにないことは書かない
- 「鉄板」「抜群の気配」などの断定、変動するオッズは書かない
- 着順の羅列はしない
"""
from __future__ import annotations

from autorace_api import PLACE_JA

CIRCLE = "⓪①②③④⑤⑥⑦⑧"


def _riders(program: dict) -> dict[int, dict]:
    out = {}
    for p in program["playerList"]:
        name = p["playerName"].replace("　", " ").split()
        out[p["carNo"]] = {"名字": name[0], "ハンデ": p["handicap"],
                           "試走T": p.get("trialRunTime"), "欠車": bool(p.get("absent"))}
    return out


def _c(n: int) -> str:
    return CIRCLE[n]


def build(place: str, race: int, program: dict, picks: dict) -> str:
    rd = {k: v for k, v in _riders(program).items() if not v["欠車"]}
    order = picks["順位"]
    honmei, taikou = picks["本命"], picks["対抗"]
    a = order[0]
    A = rd[a]
    who = lambda n: f"{_c(n)}{rd[n]['名字']}"  # noqa: E731
    line = lambda n: f"{rd[n]['ハンデ']}線"  # noqa: E731

    trials = sorted((float(v["試走T"]), k) for k, v in rd.items() if v["試走T"])
    fastest = trials[0][1] if trials else None
    min_h, max_h = min(v["ハンデ"] for v in rd.values()), max(v["ハンデ"] for v in rd.values())

    # 2・3着の相手は本命の買い目に出てくる順
    seen = []
    for combo in honmei:
        for x in map(int, combo.split("-")):
            if x != a and x not in seen:
                seen.append(x)
    partners = seen[:2]
    others = []
    for combo in honmei + taikou:
        for x in map(int, combo.split("-")):
            if x != a and x not in partners and x not in others:
                others.append(x)

    # タイトル
    title = f"🏁 {PLACE_JA[place]}{race}R｜{_c(a)}中心"

    # 中心
    t_note = f"試走{A['試走T']}" + ("は一番時計" if a == fastest else "")
    # 交わす必要がある相手：前のハンデの車と、同じハンデで内枠（車番が小さい）の車
    front = sorted([k for k, v in rd.items()
                    if v["ハンデ"] < A["ハンデ"] or (v["ハンデ"] == A["ハンデ"] and k < a)],
                   key=lambda k: (rd[k]["ハンデ"], k))
    if not front:
        center = (f"🎯 {who(a)}の先攻めから。{t_note}。{line(a)}から先手を取れれば、"
                  "後ろの仕掛けを待たずにペースを上げる形。")
    else:
        verb = "追い込み" if A["ハンデ"] == max_h else "抜け出し"
        fr = "".join(_c(k) for k in front)
        center = (f"🎯 {who(a)}の{verb}から。{t_note}。{line(a)}から{fr}を早めに交わせれば、"
                  "後ろの仕掛けを待たずにペースを上げる形。")

    # 相手
    sents = []
    for i, b in enumerate(partners):
        B = rd[b]
        if B["ハンデ"] > A["ハンデ"] and i == 0:
            sents.append(f"{_c(b)}は試走{B['試走T']}、{line(b)}から追い上げる間に{_c(a)}に離されると届かない。")
        elif B["ハンデ"] > A["ハンデ"]:
            sents.append(f"{_c(b)}は{line(b)}から試走{B['試走T']}。{_c(a)}の後ろで2着争いに加われるか。")
        elif B["ハンデ"] < A["ハンデ"]:
            sents.append(f"{_c(b)}は{line(b)}から先に出て、前で粘れるか。")
        else:
            sents.append(f"{_c(b)}は同じ{line(b)}。{_c(a)}より先に出られれば逆転まで。")
    rival = f"🔥 相手は{'と'.join(who(b) for b in partners)}。" + "".join(sents)

    # 3着
    third = ""
    if others:
        third = f"🔸 3着は{'、'.join(who(x) for x in others)}も拾い、{_c(partners[0])}との一本被りにはしない。"

    # 懸念材料：頭が後方なら前団の抵抗、頭が最前なら後方の追い上げ
    rear = max(partners, key=lambda k: (rd[k]["ハンデ"], -k))
    if front:
        worry = f"⚠️ {''.join(_c(k) for k in front)}の抵抗が長引けば、後方の{_c(rear)}が届く展開まで。"
    else:
        worry = f"⚠️ 後方{_c(rear)}の追い上げが早ければ、逆転まで。"

    body = [title, "", center, "", rival]
    if third:
        body += ["", third]
    body += ["", worry, "", "✅ 本命", *honmei, "", "🔄 対抗", *taikou, "",
             f"#{PLACE_JA[place]}オート #オートレース予想"]
    text = "\n".join(body)
    _check(text, honmei + taikou)
    return text


def _check(text: str, combos: list[str]) -> None:
    """記事に出てきた車番がすべて買い目に入っているか確認する（前団の説明は除く）。"""
    bought = {int(x) for c in combos for x in c.split("-")}
    for line in text.splitlines():
        if line.startswith(("🔥", "🔸")):
            for i, ch in enumerate(CIRCLE):
                if ch in line and i not in bought:
                    raise AssertionError(f"記事で拾った{ch}が買い目に入っていない")
    for ng in ("鉄板", "抜群", "オッズ"):
        if ng in text:
            raise AssertionError(f"使わない言葉が入っている: {ng}")
