import ast
import asyncio
import json
import operator
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from telethon import TelegramClient, events, functions, types
from telethon.errors import (AuthKeyUnregisteredError, FloodWaitError, SessionRevokedError,
                             UserDeactivatedBanError, UserDeactivatedError)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import features
from manager import setup_manager
from banner import refresh_banner
from games import setup_games
from panel import setup_panel
import extras
import more

# ================= تنظیمات =================
API_ID = int(os.getenv("API_ID", "123456"))          # از my.telegram.org
API_HASH = os.getenv("API_HASH", "your_api_hash")    # از my.telegram.org
SESSION = os.getenv("SELF_SESSION", "clock_self")
TZ = ZoneInfo("Asia/Tehran")
PREFIX = "."                 # دستورها با این علامت شروع می‌شن: .پینگ
CFG_FILE = os.getenv("SELF_CFG", "self_config.json")
OWNER_ID = int(os.getenv("OWNER_ID") or 0)            # آیدی عددی خودت (از @userinfobot)
MANAGER_TOKEN = os.getenv("MANAGER_BOT_TOKEN")        # بات مدیریت/فعالسازی (اختیاری)
HELPER_TOKEN = os.getenv("HELPER_BOT_TOKEN") or os.getenv("BOT_TOKEN")  # بات هلپر برای پنل inline
BANNER_PATH = os.getenv("BANNER_PATH", "assets/banner.jpg")  # عکس بنر خودت (اختیاری)
HUB_HELPER = os.getenv("HUB_HELPER_USERNAME")        # حالت هاب: یوزرنیم بات هلپر مشترک (پروسه‌ی کاربر)
# برای دستور هوش مصنوعی: export ANTHROPIC_API_KEY=...
# ===========================================

client = TelegramClient(SESSION, API_ID, API_HASH)
START = time.time()

DEFAULT = {
    "enabled": True,
    "clock": True, "clock_mode": "last",
    "base_first": None, "base_last": None,
    "online": False,
    "secretary": False, "secretary_text": "الان سرکارم، بعداً جواب می‌دم 🙏",
    "autoseen": False, "pvlock": False, "antilogin": False,
    "react": None, "action": None, "textmode": None,
    "autoreplies": {}, "muted": [], "filters": {},
    "gbans": [], "friends": [], "friend_words": [],
    "content_on": True, "content": {}, "voice": "زن",
}


def load():
    c = json.loads(json.dumps(DEFAULT))
    if os.path.exists(CFG_FILE):
        try:
            with open(CFG_FILE, encoding="utf-8") as f:
                c.update(json.load(f))
        except Exception:
            pass
    return c


cfg = load()


def save():
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)


