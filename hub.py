"""
هاب چندکاربره NRT Self
=======================
یه بات واحد که هر کاربر می‌تونه توش اکانت خودش رو با شماره فعال کنه (سلف جدا، پروسه‌ی جدا)،
و ادمین از همین بات مدیریتشون می‌کنه: دیدن لیست کاربرا، افزایش/کاهش موجودی (الماس) هرکس،
الماس همگانی، پیام تکی یا همگانی. هر کاربر وقتی اولین‌بار میاد ۶ ساعت تست رایگان می‌گیره؛
بعدش موجودی الماسش (که با نرخ ثابت تبدیل به زمان می‌شه) سلفش رو روشن نگه می‌داره و با گذشت
زمان واقعی کم می‌شه؛ وقتی صفر شد سلف خودش خاموش می‌شه.

اجرا:  python hub.py
نیاز به env: API_ID, API_HASH, HUB_BOT_TOKEN (بات اصلی/مدیریت)، ADMIN_IDS (آیدی عددی ادمین/ادمین‌ها
با کاما جدا)، و اختیاری HUB_HELPER_BOT_TOKEN برای پنل inline مشترک (.پنل هر کاربر).
"""
import asyncio
import os
import sqlite3
import sys
import time
from html import escape

from telethon import Button, TelegramClient, errors, events

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from panel import setup_panel_hub
from games import setup_games

# ================= تنظیمات =================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
HUB_BOT_TOKEN = os.getenv("HUB_BOT_TOKEN")
HELPER_BOT_TOKEN = os.getenv("HUB_HELPER_BOT_TOKEN")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
if os.getenv("OWNER_ID"):
    ADMIN_IDS.add(int(os.getenv("OWNER_ID")))

DB_PATH = os.getenv("HUB_DB", "hub.db")
SESS_DIR = os.getenv("HUB_SESSIONS_DIR", "hub_sessions")
CFG_DIR = os.getenv("HUB_CONFIGS_DIR", "hub_configs")
PYTHON = sys.executable
SELF_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "self_bot.py")

# هر الماس معادل چند ثانیه از آنلاین‌بودن سلفه. پیش‌فرض ≈ ۳۰ دقیقه به ازای هر الماس
# (431 الماس ≈ 8 روز و 23 ساعت را با این نرخ می‌شه تنظیم کرد).
DIAMOND_SECONDS = float(os.getenv("DIAMOND_SECONDS", "1796"))
TRIAL_SECONDS = float(os.getenv("TRIAL_SECONDS", str(6 * 3600)))
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")          # رمز پنل وب ادمین (خالی = پنل وب خاموش)
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_SECURE = os.getenv("WEB_SECURE", "0") == "1"      # پشت HTTPS بودی 1 بذار
TICK = 20  # ثانیه؛ هر چند وقت یه‌بار موجودی/تایمر چک و کم می‌شه

os.makedirs(SESS_DIR, exist_ok=True)
os.makedirs(CFG_DIR, exist_ok=True)

# ================= دیتابیس =================
_db = sqlite3.connect(DB_PATH)
_db.execute("""CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    phone TEXT,
    diamonds REAL DEFAULT 0,
    trial_used INTEGER DEFAULT 0,
    trial_seconds REAL DEFAULT 0,
    banned INTEGER DEFAULT 0,
    logged_in INTEGER DEFAULT 0,
    created_at REAL
)""")
_db.execute("""CREATE TABLE IF NOT EXISTS admins(
    user_id INTEGER PRIMARY KEY,
    added_by INTEGER,
    added_at REAL
)""")
_db.execute("""CREATE TABLE IF NOT EXISTS transfers(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER,
    to_id INTEGER,
    amount REAL,
    at REAL
)""")
_db.commit()

# مالک‌ها = آیدی‌های داخل .env (ADMIN_IDS/OWNER_ID)؛ فقط اون‌ها می‌تونن ادمین اضافه/حذف کنن.
# ادمین‌هایی که از پنل «مدیریت ادمین» اضافه می‌شن توی جدول admins ذخیره و به ADMIN_IDS اضافه می‌شن
# (webpanel همین set رو می‌بینه).
OWNERS = frozenset(ADMIN_IDS)
for (_aid,) in _db.execute("SELECT user_id FROM admins").fetchall():
    ADMIN_IDS.add(_aid)


def db_get(uid, username=None):
    row = _db.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    cols = [c[0] for c in _db.execute("SELECT * FROM users LIMIT 0").description]
    if row is None:
        _db.execute("INSERT INTO users(user_id, username, created_at) VALUES(?,?,?)",
                    (uid, username, time.time()))
        _db.commit()
        return db_get(uid, username)
    u = dict(zip(cols, row))
    if username and u["username"] != username:
        _db.execute("UPDATE users SET username=? WHERE user_id=?", (username, uid))
        _db.commit()
        u["username"] = username
    return u


def db_set(uid, **kw):
    if not kw:
        return
    keys = ", ".join(f"{k}=?" for k in kw)
    _db.execute(f"UPDATE users SET {keys} WHERE user_id=?", (*kw.values(), uid))
    _db.commit()


def db_all(include_banned=True):
    rows = _db.execute("SELECT user_id FROM users" + ("" if include_banned else " WHERE banned=0")).fetchall()
    return [r[0] for r in rows]


def db_search(q):
    q = q.strip()
    like = f"%{q}%"
    rows = _db.execute(
        "SELECT user_id FROM users WHERE CAST(user_id AS TEXT)=? OR username LIKE ? LIMIT 30",
        (q, like)).fetchall()
    return [r[0] for r in rows]


