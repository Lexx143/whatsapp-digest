#!/usr/bin/env python3
"""Мини-клиент Telegram Bot API: отправка дайджеста, определение chat_id.

Использование:
  python3 tg.py send --file digest.md [--hint]   # отправить текст в TELEGRAM_CHAT_ID
  python3 tg.py chat-id                          # показать чаты, где бота видно (getUpdates)
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from common import load_config

MAX_LEN = 4000  # лимит Telegram 4096, оставляем запас

HINT = "\n\n💬 Ответьте на это сообщение (reply), чтобы скорректировать следующие сводки."


def api(token: str, method: str, **params):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=60) as resp:
        payload = json.loads(resp.read())
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram {method}: {payload}")
    return payload["result"]


def split_chunks(text: str) -> list[str]:
    """Режет текст по строкам на куски <= MAX_LEN."""
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > MAX_LEN:  # аварийный случай: одна строка длиннее лимита
            chunks.append(current + line[:MAX_LEN])
            current, line = "", line[MAX_LEN:]
        if len(current) + len(line) > MAX_LEN:
            chunks.append(current)
            current = ""
        current += line
    if current.strip():
        chunks.append(current)
    return chunks or [""]


def cmd_send(cfg: dict, args) -> None:
    token, chat_id = cfg["TELEGRAM_BOT_TOKEN"], cfg["TELEGRAM_CHAT_ID"]
    text = Path(args.file).read_text() if args.file else sys.stdin.read()
    if not text.strip():
        raise SystemExit("Пустой текст — нечего отправлять")
    chunks = split_chunks(text.strip())
    if args.hint:
        chunks[-1] += HINT
    for chunk in chunks:
        api(token, "sendMessage", chat_id=chat_id, text=chunk)
    print(f"Отправлено сообщений: {len(chunks)}", file=sys.stderr)


def cmd_chat_id(cfg: dict) -> None:
    token = cfg["TELEGRAM_BOT_TOKEN"]
    me = api(token, "getMe")
    print(f"Бот: @{me['username']}")
    updates = api(token, "getUpdates", timeout=0)
    seen = {}
    for u in updates:
        msg = u.get("message") or u.get("my_chat_member") or {}
        chat = msg.get("chat")
        if chat:
            seen[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name")
    if not seen:
        print("Обновлений нет. Напишите любое сообщение в группу с ботом и повторите.")
    for cid, title in seen.items():
        print(f"chat_id: {cid}  — {title}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_send = sub.add_parser("send")
    p_send.add_argument("--file")
    p_send.add_argument("--hint", action="store_true", help="добавить подсказку про обратную связь")
    sub.add_parser("chat-id")
    args = ap.parse_args()

    cfg = load_config()
    if "TELEGRAM_BOT_TOKEN" not in cfg:
        raise SystemExit("Нет TELEGRAM_BOT_TOKEN в config.env")
    if args.cmd == "send":
        cmd_send(cfg, args)
    elif args.cmd == "chat-id":
        cmd_chat_id(cfg)