# ---------- ابزارهای کمکی ----------
DIGITS = str.maketrans("0123456789", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿")
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
CLOCK_RE = re.compile(r"\s*[\U0001D7F6-\U0001D7FF]{2} : [\U0001D7F6-\U0001D7FF]{2}$")
COMMANDS = {}
secretary_seen = {}
autoreply_seen = {}
bot_state = {}


def cmd(*names):
    def deco(fn):
        for n in names:
            COMMANDS[n] = fn
        return fn
    return deco


async def out(e, text):
    text = text[:4000]
    try:
        await e.edit(text, parse_mode=None)
    except Exception:
        await e.respond(text, parse_mode=None)


def parse_onoff(a):
    w = a.split()[0] if a else ""
    if w in ("روشن", "on", "1"):
        return True
    if w in ("خاموش", "off", "0"):
        return False
    raise ValueError("بنویس: روشن یا خاموش")


async def target(e, arg):
    if e.is_reply:
        r = await e.get_reply_message()
        return r.sender_id
    if arg:
        a = arg.split()[0]
        ent = await client.get_entity(int(a) if a.lstrip("-").isdigit() else a)
        return ent.id
    if e.is_private:
        return e.chat_id
    raise ValueError("ریپلای کن یا آیدی بده")


def clock_text():
    return datetime.now(TZ).strftime("%H : %M").translate(DIGITS)


# ---------- ساعت کنار اسم ----------
clock_state = {"shown": None}


async def snapshot_name(force=False):
    if cfg["base_first"] is not None and not force:
        return
    me = await client.get_me()
    cfg["base_first"] = CLOCK_RE.sub("", me.first_name or "")
    cfg["base_last"] = CLOCK_RE.sub("", me.last_name or "")
    save()


async def restore_name():
    if cfg["base_first"] is None:
        return
    await client(functions.account.UpdateProfileRequest(
        first_name=cfg["base_first"], last_name=cfg["base_last"] or ""))
    clock_state["shown"] = None


async def apply_clock():
    if not cfg["clock"] or not cfg["enabled"]:
        return
    t = clock_text()
    key = (t, cfg["clock_mode"])
    if clock_state["shown"] == key:
        return
    f, l = cfg["base_first"], cfg["base_last"] or ""
    if cfg["clock_mode"] == "first":
        f = f"{f} {t}".strip()
    else:
        l = f"{l} {t}".strip()
    await client(functions.account.UpdateProfileRequest(first_name=f, last_name=l))
    clock_state["shown"] = key


async def clock_loop():
    while True:
        try:
            await apply_clock()
        except FloodWaitError as ex:
            await asyncio.sleep(ex.seconds + 1)
            continue
        except Exception as ex:
            print("clock error:", ex)
        await asyncio.sleep(60 - datetime.now(TZ).second + 0.5)


async def online_loop():
    while True:
        try:
            if cfg["online"] and cfg["enabled"]:
                await client(functions.account.UpdateStatusRequest(offline=False))
        except Exception:
            pass
        await asyncio.sleep(25)


async def antilogin_loop():
    known = None
    while True:
        try:
            if cfg["antilogin"] and cfg["enabled"]:
                auths = (await client(functions.account.GetAuthorizationsRequest())).authorizations
                if known is None:
                    known = {a.hash for a in auths}
                else:
                    for a in auths:
                        if not a.current and a.hash not in known:
                            await client(functions.account.ResetAuthorizationRequest(hash=a.hash))
                            await client.send_message(
                                "me", f"🚨 نشست جدید بسته شد: {a.device_model} | {a.ip} | {a.country}")
            else:
                known = None
        except Exception as ex:
            print("antilogin error:", ex)
        await asyncio.sleep(30)


# ---------- دستورات: عمومی ----------
HELP = f"""📖 دستورات NRT Self (پیشوند: {PREFIX})
⚙️ پنل | پینگ | اطلاعات | ثبت نام
🕒 ساعت روشن/خاموش/اول/آخر
🟢 حالت‌ها:
آنلاین | منشی | منشی متن ... | اکشن typing/voice/video/game/خاموش | متن بولد/ایتالیک/مونو/اسپویلر/خاموش
🛠 ابزارها:
هوا شهر | ارز 100 USD EUR | کریپتو bitcoin | ترجمه en متن | محاسبه 2+2 | هوش مصنوعی سوال
🎙 صدا: متن به ویس [مرد/زن] متن | صدای ویس مرد/زن | ویس به متن (ریپلای)
🎵 آهنگ اسم | 2 | سرچ یوتیوب متن | کیفیت (ریپلای روی عکس)
🎮 تاس | دارت | بولینگ | بسکتبال | کازینو [عدد]
🔁 تبدیل (ریپلای): عکس/ویدیو/گیف/استیکر/دایره به ... مثلا: ویدیو به دایره
👥 گروه:
تگ [تعداد] | همه | حذف [تعداد] | بن | سیک | آنبن | پین | حذف پین
بن ال | حذف بن ال | لیست بن ال
🫂 دوست: تنظیم دوست | حذف دوست | لیست دوستان | پاکسازی لیست دوستان | تنظیم لیست دوست
تنظیم کلمات دوست متن | تنظیم لیست کلمات دوست | پاکسازی لیست کلمات دوست
📦 محتوا: محتوا روشن/خاموش | محتوا جدید کلمه | ذخیره محتوا کلمه | حذف محتوا کلمه | لیست محتوا
🔒 امنیت:
قفل پیوی | بلاک | آنبلاک | سکوت | رفع سکوت | فیلتر کلمه | حذف فیلتر کلمه | ضد لاگین | بکاپ 500
🤖 خودکار:
سین خودکار | پاسخ کلمه | جواب | حذف پاسخ کلمه | ری اکشن روشن ❤
🗡 دشمن: تنظیم دشمن | حذف دشمن | لیست دشمن | پاکسازی لیست دشمن
تنظیم فحش متن | حذف فحش متن | لیست فحش | تنظیم لیست فحش (ریپلای فایل)
📣 تبچی (بنر خودکار): تبچی روشن/خاموش | وضعیت تبچی | لیست بنر ها
تنظیم بنر فور/کپی (ریپلای) | حذف بنر N | پاکسازی لیست بنر ها
تنظیم دقیقه بنر دقیقه N | تنظیم/حذف گپ هدف بنر N | تنظیم هدف بنر N (همه)
فور بنر در تعداد (ریپلای)
💥 اسپم متن تعداد  (یا ریپلای: اسپم تعداد) — حداکثر ۳۰۰
📸 اسکرین صفحه [تعداد] | اسکرین صفحه روشن/خاموش | اسکرین صفحه تعداد N
⭐ استارزی: تنظیم عکس استارزی (ریپلای) | تنظیم زمان استارزی HH:MM | استارزی روشن/خاموش
🔴 لایو: لایو عنوان | پخش لینک/اسم (یا ریپلای) | مکث | ادامه | بعدی | صف | قطع
جلو/عقب/برو ثانیه | پنل لایو
🔣 پرفیکس [نماد|پیش‌فرض] | جوین (ریپلای روی لینک) | عضویت اجباری تنظیم @ch/روشن/خاموش
💬 کامنت اول روشن/خاموش | کامنت اول متن ... | افزودن/حذف @ch
🛡 نگهبان روشن/خاموش | نگهبان لینک/فوروارد/منشن/استیکر/گیف روشن/خاموش
🧰 کاربردی: آیدی | تاریخ | یادآوری 30 دقیقه متن | لیست یادآوری | لینک پیام | ذخیره (ریپلای)
⬇️ دانلود لینک | دانلود صدا لینک | 🌐 اسکرین سایت.com (بدون لینک = اسکرین چت)
🛠 مدیریت گروه | قفل گروه | بازکردن گروه | عنوان گروه | توضیحات گروه | لینک گروه
ترفیع | عزل | اخراج | لیست ادمین | حالت آرام ثانیه
🎯 تقلب تاس 6 | دارت | بولینگ | بسکتبال | فوتبال | کازینو عدد
🔥 چالش استارزی روشن [روز] | خاموش | ریست
🐱 بازی گربه بگیر [اسم] | غذا | بازی | خواب | اسم X | ریست
(روشن/خاموش بعد از اسم هر حالت میاد)"""


@cmd("راهنما", "help")
async def help_cmd(e, a):
    await out(e, HELP)


async def ping_text():
    t = time.time()
    await client(functions.help.GetConfigRequest())
    return f"🏓 {int((time.time() - t) * 1000)}ms"


async def info_text():
    me = await client.get_me()
    flags = ["clock", "online", "secretary", "autoseen", "pvlock", "antilogin"]
    st = " | ".join(f"{k}:{'✅' if cfg[k] else '⛔'}" for k in flags)
    up = int((time.time() - START) // 60)
    return f"👤 {me.first_name} | id: {me.id}\n⏱ آپتایم: {up} دقیقه\n{st}"


@cmd("پینگ", "ping")
async def ping(e, a):
    await out(e, await ping_text())


@cmd("اطلاعات")
async def info(e, a):
    await out(e, await info_text())


@cmd("پنل", "panel")
async def panel_cmd(e, a):
    if not bot_state.get("client"):
        raise ValueError("HELPER_BOT_TOKEN تنظیم نشده (از BotFather بگیر و inline mode رو روشن کن)")
    res = await client.inline_query(bot_state["username"], "panel")
    if not res:
        raise ValueError("بات جواب نداد؛ inline mode رو توی BotFather روشن کن")
    await e.delete()
    await res[0].click(e.chat_id)


@cmd("ثبت نام")
async def snap(e, a):
    await snapshot_name(force=True)
    await out(e, f"✅ اسم اصلی ثبت شد: {cfg['base_first']} {cfg['base_last'] or ''}")


@cmd("ساعت")
async def clock_cmd(e, a):
    w = a.split()[0] if a else ""
    if w in ("اول", "first"):
        cfg["clock_mode"], cfg["clock"] = "first", True
        await restore_name()
    elif w in ("آخر", "last"):
        cfg["clock_mode"], cfg["clock"] = "last", True
        await restore_name()
    else:
        cfg["clock"] = parse_onoff(a)
        if not cfg["clock"]:
            await restore_name()
    save()
    await apply_clock()
    await out(e, f"🕒 ساعت: {'✅ روشن (' + cfg['clock_mode'] + ')' if cfg['clock'] else '⛔ خاموش'}")


def make_toggle(name, key, label):
    @cmd(name)
    async def _(e, a):
        cfg[key] = parse_onoff(a)
        save()
        await out(e, f"{label}: {'✅ روشن' if cfg[key] else '⛔ خاموش'}")


make_toggle("آنلاین", "online", "🟢 حالت آنلاین")
make_toggle("منشی", "secretary", "🗂 منشی")
make_toggle("سین خودکار", "autoseen", "👁 سین خودکار")
make_toggle("قفل پیوی", "pvlock", "🔒 قفل پیوی (پیام غریبه‌ها پاک می‌شه)")
make_toggle("ضد لاگین", "antilogin", "🛡 ضد لاگین")


@cmd("منشی متن")
async def sec_text(e, a):
    if not a:
        raise ValueError("متن منشی رو بنویس")
    cfg["secretary_text"] = a
    save()
    await out(e, "✅ متن منشی تنظیم شد")


@cmd("اکشن")
async def action_cmd(e, a):
    m = {"typing": "typing", "تایپ": "typing", "voice": "record-voice", "ویس": "record-voice",
         "video": "record-video", "ویدیو": "record-video", "game": "game", "بازی": "game"}
    if a in ("خاموش", "off"):
        cfg["action"] = None
    elif a in m:
        cfg["action"] = m[a]
    else:
        raise ValueError("typing / voice / video / game / خاموش")
    save()
    await out(e, f"🎭 حالت اکشن: {cfg['action'] or '⛔ خاموش'}")


@cmd("متن")
async def text_mode(e, a):
    m = {"بولد": "bold", "bold": "bold", "ایتالیک": "italic", "italic": "italic",
         "مونو": "mono", "mono": "mono", "اسپویلر": "spoiler", "spoiler": "spoiler"}
    if a in ("خاموش", "off"):
        cfg["textmode"] = None
    elif a in m:
        cfg["textmode"] = m[a]
    else:
        raise ValueError("بولد / ایتالیک / مونو / اسپویلر / خاموش")
    save()
    await out(e, f"✍️ حالت متن: {cfg['textmode'] or '⛔ خاموش'}")


WRAP = {"bold": ("**", "**"), "italic": ("__", "__"), "mono": ("`", "`"), "spoiler": ("||", "||")}


async def style_text(e, text):
    m = cfg["textmode"]
    if not m or e.message.media or e.message.fwd_from:
        return
    a, b = WRAP[m]
    try:
        await e.edit(f"{a}{text}{b}")
    except Exception:
        pass


# ---------- ابزارها ----------
@cmd("هوا")
async def weather(e, a):
    city = a or "Tehran"
    r = await asyncio.to_thread(
        requests.get, f"https://wttr.in/{quote(city)}?format=3&lang=fa", timeout=10)
    await out(e, "🌤 " + r.text.strip())


@cmd("ارز")
async def fx(e, a):
    p = a.translate(FA_DIGITS).upper().split()
    if len(p) == 3:
        amt, fr, to = float(p[0]), p[1], p[2]
    elif len(p) == 2:
        amt, fr, to = 1.0, p[0], p[1]
    else:
        raise ValueError("مثال: .ارز 100 USD EUR")
    j = await asyncio.to_thread(
        lambda: requests.get(f"https://open.er-api.com/v6/latest/{fr}", timeout=10).json())
    rate = j.get("rates", {}).get(to)
    if rate is None:
        raise ValueError("ارز نامعتبر")
    await out(e, f"💱 {amt:g} {fr} = {amt * rate:,.4f} {to}")


@cmd("کریپتو")
async def crypto(e, a):
    cid = (a or "bitcoin").lower()
    j = await asyncio.to_thread(lambda: requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": cid, "vs_currencies": "usd", "include_24hr_change": "true"},
        timeout=10).json())
    if cid not in j:
        raise ValueError("اسم ارز درست نیست (مثلا bitcoin)")
    d = j[cid]
    await out(e, f"🪙 {cid}: ${d['usd']:,} ({d.get('usd_24h_change', 0):+.2f}%)")


@cmd("ترجمه")
async def translate(e, a):
    from deep_translator import GoogleTranslator
    lang, text = "fa", a
    parts = a.split(None, 1)
    if parts and re.fullmatch(r"[a-z]{2}(-[A-Za-z]{2})?", parts[0]):
        lang = parts[0]
        text = parts[1] if len(parts) > 1 else ""
    if not text and e.is_reply:
        text = (await e.get_reply_message()).raw_text or ""
    if not text:
        raise ValueError("متن بده یا ریپلای کن. مثال: .ترجمه en سلام")
    res = await asyncio.to_thread(
        lambda: GoogleTranslator(source="auto", target=lang).translate(text))
    await out(e, f"🌐 {res}")


OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
       ast.FloorDiv: operator.floordiv, ast.USub: operator.neg}


