#!/usr/bin/env python3
"""Сбор обратной связи из Telegram в memory/feedback.md.

Забирает новые апдейты (offset хранится в state/tg_offset). Обратной связью
считаются: ответы (reply) на сообщения бота и сообщения с упоминанием
@бота. При FEEDBACK_ALL=1 в config.env — любые сообщения людей в целевом чате.
"""
import sys
from datetime import datetime
from pathlib import Path

from common import DATA_DIR, load_config
from tg import api

OFFSET_PATH = DATA_DIR / "state" / "tg_offset"
FEEDBACK_PATH = DATA_DIR / "memory" / "feedback.md"


def main():
    cfg = load_config()
    token = cfg.get("TELEGRAM_BOT_TOKEN")
    chat_id = cfg.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram не настроен — пропускаю сбор обратной связи", file=sys.stderr)
        return

    offset = int(OFFSET_PATH.read_text()) if OFFSET_PATH.exists() else None
    me = api(token, "getMe")
    bot_id, bot_username = me["id"], me["username"].lower()
    updates = api(token, "getUpdates", offset=offset, timeout=0)

    collected = []
    max_update_id = None
    for u in updates:
        max_update_id = u["update_id"]
        msg = u.get("message")
        if not msg or not msg.get("text"):
            continue
        if str(msg["chat"]["id"]) != str(chat_id):
            continue
        author = msg.get("from", {})
        if author.get("is_bot"):
            continue
        reply_to_bot = (msg.get("reply_to_message", {}).get("from", {}).get("id") == bot_id)
        mentions_bot = f"@{bot_username}" in msg["text"].lower()
        if not (reply_to_bot or mentions_bot or cfg.get("FEEDBACK_ALL") == "1"):
            continue
        name = " ".join(filter(None, [author.get("first_name"), author.get("last_name")])) or author.get("username", "?")
        date = datetime.fromtimestamp(msg["date"]).strftime("%Y-%m-%d %H:%M")
        text = msg["text"].replace(f"@{me['username']}", "").strip()
        collected.append(f"- [{date}] {name}: {text}")

    if collected:
        FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        header = "" if FEEDBACK_PATH.exists() else "# Обратная связь на дайджесты\n\n"
        with FEEDBACK_PATH.open("a") as f:
            f.write(header + "\n".join(collected) + "\n")
        print(f"Собрано отзывов: {len(collected)}", file=sys.stderr)
    else:
        print("Новой обратной связи нет", file=sys.stderr)

    if max_update_id is not None:
        OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
        OFFSET_PATH.write_text(str(max_update_id + 1))


if __name__ == "__main__":
    main()
