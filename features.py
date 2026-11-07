"""قابلیت‌های اضافه: بازی، صدا، موسیقی/یوتیوب، ابزار تبدیل، کیفیت عکس،
دوست، بن سراسری و محتوای ذخیره‌شده."""
import asyncio
import os
import random
import shutil
import tempfile
import time

from telethon import functions, types

KINDS = ["عکس", "ویدیو", "گیف", "استیکر", "دایره"]
MOVING = {"ویدیو", "گیف", "دایره"}
VOICES = {"مرد": "fa-IR-FaridNeural", "زن": "fa-IR-DilaraNeural"}
GAMES = {"تاس": "🎲", "دارت": "🎯", "بولینگ": "🎳", "بسکتبال": "🏀"}
MAX_SONG_SEC = 15 * 60


# ================= توابع خالص (بدون تلگرام؛ قابل تست) =================
async def run_ff(*args):
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg نصب نیست (apt install ffmpeg)")
    p = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await p.communicate()
    if p.returncode:
        raise ValueError("ffmpeg: " + err.decode(errors="ignore")[-200:])


def kind_of(m):
    if m.video_note:
        return "دایره"
    if m.sticker:
        return "استیکر"
    if m.gif:
        return "گیف"
    if m.video:
        return "ویدیو"
    if m.photo:
        return "عکس"
    return None


async def convert_file(src, tgt, inp, wd):
    """src/tgt از KINDS. خروجی: (مسیر فایل، kwargs برای send_file)."""
    moving = src in MOVING or inp.endswith(".webm")
    out = os.path.join(wd, "out")
    loop = [] if moving else ["-loop", "1", "-t", "3"]  # عکس/استیکر ثابت ← ۳ ثانیه ویدیو

    if tgt == "عکس":
        o = out + ".jpg"
        await run_ff("-i", inp, "-frames:v", "1", "-q:v", "2", o)
        return o, {}

    if tgt == "استیکر":
        sticker = types.DocumentAttributeSticker(alt="🙂", stickerset=types.InputStickerSetEmpty())
        if not moving:
            from PIL import Image
            o = out + ".webp"
            im = Image.open(inp).convert("RGBA")
            k = 512 / max(im.size)
            im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
            im.save(o, "WEBP")
            return o, {"force_document": True,
                       "attributes": [sticker, types.DocumentAttributeImageSize(w=im.width, h=im.height)]}
        o = out + ".webm"
        await run_ff("-t", "3", "-i", inp, "-an",
                     "-vf", "scale=512:512:force_original_aspect_ratio=decrease,fps=30",
                     "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                     "-b:v", "200k", "-maxrate", "250k", "-bufsize", "500k", o)
        return o, {"force_document": True,
                   "attributes": [sticker, types.DocumentAttributeVideo(duration=3, w=512, h=512)]}

    if tgt in ("گیف", "ویدیو"):
        o = out + ".mp4"
        audio = ["-an"] if tgt == "گیف" else ["-map", "0:a?", "-c:a", "aac"]
        await run_ff(*loop, "-i", inp, "-map", "0:v:0", *audio,
                     "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                     "-c:v", "libx264", "-preset", "veryfast", "-movflags", "+faststart", o)
        if tgt == "گیف":
            return o, {"force_document": False, "attributes": [types.DocumentAttributeAnimated()]}
        return o, {"supports_streaming": True}

    if tgt == "دایره":
        o = out + ".mp4"
        await run_ff(*loop, "-i", inp, "-t", "60", "-map", "0:v:0", "-map", "0:a?",
                     "-vf", "crop='min(iw,ih)':'min(iw,ih)',scale=384:384,format=yuv420p",
                     "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
                     "-movflags", "+faststart", o)
        return o, {"video_note": True}

    raise ValueError("مقصد نامعتبر")


def enhance_image(path_in, path_out):
    """بزرگ‌کردن ۲ برابر + شارپ ملایم (بدون هوش مصنوعی)."""
    from PIL import Image, ImageEnhance, ImageFilter
    im = Image.open(path_in).convert("RGB")
    w, h = im.size
    k = min(2.0, 4096 / max(w, h))
    if k > 1:
        im = im.resize((round(w * k), round(h * k)), Image.LANCZOS)
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=140, threshold=3))
    im = ImageEnhance.Contrast(im).enhance(1.05)
    im.save(path_out, "JPEG", quality=95)