def calc_node(n):
    if isinstance(n, ast.Expression):
        return calc_node(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in OPS:
        l, r = calc_node(n.left), calc_node(n.right)
        if isinstance(n.op, ast.Pow) and abs(r) > 100:
            raise ValueError("توان خیلی بزرگه")
        return OPS[type(n.op)](l, r)
    if isinstance(n, ast.UnaryOp) and type(n.op) in OPS:
        return OPS[type(n.op)](calc_node(n.operand))
    raise ValueError("عبارت نامعتبر")


@cmd("محاسبه")
async def calc(e, a):
    expr = a.translate(FA_DIGITS).replace("×", "*").replace("÷", "/").replace("^", "**")
    res = calc_node(ast.parse(expr, mode="eval"))
    await out(e, f"🧮 {a} = {res:g}" if isinstance(res, float) else f"🧮 {a} = {res}")


@cmd("هوش مصنوعی")
async def ai(e, a):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("متغیر ANTHROPIC_API_KEY تنظیم نشده")
    q = a or ((await e.get_reply_message()).raw_text if e.is_reply else "")
    if not q:
        raise ValueError("سوالت رو بنویس")

    def ask():
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-5-5", "max_tokens": 800,
                  "messages": [{"role": "user", "content": q}]},
            timeout=60)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])

    await out(e, "🤖 " + await asyncio.to_thread(ask))


