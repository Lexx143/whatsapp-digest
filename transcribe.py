#!/usr/bin/env python3
"""Расшифровка голосовых (mlx-whisper) и рендер markdown-транскрипта.

Вход: JSON от extract.py. Выход: transcript.md для анализа.
Расшифровки кэшируются в state/transcripts.json по пути файла,
чтобы не гонять whisper повторно.
"""
import argparse
import json
import sys
from pathlib import Path

from common import DATA_DIR

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
CACHE_PATH = DATA_DIR / "state" / "transcripts.json"


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def transcribe_voice(messages: list) -> None:
    """Проставляет msg['transcript'] всем голосовым с локальным файлом."""
    voice = [m for m in messages if m["type"] == "голосовое" and m.get("media_path")]
    if not voice:
        return
    cache = load_cache()
    todo = [m for m in voice if m["media_path"] not in cache]
    if todo:
        try:
            import mlx_whisper
        except ImportError:
            print("mlx-whisper не установлен — голосовые останутся без расшифровки", file=sys.stderr)
            mlx_whisper = None
        if mlx_whisper:
            for i, m in enumerate(todo, 1):
                print(f"whisper {i}/{len(todo)}: {Path(m['media_path']).name}", file=sys.stderr)
                try:
                    result = mlx_whisper.transcribe(
                        m["media_path"], path_or_hf_repo=WHISPER_MODEL, language="ru"
                    )
                    cache[m["media_path"]] = result["text"].strip()
                except Exception as e:  # битый файл не должен ронять весь прогон
                    print(f"  ошибка: {e}", file=sys.stderr)
                    cache[m["media_path"]] = None
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    for m in voice:
        m["transcript"] = cache.get(m["media_path"])


def render(data: dict) -> str:
    """Markdown-транскрипт, сгруппированный по чатам."""
    lines = [
        f"# Переписка WhatsApp за окно {data['window']['from']} → {data['window']['to']}",
        "",
    ]
    by_chat: dict[str, list] = {}
    for m in data["messages"]:
        by_chat.setdefault(m["chat"], []).append(m)

    for chat, msgs in by_chat.items():
        lines += [f"## {chat}", ""]
        last_day = None
        for m in msgs:
            day, hhmm = m["time"].split(" ")
            if day != last_day:
                lines += [f"### {day}", ""]
                last_day = day
            body = []
            if m["type"] == "голосовое":
                dur = f", {m['duration']}с" if m.get("duration") else ""
                if m.get("transcript"):
                    body.append(f"[голосовое{dur}, расшифровка]: {m['transcript']}")
                else:
                    body.append(f"[голосовое{dur}, расшифровать не удалось]")
            elif m["type"] == "изображение" and m.get("media_path"):
                body.append(f"[изображение, файл: {m['media_path']}]")
            elif m["type"]:
                body.append(f"[{m['type']}]")
            if m.get("caption"):
                body.append(f"Подпись: {m['caption']}")
            if m.get("text"):
                body.append(m["text"])
            text = " ".join(body).replace("\n", "\n  ")
            lines.append(f"- **{hhmm} {m['sender']}**: {text}")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("messages_json")
    ap.add_argument("--out", required=True, help="куда писать transcript.md")
    ap.add_argument("--no-whisper", action="store_true", help="пропустить расшифровку голосовых")
    args = ap.parse_args()

    data = json.loads(Path(args.messages_json).read_text())
    if not args.no_whisper:
        transcribe_voice(data["messages"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data))

    n_voice = sum(1 for m in data["messages"] if m["type"] == "голосовое")
    n_img = sum(1 for m in data["messages"] if m["type"] == "изображение")
    print(f"Транскрипт: {data['count']} сообщений, голосовых {n_voice}, картинок {n_img} → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
