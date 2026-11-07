"""پنل دکمه‌ای (inline) برای NRT Self — با یه بات تلگرام معمولی کار می‌کنه."""
import os

from telethon import Button, events

from details import detail_text

BANNER_DIR = os.getenv("BANNER_DIR", "banners")


def banner_file(uid):
    """مسیر بنر اختصاصی هر کاربر (با عکس پروفایل خودش)؛ اگه نبود بنر پیش‌فرض."""
    for path in (os.path.join(BANNER_DIR, f"user_{uid}.jpg"),
                 os.getenv("BANNER_PATH", "assets/banner.jpg")):
        if os.path.exists(path):
            return path
    return None


def panel_article(ev, uid, title, text, rows):
    path = banner_file(uid)
    if path:
        return ev.builder.photo(path, text=text, buttons=rows, id="panel")
    return ev.builder.article(title, text=text, buttons=rows)

CYCLES = {
    "react": [None, "❤", "👍", "🔥", "😂"],
    "action": [None, "typing", "record-voice", "record-video", "game"],
    "textmode": [None, "bold", "italic", "mono", "spoiler"],
    "clock_mode": ["last", "first"],
}

# kind: t=روشن/خاموش | c=چرخشی | a=اجرای مستقیم | h=راهنمای دستور (نیاز به متن داره)
# ۸ صفحه، هم‌ترتیب با منوی LTM Self
PAGES = {
    1: ("🛠 مدیریت سلف", [
        ("t", "enabled", "⚡ مدیریت سلف"),
        ("a", "info", "ℹ️ اطلاعات"), ("a", "ping", "🏓 پینگ"),
        ("h", "داخل بات هاب: /start ← 💎 انتقال الماس (به آیدی یا یوزرنیم کاربر هاب)", "💎 انتقال الماس"),
        ("h", "پنل ادمین هاب ← 👮 مدیریت ادمین (فقط مالک‌ها می‌تونن اضافه/حذف کنن)", "👮 مدیریت ادمین"),
        ("h", ".پرفیکس /  ← تغییر پیشوند دستورها  |  .پرفیکس پیش‌فرض", "🔣 پرفیکس"),
        ("h", ".عضویت اجباری تنظیم @ch  ←  بعد توی گروه: .عضویت اجباری روشن", "📢 عضویت اجباری"),
        ("h", ".جوین  ← ریپلای روی پیامی که لینک/یوزرنیم گروه یا کانال داره", "🔗 جوین از پیام"),
        ("h", ".راهنما  ← لیست همه دستورها", "📖 راهنما"),
        ("h", ".ثبت نام  ← ثبت اسم فعلی به‌عنوان اسم اصلی", "💾 ثبت نام"),
    ]),
    2: ("⚡ قابلیت‌های خودکار", [
        ("t", "autoseen", "👁 سین خودکار"), ("c", "react", "❤ ری‌اکشن"),
        ("h", ".پاسخ کلمه | جواب", "💬 پاسخ خودکار"),
        ("h", ".حذف پاسخ کلمه", "🗑 حذف پاسخ"),
        ("t", "fc_on", "🥇 کامنت اول"),
        ("h", ".کامنت اول افزودن @ch  |  .کامنت اول متن اول 🔥|زود اومدم", "⚙️ تنظیم کامنت اول"),
    ]),
    3: ("🔒 امنیت و حریم خصوصی", [
        ("h", ".نگهبان روشن  |  .نگهبان لینک/فوروارد/منشن/استیکر/گیف روشن  (توی گروه، ادمین باش)", "🛡 نگهبان چت"),
        ("t", "pvlock", "🔒 قفل پیوی"), ("t", "antilogin", "🛡 ضد لاگین"),
        ("h", ".بلاک / .آنبلاک  (ریپلای یا آیدی)", "⛔ بلاک"),
        ("h", ".سکوت / .رفع سکوت  (ریپلای)", "🔇 سکوت"),
        ("h", ".فیلتر کلمه  |  .حذف فیلتر کلمه", "🚫 فیلتر کلمات"),
        ("h", ".بکاپ 500  ← ۵۰۰ پیام آخر به Saved Messages", "💾 بکاپ چت"),
    ]),
    4: ("🎭 حالت‌ها و ظاهر", [
        ("t", "online", "🟢 حالت آنلاین"), ("t", "secretary", "🗂 حالت منشی"),
        ("c", "textmode", "✍️ حالت متن"), ("c", "action", "🎭 حالت اکشن"),
        ("t", "clock", "🕒 ساعت"), ("c", "clock_mode", "📍 جای ساعت"),
        ("h", ".هوا تهران", "🌤 آب و هوا"),
    ]),
    5: ("🧰 ابزارها (1)", [
        ("h", ".آیدی | .تاریخ | .یادآوری 30 دقیقه متن | .لینک پیام | .ذخیره  (ریپلای)", "🧰 کاربردی"),
        ("h", ".محاسبه 2+2*3", "🧮 محاسبات"),
        ("h", ".ارز 100 USD EUR", "💱 قیمت ارز"), ("h", ".کریپتو bitcoin", "🪙 کریپتو"),
        ("h", ".دانلود لینک  |  .دانلود صدا لینک  (یا ریپلای روی لینک)", "⬇️ دانلود"),
        ("h", ".ترجمه en سلام  (یا ریپلای)", "🌐 ترجمه"),
        ("h", ".هوش مصنوعی سوالت", "🤖 هوش مصنوعی"),
        ("h", ".کیفیت  (ریپلای روی عکس)", "🖼 کیفیت عکس"),
        ("h", "ریپلای: .عکس/ویدیو/گیف/استیکر/دایره به ...  مثلا .ویدیو به دایره", "🔁 ابزار تبدیل"),
    ]),
    6: ("🎵 ابزارها (2)", [
        ("h", ".آهنگ اسم  |  .آهنگ اسم | 2", "🎵 سرچ آهنگ"),
        ("h", ".سرچ یوتیوب متن  |  .سرچ یوتیوب متن | 3", "▶️ سرچ یوتیوب"),
    ]),
    7: ("👥 گروه و پیام", [
        ("h", ".مدیریت گروه ← لیست دستورها (قفل گروه، عنوان، لینک، ترفیع، عزل، اخراج، حالت آرام)", "🛠 مدیریت گروه"),
        ("h", ".تگ 20  |  .همه  ← تگ ۲۰ نفر / همه", "📣 تگ اعضا"),
        ("h", ".اسپم متن 10  (یا ریپلای: .اسپم 10)", "💥 اسپم"),
        ("h", ".حذف 10  ← ۱۰ پیام آخر خودت", "🗑 حذف پیام"),
        ("h", ".اسکرین google.com  ← اسکرین سایت", "🌐 اسکرین"),
        ("h", ".متن به ویس متن  |  .متن به ویس مرد متن  (یا ریپلای)", "🎙 متن به ویس"),
        ("h", ".ویس به متن  (ریپلای روی ویس)", "📝 ویس به متن"),
        ("h", ".اسکرین صفحه 5  ← عکس از آخرین پیام‌های چت", "📸 اسکرین صفحه"),
        ("t", "screen_on", "🤖 اسکرین خودکار"),
        ("h", ".لایو عنوان  |  .پخش لینک  |  .پنل لایو", "🔴 لایو"),
        ("h", ".بن / .سیک / .آنبن  (ریپلای)", "⛔ بن"), ("h", ".پین / .حذف پین  (ریپلای)", "📌 پین"),
        ("h", ".بن ال / .حذف بن ال / .لیست بن ال  ← بن سراسری", "🌐 بن سراسری"),
    ]),
    8: ("🎮 بازی و سرگرمی", [
        ("h", ".تقلب تاس 6  |  دارت | بولینگ | بسکتبال | فوتبال | کازینو 64", "🎯 تقلب"),
        ("h", ".چالش استارزی روشن 30  (اول استارزی رو تنظیم کن)", "🔥 چالش استارزی"),
        ("h", ".تنظیم عکس استارزی (ریپلای)  |  .تنظیم زمان استارزی 20:00  |  .استارزی روشن", "⭐ استارزی"),
        ("h", ".تنظیم دوست / .حذف دوست  |  .لیست دوستان  |  .تنظیم کلمات دوست متن", "🫂 دوست"),
        ("h", ".تنظیم دشمن / .حذف دشمن  |  .لیست دشمن  |  .تنظیم فحش متن", "🗡 دشمن"),
        ("h", ".بازی گربه بگیر  |  غذا | بازی | خواب | اسم X", "🐱 بازی گربه"),
        ("t", "tabchi_on", "📣 تبچی"),
        ("h", ".تنظیم بنر فور (ریپلای)  |  .تنظیم دقیقه بنر 30 1  |  .تنظیم هدف بنر 1", "⚙️ تنظیم تبچی"),
        ("t", "content_on", "📦 محتوا"),
        ("h", ".محتوا جدید کلمه ← بعد: .ذخیره محتوا کلمه (ریپلای)  |  .لیست محتوا", "🗂 مدیریت محتوا"),
        ("h", ".تاس  .دارت  .بولینگ  .بسکتبال", "🎲 تاس و بازی‌ها"),
        ("h", ".کازینو  یا  .کازینو 64  ← اسلات تا رسیدن به عدد", "🎰 کازینو"),
    ]),
}