# ---------- گروه ----------
async def do_tag(e, text, limit):
    if e.is_private:
        raise ValueError("فقط توی گروه")
    users = [u async for u in client.iter_participants(e.chat_id, limit=limit)
             if not u.bot and not u.deleted]
    reply_to = e.reply_to_msg_id
    await e.delete()
    for i in range(0, len(users), 5):
        names = " ".join(
            f"[{re.sub(r'[][()*_`~|]', '', (u.first_name or 'user'))[:15] or 'user'}](tg://user?id={u.id})"
            for u in users[i:i + 5])
        await client.send_message(e.chat_id, f"{text}\n{names}".strip(), reply_to=reply_to)
        await asyncio.sleep(2)


@cmd("تگ")
async def tag(e, a):
    if a.isdigit():                     # .تگ 20 ← ۲۰ نفر
        await do_tag(e, "", min(int(a), 500))
    else:                               # .تگ متن ← ۱۰۰ نفر با متن
        await do_tag(e, a, 100)


@cmd("همه")
async def tag_all(e, a):
    await do_tag(e, a, 1000)


@cmd("حذف")
async def delete_mine(e, a):
    if e.is_reply and not a.isdigit():  # .حذف با ریپلای ← همون پیام + دستور
        r = await e.get_reply_message()
        await client.delete_messages(e.chat_id, [r.id, e.id])
        return
    n = int(a) if a.isdigit() else 1
    ids = [m.id async for m in client.iter_messages(e.chat_id, from_user="me", limit=n + 1)]
    await client.delete_messages(e.chat_id, ids)