def db_find_user(q):
    """آیدی عددی یا @یوزرنیم ← user_id کاربرِ ثبت‌نام‌کرده توی هاب (یا None)."""
    q = q.strip().lstrip("@")
    if not q:
        return None
    if q.isdigit():
        row = _db.execute("SELECT user_id FROM users WHERE user_id=?", (int(q),)).fetchone()
    else:
        row = _db.execute("SELECT user_id FROM users WHERE LOWER(username)=LOWER(?)", (q,)).fetchone()
    return row[0] if row else None


def fmt_duration(seconds):
    seconds = max(0, int(seconds))
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    if d:
        return f"{d} روز و {h} ساعت"
    if h:
        return f"{h} ساعت و {m} دقیقه"
    return f"{m} دقیقه"


def sess_path(uid):
    return os.path.join(SESS_DIR, f"user_{uid}")  # telethon adds .session


def cfg_path(uid):
    return os.path.join(CFG_DIR, f"user_{uid}.json")


def is_logged_in(uid):
    return os.path.exists(sess_path(uid) + ".session")


# ================= پروسه‌های سلف هر کاربر =================
running = {}   # uid -> {"proc": Process, "mode": "trial"/"paid", "last": ts}


def is_admin(uid):
    return uid in ADMIN_IDS


def runway_seconds(u):
    if is_admin(u["user_id"]):
        return float("inf"), "admin"       # ادمین: موجودی/کیف پول بی‌نهایت
    if u["trial_seconds"] > 0:
        return u["trial_seconds"], "trial"
    return u["diamonds"] * DIAMOND_SECONDS, "paid"