def detail_view(n, idx):
    """صفحه‌ی توضیح یک قابلیت + دکمه‌ی بازگشت به همون صفحه."""
    label = PAGES[n][1][idx][2]
    text = detail_text(label)
    if text is None:
        return None
    return text, [[Button.inline("🔙 بازگشت به دستورات", f"p:{n}".encode())]]


def item_label(item, cfg):
    kind, key, text = item
    if kind == "t":
        return f"{'✅' if cfg.get(key) else '⛔'} {text}"
    if kind == "c":
        return f"{text}: {cfg.get(key) or '⛔'}"
    return text


def main_view():
    ids = sorted(PAGES)
    rows = [[Button.inline(PAGES[n][0], f"p:{n}".encode()) for n in ids[i:i + 2]]
            for i in range(0, len(ids), 2)]
    rows.append([Button.inline("❌ بستن پنل", b"x")])
    return "🎛 پنل NRT Self\nیه بخش رو انتخاب کن:", rows


def page_view(n, cfg):
    title, items = PAGES[n]
    btns = [Button.inline(item_label(it, cfg), f"i:{n}:{i}".encode()) for i, it in enumerate(items)]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    nav = [Button.inline(f"「{k}」" if k == n else str(k), f"p:{k}".encode())
           for k in sorted(PAGES)]
    rows.extend(nav[i:i + 5] for i in range(0, len(nav), 5))  # مثل منوی اصلی: ۵ تا در هر ردیف
    rows.append([Button.inline("🔙 بازگشت به منوی اصلی", b"m")])
    return f"{title}  ({n}/{len(PAGES)})", rows