async def synth(text, gender, wd):
    mp3 = os.path.join(wd, "v.mp3")
    try:
        import edge_tts
        await edge_tts.Communicate(text, VOICES[gender]).save(mp3)
    except Exception:
        try:
            from gtts import gTTS
        except ImportError:
            raise ValueError("edge-tts یا gTTS نصب نیست")
        await asyncio.to_thread(lambda: gTTS(text, lang="fa").save(mp3))
    if shutil.which("ffmpeg"):
        ogg = os.path.join(wd, "v.ogg")
        await run_ff("-i", mp3, "-c:a", "libopus", "-b:a", "32k", "-ac", "1", ogg)
        return ogg
    return mp3


def parse_q(a):
    q, _, n = a.partition("|")
    n = int(n.strip()) if n.strip().isdigit() else 1
    return q.strip(), max(1, min(n, 10))


def yt_search(q, n):
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "extract_flat": True}) as y:
        info = y.extract_info(f"ytsearch{n}:{q}", download=False)
    return info.get("entries") or []


def yt_download(url, wd):
    import yt_dlp
    opts = {"quiet": True, "noplaylist": True, "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": os.path.join(wd, "%(id)s.%(ext)s"), "max_filesize": 50 * 1024 * 1024}
    if shutil.which("ffmpeg"):
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                   "preferredcodec": "mp3", "preferredquality": "128"}]
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
    files = [os.path.join(wd, f) for f in os.listdir(wd)]
    if not files:
        raise ValueError("دانلود نشد (شاید حجم بالای ۵۰ مگ یا محدودیت یوتیوب)")
    return files[0], info


def sr_transcribe(wav):
    import speech_recognition as sr
    r = sr.Recognizer()
    with sr.AudioFile(wav) as s:
        audio = r.record(s)
    return r.recognize_google(audio, language="fa-IR")


