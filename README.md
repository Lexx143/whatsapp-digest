# WhatsApp Daily Digest → Telegram

Ежедневно в 09:30 читает локальную базу WhatsApp на Mac, расшифровывает голосовые
(whisper), смотрит картинки, анализирует переписку через Claude с долговременной
памятью (клиенты/проекты/задачи в динамике) и шлёт дайджест в Telegram-группу.
На дайджест можно отвечать в Telegram — обратная связь учитывается со следующего запуска.

## Отслеживаемые чаты

Задаются в `~/.whatsapp-digest/chats.json` (JID → название): рабочие группы с планами/отчётами
и, при необходимости, личные переписки. Как найти JID — в HANDOFF.md, раздел «Установка».

## Установка

0. Один раз авторизовать Claude CLI для headless-запусков: открыть Terminal,
   выполнить `claude` → `/login` (логин десктоп-приложения на CLI не распространяется).
   Проверка: `claude -p "скажи ок"` должен ответить без «Not logged in».
1. `./install.sh` — создаст `~/.whatsapp-digest/` (state, memory, digests, logs, config.env),
   venv с mlx-whisper и LaunchAgent на 09:30.
2. Создать бота у @BotFather → токен в `~/.whatsapp-digest/config.env`.
3. Добавить бота в Telegram-группу, написать там что-нибудь, затем
   `python3 tg.py chat-id` → `TELEGRAM_CHAT_ID` в config.env.
4. Тест: `./digest.sh` (или за период: `./digest.sh --from 2026-07-09`).

## Как это работает

`digest.sh`: feedback.py (сбор ответов из TG) → extract.py (SQLite → JSON) →
transcribe.py (whisper + transcript.md) → `claude -p` (читает транскрипт, картинки,
`memory/context.md`, `memory/feedback.md`; обновляет память; выдаёт дайджест) →
tg.py send → сдвиг `state/last_run`.

Окно анализа — «с прошлого успешного запуска», поэтому пропущенные дни и выходные
подхватываются без дублей.

## Данные (вне git): `~/.whatsapp-digest/`

- `config.env` — токен, chat_id, модель (`CLAUDE_MODEL=sonnet|opus`), `FEEDBACK_ALL`
- `memory/context.md` — долговременная память (ведёт Claude)
- `memory/feedback.md` — обратная связь из Telegram
- `digests/YYYY-MM-DD.md` — архив дайджестов
- `state/` — last_run, tg_offset, кэш расшифровок; `logs/` — логи по дням

## Требования / ограничения

- Mac включён, WhatsApp Desktop запущен и синхронизирован к 09:30.
- `claude` CLI в PATH (анализ идёт по подписке, headless `claude -p`).
- ffmpeg (есть), mlx-whisper (ставит install.sh; первая расшифровка скачивает модель ~1.5 ГБ).
- Видео не расшифровываются (помечаются в транскрипте).
