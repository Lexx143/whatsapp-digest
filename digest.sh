#!/bin/zsh
# Ежедневный прогон: feedback → extract → transcribe → анализ (claude -p) → Telegram.
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
DATA_DIR="${WA_DIGEST_DATA:-$HOME/.whatsapp-digest}"
WORK="$DATA_DIR/work"
LOG="$DATA_DIR/logs/$(date +%F).log"
mkdir -p "$WORK" "$DATA_DIR/logs" "$DATA_DIR/state" "$DATA_DIR/memory" "$DATA_DIR/digests"

exec >>"$LOG" 2>&1
echo "=== запуск $(date '+%F %T') ==="

# venv с mlx-whisper, если есть; иначе системный python
PY="$DATA_DIR/venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"

CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"
[[ -n "$CLAUDE_BIN" ]] || CLAUDE_BIN="$HOME/.local/bin/claude"
[[ -x "$CLAUDE_BIN" ]] || { echo "claude CLI не найден"; exit 1; }

# Модель для анализа (можно переопределить в config.env: CLAUDE_MODEL=opus)
CLAUDE_MODEL="$(grep -E '^CLAUDE_MODEL=' "$DATA_DIR/config.env" 2>/dev/null | cut -d= -f2 || true)"
CLAUDE_MODEL="${CLAUDE_MODEL:-sonnet}"

export PYTHONPATH="$SCRIPT_DIR"

notify_error() {
  echo "ОШИБКА на шаге: $1"
  "$PY" "$SCRIPT_DIR/tg.py" send <<< "⚠️ WhatsApp-дайджест не собрался (шаг: $1). Подробности: $LOG" || true
}

# Проверочный проход: контролёр фактов вычищает неподтверждённое из дайджеста.
# $1 — файл дайджеста (перезаписывается), $2 — файл транскрипта-первоисточника.
verify_digest() {
  local digest_file="$1" transcript_file="$2"
  local vprompt
  vprompt="$(cat "$SCRIPT_DIR/prompt-verify.md")
Задание: дайджест — в файле $digest_file, транскрипт-первоисточник — в файле $transcript_file."
  (
    cd "$DATA_DIR"
    "$CLAUDE_BIN" -p "$vprompt" --model "$CLAUDE_MODEL" --allowedTools "Read" > "$digest_file.verified"
  ) || return 1
  # защита от пустого ответа контролёра — тогда оставляем оригинал
  if [[ -s "$digest_file.verified" ]] && grep -q "🚨\|📅\|📊" "$digest_file.verified"; then
    # отрезаем служебные части контролёра: всё до первого заголовка дайджеста
    # и всё после него, что похоже на протокол проверки («Что удалено», «---» в хвосте)
    "$PY" - "$digest_file.verified" <<'PYEOF'
import pathlib, re, sys
p = pathlib.Path(sys.argv[1])
t = p.read_text()
i = min((j for j in (t.find(e) for e in ("🚨", "📅", "📊")) if j >= 0), default=0)
t = t[i:].replace("**", "")
m = re.search(r"\n-{3,}\s*\n|\nЧто удалено", t)
if m:
    t = t[:m.start()]
p.write_text(t.rstrip() + "\n")
PYEOF
    mv "$digest_file.verified" "$digest_file"
  else
    echo "контролёр вернул пустое/битое — отправляю без проверки"
    rm -f "$digest_file.verified"
  fi
}

# 0. Ждём сеть: после пробуждения Mac Wi-Fi поднимается позже launchd (до 5 минут)
NET_OK=0
for i in {1..30}; do
  if curl -s --max-time 8 -o /dev/null "https://api.telegram.org"; then NET_OK=1; break; fi
  echo "сеть недоступна, жду ($i/30)…"
  sleep 10
done
[[ "$NET_OK" == "1" ]] || { echo "сети нет 5 минут — выхожу, launchd попробует завтра"; exit 1; }

# 1. Обратная связь из Telegram (не критично при сбое)
"$PY" "$SCRIPT_DIR/feedback.py" || echo "feedback.py упал — продолжаю"

