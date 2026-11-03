"""Discord への投稿。Webhook の URL は GitHub の Secrets（DISCORD_WEBHOOK_URL）から読む。
URL が設定されていなければ何もしない。URL はコードやログに出さない。
"""
from __future__ import annotations

import os

import requests

LIMIT = 2000  # Discord の1メッセージの上限文字数


def discord(text: str) -> bool:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        return False
    chunks = [text[i:i + LIMIT] for i in range(0, len(text), LIMIT)] or [""]
    for c in chunks:
        r = requests.post(url, json={"content": c, "allowed_mentions": {"parse": []}}, timeout=15)
        if r.status_code >= 300:
            raise RuntimeError(f"Discord への投稿に失敗（HTTP {r.status_code}）")
    return True
