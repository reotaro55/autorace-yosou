"""数値ルールの買い目から予想記事を作る。

型（チャッピーの記事を参考）
  🏁 タイトル（場名R＋短い中立的な言葉）
  頭の選手と勝ち筋（ハンデ配置と試走T）
  相手筆頭と、2人目の出番の条件
  3着の押さえと、本線が崩れる条件
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


def avg_st(program: dict, player_code: str) -> float | None:
    """近10走の平均ST。記録が3走未満なら判断材料にしない（None）。"""
    sts = []
    for x in (program.get("latest10List") or {}).get(player_code, []):
        try:
            v = float(x.get("stTime") or 0)
        except ValueError:
            continue
        if v > 0:
            sts.append(v)
    return round(sum(sts) / len(sts), 2) if len(sts) >= 3 else None


def _riders(program: dict) -> dict[int, dict]:
    out = {}
    for p in program["playerList"]:
        name = p["playerName"].replace("　", " ").split()
        out[p["carNo"]] = {"名字": name[0], "ハンデ": p["handicap"],
                           "試走T": p.get("trialRunTime"), "欠車": bool(p.get("absent")),
                           "ST": avg_st(program, p.get("playerCode", ""))}
    return out


def _c(n: int) -> str:
    return CIRCLE[n]


def build(place: str, race: int, program: dict, picks: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    v = race % 2  # 言い回しの切り替え
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
    title = f"🏁{PLACE_JA[place]}{race}R｜" + ((f"{day}の初戦" if race == 1 else f"{day}の一戦") if day else "展開予想")

    fast = a == fastest
    t_fast = f"試走{A['試走T']}は一番時計。" if fast else ""
    heads = {int(c.split("-")[0]) for c in honmei + taikou}
    fl = "内枠勢" if all_same else "前団"

    # ① 頭の選手と勝ち筋
    if not front:
        if all_same:
            p1 = f"{who(a)}の先行から。最内を生かして先手を取り、後続に内を渡さず押し切る形を狙う。{t_fast}"
        else:
            p1 = (f"{who(a)}の先行から。{line(a)}から先手を取り、後続に並ばせず押し切る形を狙う。{t_fast}")
    elif all_same:
        n = max(rd)
        pos = "大外" if a == n else ("外枠" if a > n / 2 else "中枠")
        p1 = (f"{who(a)}は{pos}からどこまで出られるか。試走{A['試走T']}" + ("の一番時計でも" if fast else "でも") +
              f"、内の{grp(front, '車')}をまとめて交わせるとは限らない。" +
              ("立ち上がりで好位を取れれば、早めに抜け出す形。" if v == 0
               else "前を早めに捌ければ、後ろの仕掛けを待たずにペースを上げる形。"))
    else:
        verb = "追い込み" if A["ハンデ"] == max_h else "抜け出し"
        p1 = (f"{who(a)}の{verb}から。{line(a)}から{grp(front, '前団')}を早めに捌ければ、"
              f"後ろを待たずにペースを上げる形。{t_fast}")

    # スタート：近10走の平均STで、頭の出足を一言添える（STだけで隊列は決めつけない）
    sts = sorted(v["ST"] for v in rd.values() if v["ST"] is not None)
    if A["ST"] is not None and len(sts) >= 3:
        good = A["ST"] <= sts[1]  # 上位2番目以内
        st = f"近10走の平均ST{A['ST']:.2f}"
        if not front:
            p1 += (f"{st}と出足もあり、内の先手は譲りにくい。" if good
                   else f"{st}とスタートは目立たず、出遅れれば後続に並ばれる。")
        else:
            p1 += (f"{st}と出足があり、序盤から前との差を詰められる。" if good
                   else f"{st}とスタートは平凡。序盤で前に離されると捌きに手間取る。")

    # ② 相手：筆頭と、出番の条件つきの2人目
    b, c = partners[0], (partners[1] if len(partners) > 1 else None)
    B = rd[b]
    if b in front:
        pos_b = "内枠" if B["ハンデ"] == A["ハンデ"] else line(b)
        sb = (f"{pos_b}から先に出て、{_c(a)}の攻めをしのげば逆転まで。" if v == 0
              else f"{pos_b}を生かして{_c(a)}より先に出られれば逆転まで。")
    elif B["ハンデ"] > A["ハンデ"]:
        sb = f"{line(b)}から追う形で、{_c(a)}に離されなければ届く。"
    else:
        sb = (f"{_c(a)}が抜け出す前に好位へ付け、早めに射程へ入れれば" +
              ("逆転まで。" if b in heads else "2着は堅く争う。"))
    p2 = f"相手筆頭は{who(b)}。{sb}"
    if b in front and B["ST"] is not None and A["ST"] is not None and B["ST"] <= A["ST"] - 0.02:
        p2 += f"平均ST{B['ST']:.2f}と出足は{_c(a)}より上。"
    if c:
        C = rd[c]
        if c in front:
            p2 += f"{who(c)}も前で粘れば2着争い。"
        elif C["ハンデ"] > A["ハンデ"]:
            p2 += f"{who(c)}は{line(c)}から試走{C['試走T']}。後方からどこまで詰められるか。"
        else:
            p2 += f"{who(c)}は道中の捲りでどこまで進出できるか。{_c(a)}{_c(b)}の争いが長引けば出番。"

    # ③ 押さえと、本線が崩れる条件
    ahead = [k for k in partners if k in front]
    behind = [k for k in partners if rd[k]["ハンデ"] > A["ハンデ"]]
    if front and behind:
        far = max(behind, key=lambda k: (rd[k]["ハンデ"], k))
        worry = f"{grp(front, fl)}の抵抗が長引けば、後方の{_c(far)}が届く展開まで。"
    elif front and ahead:
        worry = f"{_c(a)}が捌きに手間取れば、{cs(ahead)}の前残りまで。"
    else:
        worry = f"まずは{cs([a] + partners)}を中心に組む。"
    keep = f"{'、'.join(who(x) for x in others)}は3着の押さえ。" if others else ""
    p3 = keep + worry

    tags = [f"#{PLACE_JA[place]}オート", "#オートレース予想"] + ([f"#{meta['tag']}"] if meta.get("tag") else [])
    body = [title, "", p1, "", p2, "", p3, "", "✅本命", *honmei, "", "🔄対抗", *taikou, "", " ".join(tags)]
    text = "\n".join(body)
    _check(text, honmei + taikou, [a] + partners + others)
    return text


def _check(text: str, combos: list[str], picked: list[int]) -> None:
    """記事で相手・押さえとして名前を出した車が、すべて買い目に入っているか確認する。"""
    bought = {int(x) for c in combos for x in c.split("-")}
    for n in picked:
        if n not in bought:
            raise AssertionError(f"記事で拾った{CIRCLE[n]}が買い目に入っていない")
    for ng in ("鉄板", "抜群", "オッズ"):
        if ng in text:
            raise AssertionError(f"使わない言葉が入っている: {ng}")
