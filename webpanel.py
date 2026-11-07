"""پنل وبِ مدیریت هاب (فقط برای ادمین) — بدون وابستگی اضافه، با asyncio خالص.

فعال‌سازی: توی .env مقدار WEB_PASSWORD رو بذار. پیش‌فرض فقط روی 127.0.0.1:8080 گوش می‌ده.
برای دسترسی از بیرون: پشت nginx/caddy با HTTPS بذار (و WEB_SECURE=1)، یا با SSH tunnel بازش کن.
"""
import asyncio
import hmac
import os
import re
import secrets
import time
from html import escape
from urllib.parse import parse_qs, quote, unquote, urlsplit

SESSION_TTL = 12 * 3600
MAX_BODY = 64 * 1024
PAGE_SIZE = 20

CSS = """
:root{--bg:#0e0620;--card:#1a0d33;--line:#3a1f66;--tx:#f1e9ff;--mut:#a995cf;--p:#a855f7;--r:#ff3c5a;--g:#22c55e}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0,#2a0f52,#0e0620 60%) fixed;color:var(--tx);
font-family:Tahoma,Vazirmatn,system-ui,sans-serif;line-height:1.7}
a{color:#c4a1ff;text-decoration:none}.wrap{max-width:1000px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:0}h2{font-size:17px;margin:0 0 10px}
.top{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:16px}
.logo{font-weight:800;font-size:24px;background:linear-gradient(90deg,#ff3c5a,#c03cff,#5a78ff);-webkit-background-clip:text;color:transparent}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:14px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:14px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;text-align:center}
.stat b{display:block;font-size:24px}.stat span{color:var(--mut);font-size:13px}
table{width:100%;border-collapse:collapse}th,td{padding:8px 6px;border-bottom:1px solid var(--line);text-align:right;font-size:14px}
th{color:var(--mut);font-weight:600}.tw{overflow-x:auto}
input,textarea,select{background:#12082a;color:var(--tx);border:1px solid var(--line);border-radius:10px;padding:9px 11px;font:inherit;max-width:100%}
textarea{width:100%;min-height:90px}
button,.btn{background:linear-gradient(90deg,#8b3cff,#c03cff);color:#fff;border:0;border-radius:10px;padding:9px 14px;font:inherit;cursor:pointer;display:inline-block}
.btn.red,button.red{background:linear-gradient(90deg,#e11d48,#ff3c5a)}.btn.gray,button.gray{background:#2c1b4d}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px}
.tag{padding:2px 9px;border-radius:99px;font-size:12px;background:#2c1b4d}.on{background:#0f3d24;color:#7dffb0}.off{background:#3a1f66}.ban{background:#4a1020;color:#ff9aa9}
.flash{background:#1d0f3b;border:1px solid var(--p);border-radius:12px;padding:10px 14px;margin-bottom:14px}
.card{box-shadow:0 8px 30px #0006;backdrop-filter:blur(6px)}button:hover,.btn:hover{filter:brightness(1.12);transform:translateY(-1px)}
button,.btn{transition:.15s}.nav{display:flex;gap:8px;align-items:center}.nav a{padding:7px 13px;border-radius:10px;background:#2c1b4d}
.nav a.cur{background:linear-gradient(90deg,#8b3cff,#c03cff);color:#fff}.hint{color:var(--mut);font-size:12.5px;margin:2px 0 10px}
.field{margin-bottom:14px}.field label{display:block;font-weight:700;margin-bottom:4px}.field input{width:100%}
.mut{color:var(--mut)}.center{text-align:center}.login{max-width:360px;margin:12vh auto}
"""


