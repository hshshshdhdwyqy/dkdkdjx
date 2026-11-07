"""
قابلیت‌های تکمیلی (الهام‌گرفته از پنل LTM Self): تبچی (بنر تبلیغاتی خودکار)،
دشمن + فحش (پاسخ خودکار توهین به دشمن‌ها)، اسپم، اسکرین صفحه (رندر چت به عکس)،
استارزی (پست خودکار زمان‌بندی‌شده‌ی روزانه) و لایو (پخش صف‌دار ساده + پنل کنترل).

⚠️ «لایو» اینجا یه پخش‌کننده‌ی صف‌دار ساده‌ست (فایل بعدی رو توی چت می‌فرسته و پیام
وضعیت رو ویرایش می‌کنه)، نه استریم واقعی صدا/ویدیو به تماس گروهی تلگرام؛ اون به
pytgcalls و زیرساخت WebRTC جدا نیاز داره که اینجا نیست.
⚠️ «استارزی» یه پست خودکار زمان‌بندی‌شده‌ی روزانه‌ست، نه محتوای واقعی پولی/پشت پولی
استارز تلگرام (که نیاز به تایید جداگانه‌ی API داره).
"""
import asyncio
import io
import os
import random
import time
from datetime import datetime

from telethon import Button, events, functions, types

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None

try:
    import arabic_reshaper
    from bidi.algorithm import get_display

    def rtl(text):
        return get_display(arabic_reshaper.reshape(text))
except ImportError:
    def rtl(text):
        return text

