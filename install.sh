#!/usr/bin/env bash
# NRT Self installer for Ubuntu/Debian VPS:  bash install.sh
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "📦 Installing dependencies (python, ffmpeg)..."
$SUDO apt-get update -y
$SUDO apt-get install -y python3 python3-venv python3-pip ffmpeg fonts-dejavu wget openssl
python3 -m venv venv
./venv/bin/pip install -q -r requirements.txt

if [ ! -f assets/Vazirmatn-Regular.ttf ]; then
  echo "🔤 Downloading Persian font..."
  wget -q -O assets/Vazirmatn-Regular.ttf \
    "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Regular.ttf" || \
    echo "⚠️ Font download failed; screenshots will use the default font"
fi

ask_required() {  # $1=variable name  $2=prompt text
  local v=""
  while [ -z "$v" ]; do read -rp "$2" v; done
  printf -v "$1" '%s' "$v"
}
ask_optional() { local v=""; read -rp "$2" v; printf -v "$1" '%s' "$v"; }

MODE=1
if [ ! -f .env ]; then
  umask 077
  echo
  echo "Which mode do you want?"
  echo "  1) Personal self (only you)"
  echo "  2) Multi-user hub + web admin panel (sell the self / multiple users)"
  read -rp "Choose (1 or 2) [1]: " MODE; MODE="${MODE:-1}"
  echo
  ask_required API_ID "API_ID (from my.telegram.org): "
  ask_required API_HASH "API_HASH (from my.telegram.org): "
  ask_required OWNER_ID "Your numeric Telegram ID (from @userinfobot): "
  ask_optional GAME_CHAT_ID "Game group numeric ID (e.g. -1001234567890; empty = all chats): "
  read -rsp "ANTHROPIC_API_KEY (optional, for the AI command; input hidden): " ANTHROPIC_API_KEY; echo
  {
    echo "API_ID=$API_ID"
    echo "API_HASH=$API_HASH"
    echo "OWNER_ID=$OWNER_ID"
    echo "GAME_CHAT_ID=$GAME_CHAT_ID"
    echo "BANNER_PATH=assets/banner.jpg"
    echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY"
  } > .env
  if [ "$MODE" = "2" ]; then
    echo "--- Hub bots (from @BotFather) ---"
    ask_required HUB_BOT_TOKEN "Main hub bot token (from @BotFather): "
    ask_optional HUB_HELPER_BOT_TOKEN "Helper/game bot token (optional; run /setinline in @BotFather after creating it): "
    ask_optional ADMIN_IDS "ADMIN_IDS (admin numeric IDs, comma-separated; empty = only you): "
    ADMIN_IDS="${ADMIN_IDS:-$OWNER_ID}"
    read -rsp "Web panel password (empty = auto-generate; input hidden): " WEB_PASSWORD; echo
    GEN_PASS=""
    if [ -z "$WEB_PASSWORD" ]; then
      WEB_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)"; GEN_PASS=1
    fi
    ask_optional WEB_DOMAIN "Domain for the web panel with HTTPS (e.g. panel.example.com; empty = SSH tunnel only): "
    {
      echo "HUB_BOT_TOKEN=$HUB_BOT_TOKEN"
      echo "HUB_HELPER_BOT_TOKEN=$HUB_HELPER_BOT_TOKEN"
      echo "ADMIN_IDS=$ADMIN_IDS"
      echo "WEB_PASSWORD=$WEB_PASSWORD"
      echo "WEB_HOST=127.0.0.1"
      echo "WEB_PORT=8080"
      if [ -n "$WEB_DOMAIN" ]; then echo "WEB_SECURE=1"; else echo "WEB_SECURE=0"; fi
    } >> .env
  else
    echo "--- Bots (from @BotFather) ---"
    ask_required MANAGER_BOT_TOKEN "Manager bot token (from @BotFather): "
    ask_required HELPER_BOT_TOKEN "Helper/panel bot token (run /setinline in @BotFather after creating it): "
    {
      echo "MANAGER_BOT_TOKEN=$MANAGER_BOT_TOKEN"
      echo "HELPER_BOT_TOKEN=$HELPER_BOT_TOKEN"
    } >> .env
  fi
  chmod 600 .env
else
  grep -q '^HUB_BOT_TOKEN=.' .env && MODE=2
  echo "ℹ️ .env already exists; skipping questions (mode: $MODE)"
fi

if [ "$MODE" = "2" ]; then ENTRY="hub.py"; else ENTRY="self_bot.py"; fi

echo "⚙️ Creating systemd service ($ENTRY)..."
$SUDO tee /etc/systemd/system/telegram-self.service >/dev/null <<UNIT
[Unit]
Description=NRT Self
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python $DIR/$ENTRY
Restart=always
RestartSec=5
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
$SUDO systemctl daemon-reload
$SUDO systemctl enable telegram-self
$SUDO systemctl restart telegram-self

if [ "$MODE" = "2" ] && [ -n "${WEB_DOMAIN:-}" ]; then
  echo "🔒 Setting up HTTPS with Caddy for $WEB_DOMAIN (the domain must point to this server's IP)..."
  if $SUDO apt-get install -y caddy; then
    printf '%s {\n    reverse_proxy 127.0.0.1:8080\n}\n' "$WEB_DOMAIN" | $SUDO tee /etc/caddy/Caddyfile >/dev/null
    $SUDO systemctl restart caddy
  else
    echo "⚠️ Caddy install failed; set up SSH tunnel or nginx manually."
    WEB_DOMAIN=""
  fi
fi

echo
echo "✅ Done."
if [ "$MODE" = "2" ]; then
  echo "• Send /start to the hub bot (admins: /admin)."
  if [ -n "${WEB_DOMAIN:-}" ]; then
    echo "• Web panel:  https://$WEB_DOMAIN"
  else
    echo "• Web panel (SSH tunnel):  ssh -L 8080:127.0.0.1:8080 user@SERVER_IP  ->  http://127.0.0.1:8080"
  fi
  [ -n "${GEN_PASS:-}" ] && echo "• Web panel password: $WEB_PASSWORD   (also saved in .env)"
else
  echo "• Send /start to the manager bot and tap \"Activate self\"; then type .panel in any chat."
fi
echo "• Status: systemctl status telegram-self"
echo "• Logs:   journalctl -u telegram-self -f"
