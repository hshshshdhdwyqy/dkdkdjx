"""بات مدیریت: فعال‌سازی سلف با شماره + کیبورد دکمه‌ای کد ورود، و مدیریت (خاموش/روشن/حذف).
فقط OWNER_ID می‌تونه از این بات استفاده کنه."""
import os
from html import escape

from telethon import Button, errors, events

WELCOME = (
    "👋 <b>به NRT Self خوش اومدی!</b>\n\n"
    "این بات سلف روی اکانت خودت رو فعال و مدیریت می‌کنه.\n\n"
    "🔐 <b>نکته امنیتی:</b> کد ورود تلگرام رو فقط با کیبورد دکمه‌ای همین بات وارد کن. "
    "اگه کد رو توی چت تایپ کنی، تلگرام باطلش می‌کنه."
)


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


def setup_manager(bot, owner_id, client, cfg, hooks, banner=None):
    st = {"step": None, "phone": None, "hash": None, "code": ""}

    def reset():
        st.update(step=None, phone=None, hash=None, code="")

    async def authorized():
        try:
            return await client.is_user_authorized()
        except Exception:
            return False

    def status(auth):
        if not auth:
            return "🔒 وضعیت: لاگین نشده"
        return "✅ وضعیت: روشن" if cfg["enabled"] else "⏸ وضعیت: خاموش"

    def kb_main(auth):
        if not auth:
            return [[Button.inline("🔐 فعالسازی سلف", b"l:start")]]
        return [[Button.inline("ℹ️ اطلاعات اکانت", b"m:info"),
                 Button.inline("⚙️ مدیریت سلف", b"m:manage")]]

    back_main = [[Button.inline("🏠 منوی اصلی", b"m:main")]]

    async def view(name):
        auth = await authorized()
        if name == "info":
            i = await hooks["info"]() if auth else None
            if not i:
                return WELCOME + "\n\n" + status(False), kb_main(False)
            lines = ["ℹ️ <b>اطلاعات اکانت</b>\n",
                     f"👤 نام: {escape(i['name'])}",
                     f"🔗 یوزرنیم: <code>@{escape(i['username'])}</code>" if i["username"]
                     else "🔗 یوزرنیم: ندارد",
                     f"🆔 آیدی عددی: <code>{i['id']}</code>",
                     f"⏱ آپتایم: {i['uptime']} دقیقه",
                     status(True)]
            return "\n".join(lines), [[Button.inline("🔙 بازگشت", b"m:main")]]
        if name == "manage" and auth:
            on = cfg["enabled"]
            return (f"⚙️ <b>مدیریت سلف</b>\n\n{status(True)}"), [
                [Button.inline(f"{'🟢' if on else '🔴'} وضعیت سلف: {'روشن' if on else 'خاموش'}", b"m:status")],
                [Button.inline("⏸ خاموش کردن", b"m:off"), Button.inline("🗑 حذف سلف", b"m:del")],
                [Button.inline("▶️ فعالسازی دوباره", b"m:on")],
                [Button.inline("🔑 بازیابی حساب", b"m:recover")],
                [Button.inline("🔙 بازگشت", b"m:main")]]
        if name == "del" and auth:
            return ("⚠️ <b>مطمئنی؟</b>\nنشست سلف پاک می‌شه و از اکانت خارج می‌شی. "
                    "برای فعال‌سازی دوباره باید دوباره لاگین کنی."), [
                [Button.inline("✅ بله، حذف کن", b"m:delyes"), Button.inline("❌ خیر", b"m:manage")]]
        return WELCOME + "\n\n" + status(auth), kb_main(auth)

    async def send_main(chat):
        auth = await authorized()
        text, buttons = WELCOME + "\n\n" + status(auth), kb_main(auth)
        user_banner = os.path.join(os.getenv("BANNER_DIR", "banners"), f"user_{owner_id}.jpg")
        banner_use = user_banner if os.path.exists(user_banner) else banner
        if banner_use and os.path.exists(banner_use):
            await bot.send_file(chat, banner_use, caption=text, buttons=buttons, parse_mode="html")
        else:
            await bot.send_message(chat, text, buttons=buttons, parse_mode="html")

    async def begin_login(ev):
        reset()
        st["step"] = "phone"
        await ev.answer()
        await bot.send_message(
            owner_id,
            "📱 شماره‌ی تلفنت رو با دکمه‌ی پایین بفرست (فقط شماره‌ی خودت قبول می‌شه).",
            buttons=[[Button.request_phone("📱 ارسال شماره تلفن", resize=True)],
                     [Button.text("❌ انصراف", resize=True)]])

    async def finish_login(ev):
        me = await client.get_me()
        if me.id != owner_id:
            await client.log_out()
            reset()
            await ev.edit("❌ این اکانت با OWNER_ID یکی نیست؛ خارج شدم.", buttons=back_main)
            import asyncio
            asyncio.create_task(hooks["restart"]())
            return
        reset()
        await ev.edit("✅ <b>سلف فعال شد!</b>\nتوی تلگرام <code>.راهنما</code> یا <code>.پنل</code> بنویس.",
                      buttons=back_main, parse_mode="html")
        await hooks["activate"]()

    async def submit_code(ev):
        try:
            await client.sign_in(st["phone"], st["code"], phone_code_hash=st["hash"])
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
            reset()
            await ev.edit("⌛ کد منقضی شد. دوباره از «فعالسازی» شروع کن.", buttons=back_main)
            return
        await finish_login(ev)

    async def keypad_press(ev, key):
        if st["step"] != "code":
            await ev.answer("⌛ این کیبورد منقضی شده. دوباره از «فعالسازی» شروع کن.", alert=True)
            return
        if key == "cancel":
            reset()
            await ev.edit("🚫 لغو شد.", buttons=back_main)
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
            await submit_code(ev)
            return
        await ev.edit(code_text(st["code"]), buttons=keypad(), parse_mode="html")

    @bot.on(events.CallbackQuery)
    async def on_cb(ev):
        if ev.sender_id != owner_id:
            await ev.answer("این بات خصوصیه", alert=True)
            return
        d = ev.data.decode()
        try:
            if d in ("l:start", "m:recover"):
                if await authorized():
                    await ev.answer("✅ حساب الان فعاله. برای لاگین مجدد اول «حذف سلف» رو بزن.", alert=True)
                else:
                    await begin_login(ev)
                return
            if d.startswith("k:"):
                await keypad_press(ev, d[2:])
                return
            if d == "m:status":
                await ev.answer("🟢 روشن" if cfg["enabled"] else "🔴 خاموش", alert=True)
                return
            if d == "m:off":
                await hooks["set_enabled"](False)
                d = "m:manage"
            elif d == "m:on":
                await hooks["set_enabled"](True)
                d = "m:manage"
            elif d == "m:delyes":
                await ev.edit("⏳ در حال حذف سلف...", buttons=[])
                await hooks["delete"]()
                await ev.edit("🗑 سلف حذف شد. بات چند ثانیه دیگه ریستارت می‌شه؛ بعدش /start بزن.",
                              buttons=[])
                return
            text, buttons = await view(d.split(":", 1)[1])
            await ev.edit(text, buttons=buttons, parse_mode="html")
        except Exception as ex:
            if "not modified" not in str(ex).lower():
                print("manager error:", ex)
            try:
                await ev.answer()
            except Exception:
                pass

    @bot.on(events.NewMessage(incoming=True))
    async def on_msg(ev):
        if ev.sender_id != owner_id or not ev.is_private:
            return
        m = ev.message
        text = (m.raw_text or "").strip()
        if text.startswith("/start"):
            reset()
            await send_main(owner_id)
            return
        if text in ("❌ انصراف", "/cancel"):
            reset()
            await bot.send_message(owner_id, "🚫 لغو شد.", buttons=Button.clear())
            await send_main(owner_id)
            return
        if st["step"] == "phone" and m.contact:
            if m.contact.user_id != owner_id:
                await ev.respond("❌ فقط شماره‌ی خودت (با دکمه‌ی پایین) قبول می‌شه.")
                return
            phone = "+" + m.contact.phone_number.lstrip("+")
            try:
                sent = await client.send_code_request(phone)
            except errors.FloodWaitError as ex:
                await ev.respond(f"⏳ تلگرام محدود کرد؛ {ex.seconds} ثانیه صبر کن.")
                return
            except Exception as ex:
                await ev.respond(f"❌ خطا: {ex}")
                return
            st.update(step="code", phone=phone, hash=sent.phone_code_hash, code="")
            await ev.respond("✅ کد به تلگرامت ارسال شد.", buttons=Button.clear())
            await ev.respond(code_text(""), buttons=keypad(), parse_mode="html")
            return
        if st["step"] == "password" and text:
            try:
                await m.delete()
            except Exception:
                pass
            try:
                await client.sign_in(password=text)
            except errors.PasswordHashInvalidError:
                await bot.send_message(owner_id, "❌ رمز اشتباهه. دوباره بنویس.")
                return
            except Exception as ex:
                await bot.send_message(owner_id, f"❌ خطا: {ex}")
                return
            me = await client.get_me()
            if me.id != owner_id:
                await client.log_out()
                reset()
                await bot.send_message(owner_id, "❌ این اکانت با OWNER_ID یکی نیست؛ خارج شدم.")
                import asyncio
                asyncio.create_task(hooks["restart"]())
                return
            reset()
            await bot.send_message(owner_id, "✅ سلف فعال شد! توی تلگرام .راهنما یا .پنل بنویس.",
                                   buttons=back_main)
            await hooks["activate"]()
