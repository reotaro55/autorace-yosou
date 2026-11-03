import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import autopick  # noqa: E402
import strategy  # noqa: E402

PROG = json.loads((Path(__file__).parent / "fixture_program_kawaguchi_2026-11-02_08.json").read_text(encoding="utf-8"))


def test_rank_and_picks():
    rule = strategy.load_rule("v1")
    ranked = strategy.rank(PROG, rule, 3100)
    # ③: (3100+10)/100 × (3.68+0.093) = 117.34
    top = ranked[0]
    assert top["車"] == 3 and top["見込み走破時間"] == pytest.approx(31.10 * 3.773, abs=0.01)
    p = strategy.make_picks(PROG, rule, 3100)
    assert len(p["本命"]) == 3 and len(p["対抗"]) == 3
    assert len(set(p["本命"] + p["対抗"])) == 6
    assert p["本命"][0].startswith("3-")


def test_missing_trial_waits():
    prog = json.loads(json.dumps(PROG))
    prog["playerList"][0]["trialRunTime"] = None
    with pytest.raises(ValueError):
        strategy.make_picks(prog, strategy.load_rule("v1"))


def test_absent_skipped():
    prog = json.loads(json.dumps(PROG))
    prog["playerList"][2]["absent"] = 1
    order = strategy.make_picks(prog, strategy.load_rule("v1"))["順位"]
    assert 3 not in order and len(order) == 6


def test_dates():
    h = {"periodStartDate": "2026-11-01", "paragraphday": 3}
    assert autopick.race_date(h) == "2026-11-03"
    assert autopick.deadline_iso("2026-11-03", "18:48") == "2026-11-03T18:48:00+09:00"
    assert autopick.deadline_iso("2026-11-03", "24:35") == "2026-11-04T00:35:00+09:00"


def test_article_matches_picks():
    import article
    p = strategy.make_picks(PROG, strategy.load_rule("v1"), 3100)
    text = article.build("kawaguchi", 8, PROG, p)
    assert text.startswith("🏁川口8R｜展開予想")
    assert "①②を早めに捌ければ" in text  # 同じ10線の内枠②も交わす相手に入る
    for combo in p["本命"] + p["対抗"]:
        assert combo in text
    for ng in ("鉄板", "抜群", "オッズ", "外のコース"):
        assert ng not in text


def test_article_all_cases():
    """全車を順番に頭にして、記事生成が破綻しないか確認する。"""
    import article
    import copy
    for car in range(1, 8):
        prog = copy.deepcopy(PROG)
        for pl in prog["playerList"]:
            if pl["carNo"] == car:
                pl["trialRunTime"] = "3.20"
        p = strategy.make_picks(prog, strategy.load_rule("v1"), 3100)
        assert p["順位"][0] == car
        article.build("kawaguchi", 8, prog, p)


def test_discord_skips_without_url(monkeypatch):
    import notify
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    assert notify.discord("test") is None


def test_article_same_handicap():
    """全車同ハン（枠なり）のレースで、状況に合わない言い回しが出ないこと。"""
    import article
    import copy
    prog = copy.deepcopy(PROG)
    for pl in prog["playerList"]:
        pl["handicap"] = 0
    prog["playerList"][6]["trialRunTime"] = "3.20"  # ⑦を頭に
    p = strategy.make_picks(prog, strategy.load_rule("v1"), 3100)
    text = article.build("hamamatsu", 1, prog, p)
    assert "大外から" in text and "まとめて交わせるとは限らない" in text and "相手筆頭" in text
    assert "追い込み" not in text and "後方の" not in text
    assert "①②③④⑤⑥" not in text and "前団" not in text