@cmd("بن", "سیک")
async def ban(e, a):
    uid = await target(e, a)
    await client.edit_permissions(e.chat_id, uid, view_messages=False)
    await out(e, "⛔ بن شد")


@cmd("آنبن", "آن بن")
async def unban(e, a):
    uid = await target(e, a)
    await client.edit_permissions(e.chat_id, uid, view_messages=True)
    await out(e, "✅ آنبن شد")


@cmd("پین")
async def pin(e, a):
    if not e.is_reply:
        raise ValueError("روی یه پیام ریپلای کن")
    await client.pin_message(e.chat_id, e.reply_to_msg_id)
    await e.delete()


@cmd("حذف پین")
async def unpin(e, a):
    if not e.is_reply:
        raise ValueError("روی یه پیام ریپلای کن")
    await client.unpin_message(e.chat_id, e.reply_to_msg_id)
    await e.delete()


# ---------- امنیت ----------
@cmd("بلاک")
async def block(e, a):
    uid = await target(e, a)
    await client(functions.contacts.BlockRequest(id=await client.get_input_entity(uid)))
    await out(e, "⛔ بلاک شد")


@cmd("آنبلاک")
async def unblock(e, a):
    uid = await target(e, a)
    await client(functions.contacts.UnblockRequest(id=await client.get_input_entity(uid)))
    await out(e, "✅ آنبلاک شد")