# ================= ثبت دستورها =================
def setup(client, cfg, save, cmd, out, target):
    friend_seen = {}
    me_cache = {}

    async def my_id():
        if "id" not in me_cache:
            me_cache["id"] = (await client.get_me()).id
        return me_cache["id"]

    async def need_reply(e):
        if not e.is_reply:
            raise ValueError("روی یه پیام ریپلای کن")
        return await e.get_reply_message()

    # ---------- بازی و کازینو ----------
    async def roll(e, emoji):
        return await client.send_file(e.chat_id, types.InputMediaDice(emoji),
                                      reply_to=e.reply_to_msg_id)

    def make_game(name, emoji):
        @cmd(name)
        async def _(e, a):
            await e.delete()
            await roll(e, emoji)

    for _n, _e in GAMES.items():
        make_game(_n, _e)

    @cmd("کازینو")
    async def casino(e, a):
        want = int(a) if a.strip().isdigit() else None
        if want is not None and not 1 <= want <= 64:
            raise ValueError("عدد بین ۱ تا ۶۴")
        await e.delete()
        for i in range(12 if want else 1):
            m = await roll(e, "🎰")
            if want is None or m.media.value == want:
                return
            if i < 11:
                await asyncio.sleep(1.5)
                await m.delete()

    # ---------- متن به ویس / ویس به متن ----------
    async def tts_cmd(e, a, gender):
        text = a or ((await e.get_reply_message()).raw_text if e.is_reply else "")
        if not text:
            raise ValueError("متن بده یا ریپلای کن")
        gender = gender or cfg["voice"]
        await out(e, "⏳ در حال ساخت ویس...")
        with tempfile.TemporaryDirectory() as wd:
            p = await synth(text[:1000], gender, wd)
            await client.send_file(e.chat_id, p, voice_note=True, reply_to=e.reply_to_msg_id)
        await e.delete()

    def make_tts(name, gender):
        @cmd(name)
        async def _(e, a):
            await tts_cmd(e, a, gender)

    make_tts("متن به ویس", None)
    make_tts("ویس", None)
    make_tts("متن به ویس مرد", "مرد")
    make_tts("متن به ویس زن", "زن")

    def make_voice_set(name, gender):
        @cmd(name)
        async def _(e, a):
            cfg["voice"] = gender
            save()
            await out(e, f"🎙 صدای پیش‌فرض: {gender}")

    make_voice_set("صدای ویس مرد", "مرد")
    make_voice_set("صدای ویس زن", "زن")

    @cmd("ویس به متن")
    async def stt(e, a):
        r = await need_reply(e)
        if not (r.voice or r.audio or r.video_note):
            raise ValueError("روی یه ویس ریپلای کن")
        await out(e, "⏳ در حال تبدیل...")
        text = None
        try:  # ترنسکرایب خود تلگرام (نیاز به پریمیوم)
            for _ in range(8):
                res = await client(functions.messages.TranscribeAudioRequest(
                    peer=await e.get_input_chat(), msg_id=r.id))
                text = res.text
                if not res.pending:
                    break
                await asyncio.sleep(2)
        except Exception:
            text = None
        if not text:
            try:
                with tempfile.TemporaryDirectory() as wd:
                    src = await r.download_media(os.path.join(wd, "in"))
                    wav = os.path.join(wd, "a.wav")
                    await run_ff("-i", src, "-ar", "16000", "-ac", "1", wav)
                    text = await asyncio.to_thread(sr_transcribe, wav)
            except ImportError:
                raise ValueError("برای غیرپریمیوم‌ها: pip install SpeechRecognition")
            except Exception as ex:
                raise ValueError(f"تشخیص گفتار ناموفق بود ({ex})")
        await out(e, "📝 " + text)

    # ---------- آهنگ و یوتیوب ----------
    async def query_from(e, a):
        q, n = parse_q(a)
        if not q and e.is_reply:
            r = await e.get_reply_message()
            if r.voice or r.audio or r.video:
                raise ValueError("شناسایی آهنگ از روی ویس پشتیبانی نمی‌شه؛ اسم آهنگ رو بنویس")
            q = (r.raw_text or "").strip()
        if not q:
            raise ValueError("اسم آهنگ رو بنویس. مثال: .آهنگ اسم | 2")
        return q, n

    async def music(e, a):
        q, n = await query_from(e, a)
        await out(e, "🔎 در حال جستجو...")
        try:
            res = await asyncio.to_thread(yt_search, q, n)
        except ImportError:
            raise ValueError("pip install yt-dlp")
        if len(res) < n:
            raise ValueError("نتیجه‌ای پیدا نشد")
        v = res[n - 1]
        if (v.get("duration") or 0) > MAX_SONG_SEC:
            raise ValueError("آهنگ بیشتر از ۱۵ دقیقه‌ست")
        await out(e, f"⬇️ دانلود: {v.get('title', '')[:80]}")
        with tempfile.TemporaryDirectory() as wd:
            path, info = await asyncio.to_thread(
                yt_download, f"https://www.youtube.com/watch?v={v['id']}", wd)
            title = info.get("title", "")
            await client.send_file(
                e.chat_id, path, reply_to=e.reply_to_msg_id,
                caption=f"🎵 {title}\nMusic Finder | NRT Self",
                attributes=[types.DocumentAttributeAudio(
                    duration=int(info.get("duration") or 0), title=title[:60],
                    performer=(info.get("uploader") or "")[:60])])
        await e.delete()

    cmd("آهنگ", "سرچ آهنگ")(music)

    @cmd("سرچ یوتیوب")
    async def yt(e, a):
        q, n = await query_from(e, a)
        try:
            res = await asyncio.to_thread(yt_search, q, n)
        except ImportError:
            raise ValueError("pip install yt-dlp")
        if len(res) < n:
            raise ValueError("نتیجه‌ای پیدا نشد")
        v = res[n - 1]
        await out(e, f"🔎 {v.get('title', '')}\nhttps://www.youtube.com/watch?v={v['id']}")

    # ---------- کیفیت عکس ----------
    @cmd("کیفیت")
    async def quality(e, a):
        r = await need_reply(e)
        if not r.photo:
            raise ValueError("روی یه عکس ریپلای کن")
        await out(e, "⏳ در حال بهبود...")
        with tempfile.TemporaryDirectory() as wd:
            src = await r.download_media(os.path.join(wd, "in"))
            dst = os.path.join(wd, "hq.jpg")
            await asyncio.to_thread(enhance_image, src, dst)
            await client.send_file(e.chat_id, dst, force_document=True, reply_to=r.id)
        await e.delete()

    # ---------- ابزار تبدیل ----------
    async def do_convert(e, src, tgt):
        r = await need_reply(e)
        k = kind_of(r)
        if not k:
            raise ValueError("این پیام مدیا نداره")
        if src and k != src:
            raise ValueError(f"پیام ریپلای‌شده {src} نیست (این {k}ـه)")
        if k == tgt:
            raise ValueError("مبدأ و مقصد یکیه")
        if r.sticker and r.document.mime_type == "application/x-tgsticker":
            raise ValueError("استیکر انیمیشنی (tgs) پشتیبانی نمی‌شه")
        await out(e, "⏳ در حال تبدیل...")
        with tempfile.TemporaryDirectory() as wd:
            inp = await r.download_media(os.path.join(wd, "in"))
            o, kw = await convert_file(k, tgt, inp, wd)
            await client.send_file(e.chat_id, o, reply_to=r.id, **kw)
        await e.delete()

    def make_conv(src, tgt):
        @cmd(f"{src} به {tgt}")
        async def _(e, a):
            await do_convert(e, src, tgt)

    for _s in KINDS:
        for _t in KINDS:
            if _s != _t:
                make_conv(_s, _t)

    @cmd("دایره")
    async def circle(e, a):
        await do_convert(e, None, "دایره")

    # ---------- بن سراسری ----------
    @cmd("بن ال")
    async def gban_add(e, a):
        uid = await target(e, a)
        if uid not in cfg["gbans"]:
            cfg["gbans"].append(uid)
        save()
        await out(e, f"⛔ به لیست بن سراسری اضافه شد: {uid}\n(توی گروه‌هایی که ادمینی، با اولین پیامش بن می‌شه)")

    @cmd("حذف بن ال")
    async def gban_del(e, a):
        uid = await target(e, a)
        if uid in cfg["gbans"]:
            cfg["gbans"].remove(uid)
        save()
        await out(e, f"✅ از لیست بن سراسری حذف شد: {uid}")

    @cmd("لیست بن ال")
    async def gban_list(e, a):
        await out(e, "⛔ بن سراسری:\n" + ("\n".join(map(str, cfg["gbans"])) or "خالی"))

    # ---------- لیست دوستان ----------
    async def read_lines(e):
        r = await need_reply(e)
        if not r.document:
            raise ValueError("روی فایل txt ریپلای کن")
        data = await r.download_media(bytes)
        return [x.strip() for x in data.decode("utf-8", "ignore").splitlines() if x.strip()]

    @cmd("تنظیم دوست")
    async def friend_add(e, a):
        uid = await target(e, a)
        if uid not in cfg["friends"]:
            cfg["friends"].append(uid)
        save()
        await out(e, f"✅ به دوستان اضافه شد: {uid}")

    @cmd("حذف دوست")
    async def friend_del(e, a):
        uid = await target(e, a)
        if uid in cfg["friends"]:
            cfg["friends"].remove(uid)
        save()
        await out(e, f"✅ از دوستان حذف شد: {uid}")

    @cmd("لیست دوستان")
    async def friend_list(e, a):
        await out(e, f"👥 دوستان ({len(cfg['friends'])}):\n" +
                  ("\n".join(map(str, cfg["friends"][:60])) or "خالی"))

    @cmd("پاکسازی لیست دوستان")
    async def friend_clear(e, a):
        cfg["friends"] = []
        save()
        await out(e, "🧹 لیست دوستان پاک شد")

    @cmd("تنظیم لیست دوست")
    async def friend_set(e, a):
        ids = []
        for line in (await read_lines(e))[:200]:
            if line.lstrip("-").isdigit():
                ids.append(int(line))
                continue
            try:
                ids.append((await client.get_entity(line)).id)
            except Exception:
                pass
            await asyncio.sleep(0.4)
        cfg["friends"] = ids
        save()
        await out(e, f"✅ لیست دوستان جایگزین شد ({len(ids)} نفر)")

    @cmd("تنظیم کلمات دوست")
    async def fw_add(e, a):
        if not a:
            raise ValueError("متن رو بنویس")
        cfg["friend_words"].append(a)
        save()
        await out(e, f"✅ کلمه اضافه شد ({len(cfg['friend_words'])})")

    @cmd("تنظیم لیست کلمات دوست")
    async def fw_set(e, a):
        cfg["friend_words"] = await read_lines(e)
        save()
        await out(e, f"✅ کلمات دوست جایگزین شد ({len(cfg['friend_words'])})")

    @cmd("پاکسازی لیست کلمات دوست")
    async def fw_clear(e, a):
        cfg["friend_words"] = []
        save()
        await out(e, "🧹 کلمات دوست پاک شد")

    # ---------- محتوا ----------
    @cmd("محتوا")
    async def content_toggle(e, a):
        w = a.split()[0] if a else ""
        if w not in ("روشن", "خاموش"):
            raise ValueError("بنویس: .محتوا روشن / خاموش")
        cfg["content_on"] = w == "روشن"
        save()
        await out(e, f"📦 محتوا: {'✅ روشن' if cfg['content_on'] else '⛔ خاموش'}")

    @cmd("محتوا جدید")
    async def content_new(e, a):
        if not a:
            raise ValueError("کلمه رو بنویس")
        cfg["content"].setdefault(a, None)
        save()
        await out(e, f"✅ کلمه ثبت شد: {a}\nحالا روی یه پیام ریپلای کن و بنویس: .ذخیره محتوا {a}")

    @cmd("ذخیره محتوا")
    async def content_save(e, a):
        if not a:
            raise ValueError("کلمه رو بنویس")
        r = await need_reply(e)
        saved = await client.send_message("me", r)  # کپی توی Saved Messages
        cfg["content"][a] = saved.id
        save()
        await out(e, f"💾 ذخیره شد زیر «{a}»")

    @cmd("حذف محتوا")
    async def content_del(e, a):
        cfg["content"].pop(a, None)
        save()
        await out(e, f"✅ حذف شد: {a}")

    @cmd("لیست محتوا")
    async def content_list(e, a):
        rows = [f"{'✅' if v else '⬜'} {k}" for k, v in cfg["content"].items()]
        await out(e, f"📦 محتوا ({'روشن' if cfg['content_on'] else 'خاموش'}):\n" +
                  ("\n".join(rows) or "خالی"))

    # ---------- هوک‌ها ----------
    async def on_outgoing_text(e, text):
        """اگه متن دقیقاً یه کلمه‌ی محتوا باشه، با محتوای ذخیره‌شده جایگزین می‌شه."""
        if not cfg["content_on"] or e.chat_id == await my_id():
            return False
        mid = cfg["content"].get(text)
        if not mid:
            return False
        msg = await client.get_messages("me", ids=mid)
        if not msg or (msg.message or "") == text:
            return False
        await e.delete()
        await client.send_message(e.chat_id, msg, reply_to=e.reply_to_msg_id)
        return True

    async def on_incoming(e):
        sid = e.sender_id
        if not sid:
            return
        if sid in cfg["gbans"] and not e.is_private:
            try:
                await client.edit_permissions(e.chat_id, sid, view_messages=False)
                await e.delete()
            except Exception:
                pass
            return True
        if sid in cfg["friends"] and cfg["friend_words"]:
            k, now = (e.chat_id, sid), time.time()
            if now - friend_seen.get(k, 0) > 60:
                friend_seen[k] = now
                await e.reply(random.choice(cfg["friend_words"]))
        return False

    return {"outgoing": on_outgoing_text, "incoming": on_incoming}
