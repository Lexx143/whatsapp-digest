#!/usr/bin/env python3
"""Извлечение сообщений целевых чатов из локальной базы WhatsApp (macOS).

Читает копию ChatStorage.sqlite (чтобы не мешать работающему WhatsApp),
разрешает имена отправителей через адресную книгу и push-имена,
выводит JSON с сообщениями за окно анализа.

Окно по умолчанию: с момента прошлого успешного запуска (state/last_run)
до текущего момента; при первом запуске — последние 25 часов.
"""
import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from common import DATA_DIR, CONTAINER, CHATS

CHAT_DB = CONTAINER / "ChatStorage.sqlite"
CONTACTS_DB = CONTAINER / "ContactsV2.sqlite"
MEDIA_BASE = CONTAINER / "Message"
APPLE_EPOCH = 978307200  # Core Data: секунды от 2001-01-01

MSG_TYPES = {
    0: None,  # текст
    1: "изображение",
    2: "видео",
    3: "голосовое",
    4: "контакт",
    5: "геолокация",
    7: "ссылка",
    8: "документ",
    11: "gif",
    14: "удалённое сообщение",
    15: "стикер",
}


def copy_db(src: Path, tmpdir: Path) -> Path:
    """Копирует sqlite-базу вместе с -wal/-shm, чтобы читать согласованный снимок."""
    dst = tmpdir / src.name
    shutil.copy2(src, dst)
    for suffix in ("-wal", "-shm"):
        side = src.with_name(src.name + suffix)
        if side.exists():
            shutil.copy2(side, tmpdir / side.name)
    return dst


def load_names(tmpdir: Path) -> dict:
    """JID → имя: адресная книга (приоритет), затем push-имена WhatsApp."""
    names = {}
    con = sqlite3.connect(f"file:{copy_db(CONTACTS_DB, tmpdir)}?mode=ro", uri=True)
    try:
        for full, wa_jid, lid in con.execute(
            "SELECT ZFULLNAME, ZWHATSAPPID, ZLID FROM ZWAADDRESSBOOKCONTACT WHERE ZFULLNAME IS NOT NULL"
        ):
            for jid in (wa_jid, lid):
                if jid:
                    names[jid] = full
    finally:
        con.close()
    return names


def load_pushnames(con: sqlite3.Connection) -> dict:
    return {
        jid: name
        for jid, name in con.execute("SELECT ZJID, ZPUSHNAME FROM ZWAPROFILEPUSHNAME")
        if jid and name and name != "~"
    }


def parse_when(value: str, end_of_day: bool = False) -> float:
    """YYYY-MM-DD или ISO-datetime → unix ts."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise SystemExit(f"Не понял дату: {value!r} (ожидаю YYYY-MM-DD или ISO)")
    if len(value) == 10 and end_of_day:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt.timestamp()


def resolve_window(args) -> tuple[float, float]:
    now = time.time()
    end = parse_when(args.to, end_of_day=True) if args.to else now
    if args.since:
        start = parse_when(args.since)
    else:
        last_run = DATA_DIR / "state" / "last_run"
        if last_run.exists():
            start = float(last_run.read_text().strip())
        else:
            start = now - 25 * 3600
    return start, end


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="since", help="начало окна (YYYY-MM-DD или ISO)")
    ap.add_argument("--to", dest="to", help="конец окна (YYYY-MM-DD или ISO)")
    ap.add_argument("--out", help="файл для JSON (по умолчанию stdout)")
    args = ap.parse_args()

    if not CHAT_DB.exists():
        raise SystemExit(f"Не найдена база WhatsApp: {CHAT_DB}")

    start, end = resolve_window(args)

    with tempfile.TemporaryDirectory(prefix="wa-digest-") as tmp:
        tmpdir = Path(tmp)
        names = load_names(tmpdir)
        con = sqlite3.connect(f"file:{copy_db(CHAT_DB, tmpdir)}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            names = {**load_pushnames(con), **names}  # адресная книга важнее push-имён

            placeholders = ",".join("?" * len(CHATS))
            rows = con.execute(
                f"""
                SELECT m.ZMESSAGEDATE AS mdate, m.ZISFROMME AS fromme,
                       m.ZMESSAGETYPE AS mtype, m.ZTEXT AS text,
                       m.ZGROUPEVENTTYPE AS gevent,
                       s.ZCONTACTJID AS chat_jid, s.ZPARTNERNAME AS partner,
                       s.ZSESSIONTYPE AS stype,
                       gm.ZMEMBERJID AS member_jid,
                       mi.ZMEDIALOCALPATH AS media_path, mi.ZTITLE AS media_title,
                       mi.ZMOVIEDURATION AS media_dur
                FROM ZWAMESSAGE m
                JOIN ZWACHATSESSION s ON m.ZCHATSESSION = s.Z_PK
                LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK
                LEFT JOIN ZWAMEDIAITEM mi ON m.ZMEDIAITEM = mi.Z_PK
                WHERE s.ZCONTACTJID IN ({placeholders})
                  AND m.ZMESSAGEDATE > ? AND m.ZMESSAGEDATE <= ?
                ORDER BY m.ZMESSAGEDATE
                """,
                [*CHATS.keys(), start - APPLE_EPOCH, end - APPLE_EPOCH],
            ).fetchall()
        finally:
            con.close()

    messages = []
    for r in rows:
        if r["mtype"] == 6:  # системные события группы (вошёл/вышел и т.п.)
            continue
        mtype = MSG_TYPES.get(r["mtype"], "медиа")
        text = (r["text"] or "").strip()
        caption = (r["media_title"] or "").strip()
        if not text and not caption and not r["media_path"]:
            continue  # пустышки: реакции, служебные записи без содержимого

        if r["fromme"]:
            sender = "Я"
        elif r["stype"] == 0:  # личный чат
            sender = r["partner"] or names.get(r["chat_jid"], r["chat_jid"])
        else:
            jid = r["member_jid"]
            sender = names.get(jid, jid or "неизвестный")

        media_path = None
        if r["media_path"]:
            p = MEDIA_BASE / r["media_path"]
            if p.exists():
                media_path = str(p)

        messages.append({
            "ts": r["mdate"] + APPLE_EPOCH,
            "time": datetime.fromtimestamp(r["mdate"] + APPLE_EPOCH).strftime("%Y-%m-%d %H:%M"),
            "chat": CHATS[r["chat_jid"]],
            "sender": sender,
            "type": mtype,
            "text": text or None,
            "caption": caption or None,
            "media_path": media_path,
            "duration": int(r["media_dur"]) if r["media_dur"] else None,
        })

    out = {
        "window": {
            "from": datetime.fromtimestamp(start).isoformat(timespec="minutes"),
            "to": datetime.fromtimestamp(end).isoformat(timespec="minutes"),
            "end_ts": end,
        },
        "count": len(messages),
        "messages": messages,
    }
    payload = json.dumps(out, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(payload)
        print(f"Сообщений: {len(messages)}, окно {out['window']['from']} → {out['window']['to']}", file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
