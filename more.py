"""
قابلیت‌های تکمیلی ۲ (طبق منوی LTM Self):
پرفیکس، جوین از پیام، عضویت اجباری، کامنت اول خودکار، نگهبان چت، کاربردی (آیدی/تاریخ/یادآوری/...)،
دانلود، اسکرین سایت، مدیریت گروه، تقلب (تاس/دارت/...)، چالش استارزی و بازی گربه.

نکته: «ایموجی پریمیوم»، «ایموجی پریمیوم چنل»، «کارخونه میوی»، «میو خودکار»، «پیشی خودکار» و
«ماهی‌گیری خودکار» عمداً اضافه نشدن.
"""
import asyncio
import glob
import io
import ipaddress
import os
import random
import re
import shutil
import socket
import tempfile
import time
from datetime import datetime
from urllib.parse import quote, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from telethon import errors, events, functions, types

TZ = ZoneInfo("Asia/Tehran")
FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
DOMAIN_RE = re.compile(r"^(https?://)?([\w-]+\.)+[a-z]{2,}(:\d+)?(/\S*)?$", re.I)
TME_RE = re.compile(r"(?:https?://)?t\.me/(\+[\w-]+|joinchat/[\w-]+|[A-Za-z]\w{3,31})", re.I)
AT_RE = re.compile(r"(?<![\w/])@([A-Za-z]\w{3,31})")
TME_SKIP = {"joinchat", "addstickers", "addemoji", "c", "s", "share", "proxy", "socks", "login",
            "addtheme", "setlanguage", "bg", "iv", "boost", "m", "invoice", "giftcode"}

FILE_EXT = (".mp4", ".mkv", ".webm", ".mov", ".mp3", ".m4a", ".ogg", ".wav", ".jpg", ".jpeg", ".png",
            ".gif", ".webp", ".pdf", ".zip", ".rar", ".7z", ".apk", ".txt")
MAX_DL = 200 * 1024 * 1024

CHEAT = {"تاس": ("🎲", 6), "دارت": ("🎯", 6), "بولینگ": ("🎳", 6), "بسکتبال": ("🏀", 5),
         "فوتبال": ("⚽", 5), "کازینو": ("🎰", 64)}

GUARD_TYPES = {"لینک": "link", "فوروارد": "forward", "منشن": "mention", "استیکر": "sticker", "گیف": "gif"}
GUARD_FA = {v: k for k, v in GUARD_TYPES.items()}

UNITS = {"s": 1, "sec": 1, "ثانیه": 1, "m": 60, "min": 60, "دقیقه": 60,
         "h": 3600, "ساعت": 3600, "d": 86400, "روز": 86400}

WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
JMONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
           "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