@cmd("سکوت")
async def mute(e, a):
    uid = await target(e, a)
    k = f"{e.chat_id}:{uid}"
    if k not in cfg["muted"]:
        cfg["muted"].append(k)
    save()
    await out(e, "🔇 سکوت شد (پیام‌هاش پاک می‌شه؛ توی گروه باید ادمین باشی)")


@cmd("رفع سکوت")
async def unmute(e, a):
    uid = await target(e, a)
    k = f"{e.chat_id}:{uid}"
    if k in cfg["muted"]:
        cfg["muted"].remove(k)
    save()
    await out(e, "🔊 سکوت برداشته شد")


@cmd("فیلتر")
async def add_filter(e, a):
    words = cfg["filters"].setdefault(str(e.chat_id), [])
    if not a:
        return await out(e, "🚫 فیلترها: " + ("، ".join(words) or "خالی"))
    if a not in words:
        words.append(a)
    save()
    await out(e, f"🚫 فیلتر شد: {a} (توی گروه باید ادمین باشی)")


@cmd("حذف فیلتر")
async def del_filter(e, a):
    words = cfg["filters"].get(str(e.chat_id), [])
    if a in words:
        words.remove(a)
        save()
    await out(e, f"✅ فیلتر برداشته شد: {a}")


@cmd("بکاپ")
async def backup(e, a):
    n = int(a) if a.isdigit() else 1000
    path = f"backup_{abs(e.chat_id)}.txt"
    with open(path, "w", encoding="utf-8") as f:
        async for m in client.iter_messages(e.chat_id, limit=n):
            body = m.text or (f"<{type(m.media).__name__}>" if m.media else "")
            f.write(f"[{m.date:%Y-%m-%d %H:%M}] {m.sender_id}: {body}\n")
    await client.send_file("me", path, caption=f"بکاپ چت {e.chat_id}")
    os.remove(path)
    await out(e, "✅ بکاپ به Saved Messages فرستاده شد")


# ---------- خودکارها ----------
@cmd("پاسخ")
async def add_reply(e, a):
    if "|" not in a:
        raise ValueError("مثال: .پاسخ سلام | سلام عزیزم")
    k, v = (x.strip() for x in a.split("|", 1))
    cfg["autoreplies"][k] = v
    save()
    await out(e, f"✅ پاسخ خودکار ثبت شد: {k}")


@cmd("حذف پاسخ")
async def del_reply(e, a):
    cfg["autoreplies"].pop(a, None)
    save()
    await out(e, f"✅ پاسخ حذف شد: {a}")


@cmd("ری اکشن")
async def react_cmd(e, a):
    p = a.split()
    on = parse_onoff(a)
    cfg["react"] = (p[1] if len(p) > 1 else "❤") if on else None
    save()
    await out(e, f"❤ ری‌اکشن خودکار: {cfg['react'] or '⛔ خاموش'}")


# ---------- هندلرها ----------
hooks = features.setup(client, cfg, save, cmd, out, target)
extra_hooks = extras.setup_extras(client, cfg, save, cmd, out, target, bot_state)
more_hooks = more.setup_more(client, cfg, save, cmd, out, target, bot_state, COMMANDS, PREFIX)


def match_command(body):
    """طولانی‌ترین نام دستور (تا ۴ کلمه) رو پیدا می‌کنه. خروجی: (تابع، آرگومان)."""
    words = body.split()
    for n in (4, 3, 2, 1):
        if len(words) >= n:
            name = " ".join(words[:n])
            if name in COMMANDS:
                pieces = body.split(None, n)
                return COMMANDS[name], (pieces[n] if len(pieces) > n else "")
    return None, ""


@client.on(events.NewMessage(outgoing=True))
async def router(e):
    if not cfg["enabled"]:
        return
    text = (e.raw_text or "").strip()
    if not text:
        return
    prefix = cfg.get("prefix") or PREFIX
    if not text.startswith(prefix):
        if text.startswith(PREFIX + "پرفیکس"):   # نجات: با نقطه همیشه می‌شه پرفیکس رو برگردوند
            prefix = PREFIX
        else:
            prefix = None
    if prefix is None:
        try:
            if await hooks["outgoing"](e, text):   # جایگزینی «محتوا»
                return
        except Exception as ex:
            print("content error:", ex)
        await style_text(e, text)
        return
    fn, arg = match_command(text[len(prefix):].strip())
    if not fn:
        return
    try:
        await fn(e, arg)
    except Exception as ex:
        await out(e, f"❌ {ex}")


