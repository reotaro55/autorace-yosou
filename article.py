"""数値ルールの買い目から予想記事を作る。

型（チャッピーの記事を参考）
  🏁 タイトル（場名R＋短い中立的な言葉）
  🎯 頭の選手と勝ち筋（ハンデ配置と試走T）
  🔥 2・3着の主な相手と、その条件
  🔸 押さえと、本線が崩れる条件
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


def build(place: str, race: int, program: dict, picks: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    rd = {k: v for k, v in _riders(program).items() if not v["欠車"]}
    order = picks["順位"]
    honmei, taikou = picks["本命"], picks["対抗"]
    a = order[0]
    A = rd[a]
    who = lambda n: f"{_c(n)}{rd[n]['名字']}"  # noqa: E731
    line = lambda n: f"{rd[n]['ハンデ']}線"  # noqa: E731
    cs = lambda ns: "".join(_c(n) for n in ns)  # noqa: E731

    trials = sorted((float(v["試走T"]), k) for k, v in rd.items() if v["試走T"])
    fastest = trials[0][1] if trials else None
    min_h, max_h = min(v["ハンデ"] for v in rd.values()), max(v["ハンデ"] for v in rd.values())
    all_same = min_h == max_h  # 全車同ハン（枠なり発走）

    # 2・3着の相手は本命の買い目に出てくる順、押さえは残り
    partners, others = [], []
    for combo in honmei:
        for x in map(int, combo.split("-")):
            if x != a and x not in partners:
                partners.append(x)
    partners = partners[:2]
    for combo in honmei + taikou:
        for x in map(int, combo.split("-")):
            if x != a and x not in partners and x not in others:
                others.append(x)

    # 前にいて交わす必要がある車：前のハンデの車と、同じハンデで内枠の車
    front = sorted([k for k, v in rd.items()
                    if v["ハンデ"] < A["ハンデ"] or (v["ハンデ"] == A["ハンデ"] and k < a)],
                   key=lambda k: (rd[k]["ハンデ"], k))
    grp = lambda cars, label: cs(cars) if len(cars) <= 3 else label  # noqa: E731

    # タイトル：場名R＋開催日の言葉（中立的に）
    day = meta.get("day_label", "")
    title = f"🏁 {PLACE_JA[place]}{race}R｜" + (f"{day}の初戦" if day and race == 1 else (day or "展開予想"))

    # ① 頭の選手と勝ち筋
    fast = a == fastest
    if not front:
        lead = "最内から" if all_same else f"{line(a)}から"
        p1 = (f"🎯 {who(a)}の先行から。{lead}先に出れば、そのまま押し切る形。"
              f"試走{A['試走T']}" + ("は一番時計。" if fast else "。"))
    elif all_same:
        n = max(rd)
        pos = "大外" if a == n else ("外枠" if a > n / 2 else "中枠")
        p1 = (f"🎯 {who(a)}は{pos}から。試走{A['試走T']}" + ("の一番時計でも" if fast else "でも") +
              f"、内の{grp(front, '車')}をまとめて交わせるとは限らない。立ち上がりで好位を取れれば、早めに抜け出す形。")
    else:
        verb = "追い込み" if A["ハンデ"] == max_h else "抜け出し"
        p1 = (f"🎯 {who(a)}の{verb}から。{line(a)}から{grp(front, '前団')}を早めに捌ければ、"
              f"後ろを待たずにペースを上げる形。試走{A['試走T']}" + ("は一番時計。" if fast else "。"))

    # ② 相手
    cl = []
    for i, b in enumerate(partners):
        B = rd[b]
        place_from = "内枠から" if B["ハンデ"] == A["ハンデ"] else f"{line(b)}から"
        if b in front:
            cl.append(f"{_c(b)}は{place_from}先に出て、{_c(a)}の攻めをしのげば逆転まで。" if i == 0
                      else f"{_c(b)}も前で粘れば2着争い。")
        elif B["ハンデ"] > A["ハンデ"]:
            cl.append(f"{_c(b)}は{line(b)}から追う形で、{_c(a)}に離されなければ届く。" if i == 0
                      else f"{_c(b)}は試走{B['試走T']}、後方から2着争いに加われるか。")
        else:
            cl.append(f"{_c(b)}は{_c(a)}の後ろを追走する形。")
    p2 = f"🔥 相手は{'と'.join(who(b) for b in partners)}。" + "".join(cl)

    # ③ 押さえと崩れる条件（ここに出す車はすべて買い目に入っている）
    ahead = [k for k in partners if k in front]
    behind = [k for k in partners if rd[k]["ハンデ"] > A["ハンデ"]]
    if front and ahead:
        worry = f"{_c(a)}が捌きに手間取れば、{cs(ahead)}の前残りまで。"
    elif behind:
        far = max(behind, key=lambda k: (rd[k]["ハンデ"], k))
        worry = f"{_c(a)}の抜け出しが遅れれば、{_c(far)}の逆転まで。"
    else:
        worry = f"{_c(a)}が先手を取れなければ、{cs(partners)}の逆転まで。"
    keep = f"{'、'.join(who(x) for x in others)}の残りも押さえ、{_c(partners[0])}との一本被りにはしない。" if others else ""
    p3 = f"🔸 {keep}{worry}"

    tags = [f"#{PLACE_JA[place]}オート", "#オートレース予想"] + ([f"#{meta['tag']}"] if meta.get("tag") else [])
    body = [title, "", p1, "", p2, "", p3, "", "✅ 本命", *honmei, "", "🔄 対抗", *taikou, "", " ".join(tags)]
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
