#!/usr/bin/env bash
# نصب NRT Self روی VPS اوبونتو/دبیان:  bash install.sh
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "📦 نصب پیش‌نیازها (python, ffmpeg)..."
$SUDO apt-get update -y
$SUDO apt-get install -y python3 python3-venv python3-pip ffmpeg fonts-dejavu wget openssl
python3 -m venv venv
./venv/bin/pip install -q -r requirements.txt

if [ ! -f assets/Vazirmatn-Regular.ttf ]; then
  echo "🔤 دانلود فونت فارسی..."
  wget -q -O assets/Vazirmatn-Regular.ttf \
    "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Regular.ttf" || \
    echo "⚠️ دانلود فونت نشد؛ اسکرین صفحه با فونت پیش‌فرض کار می‌کنه"
fi

ask_required() {  # $1=نام متغیر  $2=متن سوال
  local v=""
  while [ -z "$v" ]; do read -rp "$2" v; done
  printf -v "$1" '%s' "$v"
}
ask_optional() { local v=""; read -rp "$2" v; printf -v "$1" '%s' "$v"; }

MODE=1
if [ ! -f .env ]; then
  umask 077
  echo
  echo "کدوم حالت رو می‌خوای؟"
  echo "  1) سلف شخصی (فقط خودت)"
  echo "  2) هاب چندکاربره + پنل وب مدیریت (فروش سلف / چند نفر)"
  read -rp "عدد (1 یا 2) [1]: " MODE; MODE="${MODE:-1}"
  echo
  ask_required API_ID "API_ID (از my.telegram.org): "
  ask_required API_HASH "API_HASH: "
  ask_required OWNER_ID "آیدی عددی خودت (از @userinfobot): "
  ask_optional GAME_CHAT_ID "آیدی عددی گروه بازی (مثل -1001234567890؛ خالی = همه‌ی چت‌ها): "
  read -rsp "ANTHROPIC_API_KEY (اختیاری، برای دستور هوش مصنوعی): " ANTHROPIC_API_KEY; echo
  {
    echo "API_ID=$API_ID"
    echo "API_HASH=$API_HASH"
    echo "OWNER_ID=$OWNER_ID"
    echo "GAME_CHAT_ID=$GAME_CHAT_ID"
    echo "BANNER_PATH=assets/banner.jpg"
    echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY"
  } > .env
  if [ "$MODE" = "2" ]; then
    echo "--- بات‌های هاب (از @BotFather) ---"
    ask_required HUB_BOT_TOKEN "توکن بات اصلی هاب: "
    ask_optional HUB_HELPER_BOT_TOKEN "توکن بات هلپر/بازی (اختیاری؛ بعد از ساخت /setinline بزن): "
    ask_ids="ADMIN_IDS (آیدی عددی ادمین‌ها با کاما؛ خالی = فقط خودت): "
    ask_optional ADMIN_IDS "$ask_ids"; ADMIN_IDS="${ADMIN_IDS:-$OWNER_ID}"
    read -rsp "رمز پنل وب (خالی = خودکار ساخته می‌شه): " WEB_PASSWORD; echo
    GEN_PASS=""
    if [ -z "$WEB_PASSWORD" ]; then WEB_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)"; GEN_PASS=1; fi
    ask_optional WEB_DOMAIN "دامنه برای پنل وب با HTTPS (مثلا panel.example.com؛ خالی = فقط SSH tunnel): "
    {
      echo "HUB_BOT_TOKEN=$HUB_BOT_TOKEN"
      echo "HUB_HELPER_BOT_TOKEN=$HUB_HELPER_BOT_TOKEN"
      echo "ADMIN_IDS=$ADMIN_IDS"
      echo "WEB_PASSWORD=$WEB_PASSWORD"
      echo "WEB_HOST=127.0.0.1"
      echo "WEB_PORT=8080"
      [ -n "$WEB_DOMAIN" ] && echo "WEB_SECURE=1" || echo "WEB_SECURE=0"
    } >> .env
  else
    echo "--- بات‌ها (از @BotFather) ---"
    ask_required MANAGER_BOT_TOKEN "توکن بات مدیریت: "
    ask_required HELPER_BOT_TOKEN "توکن بات هلپر/پنل (بعد از ساخت /setinline بزن): "
    {
      echo "MANAGER_BOT_TOKEN=$MANAGER_BOT_TOKEN"
      echo "HELPER_BOT_TOKEN=$HELPER_BOT_TOKEN"
    } >> .env
  fi
  chmod 600 .env
else
  grep -q '^HUB_BOT_TOKEN=.' .env && MODE=2
  echo "ℹ️ فایل .env از قبل هست؛ سؤال‌ها رد شد (حالت: $MODE)"
fi

if [ "$MODE" = "2" ]; then ENTRY="hub.py"; else ENTRY="self_bot.py"; fi

echo "⚙️ ساخت سرویس ($ENTRY)..."
$SUDO tee /etc/systemd/system/telegram-self.service >/dev/null <<UNIT
[Unit]
Description=NRT Self
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory="$DIR"
ExecStart="$DIR/venv/bin/python" "$DIR/$ENTRY"
Restart=always
RestartSec=5
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now telegram-self
$SUDO systemctl restart telegram-self

if [ "$MODE" = "2" ] && [ -n "${WEB_DOMAIN:-}" ]; then
  echo "🔒 راه‌اندازی HTTPS با Caddy برای $WEB_DOMAIN (دامنه باید به IP این سرور اشاره کنه)..."
  if $SUDO apt-get install -y caddy; then
    printf '%s {\n    reverse_proxy 127.0.0.1:8080\n}\n' "$WEB_DOMAIN" | $SUDO tee /etc/caddy/Caddyfile >/dev/null
    $SUDO systemctl restart caddy
  else
    echo "⚠️ نصب caddy نشد؛ با SSH tunnel یا nginx دستی ست کن."
    WEB_DOMAIN=""
  fi
fi

echo
echo "✅ تموم شد."
if [ "$MODE" = "2" ]; then
  echo "• توی بات هاب /start بزن (ادمین‌ها /admin)."
  if [ -n "${WEB_DOMAIN:-}" ]; then echo "• پنل وب:  https://$WEB_DOMAIN"
  else
    echo "• پنل وب (SSH tunnel):  ssh -L 8080:127.0.0.1:8080 user@IP_سرور  ←  http://127.0.0.1:8080"
  fi
  [ -n "${GEN_PASS:-}" ] && echo "• رمز پنل وب: $WEB_PASSWORD   (توی .env هم هست)"
else
  echo "• توی بات مدیریت /start بزن و «فعالسازی سلف» رو بزن؛ بعد توی هر چت .پنل"
fi
echo "• لاگ: journalctl -u telegram-self -f"