def setup_panel(bot, owner_id, cfg, save, on_change, actions):
    @bot.on(events.NewMessage(pattern=r'/start', func=lambda e: e.is_private))
    async def start(ev):
        if ev.sender_id != owner_id:
            return
        await ev.respond(
            '🎛 پنل NRT Self\nروی دکمه بزن و یه چت انتخاب کن تا پنل اونجا باز بشه:',
            buttons=[[Button.switch_inline('🎛 باز کردن پنل', query='panel')]])

    @bot.on(events.InlineQuery)
    async def inline(ev):
        if ev.sender_id != owner_id:
            await ev.answer([])
            return
        text, rows = main_view()
        await ev.answer([panel_article(ev, ev.sender_id, "پنل NRT Self", text, rows)],
                        cache_time=0, private=True)

    @bot.on(events.CallbackQuery(pattern=rb"(p:|i:|m$|x$)"))   # دکمه‌های بازی (g:) مال games.py
    async def callback(ev):
        if ev.sender_id != owner_id:
            await ev.answer("این پنل مال تو نیست", alert=True)
            return
        d = ev.data.decode().split(":")
        try:
            if d[0] == "x":
                await ev.edit("🎛 پنل بسته شد", buttons=[])
                return
            if d[0] == "m":
                text, rows = main_view()
            elif d[0] == "p":
                text, rows = page_view(int(d[1]), cfg)
            else:
                n, idx = int(d[1]), int(d[2])
                kind, key, _ = PAGES[n][1][idx]
                if kind == "t":
                    cfg[key] = not cfg.get(key)
                    save()
                    await on_change(key)
                elif kind == "c":
                    opts, cur = CYCLES[key], cfg.get(key)
                    cfg[key] = opts[(opts.index(cur) + 1) % len(opts)] if cur in opts else opts[0]
                    save()
                    await on_change(key)
                elif kind == "a":
                    fn = actions.get(key)
                    await ev.answer(await fn() if fn else "📌 دستور .اطلاعات یا .پینگ رو توی چت بزن", alert=True)
                    return
                else:
                    dv = detail_view(n, idx)
                    if dv is None:
                        await ev.answer("📌 " + key, alert=True)
                        return
                    try:
                        await ev.edit(dv[0], buttons=dv[1], parse_mode="html")
                    except Exception as ex:
                        if "not modified" not in str(ex).lower():
                            await ev.answer("📌 " + key, alert=True)
                    return
                text, rows = page_view(n, cfg)
            await ev.edit(text, buttons=rows)
            try:
                await ev.answer()
            except Exception:
                pass
        except Exception as ex:
            if "not modified" not in str(ex).lower():
                print("panel error:", ex)