FONT_CANDIDATES = [
    "assets/Vazirmatn-Regular.ttf",
    "assets/Vazirmatn-Medium.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size):
    if Image is None:
        return None
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def setup_extras(client, cfg, save, cmd, out, target, bot_state):
    # ---------- وضعیت حالت‌های موقتی ----------
    enemy_seen = {}
    live = {}   # chat_id -> session dict

    async def need_reply(e):
        if not e.is_reply:
            raise ValueError("روی یه پیام ریپلای کن")
        return await e.get_reply_message()

    def ensure_keys():
        cfg.setdefault("enemies", [])
        cfg.setdefault("enemy_words", [])
        cfg.setdefault("tabchi_on", False)
        cfg.setdefault("banners", [])
        cfg.setdefault("screen_on", False)
        cfg.setdefault("screen_count", 3)
        cfg.setdefault("starzi", {"on": False, "time": None, "chat_id": None,
                                   "src_chat": None, "src_id": None, "last_date": None})

    ensure_keys()

    # ===================== دشمن + فحش =====================
    @cmd("تنظیم دشمن")
    async def enemy_add(e, a):
        uid = await target(e, a)
        if uid not in cfg["enemies"]:
            cfg["enemies"].append(uid)
            save()
        await out(e, f"🗡 به لیست دشمنا اضافه شد: {uid}")

    @cmd("حذف دشمن")
    async def enemy_del(e, a):
        uid = await target(e, a)
        if uid in cfg["enemies"]:
            cfg["enemies"].remove(uid)
            save()
        await out(e, f"✅ حذف شد: {uid}")

    @cmd("لیست دشمن")
    async def enemy_list(e, a):
        await out(e, "🗡 دشمن‌ها:\n" + ("\n".join(str(x) for x in cfg["enemies"]) or "خالی"))

    @cmd("پاکسازی لیست دشمن")
    async def enemy_clear(e, a):
        cfg["enemies"] = []
        save()
        await out(e, "🧹 لیست دشمن خالی شد")

    @cmd("تنظیم فحش")
    async def fw_add(e, a):
        if not a.strip():
            raise ValueError("یه متن بعدش بنویس")
        cfg["enemy_words"].append(a.strip())
        save()
        await out(e, "✅ اضافه شد")

    @cmd("حذف فحش")
    async def fw_del(e, a):
        if a.strip() in cfg["enemy_words"]:
            cfg["enemy_words"].remove(a.strip())
            save()
        await out(e, "✅ حذف شد")

    @cmd("پاکسازی لیست فحش")
    async def fw_clear(e, a):
        cfg["enemy_words"] = []
        save()
        await out(e, "🧹 لیست فحش خالی شد")

    @cmd("لیست فحش")
    async def fw_list(e, a):
        txt = "\n".join(cfg["enemy_words"]) or "خالی"
        await client.send_file(e.chat_id, io.BytesIO(txt.encode("utf-8")),
                               attributes=[types.DocumentAttributeFilename("فحش.txt")])
        await e.delete()

    @cmd("تنظیم لیست فحش")
    async def fw_set(e, a):
        r = await need_reply(e)
        if not r.file:
            raise ValueError("روی یه فایل txt ریپلای کن")
        data = await client.download_media(r, bytes)
        cfg["enemy_words"] = [ln.strip() for ln in data.decode("utf-8", "ignore").splitlines() if ln.strip()]
        save()
        await out(e, f"✅ {len(cfg['enemy_words'])} خط جایگزین شد")

    # ===================== تبچی (بنر تبلیغاتی) =====================
    @cmd("تبچی روشن")
    async def tabchi_on(e, a):
        cfg["tabchi_on"] = True
        save()
        await out(e, "✅ ارسال خودکار بنرها روشن شد")

    @cmd("تبچی خاموش")
    async def tabchi_off(e, a):
        cfg["tabchi_on"] = False
        save()
        await out(e, "⏸ ارسال خودکار بنرها خاموش شد")

    @cmd("وضعیت تبچی")
    async def tabchi_status(e, a):
        n = len(cfg["banners"])
        await out(e, f"📣 تبچی: {'روشن' if cfg['tabchi_on'] else 'خاموش'} | {n} بنر ثبت‌شده")

    def banner_line(b):
        tg = "همه" if b["targets"] == "all" else f"{len(b['targets'])} گپ"
        return (f"#{b['id']} | {b['mode']} | هر {b['interval']} دقیقه | مقصد: {tg}")

    @cmd("لیست بنر ها", "لیست بنرها")
    async def banner_list(e, a):
        if not cfg["banners"]:
            await out(e, "📭 بنری ثبت نشده")
            return
        await out(e, "📣 بنرها:\n" + "\n".join(banner_line(b) for b in cfg["banners"]))

    async def banner_add(e, mode):
        r = await need_reply(e)
        bid = (max((b["id"] for b in cfg["banners"]), default=0)) + 1
        cfg["banners"].append({"id": bid, "mode": mode, "src_chat": r.chat_id, "src_id": r.id,
                               "interval": 60, "targets": [], "last_sent": 0})
        save()
        await out(e, f"✅ بنر #{bid} ثبت شد ({mode}). حالا با «.تنظیم گپ هدف بنر {bid}» توی هر گپی که "
                      "می‌خوای بره، اضافه‌ش کن.")

    @cmd("تنظیم بنر فور")
    async def banner_fwd(e, a):
        await banner_add(e, "fwd")

    @cmd("تنظیم بنر کپی")
    async def banner_copy(e, a):
        await banner_add(e, "copy")

    def find_banner(a):
        if not a.strip().split():
            raise ValueError("شماره‌ی بنر رو بده")
        bid = int(a.split()[0])
        for b in cfg["banners"]:
            if b["id"] == bid:
                return b
        raise ValueError("همچین بنری نیست")

    @cmd("حذف بنر")
    async def banner_del(e, a):
        bid = int(a.split()[0])
        cfg["banners"] = [b for b in cfg["banners"] if b["id"] != bid]
        save()
        await out(e, f"🗑 بنر #{bid} حذف شد")

    @cmd("پاکسازی لیست بنر ها", "پاکسازی لیست بنرها")
    async def banner_clear(e, a):
        cfg["banners"] = []
        save()
        await out(e, "🧹 همه‌ی بنرها حذف شدن")

    @cmd("تنظیم دقیقه بنر")
    async def banner_minutes(e, a):
        parts = a.split()
        minutes, bid = int(parts[0]), int(parts[1])
        b = find_banner(str(bid))
        b["interval"] = max(1, minutes)
        save()
        await out(e, f"✅ بنر #{bid}: هر {b['interval']} دقیقه")

    @cmd("تنظیم گپ هدف بنر")
    async def banner_target_add(e, a):
        b = find_banner(a)
        if b["targets"] == "all":
            b["targets"] = []
        if e.chat_id not in b["targets"]:
            b["targets"].append(e.chat_id)
            save()
        await out(e, f"✅ این گپ به مقصدهای بنر #{b['id']} اضافه شد")

    @cmd("حذف گپ هدف بنر")
    async def banner_target_del(e, a):
        b = find_banner(a)
        if b["targets"] != "all" and e.chat_id in b["targets"]:
            b["targets"].remove(e.chat_id)
            save()
        await out(e, f"✅ این گپ از مقصدهای بنر #{b['id']} حذف شد")

    @cmd("تنظیم هدف بنر")
    async def banner_target_all(e, a):
        parts = a.split()
        bid = int(parts[0])
        b = find_banner(str(bid))
        b["targets"] = "all"
        save()
        await out(e, f"✅ بنر #{bid} برای همه‌ی گروه‌ها فعال شد")

    @cmd("فور بنر در")
    async def banner_fwd_recent(e, a):
        r = await need_reply(e)
        n = int(a.split()[0]) if a.split() else 10
        dialogs = await client.get_dialogs(limit=100)
        pv = [d for d in dialogs if d.is_user][:n]
        sent = 0
        for d in pv:
            try:
                await client.forward_messages(d.id, r)
                sent += 1
                await asyncio.sleep(0.3)
            except Exception:
                pass
        await out(e, f"✅ به {sent} پیوی اخیر فوروارد شد")

    async def send_banner(b):
        try:
            msg = await client.get_messages(b["src_chat"], ids=b["src_id"])
        except Exception:
            return
        if not msg:
            return
        targets = (await _all_chat_ids()) if b["targets"] == "all" else b["targets"]
        for t in targets:
            try:
                if b["mode"] == "fwd":
                    await client.forward_messages(t, msg)
                else:
                    await client.send_message(t, msg.message or "", file=msg.media)
                await asyncio.sleep(0.5)
            except Exception:
                pass
        b["last_sent"] = time.time()
        save()

    async def _all_chat_ids():
        ids = []
        async for d in client.iter_dialogs():
            if d.is_group or d.is_channel:
                ids.append(d.id)
        return ids

    async def tabchi_loop():
        while True:
            await asyncio.sleep(30)
            if not cfg["enabled"] or not cfg["tabchi_on"]:
                continue
            now = time.time()
            for b in list(cfg["banners"]):
                if now - b.get("last_sent", 0) >= b["interval"] * 60:
                    try:
                        await send_banner(b)
                    except Exception as ex:
                        print("banner error:", ex)

    # ===================== اسپم =====================
    @cmd("اسپم")
    async def spam(e, a):
        parts = a.split()
        if e.is_reply and parts and parts[-1].isdigit():
            text = (await e.get_reply_message()).raw_text or ""
            count = int(parts[-1])
        elif len(parts) >= 2 and parts[-1].isdigit():
            count = int(parts[-1])
            text = " ".join(parts[:-1])
        else:
            raise ValueError("بنویس: اسپم [متن] [تعداد]  یا  با ریپلای: اسپم [تعداد]")
        if not text:
            raise ValueError("متن خالیه")
        count = max(1, min(count, 300))
        await e.delete()
        for _ in range(count):
            await client.send_message(e.chat_id, text)
            await asyncio.sleep(0.25)

    # ===================== اسکرین صفحه =====================
    def wrap_text(draw, text, font, max_w):
        words = text.split(" ")
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    async def render_screenshot(chat_id, n, me_id):
        if Image is None:
            raise ValueError("Pillow نصب نیست")
        msgs = []
        async for m in client.iter_messages(chat_id, limit=n):
            if m.raw_text:
                msgs.append(m)
        msgs.reverse()
        if not msgs:
            raise ValueError("پیام متنی برای رندر پیدا نشد")
        W = 900
        pad, gap, bub_pad = 24, 14, 18
        font = _font(28)
        name_font = _font(22)
        bubbles = []
        y = pad
        for m in msgs:
            out_going = m.sender_id == me_id
            name = "شما" if out_going else (getattr(await m.get_sender(), "first_name", "") or "")
            text = rtl(m.raw_text[:500])
            tmp_img = Image.new("RGB", (10, 10))
            d = ImageDraw.Draw(tmp_img)
            max_bub_w = int(W * 0.72)
            lines = wrap_text(d, text, font, max_bub_w - 2 * bub_pad)
            line_h = (font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + 10) if font else 30
            bub_w = min(max_bub_w, max((int(d.textlength(ln, font=font)) for ln in lines), default=100) + 2 * bub_pad)
            bub_h = len(lines) * line_h + 2 * bub_pad + (24 if not out_going else 0)
            bubbles.append((out_going, name, lines, bub_w, bub_h, line_h))
            y += bub_h + gap
        H = y + pad
        img = Image.new("RGB", (W, H), (20, 23, 28))
        d = ImageDraw.Draw(img)
        y = pad
        for out_going, name, lines, bub_w, bub_h, line_h in bubbles:
            x1 = pad if not out_going else W - pad - bub_w
            x2 = x1 + bub_w
            color = (0, 136, 204) if out_going else (40, 44, 52)
            d.rounded_rectangle([x1, y, x2, y + bub_h], radius=16, fill=color)
            ty = y + bub_pad
            if not out_going and name_font:
                d.text((x2 - bub_pad, ty), rtl(name), font=name_font, fill=(120, 190, 255), anchor="ra")
                ty += 24
            for ln in lines:
                d.text((x2 - bub_pad, ty), ln, font=font, fill=(235, 235, 235), anchor="ra")
                ty += line_h
            y += bub_h + gap
        buf = io.BytesIO()
        buf.name = "screen.png"
        img.save(buf, "PNG")
        buf.seek(0)
        return buf

    @cmd("اسکرین صفحه")
    async def screen_cmd(e, a):
        n = int(a.split()[0]) if a.strip().isdigit() else cfg["screen_count"]
        me_id = await client.get_peer_id("me")
        await out(e, "⏳ در حال ساخت اسکرین...")
        buf = await render_screenshot(e.chat_id, n, me_id)
        await client.send_file(e.chat_id, buf)
        try:
            await e.delete()
        except Exception:
            pass

    @cmd("اسکرین صفحه روشن")
    async def screen_on(e, a):
        cfg["screen_on"] = True
        save()
        await out(e, "✅ حالت خودکار اسکرین روشن شد")

    @cmd("اسکرین صفحه خاموش")
    async def screen_off(e, a):
        cfg["screen_on"] = False
        save()
        await out(e, "⏸ حالت خودکار اسکرین خاموش شد")

    @cmd("اسکرین صفحه تعداد")
    async def screen_count(e, a):
        n = int(a.split()[0])
        if not 3 <= n <= 30:
            raise ValueError("عدد بین ۳ تا ۳۰")
        cfg["screen_count"] = n
        save()
        await out(e, f"✅ تعداد پیش‌فرض اسکرین: {n}")

    # ===================== استارزی (پست خودکار روزانه) =====================
    @cmd("تنظیم عکس استارزی")
    async def starzi_set_media(e, a):
        r = await need_reply(e)
        cfg["starzi"]["src_chat"] = r.chat_id
        cfg["starzi"]["src_id"] = r.id
        save()
        await out(e, "✅ محتوای استارزی ثبت شد")

    @cmd("تنظیم زمان استارزی")
    async def starzi_set_time(e, a):
        t = a.strip()
        h, m = t.split(":")
        int(h), int(m)
        cfg["starzi"]["time"] = f"{int(h):02d}:{int(m):02d}"
        save()
        await out(e, f"⏰ زمان استارزی: {cfg['starzi']['time']}")

    @cmd("استارزی روشن")
    async def starzi_on(e, a):
        if not cfg["starzi"]["src_id"] or not cfg["starzi"]["time"]:
            raise ValueError("اول محتوا و زمان رو با دستورهای «تنظیم عکس استارزی» و «تنظیم زمان استارزی» بده")
        cfg["starzi"]["on"] = True
        cfg["starzi"]["chat_id"] = e.chat_id
        save()
        await out(e, f"✅ استارزی روشن شد؛ هر روز {cfg['starzi']['time']} توی همین گپ پست می‌شه")

    @cmd("استارزی خاموش")
    async def starzi_off(e, a):
        cfg["starzi"]["on"] = False
        save()
        await out(e, "⏸ استارزی خاموش شد")

    async def starzi_loop():
        while True:
            await asyncio.sleep(30)
            st = cfg["starzi"]
            if not cfg["enabled"] or not st["on"] or not st["time"]:
                continue
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            if now.strftime("%H:%M") == st["time"] and st.get("last_date") != today:
                try:
                    msg = await client.get_messages(st["src_chat"], ids=st["src_id"])
                    if msg:
                        cap = msg.message or ""
                        ch = cfg.get("starzi_challenge") or {}
                        if ch.get("on"):   # چالش استارزی: «روز X از N» ته هر پست
                            ch["day"] = ch.get("day", 0) + 1
                            cap = (cap + "\n\n" if cap else "") + \
                                f"🔥 چالش استارزی — روز {ch['day']} از {ch.get('days', 30)}"
                            if ch["day"] >= ch.get("days", 30):
                                ch["on"] = False
                        await client.send_message(st["chat_id"], cap, file=msg.media)
                except Exception as ex:
                    print("starzi error:", ex)
                st["last_date"] = today
                save()

    # ===================== لایو (پخش‌کننده‌ی صف‌دار ساده) =====================
    def live_status(s):
        state = "⏸ مکث" if s["paused"] else ("▶️ پخش" if s["playing"] else "⏹ متوقف")
        q = f" | صف: {len(s['queue'])}"
        return f"🔴 لایو: {s['title']}\n{state}{q}\n⏱ موقعیت: {s['pos']}s"

    def live_kb(chat_id):
        return [
            [Button.inline("⏪ 10s", f"lv:back10:{chat_id}".encode()),
             Button.inline("⏯ مکث/ادامه", f"lv:toggle:{chat_id}".encode()),
             Button.inline("10s ⏩", f"lv:fwd10:{chat_id}".encode())],
            [Button.inline("⏭ بعدی", f"lv:next:{chat_id}".encode()),
             Button.inline("🔄 وضعیت", f"lv:status:{chat_id}".encode()),
             Button.inline("⏹ پایان", f"lv:stop:{chat_id}".encode())],
        ]

    async def live_refresh(chat_id):
        s = live.get(chat_id)
        if not s:
            return
        try:
            await client.edit_message(chat_id, s["msg_id"], live_status(s))
        except Exception:
            pass

    @cmd("لایو")
    async def live_start(e, a):
        if not a.strip():
            raise ValueError("یه عنوان بده: .لایو عنوان")
        if e.is_private:
            raise ValueError("لایو فقط تو کانال/گروهه")
        msg = await client.send_message(e.chat_id, "🔴 درحال آماده‌سازی لایو...")
        live[e.chat_id] = {"title": a.strip(), "queue": [], "playing": False,
                           "paused": False, "pos": 0, "msg_id": msg.id}
        await e.delete()
        await live_refresh(e.chat_id)

    @cmd("پخش")
    async def live_play(e, a):
        s = live.get(e.chat_id)
        if not s:
            raise ValueError("اول با «.لایو عنوان» شروع کن")
        query = a.strip()
        if e.is_reply:
            r = await e.get_reply_message()
            s["queue"].append(("msg", r.chat_id, r.id))
        elif query:
            s["queue"].append(("query", query, None))
        else:
            raise ValueError("لینک/اسم بده یا ریپلای کن")
        await e.delete()
        if not s["playing"]:
            await live_advance(e.chat_id)
        else:
            await out(e, "➕ به صف اضافه شد")

    async def live_advance(chat_id):
        s = live.get(chat_id)
        if not s or not s["queue"]:
            if s:
                s["playing"] = False
                await live_refresh(chat_id)
            return
        kind, a1, a2 = s["queue"].pop(0)
        s["playing"], s["paused"], s["pos"] = True, False, 0
        try:
            if kind == "msg":
                src = await client.get_messages(a1, ids=a2)
                if src:
                    await client.send_message(chat_id, src.message or "", file=src.media)
            else:
                import tempfile
                from features import yt_search, yt_download
                results = yt_search(a1, 1)
                if not results:
                    raise ValueError("چیزی پیدا نشد")
                with tempfile.TemporaryDirectory() as wd:
                    p = await yt_download(results[0]["url"], wd)
                    await client.send_file(chat_id, p, caption=f"🎵 {results[0]['title']}")
        except Exception as ex:
            print("live play error:", ex)
        await live_refresh(chat_id)

    @cmd("مکث")
    async def live_pause(e, a):
        s = live.get(e.chat_id)
        if s:
            s["paused"] = True
            await live_refresh(e.chat_id)
        await e.delete()

    @cmd("ادامه")
    async def live_resume(e, a):
        s = live.get(e.chat_id)
        if s:
            s["paused"] = False
            await live_refresh(e.chat_id)
        await e.delete()

    @cmd("بعدی")
    async def live_next(e, a):
        await e.delete()
        await live_advance(e.chat_id)

    @cmd("صف")
    async def live_queue(e, a):
        s = live.get(e.chat_id)
        items = ", ".join(x[1] if isinstance(x[1], str) else "پیام" for x in (s["queue"] if s else []))
        await out(e, f"📋 صف: {items or 'خالی'}")

    @cmd("قطع", "پایان لایو")
    async def live_stop(e, a):
        s = live.pop(e.chat_id, None)
        if s:
            try:
                await client.edit_message(e.chat_id, s["msg_id"], f"⏹ لایو «{s['title']}» تموم شد")
            except Exception:
                pass
        await e.delete()

    @cmd("جلو")
    async def live_fwd(e, a):
        s = live.get(e.chat_id)
        if s:
            s["pos"] += int(a.split()[0]) if a.split() else 10
            await live_refresh(e.chat_id)
        await e.delete()

    @cmd("عقب")
    async def live_back(e, a):
        s = live.get(e.chat_id)
        if s:
            s["pos"] = max(0, s["pos"] - (int(a.split()[0]) if a.split() else 10))
            await live_refresh(e.chat_id)
        await e.delete()

    @cmd("برو")
    async def live_goto(e, a):
        s = live.get(e.chat_id)
        if s and a.split():
            s["pos"] = int(a.split()[0])
            await live_refresh(e.chat_id)
        await e.delete()

    @cmd("پنل لایو")
    async def live_panel(e, a):
        s = live.get(e.chat_id)
        if not s or not bot_state.get("client"):
            raise ValueError("اول لایو رو شروع کن و HELPER_BOT_TOKEN هم تنظیم باشه")
        await bot_state["client"].send_message(
            (await client.get_me()).id, live_status(s), buttons=live_kb(e.chat_id))
        await e.delete()

    def setup_live_panel_callbacks():
        if not bot_state.get("client"):
            return

        @bot_state["client"].on(events.CallbackQuery(pattern=rb"^lv:"))
        async def on_live_cb(ev):
            _, act, chat_id = ev.data.decode().split(":")
            chat_id = int(chat_id)
            s = live.get(chat_id)
            if not s:
                await ev.answer("این لایو دیگه فعال نیست", alert=True)
                return
            if act == "toggle":
                s["paused"] = not s["paused"]
            elif act == "fwd10":
                s["pos"] += 10
            elif act == "back10":
                s["pos"] = max(0, s["pos"] - 10)
            elif act == "next":
                await live_advance(chat_id)
            elif act == "stop":
                live.pop(chat_id, None)
                await ev.edit("⏹ لایو تموم شد", buttons=[])
                return
            s = live.get(chat_id)
            if s:
                await ev.edit(live_status(s), buttons=live_kb(chat_id))
            try:
                await ev.answer()
            except Exception:
                pass

    # ===================== هوک ورودی (دشمن) =====================
    async def on_incoming(e):
        sid = e.sender_id
        if sid and sid in cfg["enemies"] and cfg["enemy_words"]:
            k, now = (e.chat_id, sid), time.time()
            if now - enemy_seen.get(k, 0) > 60:
                enemy_seen[k] = now
                await e.reply(random.choice(cfg["enemy_words"]))
        if (e.is_private and cfg["screen_on"] and (e.raw_text or "").strip() in ("اسکرین صفحه", "اسکرین")):
            try:
                await e.delete()
                me_id = await client.get_peer_id("me")
                buf = await render_screenshot(e.chat_id, cfg["screen_count"], me_id)
                await client.send_file(e.chat_id, buf)
            except Exception as ex:
                print("auto screen error:", ex)
            return True
        return False

    return {"incoming": on_incoming, "loops": [tabchi_loop, starzi_loop],
            "after_helper": setup_live_panel_callbacks}