# 2. Извлечение сообщений
"$PY" "$SCRIPT_DIR/extract.py" "$@" --out "$WORK/messages.json" || { notify_error "извлечение из базы WhatsApp"; exit 1; }

# Пустое окно (повторный запуск, выходной без сообщений) — дневной дайджест
# пропускаем: не гоняем анализ, ничего не шлём и не затираем дневной архив.
# Недельный обзор (по понедельникам, ниже) при этом всё равно выходит.
MSG_COUNT="$("$PY" -c "import json; print(json.load(open('$WORK/messages.json'))['count'])")"
SKIP_DAILY=0
if [[ "$MSG_COUNT" == "0" ]]; then
  echo "Сообщений за окно нет — дневной дайджест не формируется"
  SKIP_DAILY=1
fi

if [[ "$SKIP_DAILY" == "0" ]]; then

# 3. Расшифровка голосовых + транскрипт
"$PY" "$SCRIPT_DIR/transcribe.py" "$WORK/messages.json" --out "$WORK/transcript.md" || { notify_error "расшифровка голосовых"; exit 1; }

# 4. Анализ через Claude (headless)
PROMPT="$(cat "$SCRIPT_DIR/prompt.md")
Сегодня: $(date '+%A, %F %H:%M')."
ANALYSIS_OK=0
for attempt in 1 2 3; do
  if (
    cd "$DATA_DIR"
    # переменные вложенной сессии Claude Code ломают авторизацию CLI при ручном запуске
    unset ANTHROPIC_BASE_URL CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SESSION_ID \
          CLAUDE_CODE_CHILD_SESSION CLAUDE_CODE_OAUTH_SCOPES CLAUDE_CODE_SDK_HAS_OAUTH_REFRESH \
          CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH CLAUDE_AGENT_SDK_VERSION CLAUDE_CODE_EXECPATH \
          CLAUDE_EFFORT AI_AGENT BAGGAGE 2>/dev/null || true
    "$CLAUDE_BIN" -p "$PROMPT" --model "$CLAUDE_MODEL" --allowedTools "Read,Write" < /dev/null > "$WORK/digest.md"
  ) && [[ -s "$WORK/digest.md" ]] && ! grep -qi "request timed out" "$WORK/digest.md"; then
    ANALYSIS_OK=1; break
  fi
  echo "анализ: попытка $attempt не удалась, повтор через 60с"
  sleep 60
done
[[ "$ANALYSIS_OK" == "1" ]] || { notify_error "анализ (claude, 3 попытки)"; exit 1; }

# отрезаем служебный текст модели до начала дайджеста (первого 🚨)
"$PY" - "$WORK/digest.md" <<'EOF'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
t = p.read_text()
i = t.find("🚨")
if i > 0:
    p.write_text(t[i:])
EOF

# 4.5. Контроль фактов
verify_digest "$WORK/digest.md" "$WORK/transcript.md" || { notify_error "контроль фактов"; exit 1; }

# 5. Архив и отправка
cp "$WORK/digest.md" "$DATA_DIR/digests/$(date +%F).md"
"$PY" "$SCRIPT_DIR/tg.py" send --file "$WORK/digest.md" --hint || { notify_error "отправка в Telegram"; exit 1; }

# 6. Сдвигаем окно только после полного успеха (и только вперёд — ручной
#    прогон за старый период не должен откатывать состояние)
"$PY" - "$WORK/messages.json" "$DATA_DIR/state/last_run" <<'EOF'
import json, sys, pathlib
end = json.load(open(sys.argv[1]))["window"]["end_ts"]
p = pathlib.Path(sys.argv[2])
prev = float(p.read_text()) if p.exists() else 0
if end > prev:
    p.write_text(str(end))
EOF

fi  # SKIP_DAILY

