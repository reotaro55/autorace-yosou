"""使い方（例）
  出走表:   python cli.py program kawaguchi 2026-11-03 8
  結果取得: python cli.py result  kawaguchi 2026-11-03 8
  その日の結果をまとめて取得: python cli.py results kawaguchi 2026-11-03 1-12
  買い目記録: python cli.py pick kawaguchi 2026-11-03 8 --honmei "3-6-7,3-7-6,6-3-7" --taikou "6-7-3,7-3-6,3-6-4"
  買い目変更: 上に --reason "追加の根拠／削る根拠" を付けて同じコマンド
  見送り:   python cli.py pick kawaguchi 2026-11-03 8 --skip
  検証集計: python cli.py report
"""
import argparse
import json
import sys

import ledger
from autorace_api import (COLORS, PLACE_JA, AutoraceClient, finish_order, lap_positions,
                          load_json, replay_urls, summarize_program, trifecta_payouts)


def show_program(place, date, race, body):
    print(f"■{PLACE_JA[place]}{race}R 出走表（{date}）")
    print("車 選手        車級 ハンデ 試走T  偏差 2連率/3連率 | 直近3走（着/試走T/競走T/ST）")
    for r in summarize_program(body):
        recent = " ".join(f'{x["着"]}着/{x["試走T"]}/{x["競走T"]}/{x["ST"]}' for x in r["直近3走"])
        flag = " 欠車" if r["欠車"] else (" 再試走" if r["再試走"] else "")
        print(f'{r["車"]}({COLORS[r["車"]]}) {r["フルネーム"]:<8} {r["車級"]} {r["ハンデ"]:>3}m '
              f'{r["試走T"] or "-":>5} {r["偏差"] or "-":>4} {r["2連率"]}/{r["3連率"]}{flag} | {recent}')
    u = replay_urls(place, date, race)
    print(f'試走リプレイ: {u["試走"]}\n本走リプレイ: {u["本走"]}')


def show_result(place, date, race, body):
    order = finish_order(body)
    pays = trifecta_payouts(body)
    print(f"■{PLACE_JA[place]}{race}R 結果 着順: {'-'.join(map(str, order))}")
    print("3連単払戻: " + (", ".join(f"{k} {v:,}円" for k, v in pays.items()) or "未確認"))
    for lap in lap_positions(body):
        print(f'  周回{lap["周回"]}: {"-".join(map(str, lap["隊列"]))}')


def parse_races(spec: str) -> list[int]:
    if "-" in spec:
        a, b = spec.split("-")
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in spec.split(",")]


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("program", "result"):
        p = sub.add_parser(c)
        p.add_argument("place"); p.add_argument("date"); p.add_argument("race", type=int)
        p.add_argument("--json", action="store_true")
        p.add_argument("--cached", action="store_true", help="保存済みのデータを表示")
    p = sub.add_parser("results")
    p.add_argument("place"); p.add_argument("date"); p.add_argument("races")
    p = sub.add_parser("pick")
    p.add_argument("place"); p.add_argument("date"); p.add_argument("race", type=int)
    p.add_argument("--honmei", default=""); p.add_argument("--taikou", default="")
    p.add_argument("--kind", default="裁量", choices=ledger.KINDS)
    p.add_argument("--unit", type=int, default=100)
    p.add_argument("--actual", default="", help="実際に買った金額（検証とは別に記録）")
    p.add_argument("--skip", action="store_true", help="見送り")
    p.add_argument("--reason", default=""); p.add_argument("--memo", default="")
    sub.add_parser("report")
    p = sub.add_parser("article", help="保存済みの出走表から数値ルールの記事を作る")
    p.add_argument("place"); p.add_argument("date"); p.add_argument("race", type=int)
    p.add_argument("--distance", type=int, default=None)
    sub.add_parser("fill", help="台帳にあって結果が未取得のレースだけ結果を取りに行く")
    a = ap.parse_args(argv)

    if a.cmd in ("program", "result"):
        body = load_json(a.cmd, a.place, a.date, a.race) if a.cached else \
            getattr(AutoraceClient(), a.cmd)(a.place, a.date, a.race)
        if body is None:
            sys.exit("保存済みデータなし")
        if a.json:
            print(json.dumps(body, ensure_ascii=False, indent=1))
        else:
            (show_program if a.cmd == "program" else show_result)(a.place, a.date, a.race, body)
    elif a.cmd == "results":
        cl = AutoraceClient()
        for r in parse_races(a.races):
            try:
                show_result(a.place, a.date, r, cl.result(a.place, a.date, r))
            except Exception as e:  # 未確定・中止など
                print(f"{r}R 取得できず: {e}")
    elif a.cmd == "pick":
        row = ledger.add_pick(a.date, a.place, a.race, a.honmei, a.taikou, a.kind, a.unit,
                              a.actual, "見送り" if a.skip else "有効", a.reason, a.memo)
        print("記録:", row)
    elif a.cmd == "report":
        print(ledger.format_report(ledger.evaluate()))
    elif a.cmd == "article":
        import article
        import strategy
        prog = load_json("program", a.place, a.date, a.race) or AutoraceClient().program(a.place, a.date, a.race)
        print(article.build(a.place, a.race, prog, strategy.make_picks(prog, strategy.current_rule(), a.distance)))
    elif a.cmd == "fill":
        todo = sorted({(r["場"], r["日付"], int(r["R"])) for r in ledger._rows()
                       if load_json("result", r["場"], r["日付"], int(r["R"])) is None})
        cl = AutoraceClient()
        for place, date, race in todo:
            try:
                show_result(place, date, race, cl.result(place, date, race))
            except Exception as e:  # まだ確定していないレースなど
                print(f"{PLACE_JA[place]}{race}R({date}) 未確定または取得できず: {e}")
        print(ledger.format_report(ledger.evaluate()))


if __name__ == "__main__":
    main()