def page(title, body, sess=None, flash="", cur="/"):
    nav = ""
    if sess:
        links = "".join(f'<a href="{u}" class="{"cur" if u == cur else ""}">{t}</a>' for u, t in (("/", "📊 داشبورد"), ("/settings", "⚙️ تنظیمات")))
        nav = (f'<div class="nav">{links}</div><form method="post" action="/logout"><input type="hidden" name="csrf" value="{sess["csrf"]}">'
               '<button class="gray">خروج</button></form>')
    fl = f'<div class="flash">{escape(flash)}</div>' if flash else ""
    return (f'<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>{escape(title)}</title><style>{CSS}</style></head>'
            f'<body><div class="wrap"><div class="top"><a href="/" class="logo">NRT self</a>{nav}</div>'
            f'{fl}{body}</div></body></html>')


def csrf_input(s):
    return f'<input type="hidden" name="csrf" value="{s["csrf"]}">'


class WebPanel:
    def __init__(self, h, password, host="127.0.0.1", port=8080, secure=False):
        self.h, self.password, self.host, self.port, self.secure = h, password, host, port, secure
        self.sessions = {}          # token -> {"csrf", "exp"}
        self.fails = {}             # ip -> [count, until]

    # ---------- سرور ----------
    async def start(self):
        srv = await asyncio.start_server(self.handle, self.host, self.port, limit=MAX_BODY)
        print(f"Web panel: http://{self.host}:{self.port}")
        return srv

    async def handle(self, reader, writer):
        try:
            ip = (writer.get_extra_info("peername") or ("?",))[0]
            try:
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
            except Exception:
                return
            lines = head.decode("latin-1").split("\r\n")
            try:
                method, target, _ = lines[0].split(" ", 2)
            except ValueError:
                return
            headers = {}
            for ln in lines[1:]:
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            body = b""
            n = int(headers.get("content-length", "0") or 0)
            if n > MAX_BODY:
                return await self.send(writer, 413, "too large")
            if n:
                body = await asyncio.wait_for(reader.readexactly(n), 15)
            form = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}
            u = urlsplit(target)
            query = {k: v[0] for k, v in parse_qs(u.query).items()}
            cookies = {}
            for part in headers.get("cookie", "").split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    cookies[k.strip()] = v.strip()
            sess = self.get_session(cookies.get("nrt_s"))
            status, hdrs, out = await self.route(method, unquote(u.path), query, form, sess, ip)
            await self.send(writer, status, out, hdrs)
        except Exception as ex:
            print("web error:", ex)
            try:
                await self.send(writer, 500, "خطای داخلی")
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def send(self, writer, status, body, hdrs=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        reason = {200: "OK", 302: "Found", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
                  413: "Too Large", 429: "Too Many Requests", 500: "Error"}.get(status, "OK")
        h = {"Content-Type": "text/html; charset=utf-8", "Content-Length": str(len(data)),
             "Connection": "close", "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
             "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
             "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                                        "frame-ancestors 'none'; base-uri 'none'"}
        h.update(hdrs or {})
        head = f"HTTP/1.1 {status} {reason}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h.items()) + "\r\n"
        writer.write(head.encode("latin-1") + data)
        await writer.drain()

    # ---------- نشست ----------
    def get_session(self, token):
        s = self.sessions.get(token or "")
        if not s:
            return None
        if s["exp"] < time.time():
            self.sessions.pop(token, None)
            return None
        s["token"] = token
        return s

    def new_session(self):
        tok = secrets.token_urlsafe(32)
        self.sessions[tok] = {"csrf": secrets.token_urlsafe(24), "exp": time.time() + SESSION_TTL}
        return tok

    def cookie(self, tok, clear=False):
        c = f"nrt_s={tok}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if clear else SESSION_TTL}"
        return c + ("; Secure" if self.secure else "")

    @staticmethod
    def redirect(to, extra=None):
        h = {"Location": to}
        h.update(extra or {})
        return 302, h, ""

    def flash_to(self, to, msg):
        return self.redirect(f"{to}{'&' if '?' in to else '?'}m={quote(msg)}")

    # ---------- مسیرها ----------
    async def route(self, method, path, q, form, sess, ip):
        h = self.h
        if path == "/login":
            if method == "POST":
                f = self.fails.get(ip, [0, 0])
                if f[1] > time.time():
                    return 429, {}, page("قفل", '<div class="card center">تلاش‌های زیاد؛ چند دقیقه بعد دوباره امتحان کن.</div>')
                if hmac.compare_digest(form.get("password", "").encode(), self.password.encode()):
                    self.fails.pop(ip, None)
                    return self.redirect("/", {"Set-Cookie": self.cookie(self.new_session())})
                f[0] += 1
                if f[0] >= 5:
                    f = [0, time.time() + 300]
                self.fails[ip] = f
                await asyncio.sleep(1)
            return 200, {}, page("ورود", (
                '<form class="card login" method="post" action="/login"><h2>ورود ادمین</h2>'
                '<div class="row"><input type="password" name="password" placeholder="رمز پنل" autofocus required style="width:100%"></div>'
                '<button style="width:100%">ورود</button>'
                + ('<p class="mut">رمز اشتباه بود.</p>' if method == "POST" else "") + "</form>"))
        if not sess:
            return self.redirect("/login")
        if method == "POST":
            if not hmac.compare_digest(form.get("csrf", "").encode(), sess["csrf"].encode()):
                return 403, {}, page("خطا", '<div class="card">درخواست نامعتبر (CSRF).</div>', sess)
            if path == "/logout":
                self.sessions.pop(sess["token"], None)
                return self.redirect("/login", {"Set-Cookie": self.cookie("", clear=True)})
            return await self.post(path, form, sess)
        flash = q.get("m", "")
        if path == "/":
            return 200, {}, self.dashboard(q, sess, flash)
        if path == "/settings":
            return 200, {}, self.settings_page(sess, flash)
        if path.startswith("/user/"):
            try:
                uid = int(path.split("/")[2])
            except ValueError:
                return 404, {}, page("404", '<div class="card">پیدا نشد.</div>', sess)
            return 200, {}, self.user_page(uid, sess, flash)
        return 404, {}, page("404", '<div class="card">پیدا نشد.</div>', sess)

    # ---------- صفحه‌ها ----------
    def bal(self, u):
        return "♾ نامحدود" if u["user_id"] in self.h["admins"] else f"{u['diamonds']:.1f}"

    def dashboard(self, q, sess, flash):
        h = self.h
        ids = h["db_all"]()
        users = [h["db_get"](i) for i in ids]
        total_d = sum(u["diamonds"] for u in users if u["user_id"] not in h["admins"])
        stats = [("کل کاربرها", len(users)), ("سلف روشن", len(h["running"])),
                 ("لاگین‌شده", sum(1 for u in users if h["is_logged_in"](u["user_id"]))),
                 ("مسدود", sum(1 for u in users if u["banned"])), ("مجموع الماس", f"{total_d:.0f}")]
        st = "".join(f'<div class="stat"><b>{v}</b><span>{k}</span></div>' for k, v in stats)
        s = q.get("s", "").strip()
        if s:
            found = set(h["db_search"](s))
            users = [u for u in users if u["user_id"] in found]
        try:
            pg = max(0, int(q.get("p", "0")))
        except ValueError:
            pg = 0
        pages = max(1, (len(users) + PAGE_SIZE - 1) // PAGE_SIZE)
        pg = min(pg, pages - 1)
        rows = ""
        for u in users[pg * PAGE_SIZE:(pg + 1) * PAGE_SIZE]:
            uid = u["user_id"]
            on = uid in h["running"]
            tags = (f'<span class="tag {"on" if on else "off"}">{"روشن" if on else "خاموش"}</span> ' +
                    ('<span class="tag ban">بن</span> ' if u["banned"] else "") +
                    ('<span class="tag">ادمین</span>' if uid in h["admins"] else ""))
            un = f'@{escape(u["username"])}' if u["username"] else "—"
            rows += (f'<tr><td><a href="/user/{uid}">{uid}</a></td><td>{un}</td><td>{self.bal(u)}</td>'
                     f'<td>{tags}</td></tr>')
        nav = ""
        qs = f"&s={quote(s)}" if s else ""
        if pg > 0:
            nav += f'<a class="btn gray" href="/?p={pg-1}{qs}">قبلی</a> '
        if pg < pages - 1:
            nav += f'<a class="btn gray" href="/?p={pg+1}{qs}">بعدی</a>'
        body = (f'<div class="stats">{st}</div>'
                f'<div class="card"><form class="row" method="get" action="/">'
                f'<input name="s" value="{escape(s)}" placeholder="آیدی یا یوزرنیم"><button>جستجو</button></form>'
                f'<div class="tw"><table><tr><th>آیدی</th><th>یوزرنیم</th><th>الماس</th><th>وضعیت</th></tr>{rows}</table></div>'
                f'<div class="row" style="margin-top:10px">{nav}<span class="mut">صفحه {pg+1} از {pages}</span></div></div>'
                f'<div class="card"><h2>📢 ارسال همگانی</h2>'
                f'<form method="post" action="/broadcast/msg">{csrf_input(sess)}<textarea name="text" placeholder="متن پیام همگانی" required></textarea>'
                f'<button>ارسال به همه</button></form><hr style="border-color:var(--line)">'
                f'<form class="row" method="post" action="/broadcast/diamond">{csrf_input(sess)}'
                f'<input name="amount" type="number" step="any" min="0.01" placeholder="تعداد الماس برای همه" required>'
                f'<button>💎 الماس همگانی</button></form></div>')
        return page("پنل مدیریت", body, sess, flash)

    def user_page(self, uid, sess, flash):
        h = self.h
        u = h["db_get"](uid)
        is_adm = uid in h["admins"]
        on = uid in h["running"]
        un = f'@{escape(u["username"])}' if u["username"] else "—"
        trial = "هنوز نگرفته" if not u["trial_used"] else h["fmt_duration"](u["trial_seconds"])
        info = (f'<div class="card"><h2>👤 کاربر {uid} <span class="mut">{un}</span></h2>'
                f'<p>📱 شماره: {escape(str(u["phone"] or "—"))}<br>🔑 ورود: {"✅" if h["is_logged_in"](uid) else "🔒"}<br>'
                f'📶 سلف: {"🟢 روشن" if on else "⏸ خاموش"}<br>💎 موجودی: {self.bal(u)}<br>'
                f'🎁 تست: {escape(trial)}<br>⛔ بن: {"بله" if u["banned"] else "خیر"}</p></div>')

        def form(action, inner, cls=""):
            return (f'<form class="row" method="post" action="/user/{uid}/{action}">{csrf_input(sess)}{inner}</form>')
        acts = ""
        if not is_adm:
            acts += form("diamond", '<input name="amount" type="number" step="any" min="0.01" placeholder="تعداد الماس" required>'
                                    '<button name="op" value="add">➕ افزایش</button>'
                                    '<button class="red" name="op" value="sub">➖ کاهش</button>')
        acts += form("trial", '<button>🎁 تست هدیه</button>')
        acts += form("ban", f'<button class="red">{"🔓 رفع بن" if u["banned"] else "⛔ بن کردن"}</button>')
        if on:
            acts += form("stop", '<button class="gray">⏸ خاموش‌کردن سلفش</button>')
        msg = (f'<form method="post" action="/user/{uid}/msg">{csrf_input(sess)}'
               f'<textarea name="text" placeholder="متن پیام به این کاربر" required></textarea><button>📨 ارسال پیام</button></form>')
        return page(f"کاربر {uid}", info + f'<div class="card"><h2>عملیات</h2>{acts}</div>'
                    f'<div class="card">{msg}</div><a class="btn gray" href="/">🔙 بازگشت</a>', sess, flash)

    # ---------- عملیات ----------
    # ---------- تنظیمات (.env) ----------
    ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    EDITABLE = {
        "GAME_CHAT_ID": ("آیدی عددی گروه بازی", "مثل -1001234567890 ؛ چندتا را با کاما جدا کن. خالی = بازی در همه‌ی چت‌ها", r"-?\d+(,\s*-?\d+)*|"),
        "DIAMOND_SECONDS": ("ثانیه‌ی معادل هر الماس", "پیش‌فرض ۱۷۹۶ (حدود نیم ساعت)", r"\d{1,9}"),
        "TRIAL_SECONDS": ("طول تست رایگان (ثانیه)", "پیش‌فرض ۲۱۶۰۰ (۶ ساعت)", r"\d{1,9}"),
    }
    SECRETS = ("HUB_BOT_TOKEN", "HUB_HELPER_BOT_TOKEN", "API_HASH", "WEB_PASSWORD", "ADMIN_IDS")

    def read_env(self):
        vals = {}
        try:
            with open(self.ENV_PATH, encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        vals[k.strip()] = v.strip()
        except OSError:
            pass
        return vals

    def settings_page(self, sess, flash):
        env = self.read_env()
        fields = ""
        for k, (title, hint, _) in self.EDITABLE.items():
            fields += (f'<div class="field"><label>{escape(title)}</label>'
                       f'<input name="{k}" value="{escape(env.get(k, ""))}" dir="ltr" autocomplete="off">'
                       f'<div class="hint">{escape(hint)}</div></div>')
        ok_tag = '<span class="tag on">تنظیم شده</span>'
        no_tag = '<span class="tag off">خالی</span>'
        sec = "".join(f'<tr><td dir="ltr">{k}</td><td>{ok_tag if env.get(k) else no_tag}</td></tr>'
                      for k in self.SECRETS)
        body = (f'<div class="card"><h2>⚙️ تنظیمات</h2><form method="post" action="/settings">{csrf_input(sess)}{fields}'
                f'<button>💾 ذخیره</button></form>'
                f'<p class="hint">تغییرها بعد از ریستارت اعمال می‌شن.</p></div>'
                f'<div class="card"><h2>🔁 ریستارت</h2><p class="hint">هاب دوباره بالا میاد؛ سلف کاربرها هم خودکار برمی‌گردن.</p>'
                f'<form method="post" action="/restart" onsubmit="return confirm(\'ریستارت بشه؟\')">{csrf_input(sess)}'
                f'<button class="red">ریستارت هاب</button></form></div>'
                f'<div class="card"><h2>🔐 مقادیر محرمانه</h2><p class="hint">برای امنیت از توی وب قابل دیدن/تغییر نیستن؛ فقط فایل .env روی سرور.</p>'
                f'<div class="tw"><table>{sec}</table></div></div>')
        return page("تنظیمات", body, sess, flash, cur="/settings")

    def save_settings(self, form):
        new = {}
        for k, (title, _, rx) in self.EDITABLE.items():
            v = form.get(k, "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            if not re.fullmatch(rx, v):
                return self.flash_to("/settings", f"مقدار «{title}» نامعتبره")
            new[k] = v
        try:
            with open(self.ENV_PATH, encoding="utf-8") as f:
                lines = f.read().split("\n")
        except OSError:
            lines = []
        done = set()
        for i, line in enumerate(lines):
            k = line.split("=", 1)[0].strip()
            if "=" in line and k in new and not line.lstrip().startswith("#"):
                lines[i] = f"{k}={new[k]}"
                done.add(k)
        if lines and lines[-1] == "":
            lines.pop()
        lines += [f"{k}={v}" for k, v in new.items() if k not in done]
        tmp = self.ENV_PATH + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, self.ENV_PATH)
        return self.flash_to("/settings", "ذخیره شد ✅ برای اعمال، ریستارت کن")

    async def post(self, path, form, sess):
        h = self.h
        parts = [p for p in path.split("/") if p]
        try:
            if parts == ["settings"]:
                return self.save_settings(form)
            if parts == ["restart"]:
                if not h.get("restart"):
                    return self.flash_to("/settings", "ریستارت پشتیبانی نمی‌شه")
                asyncio.get_running_loop().call_later(1.0, h["restart"])
                return self.flash_to("/settings", "در حال ریستارت... چند ثانیه صبر کن و صفحه رو رفرش کن")
            if parts[:1] == ["broadcast"] and len(parts) == 2:
                ids = h["db_all"](include_banned=False)
                if parts[1] == "msg":
                    text = form.get("text", "").strip()
                    if not text:
                        return self.flash_to("/", "متن خالیه")
                    sent = 0
                    for uid in ids:
                        try:
                            await h["send_html"](uid, f"📢 <b>پیام همگانی:</b>\n\n{escape(text)}")
                            sent += 1
                        except Exception:
                            pass
                        await asyncio.sleep(0.05)
                    return self.flash_to("/", f"برای {sent} از {len(ids)} کاربر ارسال شد")
                if parts[1] == "diamond":
                    amount = float(form.get("amount", "0").replace(",", "."))
                    if amount <= 0:
                        raise ValueError
                    n = 0
                    for uid in ids:
                        if uid in h["admins"]:
                            continue
                        u = h["db_get"](uid)
                        h["db_set"](uid, diamonds=u["diamonds"] + amount)
                        await h["notify"](uid, f"🎁 ادمین {amount:.1f} الماس به همه‌ی کاربرا هدیه داد!")
                        n += 1
                    return self.flash_to("/", f"به {n} کاربر {amount:.1f} الماس داده شد")
            if parts[:1] == ["user"] and len(parts) == 3:
                uid, act = int(parts[1]), parts[2]
                back = f"/user/{uid}"
                u = h["db_get"](uid)
                if act == "diamond" and uid not in h["admins"]:
                    amount = float(form.get("amount", "0").replace(",", "."))
                    if amount <= 0:
                        raise ValueError
                    if form.get("op") == "add":
                        h["db_set"](uid, diamonds=u["diamonds"] + amount)
                        await h["notify"](uid, f"💎 {amount:.1f} الماس به حسابت اضافه شد. موجودی فعلی: {h['db_get'](uid)['diamonds']:.1f}")
                        return self.flash_to(back, "الماس اضافه شد")
                    new = max(0.0, u["diamonds"] - amount)
                    h["db_set"](uid, diamonds=new)
                    if new <= 0 and uid in h["running"] and h["running"][uid]["mode"] == "paid":
                        await h["stop_self"](uid, "⏰ موجودی الماست توسط ادمین صفر شد و سلفت خاموش شد.")
                    await h["notify"](uid, f"💎 {amount:.1f} الماس از حسابت کم شد. موجودی فعلی: {new:.1f}")
                    return self.flash_to(back, "الماس کم شد")
                if act == "trial":
                    h["db_set"](uid, trial_used=1, trial_seconds=h["TRIAL_SECONDS"])
                    await h["notify"](uid, f"🎁 ادمین {h['fmt_duration'](h['TRIAL_SECONDS'])} تست رایگان بهت هدیه داد!")
                    return self.flash_to(back, "تست هدیه داده شد")
                if act == "ban" and uid not in h["admins"]:
                    h["db_set"](uid, banned=0 if u["banned"] else 1)
                    if not u["banned"]:
                        await h["stop_self"](uid, "⛔ دسترسیت توسط ادمین مسدود شد.")
                    return self.flash_to(back, "وضعیت بن عوض شد")
                if act == "stop":
                    await h["stop_self"](uid, "⏸ ادمین سلفت رو خاموش کرد.")
                    return self.flash_to(back, "سلف خاموش شد")
                if act == "msg":
                    text = form.get("text", "").strip()
                    if not text:
                        return self.flash_to(back, "متن خالیه")
                    try:
                        await h["send_html"](uid, f"📨 <b>پیام از ادمین:</b>\n\n{escape(text)}")
                        return self.flash_to(back, "ارسال شد")
                    except Exception:
                        return self.flash_to(back, "ارسال نشد (شاید بات رو بلاک کرده)")
        except ValueError:
            return self.flash_to("/", "ورودی نامعتبر")
        return 404, {}, page("404", '<div class="card">پیدا نشد.</div>', sess)