async def fake_action(chat, act):
    try:
        async with client.action(chat, act):
            await asyncio.sleep(6)
    except Exception:
        pass


async def on_incoming(e):
    if not cfg["enabled"]:
        return
    if await hooks["incoming"](e):   # بن سراسری / پاسخ به دوستان
        return
    if f"{e.chat_id}:{e.sender_id}" in cfg["muted"]:
        await e.delete()
        return
    words = cfg["filters"].get(str(e.chat_id))
    if words and e.raw_text and any(w in e.raw_text for w in words):
        await e.delete()
        return
    for h in (extra_hooks["incoming"], more_hooks["incoming"]):   # دشمن/اسکرین خودکار، نگهبان، عضویت اجباری
        try:
            if await h(e):
                return
        except Exception as ex:
            print("hook error:", ex)
    if not e.is_private:
        return
    sender = await e.get_sender()
    if getattr(sender, "bot", False):
        return
    # پیام‌های رسمی تلگرام (۷۷۷۰۰۰ = کد ورود) نباید پاک بشن
    if cfg["pvlock"] and e.sender_id != 777000 and not getattr(sender, "contact", False):
        await e.delete()
        return
    if cfg["autoseen"]:
        await e.message.mark_read()
    if cfg["action"]:
        asyncio.create_task(fake_action(e.chat_id, cfg["action"]))
    if cfg["react"]:
        try:
            await client(functions.messages.SendReactionRequest(
                peer=await e.get_input_chat(), msg_id=e.id,
                reaction=[types.ReactionEmoji(emoticon=cfg["react"])]))
        except Exception:
            pass
    text = e.raw_text or ""
    for k, v in cfg["autoreplies"].items():
        if k in text:
            key = (e.sender_id, k)   # کول‌داون ۳۰ ثانیه؛ جلوی حلقه‌ی پاسخ با بات‌های دیگه
            if time.time() - autoreply_seen.get(key, 0) > 30:
                autoreply_seen[key] = time.time()
                await e.reply(v)
            return
    if cfg["secretary"] and time.time() - secretary_seen.get(e.sender_id, 0) > 6 * 3600:
        secretary_seen[e.sender_id] = time.time()
        await e.reply(cfg["secretary_text"])


@client.on(events.NewMessage(incoming=True))
async def incoming(e):
    try:
        await on_incoming(e)
    except Exception as ex:
        print("incoming error:", ex)


active = {"on": False, "tasks": []}


async def cfg_watch_loop():
    """پنل مشترک (بات هلپر توی هاب) فایل کانفیگ رو عوض می‌کنه؛ اینجا تغییرها رو اعمال می‌کنیم."""
    last = os.path.getmtime(CFG_FILE) if os.path.exists(CFG_FILE) else 0
    while True:
        await asyncio.sleep(2)
        try:
            m = os.path.getmtime(CFG_FILE)
            if m == last:
                continue
            last = m
            with open(CFG_FILE, encoding="utf-8") as f:
                new = json.load(f)
            changed = [k for k, v in new.items() if k in cfg and cfg[k] != v]
            cfg.update({k: new[k] for k in changed})
            for k in changed:
                await on_change(k)
        except Exception as ex:
            print("cfg watch error:", ex)


async def set_enabled(v):
    cfg["enabled"] = v
    save()
    try:
        if v:
            clock_state["shown"] = None
            await apply_clock()
        else:
            await restore_name()
    except Exception as ex:
        print("set_enabled error:", ex)


async def on_change(key):
    try:
        if key == "enabled":
            await set_enabled(cfg["enabled"])
            return
        if key == "clock_mode" or (key == "clock" and not cfg["clock"]):
            await restore_name()
        await apply_clock()
    except FloodWaitError as ex:
        print("flood wait:", ex.seconds)
    except Exception as ex:
        print("on_change error:", ex)