def setup_panel_hub(bot, get_ctx, deny_text="⛔ سلف تو فعال نیست (الماس یا زمانت تموم شده)."):
    """پنل مشترک برای همه‌ی کاربرهای هاب.
    get_ctx(uid) -> (cfg, save, actions) یا None. تغییرها توی فایل کانفیگ کاربر ذخیره می‌شه
    و پروسه‌ی سلف همون کاربر هر چند ثانیه یه بار اعمالشون می‌کنه."""

    @bot.on(events.InlineQuery)
    async def inline(ev):
        ctx = get_ctx(ev.sender_id)
        if not ctx:
            await ev.answer([ev.builder.article("پنل", text=deny_text)], cache_time=0, private=True)
            return
        text, rows = main_view()
        await ev.answer([panel_article(ev, ev.sender_id, "پنل سلف", text, rows)],
                        cache_time=0, private=True)

    @bot.on(events.CallbackQuery(pattern=rb"(p:|i:|m$|x$)"))
    async def callback(ev):
        ctx = get_ctx(ev.sender_id)
        if not ctx:
            await ev.answer("این پنل مال تو نیست یا سلفت فعال نیست", alert=True)
            return
        cfg, save, actions = ctx
        d = ev.data.decode().split(":")
        try:
            if d[0] == "x":
                await ev.edit("🎛 پنل بسته شد", buttons=[])
                return
            if d[0] == "m":
                text, rows = main_view()
            elif d[0] == "p":
                text, rows = page_view(int(d[1]), cfg)
            else:
                n, idx = int(d[1]), int(d[2])
                kind, key, _ = PAGES[n][1][idx]
                if kind == "t":
                    cfg[key] = not cfg.get(key)
                    save()
                elif kind == "c":
                    opts, cur = CYCLES[key], cfg.get(key)
                    cfg[key] = opts[(opts.index(cur) + 1) % len(opts)] if cur in opts else opts[0]
                    save()
                elif kind == "a":
                    fn = actions.get(key)
                    await ev.answer(await fn() if fn else "📌 دستور .اطلاعات یا .پینگ رو توی چت بزن", alert=True)
                    return
                else:
                    dv = detail_view(n, idx)
                    if dv is None:
                        await ev.answer("📌 " + key, alert=True)
                        return
                    try:
                        await ev.edit(dv[0], buttons=dv[1], parse_mode="html")
                    except Exception as ex:
                        if "not modified" not in str(ex).lower():
                            await ev.answer("📌 " + key, alert=True)
                    return
                text, rows = page_view(n, cfg)
            await ev.edit(text, buttons=rows)
            try:
                await ev.answer()
            except Exception:
                pass
        except Exception as ex:
            if "not modified" not in str(ex).lower():
                print("panel hub error:", ex)
