# WhatsApp Digest Bot → Telegram

*Читать по-русски: [README.ru.md](README.ru.md). Full architecture write-up (Russian): [HANDOFF.md](HANDOFF.md).*

An autonomous daily analyst for teams that live in WhatsApp. Every weekday morning it
reads the local WhatsApp database on a Mac, transcribes voice notes (whisper), looks at
images, analyzes the conversation with Claude — grounded in long-term memory of your
clients, projects, and stuck tasks — and posts a structured digest to a Telegram group.
Reply to any digest in Telegram and the bot adjusts its next reports: feedback is part
of the loop.

## What it sends

- **Daily** (Mon–Fri 09:30) — 30-second read: critical items, cross-department
  hand-offs, one line per manager (client work ✓ / internal / at-risk), plan-vs-fact
  misses and escalations for tasks stuck N+ days.
- **Weekly** (Monday, second message) — milestones, recurring tickets, queue and
  discipline dynamics, carry-over into the new week.
- **Monthly** (first Monday, third message) — every trend the data can support
  (clients gained/lost, backlog dynamics, plan/fact discipline per manager, task
  lifetime) plus a meta-review of the team's reporting quality itself.

## Trustworthiness

Two guards against AI slop, added after real-world pushback:

1. **Fact vs. inference marking** — anything the bot inferred (rather than read) is
   prefixed with an explicit marker in the digest.
2. **Fact-check pass** — before every send, a second Claude run adversarially verifies
   each claim of the digest against the raw transcript and deletes or fixes anything
   unsupported.

## How it learns

- `memory/context.md` — long-term memory the bot maintains itself: clients, projects,
  tasks with start dates and statuses. This is how it knows a task is "stuck for 14 days".
- `memory/feedback.md` — anyone in the Telegram group replies to a bot message (or
  mentions it); the bot ingests that before every run and treats human guidance as
  higher priority than its own judgement.

## Pipeline

`launchd (Mon–Fri 09:30)` → `digest.sh`:
`feedback.py` (collect Telegram replies) → `extract.py` (WhatsApp SQLite → JSON, window
= since last successful run) → `transcribe.py` (mlx-whisper, cached) → `claude -p`
(analysis + memory update) → fact-check pass → `tg.py send` → advance `state/last_run`.
Missed days, weekends, and a powered-off Mac are caught up automatically without
duplicates. Any step failing reports the error to the same Telegram group.

Code lives in this repo; all data lives outside git in `~/.whatsapp-digest/`
(tokens, memory, digest archive, state, logs, venv).

## Setup (~30 min)

Requirements: a Mac with WhatsApp Desktop signed in (macOS stores the chat DB
unencrypted — Windows does not), Claude Code subscription, ffmpeg, Python 3.11+.

1. Authorize Claude CLI once for headless use: run `claude` → `/login` in Terminal.
2. Clone into a **permanent** path, run `./install.sh` — creates `~/.whatsapp-digest/`,
   a venv with mlx-whisper (~1.5 GB model on first run), and the launchd agent.
3. Put your chat JIDs into `~/.whatsapp-digest/chats.json` (`{"<jid>": "Label"}`) —
   how to find them is in [HANDOFF.md](HANDOFF.md).
4. Create a bot via @BotFather → token into `~/.whatsapp-digest/config.env`; add the
   bot to your Telegram group, then `python3 tg.py chat-id` → chat id into config.
5. Test: `./digest.sh` (a period: `./digest.sh --from 2026-07-01`; weekly on demand:
   `WA_WEEKLY=1 ./digest.sh`; monthly: `WA_MONTHLY=1 ./digest.sh`).

## Limitations

- The Mac must be on and WhatsApp Desktop running for the DB to be fresh.
- Videos are not transcribed (marked in the transcript with their captions).
- Feedback applies from the next run; the bot does not chat in real time.
- An empty analysis window sends nothing (by design).

All business logic lives in four prompt files (`prompt.md`, `prompt-weekly.md`,
`prompt-monthly.md`, `prompt-verify.md`) — adapt them to your team without touching code.