async def account_info():
    me = await client.get_me()
    if not me:
        return None
    name = f"{cfg['base_first'] or me.first_name or ''} {cfg['base_last'] or me.last_name or ''}".strip()
    return {"name": name or "-", "username": me.username, "id": me.id,
            "uptime": int((time.time() - START) // 60)}


async def restart_process():
    await asyncio.sleep(1.5)
    try:
        await client.disconnect()
    except Exception:
        pass
    os.execv(sys.executable, [sys.executable] + sys.argv)


async def delete_self():
    try:
        await restore_name()
    except Exception:
        pass
    await client.log_out()
    cfg["base_first"] = cfg["base_last"] = None
    save()
    asyncio.create_task(restart_process())


BANNER_DIR = os.getenv("BANNER_DIR", "banners")


async def update_banner():
    """بنر «NRT self» با عکس پروفایل فعلی خودت (وسط دایره) برای پنل می‌سازه."""
    me = await client.get_me()
    await refresh_banner(client, os.path.join(BANNER_DIR, f"user_{me.id}.jpg"))


async def banner_loop():
    while True:
        try:
            await update_banner()
        except Exception as ex:
            print("banner error:", ex)
        await asyncio.sleep(600)   # هر ۱۰ دقیقه؛ اگه عکس پروفایلت عوض شد بنر هم عوض می‌شه


async def activate():
    if active["on"]:
        return
    active["on"] = True
    await snapshot_name()
    me = await client.get_me()
    try:
        await update_banner()   # قبل از ساخت پنل، بنر آماده باشه
    except Exception as ex:
        print("banner error:", ex)
    if HUB_HELPER:
        bot_state["client"] = True
        bot_state["username"] = HUB_HELPER
    if HELPER_TOKEN and not HUB_HELPER and not bot_state.get("client"):
        helper = TelegramClient("panel_bot", API_ID, API_HASH)
        await helper.start(bot_token=HELPER_TOKEN)
        bot_state["client"] = helper
        bot_state["username"] = (await helper.get_me()).username
        setup_panel(helper, me.id, cfg, save, on_change, {"info": info_text, "ping": ping_text})
        setup_games(helper)   # بازی‌های گروهی روی همین بات هلپر
        extra_hooks["after_helper"]()   # پنل کنترل لایو روی همین بات هلپر
    loops = [clock_loop, online_loop, antilogin_loop, banner_loop] + ([cfg_watch_loop] if HUB_HELPER else [])
    loops += extra_hooks["loops"] + more_hooks["loops"]
    active["tasks"] = [asyncio.create_task(f()) for f in loops]
    print("NRT Self is active. Send .راهنما or .پنل in any chat.")


async def main_child():
    """پروسه‌ی سلف یک کاربر (توسط hub.py اجرا می‌شه). با SIGTERM اسم رو برمی‌گردونه و خارج می‌شه."""
    import signal
    await client.connect()
    if not await client.is_user_authorized():
        print("child: session not authorized")
        sys.exit(3)
    loop = asyncio.get_running_loop()

    async def shutdown():
        try:
            await asyncio.wait_for(restore_name(), 10)
        except Exception:
            pass
        await client.disconnect()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    await activate()
    try:
        await client.run_until_disconnected()
    except (AuthKeyUnregisteredError, SessionRevokedError, UserDeactivatedError, UserDeactivatedBanError):
        print("child: session revoked")
        sys.exit(3)


async def main():
    if "--child" in sys.argv:
        await main_child()
        return
    if "--login" in sys.argv:  # لاگین از ترمینال (اگه بات مدیریت نمی‌خوای)
        await client.start()
        print("✅ لاگین انجام شد")
        await client.disconnect()
        return
    await client.connect()
    manager_ready = False
    if MANAGER_TOKEN and OWNER_ID:
        mgr = TelegramClient("manager_bot", API_ID, API_HASH)
        await mgr.start(bot_token=MANAGER_TOKEN)
        setup_manager(mgr, OWNER_ID, client, cfg, {
            "activate": activate, "info": account_info, "set_enabled": set_enabled,
            "delete": delete_self, "restart": restart_process}, BANNER_PATH)
        manager_ready = True
        print("Manager bot: @" + (await mgr.get_me()).username)
    elif MANAGER_TOKEN:
        print("⚠️ OWNER_ID تنظیم نشده؛ بات مدیریت غیرفعاله")
    if await client.is_user_authorized():
        await activate()
    elif manager_ready:
        print("لاگین نیستی؛ توی بات مدیریت /start بزن و «فعالسازی سلف» رو بزن.")
    else:
        print("لاگین نیستی: یا MANAGER_BOT_TOKEN + OWNER_ID بذار، یا بزن: python self_bot.py --login")
        return
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
