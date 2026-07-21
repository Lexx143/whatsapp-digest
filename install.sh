#!/bin/zsh
# Установка: каталог данных, venv с mlx-whisper, LaunchAgent на 9:30.
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
DATA_DIR="${WA_DIGEST_DATA:-$HOME/.whatsapp-digest}"
PLIST="$HOME/Library/LaunchAgents/com.lexx.whatsapp-digest.plist"

echo "Каталог данных: $DATA_DIR"
mkdir -p "$DATA_DIR"/{state,work,memory,digests,logs}

if [[ ! -f "$DATA_DIR/config.env" ]]; then
  cat > "$DATA_DIR/config.env" <<'EOF'
# Токен бота от @BotFather
TELEGRAM_BOT_TOKEN=
# ID группы, куда слать дайджест (узнать: python3 tg.py chat-id)
TELEGRAM_CHAT_ID=
# Модель анализа: sonnet | opus
CLAUDE_MODEL=sonnet
# 1 = считать обратной связью любые сообщения людей в группе (не только reply/упоминания)
FEEDBACK_ALL=0
EOF
  echo "Создан шаблон $DATA_DIR/config.env — заполните токен и chat_id"
fi

if [[ "${1:-}" != "--no-whisper" ]]; then
  if [[ ! -x "$DATA_DIR/venv/bin/python3" ]]; then
    echo "Создаю venv и ставлю mlx-whisper (модель ~1.5 ГБ скачается при первом прогоне)..."
    python3 -m venv "$DATA_DIR/venv"
    "$DATA_DIR/venv/bin/pip" install --quiet --upgrade pip
    "$DATA_DIR/venv/bin/pip" install --quiet mlx-whisper
  else
    echo "venv уже есть"
  fi
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.lexx.whatsapp-digest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>exec "$SCRIPT_DIR/digest.sh"</string>
  </array>
  <!-- будни: пн(1)–пт(5), по выходным дайджест не выходит; понедельник покрывает выходные -->
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$DATA_DIR/logs/launchd.log</string>
  <key>StandardErrorPath</key><string>$DATA_DIR/logs/launchd.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$UID/com.lexx.whatsapp-digest" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"
echo "LaunchAgent установлен: ежедневно в 09:30 → $SCRIPT_DIR/digest.sh"
echo "Ручной запуск сейчас: launchctl kickstart gui/$UID/com.lexx.whatsapp-digest"