# 7. По понедельникам (или при WA_WEEKLY=1) — недельный обзор вторым сообщением
if [[ "$(date +%u)" == "1" || "${WA_WEEKLY:-0}" == "1" ]]; then
  echo "--- недельный обзор ---"
  WEEK_FROM="$(date -v-7d '+%Y-%m-%dT%H:%M')"
  "$PY" "$SCRIPT_DIR/extract.py" --from "$WEEK_FROM" --out "$WORK/messages-weekly.json" || { notify_error "недельный: извлечение"; exit 1; }
  "$PY" "$SCRIPT_DIR/transcribe.py" "$WORK/messages-weekly.json" --out "$WORK/transcript-weekly.md" || { notify_error "недельный: расшифровка"; exit 1; }
  WPROMPT="$(cat "$SCRIPT_DIR/prompt-weekly.md")
Сегодня: $(date '+%A, %F %H:%M'). Окно недели: с $WEEK_FROM."
  (
    cd "$DATA_DIR"
    "$CLAUDE_BIN" -p "$WPROMPT" --model "$CLAUDE_MODEL" --allowedTools "Read" > "$WORK/weekly.md"
  ) || { notify_error "недельный: анализ"; exit 1; }
  "$PY" - "$WORK/weekly.md" <<'EOF'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
t = p.read_text()
i = t.find("📅")
if i > 0:
    t = t[i:]
t = t.replace("**", "")
p.write_text(t)
EOF
  [[ -s "$WORK/weekly.md" ]] || { notify_error "недельный: пустой ответ"; exit 1; }
  verify_digest "$WORK/weekly.md" "$WORK/transcript-weekly.md" || { notify_error "недельный: контроль фактов"; exit 1; }
  cp "$WORK/weekly.md" "$DATA_DIR/digests/$(date +%F)-weekly.md"
  "$PY" "$SCRIPT_DIR/tg.py" send --file "$WORK/weekly.md" --hint || { notify_error "недельный: отправка"; exit 1; }
fi

# 8. Первый понедельник месяца (или WA_MONTHLY=1) — месячный обзор третьим сообщением,
#    окно = прошлый календарный месяц
if [[ ( "$(date +%u)" == "1" && "$(date +%-d)" -le 7 ) || "${WA_MONTHLY:-0}" == "1" ]]; then
  echo "--- месячный обзор ---"
  MONTH_FROM="$(date -v1d -v-1m '+%Y-%m-%d')"
  MONTH_TO="$(date -v1d -v-1d '+%Y-%m-%d')"
  MONTH_TAG="$(date -v-1m '+%Y-%m')"
  "$PY" "$SCRIPT_DIR/extract.py" --from "$MONTH_FROM" --to "$MONTH_TO" --out "$WORK/messages-monthly.json" || { notify_error "месячный: извлечение"; exit 1; }
  "$PY" "$SCRIPT_DIR/transcribe.py" "$WORK/messages-monthly.json" --out "$WORK/transcript-monthly.md" || { notify_error "месячный: расшифровка"; exit 1; }
  MPROMPT="$(cat "$SCRIPT_DIR/prompt-monthly.md")
Сегодня: $(date '+%A, %F %H:%M'). Анализируемый месяц: $MONTH_TAG ($MONTH_FROM — $MONTH_TO)."
  (
    cd "$DATA_DIR"
    "$CLAUDE_BIN" -p "$MPROMPT" --model "$CLAUDE_MODEL" --allowedTools "Read" > "$WORK/monthly.md"
  ) || { notify_error "месячный: анализ"; exit 1; }
  "$PY" - "$WORK/monthly.md" <<'EOF'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
t = p.read_text()
i = t.find("📊")
if i > 0:
    t = t[i:]
t = t.replace("**", "")
p.write_text(t)
EOF
  [[ -s "$WORK/monthly.md" ]] || { notify_error "месячный: пустой ответ"; exit 1; }
  verify_digest "$WORK/monthly.md" "$WORK/transcript-monthly.md" || { notify_error "месячный: контроль фактов"; exit 1; }
  cp "$WORK/monthly.md" "$DATA_DIR/digests/$MONTH_TAG-monthly.md"
  "$PY" "$SCRIPT_DIR/tg.py" send --file "$WORK/monthly.md" --hint || { notify_error "месячный: отправка"; exit 1; }
fi

echo "=== успех $(date '+%F %T') ==="