async def start_self(uid):
    if uid in running:
        return True, "از قبل روشنه"
    if not is_logged_in(uid):
        return False, "اول باید با شماره‌ت وارد بشی"
    u = db_get(uid)
    if u["banned"]:
        return False, "دسترسیت مسدوده"
    secs, mode = runway_seconds(u)
    if secs <= 0:
        return False, "موجودی الماس یا زمان تستت تموم شده؛ از ادمین شارژ بگیر"
    env = dict(os.environ)
    env.update({
        "SELF_SESSION": sess_path(uid),
        "SELF_CFG": cfg_path(uid),
        "API_ID": str(API_ID), "API_HASH": API_HASH,
        "OWNER_ID": str(uid),
    })
    if HELPER_BOT_TOKEN:
        me = await helper_username()
        if me:
            env["HUB_HELPER_USERNAME"] = me
    env.pop("MANAGER_BOT_TOKEN", None)
    env.pop("HELPER_BOT_TOKEN", None)
    env.pop("BOT_TOKEN", None)
    proc = await asyncio.create_subprocess_exec(
        PYTHON, SELF_SCRIPT, "--child", env=env,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    running[uid] = {"proc": proc, "mode": mode, "last": time.time()}
    db_set(uid, logged_in=1)
    asyncio.create_task(_watch_exit(uid, proc))
    return True, None


async def _watch_exit(uid, proc):
    code = await proc.wait()
    info = running.pop(uid, None)
    if info is None:
        return
    if code == 3:
        db_set(uid, logged_in=0)
        await notify(uid, "⚠️ نشست اکانتت باطل/حذف شده؛ برای فعالسازی دوباره وارد شو.")


async def stop_self(uid, reason=None):
    info = running.pop(uid, None)
    if not info:
        return False
    try:
        info["proc"].terminate()
        try:
            await asyncio.wait_for(info["proc"].wait(), 10)
        except asyncio.TimeoutError:
            info["proc"].kill()
    except ProcessLookupError:
        pass
    if reason:
        await notify(uid, reason)
    return True


async def delete_self_session(uid):
    await stop_self(uid)
    for p in (sess_path(uid) + ".session", sess_path(uid) + ".session-journal", cfg_path(uid)):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    db_set(uid, logged_in=0, phone=None)


async def billing_loop():
    while True:
        await asyncio.sleep(TICK)
        now = time.time()
        for uid in list(running.keys()):
            info = running.get(uid)
            if not info:
                continue
            elapsed = now - info["last"]
            info["last"] = now
            if info["mode"] == "admin" or is_admin(uid):
                continue    # ادمین هیچ‌وقت کم نمی‌شه
            u = db_get(uid)
            if info["mode"] == "trial":
                left = max(0.0, u["trial_seconds"] - elapsed)
                db_set(uid, trial_seconds=left)
                if left <= 0:
                    await stop_self(uid, "⏰ ۶ ساعت تست رایگانت تموم شد. برای ادامه از ادمین الماس بگیر.")
            else:
                left_d = max(0.0, u["diamonds"] - elapsed / DIAMOND_SECONDS)
                db_set(uid, diamonds=left_d)
                if left_d <= 0:
                    await stop_self(uid, "⏰ موجودی الماست تموم شد و سلفت خاموش شد. برای ادامه شارژ کن.")


# ================= بات‌ها =================
bot = TelegramClient("hub_bot", API_ID, API_HASH)
helper_bot = TelegramClient("hub_helper_bot", API_ID, API_HASH) if HELPER_BOT_TOKEN else None
_helper_username_cache = {}


async def helper_username():
    if not helper_bot:
        return None
    if "u" not in _helper_username_cache:
        _helper_username_cache["u"] = (await helper_bot.get_me()).username
    return _helper_username_cache["u"]


async def notify(uid, text):
    try:
        await bot.send_message(uid, text)
    except Exception:
        pass


# ---------- وضعیت موقت ورود با شماره (مثل manager.py، ولی برای هرکسی) ----------
login_state = {}   # uid -> {"step", "phone", "hash", "code", "client"}
admin_state = {}   # admin_id -> {"action": ..., "target": uid or None}
xfer_state = {}    # uid -> {"step": "target"/"amount"/"confirm", "to": uid, "amount": float}


def keypad():
    rows = [[Button.inline(str(n), f"k:{n}".encode()) for n in r]
            for r in ((1, 2, 3), (4, 5, 6), (7, 8, 9))]
    rows.append([Button.inline("0", b"k:0")])
    rows.append([Button.inline("✔️ تایید", b"k:ok"), Button.inline("❌ پاک کردن", b"k:del")])
    rows.append([Button.inline("🚫 انصراف", b"k:cancel")])
    return rows


def code_text(code):
    return ("🔐 <b>کد ورود تلگرام</b>\n"
            "کد رو از چت «Telegram» توی اکانتت بگیر و با دکمه‌ها وارد کن:\n\n"
            f"<code>{code.ljust(5, '-')}</code>")


def status_text(u):
    lines = ["🎛 <b>وضعیت سلف</b>\n"]
    if not u["trial_used"]:
        lines.append("🎁 به‌محض فعالسازی، ۶ ساعت تست رایگان می‌گیری.")
    elif u["trial_seconds"] > 0:
        lines.append(f"🎁 باقیمونده‌ی تست رایگان: {fmt_duration(u['trial_seconds'])}")
    if is_admin(u["user_id"]):
        lines.append("💎 موجودی الماس: ♾ نامحدود (ادمین)")
    else:
        lines.append(f"💎 موجودی الماس: {u['diamonds']:.1f} (معادل {fmt_duration(u['diamonds']*DIAMOND_SECONDS)})")
    lines.append(f"📶 وضعیت: {'🟢 روشن' if u['user_id'] in running else '⏸ خاموش'}")
    lines.append(f"🔑 ورود: {'✅ انجام‌شده' if is_logged_in(u['user_id']) else '🔒 انجام‌نشده'}")
    if u["banned"]:
        lines.append("⛔ دسترسیت مسدود شده")
    return "\n".join(lines)


def user_main_kb(u):
    uid = u["user_id"]
    if u["banned"]:
        return [[Button.inline("⛔ مسدودی", b"noop")]]
    if not is_logged_in(uid):
        return [[Button.inline("🔐 فعالسازی سلف (ورود با شماره)", b"u:login")],
                [Button.inline("💎 انتقال الماس", b"u:xfer")]]
    rows = [[Button.inline("ℹ️ وضعیت/موجودی", b"u:status")],
            [Button.inline("💎 انتقال الماس", b"u:xfer")]]
    if uid in running:
        rows.append([Button.inline("⏸ خاموش کردن سلف", b"u:off")])
    else:
        rows.append([Button.inline("▶️ روشن کردن سلف", b"u:on")])
    rows.append([Button.inline("🗑 حذف سلف (خروج از اکانت)", b"u:del")])
    return rows


async def send_user_main(chat_id):
    u = db_get(chat_id)
    await bot.send_message(chat_id, status_text(u), buttons=user_main_kb(u), parse_mode="html")


# ---------- هندلرهای کاربر عادی ----------
@bot.on(events.NewMessage(pattern=r"^/start", func=lambda e: e.is_private))
async def h_start(ev):
    u = db_get(ev.sender_id, getattr(await ev.get_sender(), "username", None))
    login_state.pop(ev.sender_id, None)
    if ev.sender_id in ADMIN_IDS:
        await send_admin_main(ev.chat_id)
        return
    await send_user_main(ev.chat_id)


@bot.on(events.NewMessage(pattern=r"^/admin", func=lambda e: e.is_private))
async def h_admin(ev):
    if ev.sender_id not in ADMIN_IDS:
        return
    await send_admin_main(ev.chat_id)


@bot.on(events.CallbackQuery(pattern=rb"^u:"))
async def h_user_cb(ev):
    uid = ev.sender_id
    action = ev.data.decode().split(":", 1)[1]
    u = db_get(uid)
    try:
        if action == "login":
            if is_logged_in(uid):
                await ev.answer("از قبل وارد شدی", alert=True)
                return
            login_state[uid] = {"step": "phone"}
            await ev.answer()
            await bot.send_message(
                uid, "📱 شماره‌ی تلفنت رو با دکمه‌ی پایین بفرست (فقط شماره‌ی خودت قبول می‌شه).",
                buttons=[[Button.request_phone("📱 ارسال شماره تلفن", resize=True)],
                         [Button.text("❌ انصراف", resize=True)]])
            return
        if action == "status":
            await ev.edit(status_text(u), buttons=user_main_kb(u), parse_mode="html")
            return
        if action == "xfer":
            if is_admin(uid):
                await ev.answer("ادمین موجودی نامحدود داره؛ برای شارژ بقیه از پنل مدیریت استفاده کن.", alert=True)
                return
            if u["diamonds"] <= 0:
                await ev.answer("موجودی الماست صفره.", alert=True)
                return
            xfer_state[uid] = {"step": "target"}
            await ev.answer()
            await bot.send_message(
                uid, f"💎 موجودی تو: {u['diamonds']:.1f}\n\nآیدی عددی یا @یوزرنیمِ گیرنده رو بفرست "
                     "(گیرنده باید قبلاً توی همین بات /start زده باشه):",
                buttons=[[Button.text("❌ انصراف", resize=True)]])
            return
        if action in ("xok", "xno"):
            xs = xfer_state.get(uid)
            if not xs or xs.get("step") != "confirm":
                await ev.answer("⌛ این درخواست منقضی شده.", alert=True)
                return
            xfer_state.pop(uid, None)
            if action == "xno":
                await ev.edit("🚫 انتقال لغو شد.", buttons=user_main_kb(u))
                return
            to, amount = xs["to"], xs["amount"]
            u = db_get(uid)
            tu = db_get(to)
            if u["banned"] or tu["banned"] or is_admin(uid) or amount <= 0 or u["diamonds"] < amount:
                await ev.edit("❌ انتقال انجام نشد (موجودی کافی نیست یا گیرنده مجاز نیست).",
                              buttons=user_main_kb(u))
                return
            db_set(uid, diamonds=u["diamonds"] - amount)
            db_set(to, diamonds=tu["diamonds"] + amount)
            _db.execute("INSERT INTO transfers(from_id,to_id,amount,at) VALUES(?,?,?,?)",
                        (uid, to, amount, time.time()))
            _db.commit()
            u = db_get(uid)
            await ev.edit(f"✅ {amount:.1f} الماس به <code>{to}</code> منتقل شد.\n"
                          f"💎 موجودی فعلی: {u['diamonds']:.1f}",
                          buttons=user_main_kb(u), parse_mode="html")
            await notify(to, f"💎 {amount:.1f} الماس از طرف {uid} بهت منتقل شد.\n"
                             f"موجودی فعلی: {db_get(to)['diamonds']:.1f}")
            return
        if action == "on":
            if not u["trial_used"]:
                db_set(uid, trial_used=1, trial_seconds=TRIAL_SECONDS)
                u = db_get(uid)
            ok, err = await start_self(uid)
            if not ok:
                await ev.answer(err, alert=True)
                return
            u = db_get(uid)
            await ev.edit(status_text(u), buttons=user_main_kb(u), parse_mode="html")
            return
        if action == "off":
            await stop_self(uid)
            await ev.edit(status_text(db_get(uid)), buttons=user_main_kb(db_get(uid)), parse_mode="html")
            return
        if action == "del":
            await ev.edit("⏳ در حال حذف سلف...", buttons=[])
            await delete_self_session(uid)
            await ev.edit("🗑 سلف حذف شد و از اکانت خارج شدی.", buttons=user_main_kb(db_get(uid)))
            return
    except Exception as ex:
        if "not modified" not in str(ex).lower():
            print("user cb error:", ex)
        try:
            await ev.answer()
        except Exception:
            pass


@bot.on(events.CallbackQuery(pattern=rb"^k:"))
async def h_keypad(ev):
    uid = ev.sender_id
    st = login_state.get(uid)
    key = ev.data.decode()[2:]
    if not st or st.get("step") != "code":
        await ev.answer("⌛ این کیبورد منقضی شده. دوباره از «فعالسازی» شروع کن.", alert=True)
        return
    if key == "cancel":
        tmp = st.pop("client", None)
        if tmp:
            await tmp.disconnect()
        login_state.pop(uid, None)
        await ev.edit("🚫 لغو شد.", buttons=user_main_kb(db_get(uid)))
        return
    if key.isdigit():
        if len(st["code"]) < 6:
            st["code"] += key
    elif key == "del":
        st["code"] = st["code"][:-1]
    elif key == "ok":
        if len(st["code"]) < 5:
            await ev.answer("کد حداقل ۵ رقمه", alert=True)
            return
        await submit_code(ev, uid, st)
        return
    await ev.edit(code_text(st["code"]), buttons=keypad(), parse_mode="html")


async def submit_code(ev, uid, st):
    tc = st["client"]
    try:
        await tc.sign_in(st["phone"], st["code"], phone_code_hash=st["hash"])
    except errors.SessionPasswordNeededError:
        st["step"] = "password"
        await ev.edit("🔑 رمز دومرحله‌ای (2FA) رو توی چت بنویس؛ پیامت بعدش پاک می‌شه.",
                      buttons=[[Button.inline("🚫 انصراف", b"k:cancel")]])
        return
    except (errors.PhoneCodeInvalidError, errors.PhoneCodeEmptyError):
        st["code"] = ""
        await ev.answer("❌ کد اشتباهه", alert=True)
        await ev.edit(code_text(""), buttons=keypad(), parse_mode="html")
        return
    except errors.PhoneCodeExpiredError:
        await tc.disconnect()
        login_state.pop(uid, None)
        await ev.edit("⌛ کد منقضی شد. دوباره از «فعالسازی» شروع کن.", buttons=user_main_kb(db_get(uid)))
        return
    await finish_login(ev, uid, tc)


async def finish_login(ev, uid, tc):
    me = await tc.get_me()
    if me.id != uid:
        await tc.log_out()
        login_state.pop(uid, None)
        await ev.edit("❌ این شماره مال اکانت دیگه‌ایه؛ خارج شدم.", buttons=user_main_kb(db_get(uid)))
        return
    phone = login_state[uid].get("phone")
    await tc.disconnect()
    login_state.pop(uid, None)
    db_set(uid, phone=phone, logged_in=1)
    await ev.edit("✅ <b>وارد شدی!</b>\nحالا از «روشن کردن سلف» استفاده کن.",
                  buttons=user_main_kb(db_get(uid)), parse_mode="html")


@bot.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def h_text(ev):
    uid = ev.sender_id
    m = ev.message
    text = (m.raw_text or "").strip()

    # --- ادمین: منتظر ورودی متنی (مبلغ/پیام) ---
    ast = admin_state.get(uid)
    if uid in ADMIN_IDS and ast:
        await handle_admin_input(ev, ast)
        return

    # --- جستجوی کاربر توسط ادمین ---
    if uid in ADMIN_IDS and text.startswith("جستجو"):
        q = text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else ""
        await admin_search(ev.chat_id, q)
        return

    st = login_state.get(uid)
    if text in ("❌ انصراف", "/cancel"):
        if st and st.get("client"):
            await st["client"].disconnect()
        login_state.pop(uid, None)
        xfer_state.pop(uid, None)
        await bot.send_message(uid, "🚫 لغو شد.", buttons=Button.clear())
        await send_user_main(uid)
        return

    xs = xfer_state.get(uid)
    if xs and text:
        u = db_get(uid)
        if xs["step"] == "target":
            to = db_find_user(text)
            if to is None:
                await ev.respond("❌ این کاربر توی بات ثبت‌نام نکرده. آیدی/یوزرنیم درست بفرست:")
                return
            if to == uid:
                await ev.respond("❌ نمی‌تونی به خودت منتقل کنی.")
                return
            if db_get(to)["banned"]:
                await ev.respond("❌ این کاربر مسدوده.")
                return
            xs.update(step="amount", to=to)
            await ev.respond(f"چند الماس به <code>{to}</code> منتقل بشه؟ (حداکثر {u['diamonds']:.1f})",
                             parse_mode="html")
            return
        if xs["step"] == "amount":
            try:
                amount = round(float(text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٫", "0123456789.")).replace(",", ".")), 2)
            except ValueError:
                amount = 0
            if amount < 0.1:
                await ev.respond("❌ یه عدد (حداقل ۰.۱) بفرست.")
                return
            if amount > u["diamonds"]:
                await ev.respond(f"❌ موجودیت کافی نیست ({u['diamonds']:.1f}).")
                return
            xs.update(step="confirm", amount=amount)
            await bot.send_message(uid, "⌨️", buttons=Button.clear())
            await ev.respond(f"⚠️ تایید می‌کنی {amount:.1f} الماس به <code>{xs['to']}</code> منتقل بشه؟\n"
                             "(برگشت‌ناپذیره)", parse_mode="html",
                             buttons=[[Button.inline("✅ تایید", b"u:xok"), Button.inline("🚫 لغو", b"u:xno")]])
            return

    if st and st.get("step") == "phone" and m.contact:
        if m.contact.user_id != uid:
            await ev.respond("❌ فقط شماره‌ی خودت (با دکمه‌ی پایین) قبول می‌شه.")
            return
        phone = "+" + m.contact.phone_number.lstrip("+")
        tc = TelegramClient(sess_path(uid) + "_tmp", API_ID, API_HASH)
        await tc.connect()
        try:
            sent = await tc.send_code_request(phone)
        except errors.FloodWaitError as ex:
            await ev.respond(f"⏳ تلگرام محدود کرد؛ {ex.seconds} ثانیه صبر کن.")
            await tc.disconnect()
            return
        except Exception as ex:
            await ev.respond(f"❌ خطا: {ex}")
            await tc.disconnect()
            return
        login_state[uid] = {"step": "code", "phone": phone, "hash": sent.phone_code_hash,
                             "code": "", "client": tc}
        await ev.respond("✅ کد به تلگرامت ارسال شد.", buttons=Button.clear())
        await ev.respond(code_text(""), buttons=keypad(), parse_mode="html")
        return

    if st and st.get("step") == "password" and text:
        try:
            await m.delete()
        except Exception:
            pass
        tc = st["client"]
        try:
            await tc.sign_in(password=text)
        except errors.PasswordHashInvalidError:
            await bot.send_message(uid, "❌ رمز اشتباهه. دوباره بنویس.")
            return
        except Exception as ex:
            await bot.send_message(uid, f"❌ خطا: {ex}")
            return
        me = await tc.get_me()
        if me.id != uid:
            await tc.log_out()
            login_state.pop(uid, None)
            await bot.send_message(uid, "❌ این شماره مال اکانت دیگه‌ایه؛ خارج شدم.")
            return
        phone = st.get("phone")
        await tc.disconnect()
        login_state.pop(uid, None)
        db_set(uid, phone=phone, logged_in=1)
        await bot.send_message(uid, "✅ وارد شدی! حالا از «روشن کردن سلف» استفاده کن.",
                               buttons=user_main_kb(db_get(uid)))
        return


# ================= پنل ادمین =================
def admin_main_kb():
    return [
        [Button.inline("👥 لیست کاربران", b"a:list:0")],
        [Button.inline("🔎 جستجو با آیدی", b"a:searchhelp")],
        [Button.inline("🤖 سلف خودم (نامحدود)", b"a:me")],
        [Button.inline("💎 الماس همگانی", b"a:bdiamond"), Button.inline("📢 پیام همگانی", b"a:bmsg")],
        [Button.inline("👮 مدیریت ادمین", b"a:admins")],
    ]


async def send_admin_main(chat_id):
    total = len(db_all())
    on = len(running)
    await bot.send_message(
        chat_id,
        f"🛠 <b>پنل مدیریت</b>\n👥 کل کاربرا: {total}\n🟢 سلف روشن الان: {on}\n\n"
        "برای دیدن یه کاربر خاص بنویس:\n<code>جستجو آیدی_یا_یوزرنیم</code>",
        buttons=admin_main_kb(), parse_mode="html")


def admins_view(viewer):
    owners = sorted(OWNERS)
    extra = sorted(ADMIN_IDS - OWNERS)
    lines = ["👮 <b>مدیریت ادمین</b>\n",
             "👑 مالک‌ها: " + (" ".join(f"<code>{i}</code>" for i in owners) or "—"),
             "👮 ادمین‌ها: " + (" ".join(f"<code>{i}</code>" for i in extra) or "—")]
    rows = []
    if viewer in OWNERS:
        rows.append([Button.inline("➕ افزودن ادمین", b"a:addadmin")])
        rows += [[Button.inline(f"❌ حذف {i}", f"a:rmadmin:{i}".encode())] for i in extra]
    else:
        lines.append("\nℹ️ فقط مالک‌ها می‌تونن ادمین اضافه/حذف کنن.")
    rows.append([Button.inline("🔙 بازگشت", b"a:main")])
    return "\n".join(lines), rows


def user_detail_text(u):
    uid = u["user_id"]
    lines = [f"👤 <b>کاربر</b> <code>{uid}</code>" + (f" (@{escape(u['username'])})" if u["username"] else "")]
    lines.append(f"📱 شماره: {u['phone'] or '—'}")
    lines.append(f"🔑 ورود: {'✅' if is_logged_in(uid) else '🔒'}")
    lines.append(f"📶 سلف: {'🟢 روشن' if uid in running else '⏸ خاموش'}")
    if is_admin(uid):
        lines.append("💎 موجودی: ♾ نامحدود (ادمین)")
    else:
        lines.append(f"💎 موجودی: {u['diamonds']:.1f} الماس (≈ {fmt_duration(u['diamonds']*DIAMOND_SECONDS)})")
    if not u["trial_used"]:
        lines.append("🎁 تست رایگان: هنوز نگرفته")
    else:
        lines.append(f"🎁 باقی‌مونده‌ی تست: {fmt_duration(u['trial_seconds'])}")
    lines.append(f"⛔ بن: {'بله' if u['banned'] else 'خیر'}")
    return "\n".join(lines)


def user_detail_kb(uid):
    u = db_get(uid)
    rows = [
        [Button.inline("➕ افزایش الماس", f"a:add:{uid}".encode()),
         Button.inline("➖ کاهش الماس", f"a:sub:{uid}".encode())],
        [Button.inline("🎁 ۶ ساعت تست هدیه", f"a:trial:{uid}".encode())],
        [Button.inline("📨 ارسال پیام", f"a:msg:{uid}".encode())],
        [Button.inline("🔓 رفع بن" if u["banned"] else "⛔ بن کردن", f"a:ban:{uid}".encode())],
        [Button.inline("⏸ خاموش‌کردن سلفش", f"a:stop:{uid}".encode())] if uid in running else [],
        [Button.inline("🔙 بازگشت", b"a:main")],
    ]
    return [r for r in rows if r]


async def admin_search(chat_id, q):
    if not q:
        await bot.send_message(chat_id, "بنویس: جستجو آیدی_یا_یوزرنیم")
        return
    found = db_search(q)
    if not found:
        await bot.send_message(chat_id, "چیزی پیدا نشد.")
        return
    if len(found) == 1:
        uid = found[0]
        await bot.send_message(chat_id, user_detail_text(db_get(uid)),
                               buttons=user_detail_kb(uid), parse_mode="html")
        return
    rows = [[Button.inline(f"{uid}", f"a:view:{uid}".encode())] for uid in found]
    rows.append([Button.inline("🔙 بازگشت", b"a:main")])
    await bot.send_message(chat_id, f"🔎 {len(found)} نتیجه:", buttons=rows)


PAGE_SIZE = 10


def users_page_kb(page):
    ids = db_all()
    total_pages = max(1, (len(ids) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = ids[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]
    rows = []
    for uid in chunk:
        tag = "🟢" if uid in running else "⚪️"
        rows.append([Button.inline(f"{tag} {uid}", f"a:view:{uid}".encode())])
    nav = []
    if page > 0:
        nav.append(Button.inline("◀️ قبلی", f"a:list:{page-1}".encode()))
    if page < total_pages - 1:
        nav.append(Button.inline("بعدی ▶️", f"a:list:{page+1}".encode()))
    if nav:
        rows.append(nav)
    rows.append([Button.inline("🔙 بازگشت", b"a:main")])
    return f"👥 کاربران ({page+1}/{total_pages})", rows


@bot.on(events.CallbackQuery(pattern=rb"^a:"))
async def h_admin_cb(ev):
    if ev.sender_id not in ADMIN_IDS:
        await ev.answer("این پنل مال تو نیست", alert=True)
        return
    parts = ev.data.decode().split(":")
    d = parts[1]
    try:
        if d == "main":
            total, on = len(db_all()), len(running)
            await ev.edit(f"🛠 <b>پنل مدیریت</b>\n👥 کل کاربرا: {total}\n🟢 سلف روشن الان: {on}\n\n"
                          "برای دیدن یه کاربر خاص بنویس:\n<code>جستجو آیدی_یا_یوزرنیم</code>",
                          buttons=admin_main_kb(), parse_mode="html")
            return
        if d == "me":
            await ev.answer()
            await send_user_main(ev.sender_id)
            return
        if d == "admins":
            await ev.edit(admins_view(ev.sender_id)[0], buttons=admins_view(ev.sender_id)[1], parse_mode="html")
            return
        if d == "addadmin":
            if ev.sender_id not in OWNERS:
                await ev.answer("فقط مالک‌ها می‌تونن ادمین اضافه کنن.", alert=True)
                return
            admin_state[ev.sender_id] = {"action": "addadmin", "target": None}
            await ev.answer()
            await bot.send_message(ev.sender_id, "آیدی عددی یا @یوزرنیمِ ادمین جدید رو بفرست "
                                   "(باید قبلاً توی همین بات /start زده باشه):",
                                   buttons=[[Button.text("❌ انصراف", resize=True)]])
            return
        if d == "rmadmin":
            if ev.sender_id not in OWNERS:
                await ev.answer("فقط مالک‌ها می‌تونن ادمین حذف کنن.", alert=True)
                return
            rid = int(parts[2])
            if rid in OWNERS:
                await ev.answer("مالک رو نمی‌شه حذف کرد.", alert=True)
                return
            _db.execute("DELETE FROM admins WHERE user_id=?", (rid,))
            _db.commit()
            ADMIN_IDS.discard(rid)
            if rid in running:   # دیگه نامحدود نیست؛ از الان طبق موجودی حساب می‌شه
                secs, mode = runway_seconds(db_get(rid))
                if secs <= 0:
                    await stop_self(rid, "⏰ دسترسی ادمینی‌ت برداشته شد و موجودی نداری؛ سلفت خاموش شد.")
                else:
                    running[rid]["mode"] = mode
            await notify(rid, "ℹ️ دسترسی ادمینی‌ت برداشته شد.")
            await ev.answer("حذف شد", alert=True)
            await ev.edit(admins_view(ev.sender_id)[0], buttons=admins_view(ev.sender_id)[1], parse_mode="html")
            return
        if d == "searchhelp":
            await ev.answer("بنویس: جستجو آیدی_یا_یوزرنیم", alert=True)
            return
        if d == "list":
            text, rows = users_page_kb(int(parts[2]))
            await ev.edit(text, buttons=rows)
            return
        if d == "view":
            uid = int(parts[2])
            await ev.edit(user_detail_text(db_get(uid)), buttons=user_detail_kb(uid), parse_mode="html")
            return
        if d in ("add", "sub", "msg"):
            uid = int(parts[2])
            admin_state[ev.sender_id] = {"action": d, "target": uid}
            prompt = {"add": "چند الماس اضافه بشه؟ (عدد بفرست)",
                      "sub": "چند الماس کم بشه؟ (عدد بفرست)",
                      "msg": "متن پیام رو بفرست تا براش ارسال بشه:"}[d]
            await ev.answer()
            await bot.send_message(ev.sender_id, prompt, buttons=[[Button.text("❌ انصراف", resize=True)]])
            return
        if d == "trial":
            uid = int(parts[2])
            db_set(uid, trial_used=1, trial_seconds=TRIAL_SECONDS)
            await notify(uid, f"🎁 ادمین {fmt_duration(TRIAL_SECONDS)} تست رایگان بهت هدیه داد!")
            await ev.answer("انجام شد", alert=True)
            await ev.edit(user_detail_text(db_get(uid)), buttons=user_detail_kb(uid), parse_mode="html")
            return
        if d == "ban":
            uid = int(parts[2])
            u = db_get(uid)
            db_set(uid, banned=0 if u["banned"] else 1)
            if not u["banned"]:
                await stop_self(uid, "⛔ دسترسیت توسط ادمین مسدود شد.")
            await ev.edit(user_detail_text(db_get(uid)), buttons=user_detail_kb(uid), parse_mode="html")
            return
        if d == "stop":
            uid = int(parts[2])
            await stop_self(uid, "⏸ ادمین سلفت رو خاموش کرد.")
            await ev.edit(user_detail_text(db_get(uid)), buttons=user_detail_kb(uid), parse_mode="html")
            return
        if d in ("bdiamond", "bmsg"):
            admin_state[ev.sender_id] = {"action": d, "target": None}
            prompt = ("چند الماس به همه‌ی کاربرا اضافه بشه؟ (عدد بفرست)" if d == "bdiamond"
                      else "متن پیام همگانی رو بفرست:")
            await ev.answer()
            await bot.send_message(ev.sender_id, prompt, buttons=[[Button.text("❌ انصراف", resize=True)]])
            return
    except Exception as ex:
        if "not modified" not in str(ex).lower():
            print("admin cb error:", ex)
        try:
            await ev.answer()
        except Exception:
            pass


async def handle_admin_input(ev, ast):
    admin_id = ev.sender_id
    text = (ev.raw_text or "").strip()
    if text in ("❌ انصراف", "/cancel"):
        admin_state.pop(admin_id, None)
        await bot.send_message(admin_id, "🚫 لغو شد.", buttons=Button.clear())
        await send_admin_main(admin_id)
        return
    action, target = ast["action"], ast["target"]
    if action == "addadmin":
        if admin_id not in OWNERS:
            admin_state.pop(admin_id, None)
            return
        new = db_find_user(text)
        if new is None:
            await ev.respond("❌ این کاربر توی بات ثبت‌نام نکرده (باید /start زده باشه). دوباره بفرست:")
            return
        if new in ADMIN_IDS:
            await ev.respond("ℹ️ این کاربر از قبل ادمینه.")
            return
        _db.execute("INSERT OR IGNORE INTO admins(user_id, added_by, added_at) VALUES(?,?,?)",
                    (new, admin_id, time.time()))
        _db.commit()
        ADMIN_IDS.add(new)
        admin_state.pop(admin_id, None)
        await notify(new, "👮 تو ادمین بات شدی! برای ورود به پنل مدیریت /admin بزن.")
        await bot.send_message(admin_id, f"✅ {new} ادمین شد.", buttons=Button.clear())
        t, rows = admins_view(admin_id)
        await bot.send_message(admin_id, t, buttons=rows, parse_mode="html")
        return
    if action in ("add", "sub", "bdiamond"):
        try:
            amount = float(text.replace(",", "."))
            if amount <= 0:
                raise ValueError
        except ValueError:
            await ev.respond("❌ یه عدد مثبت بفرست.")
            return
        if action == "add":
            u = db_get(target)
            db_set(target, diamonds=u["diamonds"] + amount)
            if target in running and running[target]["mode"] == "paid":
                pass  # تیک بعدی billing_loop موجودی جدید رو می‌خونه
            await notify(target, f"💎 {amount:.1f} الماس به حسابت اضافه شد. موجودی فعلی: "
                                  f"{db_get(target)['diamonds']:.1f}")
            admin_state.pop(admin_id, None)
            await bot.send_message(admin_id, "✅ انجام شد.", buttons=Button.clear())
            await bot.send_message(admin_id, user_detail_text(db_get(target)),
                                   buttons=user_detail_kb(target), parse_mode="html")
            return
        if action == "sub":
            u = db_get(target)
            new_bal = max(0.0, u["diamonds"] - amount)
            db_set(target, diamonds=new_bal)
            if new_bal <= 0 and target in running and running[target]["mode"] == "paid":
                await stop_self(target, "⏰ موجودی الماست توسط ادمین صفر شد و سلفت خاموش شد.")
            await notify(target, f"💎 {amount:.1f} الماس از حسابت کم شد. موجودی فعلی: {new_bal:.1f}")
            admin_state.pop(admin_id, None)
            await bot.send_message(admin_id, "✅ انجام شد.", buttons=Button.clear())
            await bot.send_message(admin_id, user_detail_text(db_get(target)),
                                   buttons=user_detail_kb(target), parse_mode="html")
            return
        if action == "bdiamond":
            ids = db_all(include_banned=False)
            for uid in ids:
                if is_admin(uid):
                    continue
                u = db_get(uid)
                db_set(uid, diamonds=u["diamonds"] + amount)
                await notify(uid, f"🎁 ادمین {amount:.1f} الماس به همه‌ی کاربرا هدیه داد! موجودی فعلیت: "
                                   f"{db_get(uid)['diamonds']:.1f}")
            admin_state.pop(admin_id, None)
            await bot.send_message(admin_id, f"✅ به {len(ids)} کاربر {amount:.1f} الماس داده شد.",
                                   buttons=Button.clear())
            await send_admin_main(admin_id)
            return
    if action in ("msg", "bmsg"):
        if not text:
            await ev.respond("❌ متن خالیه.")
            return
        if action == "msg":
            ok = True
            try:
                await bot.send_message(target, f"📨 <b>پیام از ادمین:</b>\n\n{text}", parse_mode="html")
            except Exception:
                ok = False
            admin_state.pop(admin_id, None)
            await bot.send_message(admin_id, "✅ ارسال شد." if ok else "❌ ارسال نشد (شاید بات رو بلاک کرده).",
                                   buttons=Button.clear())
            await send_admin_main(admin_id)
            return
        if action == "bmsg":
            ids = db_all(include_banned=False)
            sent = 0
            for uid in ids:
                try:
                    await bot.send_message(uid, f"📢 <b>پیام همگانی:</b>\n\n{text}", parse_mode="html")
                    sent += 1
                except Exception:
                    pass
                await asyncio.sleep(0.05)
            admin_state.pop(admin_id, None)
            await bot.send_message(admin_id, f"✅ برای {sent} از {len(ids)} کاربر ارسال شد.",
                                   buttons=Button.clear())
            await send_admin_main(admin_id)
            return


# ================= پنل هلپر مشترک (.پنل هر کاربر) =================
def hub_get_ctx(uid):
    if not is_logged_in(uid) or uid not in running:
        return None
    u = db_get(uid)
    if u["banned"]:
        return None
    path = cfg_path(uid)
    if not os.path.exists(path):
        return None
    import json

    def load():
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def save_back(c):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)

    cfg = load()

    class LazyCfg(dict):
        def __setitem__(self, k, v):
            super().__setitem__(k, v)

    lc = LazyCfg(cfg)

    def do_save():
        save_back(dict(lc))

    return lc, do_save, {}


async def main():
    if not HUB_BOT_TOKEN:
        print("❌ HUB_BOT_TOKEN تنظیم نشده")
        return
    if not ADMIN_IDS:
        print("⚠️ ADMIN_IDS تنظیم نشده؛ هیچ‌کس دسترسی پنل مدیریت نداره")
    await bot.start(bot_token=HUB_BOT_TOKEN)
    print("Hub bot: @" + (await bot.get_me()).username)
    if helper_bot:
        await helper_bot.start(bot_token=HELPER_BOT_TOKEN)
        setup_panel_hub(helper_bot, hub_get_ctx)
        setup_games(helper_bot, os.getenv("HUB_GAMES_DB", "hub_games.db"))   # بازی‌ها فقط توی GAME_CHAT_ID
        print("Hub helper bot: @" + (await helper_username()))
    asyncio.create_task(billing_loop())
    if WEB_PASSWORD:
        from webpanel import WebPanel

        async def send_html(uid, text):
            await bot.send_message(uid, text, parse_mode="html")
        web = WebPanel({
            "db_get": db_get, "db_set": db_set, "db_all": db_all, "db_search": db_search,
            "running": running, "admins": ADMIN_IDS, "is_logged_in": is_logged_in,
            "stop_self": stop_self, "notify": notify, "send_html": send_html,
            "fmt_duration": fmt_duration, "TRIAL_SECONDS": TRIAL_SECONDS,
            "restart": lambda: os._exit(0),   # systemd با Restart=always دوباره بالاش میاره
        }, WEB_PASSWORD, WEB_HOST, WEB_PORT, WEB_SECURE)
        await web.start()
    else:
        print("ℹ️ WEB_PASSWORD تنظیم نشده؛ پنل وب خاموشه")
    clients = [bot] + ([helper_bot] if helper_bot else [])
    await asyncio.gather(*(c.run_until_disconnected() for c in clients))


if __name__ == "__main__":
    asyncio.run(main())
