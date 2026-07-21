"""Общие настройки whatsapp-digest."""
import os
from pathlib import Path

# Каталог данных (state, memory, digests, work, logs, config.env) — вне git.
DATA_DIR = Path(os.environ.get("WA_DIGEST_DATA", Path.home() / ".whatsapp-digest"))

CONTAINER = Path.home() / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared"

# Целевые чаты: стабильный JID → человекочитаемое название.
# Реальный список хранится вне репозитория, в <DATA_DIR>/chats.json:
#   {"1203...@g.us": "Группа «Менеджмент»", "7700...@s.whatsapp.net": "Личка с руководителем"}
# Как найти JID своих чатов — см. HANDOFF.md, раздел «Установка».
import json as _json

_chats_file = DATA_DIR / "chats.json"
if _chats_file.exists():
    CHATS = _json.loads(_chats_file.read_text())
else:
    CHATS = {
        "REPLACE_ME@g.us": "Группа «Менеджмент» (замените на свои JID в chats.json)",
    }


def load_config() -> dict:
    """Читает config.env (KEY=VALUE) из каталога данных."""
    cfg = {}
    path = DATA_DIR / "config.env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                cfg[key.strip()] = value.strip().strip('"').strip("'")
    return cfg
