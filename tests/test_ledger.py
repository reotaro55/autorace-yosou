import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import autorace_api  # noqa: E402
import ledger  # noqa: E402

FIX = Path(__file__).parent / "fixture_result_kawaguchi_2026-11-02_08.json"


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setattr(autorace_api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ledger, "LEDGER", tmp_path / "picks.csv")
    yield tmp_path


def put_result(tmp, fetched_at="2099-01-01T00:00:00+09:00", payouts=True):
    """記録より後に結果を取得した、という状態を作る。"""
    p = tmp / "result" / "2026-11-02_kawaguchi_08.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    body = json.loads(FIX.read_text(encoding="utf-8"))
    body["_fetched_at"] = fetched_at
    if not payouts:
        body["refundInfo"] = {}
    p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def test_late_record_excluded(tmp_data):
    # 結果を取得した時刻より後に書かれた行（手で台帳を書き換えた場合など）は集計しない
    ledger.add_pick("2026-11-02", "kawaguchi", 8, "3-6-7")
    put_result(tmp_data, fetched_at="2000-01-01T00:00:00+09:00")
    ev = ledger.evaluate()
    assert ev[0].status == "集計外"


def test_parse_result():
    body = json.loads(FIX.read_text(encoding="utf-8"))
    assert autorace_api.finish_order(body)[:3] == [3, 6, 7]
    assert autorace_api.trifecta_payouts(body) == {"3-6-7": 4360}
    assert autorace_api.lap_positions(body)[0]["隊列"] == [1, 3, 2, 4, 5, 7, 6]


def test_hit_and_miss_and_lock(tmp_data, monkeypatch):
    # 結果取得前に記録 → 的中扱い
    ledger.add_pick("2026-11-02", "kawaguchi", 8, "3-6-7,3-7-6,6-3-7", "3-4-6,3-6-4,6-7-3")
    put_result(tmp_data)
    ev = ledger.evaluate()
    assert ev[0].status == "的中" and ev[0].payout == 4360 and ev[0].stake == 600
    s = ledger.summary(ev, "裁量")
    assert s["回収率%"] == round(4360 / 600 * 100, 1)
    # 結果取得後の記録・変更は拒否
    with pytest.raises(PermissionError):
        ledger.add_pick("2026-11-02", "kawaguchi", 8, "3-6-7", reason="後出し")


def test_change_needs_reason(tmp_data):
    ledger.add_pick("2026-11-02", "kawaguchi", 8, "3-6-7")
    with pytest.raises(PermissionError):
        ledger.add_pick("2026-11-02", "kawaguchi", 8, "6-3-7")
    ledger.add_pick("2026-11-02", "kawaguchi", 8, "6-3-7", reason="⑥の進出を反映、3-6-7は残せる根拠なし")
    put_result(tmp_data)
    ev = ledger.evaluate()
    assert len(ev) == 1 and ev[0].status == "不的中"  # 変更後の最終買い目で判定
    assert len(ledger._rows()) == 2  # 変更前の行も残っている


def test_missing_payout_not_counted(tmp_data):
    ledger.add_pick("2026-11-02", "kawaguchi", 8, "3-6-7")
    put_result(tmp_data, payouts=False)
    ev = ledger.evaluate()
    assert ev[0].status == "払戻未確認"
    assert ledger.summary(ev)["対象レース"] == 0


def test_skip_and_kinds(tmp_data):
    ledger.add_pick("2026-11-02", "kawaguchi", 8, "", state="見送り")
    ledger.add_pick("2026-11-02", "kawaguchi", 8, "3-6-7", kind="数値")
    put_result(tmp_data)
    ev = ledger.evaluate()
    assert ledger.summary(ev, "裁量")["見送り"] == 1
    assert ledger.summary(ev, "数値")["的中"] == 1


def test_bad_combo():
    with pytest.raises(ValueError):
        ledger.add_pick("2026-11-03", "kawaguchi", 1, "3-3-7")