# ================= توابع خالص (قابل تست بدون تلگرام) =================
def g2j(gy, gm, gd):
    """تبدیل تاریخ میلادی به شمسی."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
            + gd + g_d_m[gm - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def parse_duration(tokens):
    """['10','دقیقه','متن'] یا ['30m','متن'] ← (ثانیه، متن)"""
    if not tokens:
        raise ValueError("مثال: .یادآوری 30 دقیقه زنگ بزن به علی")
    m = re.fullmatch(r"(\d+)([A-Za-zآ-ی]*)", tokens[0].translate(FA))
    if not m:
        raise ValueError("مثال: .یادآوری 30 دقیقه زنگ بزن به علی")
    n, unit, rest = int(m.group(1)), m.group(2), tokens[1:]
    if not unit:
        if rest and rest[0] in UNITS:
            unit, rest = rest[0], rest[1:]
        else:
            unit = "m"
    if unit not in UNITS:
        raise ValueError("واحد زمان: ثانیه / دقیقه / ساعت / روز")
    secs = n * UNITS[unit]
    if not 5 <= secs <= 365 * 86400:
        raise ValueError("زمان باید بین ۵ ثانیه تا ۱ سال باشه")
    return secs, " ".join(rest)


def host_is_public(url):
    """جلوگیری از SSRF: فقط آدرس‌های عمومی اینترنت (نه localhost/شبکه‌ی داخلی)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except OSError:
        return False
    for i in infos:
        ip = ipaddress.ip_address(i[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def direct_download(url, wd, limit=MAX_DL):
    cur = url
    for _ in range(5):
        if not host_is_public(cur):
            raise ValueError("این آدرس مجاز نیست")
        r = requests.get(cur, stream=True, timeout=20, allow_redirects=False,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code in (301, 302, 303, 307, 308):
            cur = urljoin(cur, r.headers.get("Location", ""))
            r.close()
            continue
        break
    else:
        raise ValueError("ریدایرکت بیش از حد")
    r.raise_for_status()
    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype in ("text/html", "application/xhtml+xml"):
        r.close()
        raise ValueError("لینک، فایل مستقیم نیست")
    name = os.path.basename(urlparse(cur).path) or "file"
    cd = r.headers.get("content-disposition", "")
    m = re.search(r'filename="?([^";]+)', cd)
    if m:
        name = os.path.basename(m.group(1))
    name = re.sub(r"[^\w.\-]", "_", name)[:80] or "file"
    path = os.path.join(wd, name)
    size = 0
    with open(path, "wb") as f:
        for chunk in r.iter_content(65536):
            size += len(chunk)
            if size > limit:
                raise ValueError("فایل بزرگ‌تر از ۲۰۰ مگابایته")
            f.write(chunk)
    return path


def ytdl_download(url, wd, audio):
    import yt_dlp
    ff = bool(shutil.which("ffmpeg"))
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "restrictfilenames": True,
            "outtmpl": os.path.join(wd, "%(title).60s.%(ext)s"),
            "max_filesize": 500 * 1024 * 1024}
    if audio:
        opts["format"] = "bestaudio/best"
        if ff:
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
    else:
        opts["format"] = ("bv*[height<=720]+ba/b[height<=720]/best" if ff
                          else "best[height<=720]/best")
        if ff:
            opts["merge_output_format"] = "mp4"
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([url])
    files = [p for p in glob.glob(os.path.join(wd, "*")) if not p.endswith((".part", ".ytdl"))]
    if not files:
        raise ValueError("چیزی دانلود نشد")
    return max(files, key=os.path.getsize)


def fetch_site_shot(url):
    r = requests.get("https://image.thum.io/get/width/1280/crop/800/noanimate/" + url, timeout=60)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        raise ValueError("اسکرین سایت گرفته نشد (سرویس جواب نداد)")
    return r.content


def cat_decay(cat, now=None):
    """کم‌شدن تدریجی سیری/خوشحالی با گذشت زمان."""
    now = now or time.time()
    hrs = max(0.0, (now - cat.get("last", now)) / 3600)
    cat["food"] = max(0, round(cat["food"] - 4 * hrs))
    cat["mood"] = max(0, round(cat["mood"] - 3 * hrs))
    cat["energy"] = min(100, round(cat["energy"] + 2 * hrs))
    cat["last"] = now
    return cat


def bar(v):
    n = max(0, min(10, round(v / 10)))
    return "▰" * n + "▱" * (10 - n)


def cat_status(cat):
    lvl = cat["xp"] // 20 + 1
    avg = (cat["food"] + cat["mood"] + cat["energy"]) / 3
    face = "😸" if avg >= 66 else ("😺" if avg >= 33 else "😿")
    return (f"{face} {cat['name']} | سطح {lvl} | XP {cat['xp']}\n"
            f"🍗 سیری   {bar(cat['food'])} {cat['food']}\n"
            f"🧶 شادی   {bar(cat['mood'])} {cat['mood']}\n"
            f"⚡ انرژی  {bar(cat['energy'])} {cat['energy']}")


# ================= نصب روی سلف =================
def setup_more(client, cfg, save, cmd, out, target, bot_state, commands, default_prefix):
    cfg.setdefault("prefix", default_prefix)
    cfg.setdefault("force_join", {"channel": None, "channel_id": None, "link": None, "chats": []})
    cfg.setdefault("guard", {})
    cfg.setdefault("fc_on", False)
    cfg.setdefault("fc_text", "اول 🔥")
    cfg.setdefault("fc_channels", [])
    cfg.setdefault("reminders", [])
    cfg.setdefault("cat", None)
    cfg.setdefault("starzi_challenge", {"on": False, "days": 30, "day": 0})
    save()

    me_cache = {}
    admin_cache = {}
    member_cache = {}
    warn_seen = {}

    async def my_id():
        if "id" not in me_cache:
            me_cache["id"] = (await client.get_me()).id
        return me_cache["id"]

    async def need_reply(e):
        if not e.is_reply:
            raise ValueError("روی یه پیام ریپلای کن")
        return await e.get_reply_message()

    def need_group(e):
        if e.is_private:
            raise ValueError("این دستور فقط توی گروه کار می‌کنه")

    def onoff(w):
        if w in ("روشن", "on", "1"):
            return True
        if w in ("خاموش", "off", "0"):
            return False
        raise ValueError("بنویس: روشن یا خاموش")

    async def get_text_and_urls(e, a):
        text = a or ""
        if e.is_reply:
            r = await e.get_reply_message()
            text += "\n" + (r.raw_text or "")
            for ent in (r.entities or []):
                if isinstance(ent, types.MessageEntityTextUrl):
                    text += "\n" + ent.url
        return text

    # ===================== پرفیکس =====================
    @cmd("پرفیکس")
    async def prefix_cmd(e, a):
        a = a.strip()
        if not a:
            return await out(e, f"🔣 پرفیکس فعلی: {cfg['prefix']}\n"
                                "تغییر: .پرفیکس /   |   برگشت به نقطه: .پرفیکس پیش‌فرض\n"
                                "(دستور «.پرفیکس» با نقطه همیشه کار می‌کنه، حتی اگه پرفیکس رو عوض کرده باشی)")
        if a in ("پیش‌فرض", "پیشفرض", "ریست", "default"):
            new = default_prefix
        else:
            if len(a) > 2 or any(ch.isalnum() or ch.isspace() for ch in a) or "@" in a:
                raise ValueError("پرفیکس باید ۱ یا ۲ نماد باشه (مثل / ! # $ .) نه حرف و عدد")
            new = a
        cfg["prefix"] = new
        save()
        await out(e, f"✅ پرفیکس شد: {new}\nمثال: {new}پینگ")

    # ===================== جوین از پیام =====================
    @cmd("جوین از پیام", "جوین")
    async def join_cmd(e, a):
        text = await get_text_and_urls(e, a)
        found = []
        for m in TME_RE.finditer(text):
            tok = m.group(1)
            if tok.lower() in TME_SKIP:
                continue
            found.append(tok)
        for m in AT_RE.finditer(text):
            found.append(m.group(1))
        uniq = list(dict.fromkeys(found))[:15]
        if not uniq:
            raise ValueError("لینک یا یوزرنیمی پیدا نشد. روی پیامی که لینک گروه/کانال داره ریپلای کن")
        await out(e, f"⏳ در حال جوین به {len(uniq)} مورد...")
        ok = already = bad = 0
        for tok in uniq:
            try:
                if tok.startswith("+") or tok.lower().startswith("joinchat/"):
                    h = tok[1:] if tok.startswith("+") else tok.split("/", 1)[1]
                    await client(functions.messages.ImportChatInviteRequest(h))
                else:
                    await client(functions.channels.JoinChannelRequest(tok))
                ok += 1
            except errors.UserAlreadyParticipantError:
                already += 1
            except errors.FloodWaitError as ex:
                await out(e, f"⏳ تلگرام محدود کرد؛ {ex.seconds} ثانیه صبر کن.\n✅ {ok} جوین شد")
                return
            except Exception:
                bad += 1
            await asyncio.sleep(3)
        await out(e, f"✅ جوین شد: {ok}\n♻️ از قبل عضو بودی: {already}\n❌ ناموفق: {bad}")

    # ===================== عضویت اجباری =====================
    @cmd("عضویت اجباری")
    async def force_join_cmd(e, a):
        fj = cfg["force_join"]
        p = a.split(None, 1)
        w = p[0] if p else ""
        if w == "تنظیم":
            if len(p) < 2:
                raise ValueError("مثال: .عضویت اجباری تنظیم @mychannel")
            ent = await client.get_entity(p[1].strip())
            if not isinstance(ent, types.Channel) or ent.megagroup:
                raise ValueError("باید یه کانال باشه")
            fj["channel"] = ent.username and "@" + ent.username or await client.get_peer_id(ent)
            fj["channel_id"] = await client.get_peer_id(ent)
            link = f"https://t.me/{ent.username}" if ent.username else None
            if not link:
                try:
                    link = (await client(functions.messages.ExportChatInviteRequest(ent))).link
                except Exception:
                    link = None
            fj["link"] = link
            member_cache.clear()
            save()
            return await out(e, f"✅ کانال عضویت اجباری: {ent.title}\nحالا توی هر گروه بنویس: .عضویت اجباری روشن")
        if w in ("روشن", "on"):
            need_group(e)
            if not fj["channel"]:
                raise ValueError("اول کانال رو تنظیم کن: .عضویت اجباری تنظیم @channel")
            if e.chat_id not in fj["chats"]:
                fj["chats"].append(e.chat_id)
            save()
            return await out(e, "✅ عضویت اجباری برای این گروه روشن شد (باید ادمین با دسترسی حذف پیام باشی)")
        if w in ("خاموش", "off"):
            need_group(e)
            if e.chat_id in fj["chats"]:
                fj["chats"].remove(e.chat_id)
            save()
            return await out(e, "⏸ عضویت اجباری این گروه خاموش شد")
        st = "روشن" if e.chat_id in fj["chats"] else "خاموش"
        await out(e, f"📢 کانال: {fj['link'] or fj['channel'] or 'تنظیم نشده'}\n"
                     f"گروه‌های فعال: {len(fj['chats'])}\nاین گروه: {st}\n\n"
                     ".عضویت اجباری تنظیم @channel | روشن | خاموش")

    async def is_admin_in(chat, uid):
        k, now = (chat, uid), time.time()
        c = admin_cache.get(k)
        if c and now - c[0] < 120:
            return c[1]
        try:
            p = await client.get_permissions(chat, uid)
            v = bool(p.is_admin or p.is_creator)
        except Exception:
            v = True   # اگه نتونستیم بفهمیم، پیامش رو پاک نمی‌کنیم
        admin_cache[k] = (now, v)
        return v

    async def force_member(uid):
        fj = cfg["force_join"]
        c, now = member_cache.get(uid), time.time()
        if c and now - c[0] < (300 if c[1] else 20):
            return c[1]
        try:
            ch = await client.get_input_entity(fj["channel_id"] or fj["channel"])
            await client(functions.channels.GetParticipantRequest(channel=ch, participant=uid))
            v = True
        except errors.UserNotParticipantError:
            v = False
        except Exception:
            v = True   # خطای دسترسی/شبکه ← کسی رو بی‌دلیل پاک نمی‌کنیم
        member_cache[uid] = (now, v)
        return v

    async def temp_warn(chat, text, reply_to=None):
        try:
            m = await client.send_message(chat, text, reply_to=reply_to, link_preview=False)
            await asyncio.sleep(12)
            await m.delete()
        except Exception:
            pass

    # ===================== نگهبان چت =====================
    @cmd("نگهبان", "نگهبان چت")
    async def guard_cmd(e, a):
        need_group(e)
        key = str(e.chat_id)
        g = cfg["guard"].setdefault(key, {"on": False, "link": True, "forward": True, "mention": True,
                                          "sticker": False, "gif": False})
        p = a.split()
        if not p or p[0] == "وضعیت":
            rows = [f"{'✅' if g[t] else '⬜'} {GUARD_FA[t]}" for t in GUARD_FA]
            return await out(e, f"🛡 نگهبان چت: {'✅ روشن' if g['on'] else '⛔ خاموش'}\n" + "\n".join(rows) +
                             "\n\n.نگهبان روشن | خاموش\n.نگهبان لینک روشن | فوروارد | منشن | استیکر | گیف")
        if p[0] in ("روشن", "خاموش"):
            g["on"] = p[0] == "روشن"
            save()
            return await out(e, f"🛡 نگهبان چت: {'✅ روشن' if g['on'] else '⛔ خاموش'}"
                                "\n(پیام غیرادمین‌ها طبق نوع‌های فعال پاک می‌شه؛ باید ادمین باشی)")
        if p[0] in GUARD_TYPES and len(p) > 1:
            g[GUARD_TYPES[p[0]]] = onoff(p[1])
            save()
            return await out(e, f"🛡 {p[0]}: {'✅ فعال' if g[GUARD_TYPES[p[0]]] else '⛔ غیرفعال'}")
        raise ValueError("مثال: .نگهبان روشن | .نگهبان لینک خاموش")

    def violates(m, g):
        ents = m.entities or []
        txt = m.raw_text or ""
        if g.get("link") and (any(isinstance(x, (types.MessageEntityUrl, types.MessageEntityTextUrl))
                                  for x in ents) or re.search(r"(t\.me/|https?://|www\.)", txt, re.I)):
            return True
        if g.get("forward") and m.fwd_from:
            return True
        if g.get("mention") and (any(isinstance(x, types.MessageEntityMention) for x in ents) or AT_RE.search(txt)):
            return True
        if g.get("sticker") and m.sticker:
            return True
        if g.get("gif") and m.gif:
            return True
        return False

    # ===================== کامنت اول خودکار =====================
    @cmd("کامنت اول", "کامنت اول خودکار")
    async def fc_cmd(e, a):
        p = a.split(None, 1)
        w = p[0] if p else ""
        rest = p[1].strip() if len(p) > 1 else ""
        if w in ("روشن", "خاموش"):
            cfg["fc_on"] = w == "روشن"
            save()
            return await out(e, f"💬 کامنت اول خودکار: {'✅ روشن' if cfg['fc_on'] else '⛔ خاموش'}")
        if w == "متن":
            if not rest:
                raise ValueError("متن رو بنویس؛ چندتا رو با | جدا کن (رندوم انتخاب می‌شه)")
            cfg["fc_text"] = rest
            save()
            return await out(e, f"✅ متن کامنت: {rest}")
        if w in ("افزودن", "حذف"):
            if not rest:
                raise ValueError("یوزرنیم کانال رو بنویس: .کامنت اول افزودن @channel")
            ent = await client.get_entity(rest)
            cid = await client.get_peer_id(ent)
            if w == "افزودن":
                if cid not in cfg["fc_channels"]:
                    cfg["fc_channels"].append(cid)
            elif cid in cfg["fc_channels"]:
                cfg["fc_channels"].remove(cid)
            save()
            return await out(e, f"✅ {'اضافه' if w == 'افزودن' else 'حذف'} شد: {getattr(ent, 'title', rest)}")
        names = []
        for cid in cfg["fc_channels"]:
            try:
                names.append(getattr(await client.get_entity(cid), "title", str(cid)))
            except Exception:
                names.append(str(cid))
        await out(e, f"💬 کامنت اول: {'✅ روشن' if cfg['fc_on'] else '⛔ خاموش'}\nمتن: {cfg['fc_text']}\n"
                     "کانال‌ها:\n" + ("\n".join(f"• {n}" for n in names) or "خالی") +
                     "\n\n.کامنت اول روشن | خاموش | متن ... | افزودن @ch | حذف @ch")

    @client.on(events.NewMessage(incoming=True, func=lambda ev: ev.is_channel and not ev.is_group))
    async def on_channel_post(ev):
        if not cfg["enabled"] or not cfg["fc_on"] or ev.chat_id not in cfg["fc_channels"]:
            return
        try:
            text = random.choice([t.strip() for t in cfg["fc_text"].split("|") if t.strip()] or ["اول 🔥"])
            await client.send_message(ev.chat_id, text, comment_to=ev.id)
        except Exception as ex:
            print("first comment error:", ex)

    # ===================== کاربردی =====================
    @cmd("آیدی")
    async def id_cmd(e, a):
        me = await my_id()
        lines = [f"🆔 آیدی من: {me}", f"💬 آیدی این چت: {e.chat_id}"]
        if e.is_reply:
            r = await e.get_reply_message()
            s = await r.get_sender()
            name = " ".join(x for x in (getattr(s, "first_name", None), getattr(s, "last_name", None)) if x) \
                or getattr(s, "title", "") or "-"
            uname = f" @{s.username}" if getattr(s, "username", None) else ""
            lines.append(f"👤 فرستنده: {name}{uname} | {r.sender_id}")
        elif a:
            ent = await client.get_entity(int(a) if a.lstrip("-").isdigit() else a.split()[0])
            lines.append(f"🔎 {getattr(ent, 'first_name', None) or getattr(ent, 'title', '')} | {ent.id}")
        await out(e, "\n".join(lines))

    @cmd("تاریخ")
    async def date_cmd(e, a):
        now = datetime.now(TZ)
        jy, jm, jd = g2j(now.year, now.month, now.day)
        await out(e, f"📅 {WEEKDAYS[now.weekday()]} {jd} {JMONTHS[jm - 1]} {jy}\n"
                     f"🗓 {now:%Y-%m-%d}\n🕒 {now:%H:%M:%S} (تهران)")

    @cmd("لینک پیام")
    async def msg_link(e, a):
        r = await need_reply(e)
        chat = await e.get_chat()
        if getattr(chat, "username", None):
            link = f"https://t.me/{chat.username}/{r.id}"
        elif isinstance(chat, types.Channel):
            link = f"https://t.me/c/{chat.id}/{r.id}"
        else:
            raise ValueError("برای چت خصوصی/گروه معمولی لینک پیام وجود نداره")
        await out(e, f"🔗 {link}")

    @cmd("ذخیره")
    async def save_msg(e, a):
        r = await need_reply(e)
        await client.forward_messages("me", r)
        await out(e, "💾 توی Saved Messages ذخیره شد")

    @cmd("یادآوری")
    async def remind(e, a):
        if len(cfg["reminders"]) >= 50:
            raise ValueError("بیش از ۵۰ یادآوری فعال نمی‌شه")
        secs, text = parse_duration(a.split())
        if not text and e.is_reply:
            text = (await e.get_reply_message()).raw_text or ""
        if not text:
            raise ValueError("متن یادآوری رو هم بنویس")
        cfg["reminders"].append({"t": time.time() + secs, "text": text[:500]})
        save()
        when = datetime.fromtimestamp(time.time() + secs, TZ).strftime("%H:%M:%S")
        await out(e, f"⏰ یادآوری ثبت شد (ساعت {when}):\n{text[:200]}")

    @cmd("لیست یادآوری")
    async def remind_list(e, a):
        rows = [f"{i + 1}. {datetime.fromtimestamp(r['t'], TZ):%m-%d %H:%M} — {r['text'][:40]}"
                for i, r in enumerate(sorted(cfg["reminders"], key=lambda x: x["t"]))]
        await out(e, "⏰ یادآوری‌ها:\n" + ("\n".join(rows) or "خالی"))

    @cmd("پاکسازی یادآوری")
    async def remind_clear(e, a):
        cfg["reminders"] = []
        save()
        await out(e, "🧹 همه‌ی یادآوری‌ها پاک شد")

    async def reminder_loop():
        while True:
            await asyncio.sleep(5)
            if not cfg["enabled"]:
                continue
            now = time.time()
            due = [r for r in cfg["reminders"] if r["t"] <= now]
            if not due:
                continue
            cfg["reminders"] = [r for r in cfg["reminders"] if r["t"] > now]
            save()
            for r in due:
                try:
                    await client.send_message("me", f"🔔 یادآوری:\n{r['text']}")
                except Exception as ex:
                    print("reminder error:", ex)

    # ===================== دانلود =====================
    @cmd("دانلود")
    async def download(e, a):
        audio = False
        p = a.split(None, 1)
        if p and p[0] in ("صدا", "آهنگ", "mp3"):
            audio, a = True, (p[1] if len(p) > 1 else "")
        text = await get_text_and_urls(e, a)
        m = URL_RE.search(text)
        if not m:
            raise ValueError("لینک بده یا روی پیام لینک‌دار ریپلای کن.\nمثال: .دانلود لینک | .دانلود صدا لینک")
        url = m.group(0).rstrip(").,،")
        if not host_is_public(url):
            raise ValueError("این آدرس مجاز نیست")
        await out(e, "⏳ در حال دانلود...")
        reply_to = e.reply_to_msg_id
        with tempfile.TemporaryDirectory() as wd:
            path = None
            if urlparse(url).path.lower().endswith(FILE_EXT):
                try:
                    path = await asyncio.to_thread(direct_download, url, wd)
                except Exception:
                    path = None
            if path is None:
                try:
                    path = await asyncio.to_thread(ytdl_download, url, wd, audio)
                except Exception as ex_y:
                    try:
                        path = await asyncio.to_thread(direct_download, url, wd)
                    except Exception:
                        raise ValueError("دانلود نشد: " + str(ex_y)[:150])
            await client.send_file(e.chat_id, path, reply_to=reply_to, supports_streaming=True)
        await e.delete()

    # ===================== اسکرین سایت =====================
    @cmd("اسکرین")
    async def site_shot(e, a):
        text = await get_text_and_urls(e, a)
        m = URL_RE.search(text)
        url = m.group(0) if m else None
        if not url and a.strip() and DOMAIN_RE.match(a.strip().split()[0]):
            url = a.strip().split()[0]
        if not url:
            fn = commands.get("اسکرین صفحه")   # بدون لینک ← همون اسکرین چت قبلی
            if fn:
                return await fn(e, a)
            raise ValueError("لینک سایت رو بنویس: .اسکرین google.com")
        if not url.lower().startswith("http"):
            url = "https://" + url
        await out(e, "⏳ در حال گرفتن اسکرین سایت...")
        data = await asyncio.to_thread(fetch_site_shot, url)
        buf = io.BytesIO(data)
        buf.name = "site.png"
        await client.send_file(e.chat_id, buf, reply_to=e.reply_to_msg_id,
                               caption=f"🌐 {url}"[:200])
        await e.delete()

    # ===================== مدیریت گروه =====================
    GROUP_HELP = ("🛠 مدیریت گروه (باید ادمین باشی):\n"
                  "قفل گروه | بازکردن گروه\n"
                  "عنوان گروه متن | توضیحات گروه متن | لینک گروه\n"
                  "ترفیع | عزل | اخراج  (ریپلای یا آیدی)\n"
                  "لیست ادمین | حالت آرام ثانیه (۰ = خاموش)\n"
                  "بن | سیک | آنبن | پین | حذف پین | تگ | همه | حذف N | نگهبان | عضویت اجباری")

    @cmd("مدیریت گروه")
    async def group_help(e, a):
        await out(e, GROUP_HELP)

    async def set_lock(e, lock):
        need_group(e)
        chat = await e.get_chat()
        br = getattr(chat, "default_banned_rights", None)
        fields = dict(br.to_dict()) if br else {}
        fields.pop("_", None)
        fields["until_date"] = None
        for k in ("send_messages", "send_media", "send_stickers", "send_gifs",
                  "send_games", "send_inline", "embed_links", "send_polls"):
            fields[k] = lock
        await client(functions.messages.EditChatDefaultBannedRightsRequest(
            peer=await e.get_input_chat(), banned_rights=types.ChatBannedRights(**fields)))

    @cmd("قفل گروه")
    async def lock_group(e, a):
        await set_lock(e, True)
        await out(e, "🔒 گروه قفل شد (فقط ادمین‌ها می‌تونن پیام بدن)")

    @cmd("بازکردن گروه", "باز کردن گروه")
    async def unlock_group(e, a):
        await set_lock(e, False)
        await out(e, "🔓 گروه باز شد")

    @cmd("عنوان گروه")
    async def set_title(e, a):
        need_group(e)
        if not a:
            raise ValueError("عنوان جدید رو بنویس")
        chat = await e.get_chat()
        if isinstance(chat, types.Channel):
            await client(functions.channels.EditTitleRequest(chat, a[:128]))
        else:
            await client(functions.messages.EditChatTitleRequest(chat.id, a[:128]))
        await out(e, "✅ عنوان گروه عوض شد")

    @cmd("توضیحات گروه")
    async def set_about(e, a):
        need_group(e)
        await client(functions.messages.EditChatAboutRequest(peer=await e.get_input_chat(), about=a[:255]))
        await out(e, "✅ توضیحات گروه عوض شد")

    @cmd("لینک گروه")
    async def group_link(e, a):
        need_group(e)
        chat = await e.get_chat()
        if getattr(chat, "username", None):
            return await out(e, f"🔗 https://t.me/{chat.username}")
        inv = await client(functions.messages.ExportChatInviteRequest(await e.get_input_chat()))
        await out(e, f"🔗 {inv.link}")

    @cmd("ترفیع")
    async def promote(e, a):
        need_group(e)
        uid = await target(e, a)
        await client.edit_admin(e.chat_id, uid, change_info=True, delete_messages=True, ban_users=True,
                                invite_users=True, pin_messages=True, add_admins=False)
        await out(e, "⭐ ادمین شد")

    @cmd("عزل")
    async def demote(e, a):
        need_group(e)
        uid = await target(e, a)
        await client.edit_admin(e.chat_id, uid, is_admin=False)
        await out(e, "✅ از ادمینی عزل شد")

    @cmd("اخراج")
    async def kick(e, a):
        need_group(e)
        uid = await target(e, a)
        await client.kick_participant(e.chat_id, uid)
        await out(e, "👢 اخراج شد (می‌تونه دوباره بیاد)")

    @cmd("لیست ادمین")
    async def admin_list(e, a):
        need_group(e)
        rows = []
        async for u in client.iter_participants(e.chat_id, filter=types.ChannelParticipantsAdmins()):
            nm = getattr(u, "first_name", None) or getattr(u, "title", None) or "user"
            rows.append(f"• {nm}" + (f" @{u.username}" if getattr(u, "username", None) else ""))
        await out(e, "👮 ادمین‌ها:\n" + ("\n".join(rows[:60]) or "خالی"))

    @cmd("حالت آرام")
    async def slow_mode(e, a):
        need_group(e)
        chat = await e.get_chat()
        if not isinstance(chat, types.Channel):
            raise ValueError("حالت آرام فقط توی سوپرگروه کار می‌کنه")
        if not a.translate(FA).strip().isdigit():
            raise ValueError("مثال: .حالت آرام 30   (۰ = خاموش)")
        want = int(a.translate(FA).strip())
        valid = [0, 10, 30, 60, 300, 900, 3600]
        sec = min(valid, key=lambda x: abs(x - want))
        await client(functions.channels.ToggleSlowModeRequest(chat, sec))
        await out(e, f"🐢 حالت آرام: {'خاموش' if sec == 0 else str(sec) + ' ثانیه'}")

    # ===================== تقلب (تاس/دارت/...) =====================
    @cmd("تقلب")
    async def cheat(e, a):
        p = a.translate(FA).split()
        if len(p) != 2 or p[0] not in CHEAT or not p[1].isdigit():
            raise ValueError("مثال: .تقلب تاس 6\nبازی‌ها: " + " | ".join(
                f"{k} (۱–{v[1]})" for k, v in CHEAT.items()))
        emoji, top = CHEAT[p[0]]
        want = int(p[1])
        if not 1 <= want <= top:
            raise ValueError(f"عدد برای {p[0]} باید بین ۱ تا {top} باشه")
        reply_to = e.reply_to_msg_id
        await e.delete()
        for i in range(15):
            try:
                m = await client.send_file(e.chat_id, types.InputMediaDice(emoji), reply_to=reply_to)
            except errors.FloodWaitError:
                return
            if m.media.value == want:
                return
            if i < 14:
                await asyncio.sleep(2)
                await m.delete()

    # ===================== چالش استارزی =====================
    @cmd("چالش استارزی")
    async def starzi_challenge(e, a):
        ch = cfg["starzi_challenge"]
        p = a.translate(FA).split()
        w = p[0] if p else "وضعیت"
        if w == "روشن":
            st = cfg.get("starzi") or {}
            if not st.get("src_id") or not st.get("time"):
                raise ValueError("اول استارزی رو تنظیم کن (تنظیم عکس استارزی + تنظیم زمان استارزی + استارزی روشن)")
            days = int(p[1]) if len(p) > 1 and p[1].isdigit() else 30
            if not 1 <= days <= 365:
                raise ValueError("تعداد روز بین ۱ تا ۳۶۵")
            ch.update(on=True, days=days, day=0)
            save()
            return await out(e, f"🔥 چالش استارزی شروع شد: {days} روز\n"
                                "هر پست روزانه‌ی استارزی با «روز X از N» ارسال می‌شه")
        if w == "خاموش":
            ch["on"] = False
            save()
            return await out(e, "⏸ چالش استارزی متوقف شد")
        if w == "ریست":
            ch["day"] = 0
            save()
            return await out(e, "🔄 شمارنده‌ی چالش صفر شد")
        await out(e, f"🔥 چالش استارزی: {'✅ روشن' if ch['on'] else '⛔ خاموش'}\n"
                     f"روز {ch['day']} از {ch['days']}\n\n.چالش استارزی روشن [تعداد روز] | خاموش | ریست")

    # ===================== بازی گربه =====================
    @cmd("بازی گربه")
    async def cat_game(e, a):
        p = a.split(None, 1)
        w = p[0] if p else ""
        arg = p[1].strip() if len(p) > 1 else ""
        cat = cfg["cat"]
        if w in ("بگیر", "adopt"):
            if cat:
                raise ValueError("یه گربه داری! برای رها کردنش: .بازی گربه ریست")
            cfg["cat"] = cat = {"name": (arg or "میمی")[:20], "food": 70, "mood": 70, "energy": 80,
                                "xp": 0, "last": time.time()}
            save()
            return await out(e, "🎉 یه بچه‌گربه گرفتی!\n" + cat_status(cat))
        if not cat:
            return await out(e, "🐱 هنوز گربه نداری.\nبرای گرفتن: .بازی گربه بگیر [اسم]")
        cat_decay(cat)
        if w == "ریست":
            cfg["cat"] = None
            save()
            return await out(e, "👋 گربه رو رها کردی. برای گرفتن جدید: .بازی گربه بگیر")
        if w == "اسم":
            if not arg:
                raise ValueError("اسم جدید رو بنویس")
            cat["name"] = arg[:20]
            msg = f"✏️ اسم گربه شد {cat['name']}"
        elif w == "غذا":
            if cat["food"] >= 95:
                msg = "😾 سیره! دیگه نمی‌خوره."
            else:
                cat["food"] = min(100, cat["food"] + 30)
                cat["xp"] += 2
                msg = "🍗 ممنون! مشغول خوردن شد."
        elif w == "بازی":
            if cat["energy"] < 15:
                msg = "😴 خیلی خستست؛ اول بذار بخوابه (.بازی گربه خواب)"
            else:
                cat["mood"] = min(100, cat["mood"] + 25)
                cat["energy"] -= 15
                cat["food"] = max(0, cat["food"] - 8)
                cat["xp"] += 3
                msg = "🧶 با کلاف بازی کرد و کلی ذوق کرد!"
        elif w == "خواب":
            cat["energy"] = min(100, cat["energy"] + 40)
            cat["xp"] += 1
            msg = "💤 یه چرت خوب زد."
        elif w in ("", "وضعیت"):
            msg = None
        else:
            raise ValueError("بگیر [اسم] | غذا | بازی | خواب | اسم X | وضعیت | ریست")
        save()
        await out(e, (msg + "\n\n" if msg else "") + cat_status(cat))

    # ===================== هوک ورودی (نگهبان + عضویت اجباری) =====================
    async def on_incoming(e):
        if e.is_private or e.out or not e.sender_id:
            return False
        chat, sid = e.chat_id, e.sender_id
        fj = cfg["force_join"]
        g = cfg["guard"].get(str(chat))
        use_fj = bool(fj["channel"] and chat in fj["chats"])
        use_g = bool(g and g.get("on"))
        if not (use_fj or use_g):
            return False
        sender = await e.get_sender()
        if sender is None or getattr(sender, "bot", False) or isinstance(sender, types.Channel):
            return False
        if sid == await my_id() or await is_admin_in(chat, sid):
            return False
        if use_g and violates(e.message, g):
            try:
                await e.delete()
            except Exception:
                pass
            return True
        if use_fj and not await force_member(sid):
            try:
                await e.delete()
            except Exception:
                return False
            k, now = (chat, sid), time.time()
            if now - warn_seen.get(k, 0) > 60:
                warn_seen[k] = now
                name = (getattr(sender, "first_name", None) or "کاربر").replace("[", "").replace("]", "")[:20]
                asyncio.create_task(temp_warn(
                    chat, f"⚠️ [{name}](tg://user?id={sid}) برای چت کردن توی این گروه اول عضو کانال شو:\n"
                          f"{fj['link'] or fj['channel']}"))
            return True
        return False

    return {"incoming": on_incoming, "loops": [reminder_loop]}
