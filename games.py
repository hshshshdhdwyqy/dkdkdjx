"""بازی‌های گروهی روی بات هلپر (۲۱ و دوئل تاس) با «سکه‌ی مجازی».
سکه‌ها فقط امتیاز بازی‌ان: خرید، فروش، انتقال یا تبدیل به پول ندارن."""
import asyncio
import html
import os
import random
import re
import sqlite3
import time
import uuid

from telethon import Button, events, types

DB_PATH = os.getenv("GAMES_DB", "games.db")


def _parse_chat_ids(raw):
    """GAME_CHAT_ID: یک یا چند آیدی عددی گروه، با کاما جدا. مثل -1001234567890"""
    ids = set()
    for part in (raw or "").replace("،", ",").split(","):
        part = part.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        if part.lstrip("-").isdigit():
            n = int(part)
            # آیدی گروه/سوپرگروه رو با یا بدون پیشوند -100 قبول می‌کنیم
            ids.add(n)
            if n > 0:
                ids.add(int(f"-100{n}"))
                ids.add(-n)
    return ids


GAME_CHATS = _parse_chat_ids(os.getenv("GAME_CHAT_ID"))   # خالی = همه‌ی چت‌ها
START_COINS, DAILY_COINS = 1000, 500
MIN_STAKE, MAX_STAKE, DEFAULT_STAKE = 10, 100000, 100
MAX_PLAYERS, LOBBY_TTL, TURN_TTL = 3, 120, 60
RNG = random.SystemRandom()
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = "♠♥♦♣"
TITLES = {"bj": "🃏 <b>بازی ۲۱</b>", "dice": "🎲 <b>دوئل تاس</b>"}
FA2EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

HELP = (
    "🎮 <b>بازی‌های گروهی</b> (با سکه‌ی مجازی)\n\n"
    "🃏 <code>/21 [شرط]</code> یا «بازی 21» ← بلک‌جک، ۲ تا ۳ نفره یا با ربات\n"
    "🎲 <code>/dice [شرط]</code> یا «دوئل تاس» ← هر کی تاس بزرگ‌تر بندازه می‌بره\n"
    "💰 <code>/balance</code> یا «موجودی»\n"
    "🎁 <code>/daily</code> یا «جایزه روزانه» ← هر ۲۴ ساعت یه بار\n"
    "🏆 <code>/top</code> ← برترین‌ها\n\n"
    f"هر کاربر با {START_COINS} سکه شروع می‌کنه. سکه‌ها فقط امتیاز بازی‌ان: "
    "خرید و فروش و تبدیل به پول ندارن.\n"
    "<i>برای کار با متن فارسی بدون اسلش، حالت Privacy بات رو توی BotFather خاموش کن "
    "(/setprivacy ← Disable).</i>")


# ---------------- منطق خالص ----------------
def card_value(rank):
    return 11 if rank == "A" else 10 if rank in ("10", "J", "Q", "K") else int(rank)


def hand_total(hand):
    t = sum(card_value(r) for r, _ in hand)
    aces = sum(1 for r, _ in hand if r == "A")
    while t > 21 and aces:
        t -= 10
        aces -= 1
    return t


def fmt_hand(hand):
    return " ".join(f"{r}{s}" for r, s in hand)


def new_deck():
    d = [(r, s) for r in RANKS for s in SUITS]
    RNG.shuffle(d)
    return d


def split_pot(pot, winners):
    """pot رو بین برنده‌ها تقسیم می‌کنه؛ باقی‌مونده به اولی. خروجی: {id: مبلغ}"""
    share, rest = divmod(pot, len(winners))
    res = {w: share for w in winners}
    res[winners[0]] += rest
    return res


# ---------------- کیف پول (sqlite) ----------------
class Wallet:
    def __init__(self, path):
        self.c = sqlite3.connect(path)
        self.c.executescript("""
            CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, coins INTEGER NOT NULL,
                                             daily REAL NOT NULL DEFAULT 0, name TEXT);
            CREATE TABLE IF NOT EXISTS escrow(game TEXT, user INTEGER, amount INTEGER);""")
        # اگه بات وسط بازی ریستارت شده بود، شرط‌ها برمی‌گردن
        for uid, amt in self.c.execute("SELECT user, SUM(amount) FROM escrow GROUP BY user").fetchall():
            self.c.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (amt, uid))
        self.c.execute("DELETE FROM escrow")
        self.c.commit()

    def get(self, uid, name=None):
        r = self.c.execute("SELECT coins FROM users WHERE id=?", (uid,)).fetchone()
        if r is None:
            self.c.execute("INSERT INTO users(id, coins, name) VALUES(?,?,?)", (uid, START_COINS, name))
            self.c.commit()
            return START_COINS
        if name:
            self.c.execute("UPDATE users SET name=? WHERE id=?", (name, uid))
            self.c.commit()
        return r[0]

    def lock(self, gid, ids, stake):
        """شرط همه رو کم می‌کنه. اگه کسی کم داشت: لیست اون‌ها (و هیچ تغییری نمی‌ده)."""
        lacking = [i for i in ids if self.get(i) < stake]
        if lacking:
            return lacking
        for i in ids:
            self.c.execute("UPDATE users SET coins = coins - ? WHERE id = ?", (stake, i))
            self.c.execute("INSERT INTO escrow VALUES(?,?,?)", (gid, i, stake))
        self.c.commit()
        return []

    def pay(self, gid, payouts):
        for uid, amt in payouts.items():
            if amt:
                self.get(uid)
                self.c.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (amt, uid))
        self.c.execute("DELETE FROM escrow WHERE game=?", (gid,))
        self.c.commit()

    def daily(self, uid):
        self.get(uid)
        last = self.c.execute("SELECT daily FROM users WHERE id=?", (uid,)).fetchone()[0]
        wait = 86400 - (time.time() - last)
        if wait > 0:
            return int(wait)
        self.c.execute("UPDATE users SET coins = coins + ?, daily = ? WHERE id = ?",
                       (DAILY_COINS, time.time(), uid))
        self.c.commit()
        return 0

    def top(self, n=10):
        return self.c.execute("SELECT name, coins FROM users ORDER BY coins DESC LIMIT ?", (n,)).fetchall()


def mention(p):
    return f'<a href="tg://user?id={p["id"]}">{html.escape(p["name"])}</a>'


# ---------------- بات ----------------
def setup_games(bot, db_path=None):
    wallet = Wallet(db_path or DB_PATH)
    games, by_chat = {}, {}

    def lobby_text(g):
        names = "\n".join(f"• {mention(p)}" for p in g["players"])
        return (f"{TITLES[g['type']]}\n💰 شرط هر نفر: <b>{g['stake']}</b> سکه\n"
                f"👥 بازیکنان ({len(g['players'])}/{MAX_PLAYERS}):\n{names}\n\n"
                f"⏳ تا {LOBBY_TTL} ثانیه؛ سازنده می‌تونه شروع کنه یا با ربات بازی کنه")

    def lobby_buttons(g):
        i = g["id"]
        return [[Button.inline("✅ پیوستن", f"g:{i}:join".encode())],
                [Button.inline("▶️ شروع", f"g:{i}:start".encode()),
                 Button.inline("🤖 با ربات", f"g:{i}:bot".encode())],
                [Button.inline("❌ لغو", f"g:{i}:cancel".encode())]]

    def play_text(g):
        n = len(g["players"])
        head = f"{TITLES['bj']}\n💰 شرط: {g['stake']} | 🏆 جایزه: {g['stake'] * (2 if g['vs_bot'] else n)}\n"
        if g["vs_bot"]:
            p = g["players"][0]
            h = g["hands"][p["id"]]
            up = g["dealer"][0]
            return (head + f"\n🤖 ربات: {up[0]}{up[1]} ؟\n"
                    f"👤 {mention(p)}: {fmt_hand(h)}  = <b>{hand_total(h)}</b>")
        lines = [head]
        for i, p in enumerate(g["players"]):
            st = g["status"][p["id"]]
            mark = ("⏳ نوبت اوست" if i == g["turn"] else "…") if st == "play" else \
                   {"stand": "✋ ایستاد", "bust": "💥 سوخت"}[st]
            lines.append(f"• {mention(p)} — {len(g['hands'][p['id']])} کارت — {mark}")
        lines.append(f"\n⏱ هر نوبت {TURN_TTL} ثانیه. «دستم» کارت‌هات رو فقط به خودت نشون می‌ده.")
        return "\n".join(lines)

    def play_buttons(g):
        i = g["id"]
        return [[Button.inline("🃏 کارت بگیر", f"g:{i}:hit".encode()),
                 Button.inline("✋ بایست", f"g:{i}:stand".encode())],
                [Button.inline("👁 دستم", f"g:{i}:hand".encode())]]

    async def edit(g, text, buttons):
        try:
            await g["msg"].edit(text, buttons=buttons, parse_mode="html")
        except Exception as ex:
            if "not modified" not in str(ex).lower():
                print("games edit error:", ex)

    def close(g):
        games.pop(g["id"], None)
        if by_chat.get(g["chat"]) == g["id"]:
            by_chat.pop(g["chat"], None)
        g["state"] = "done"

    async def finish(g, text, payouts):
        wallet.pay(g["id"], payouts)
        close(g)
        await edit(g, text, [])

    # ---- بلک‌جک ----
    async def bj_start(g):
        g["deck"], g["hands"], g["status"], g["turn"] = new_deck(), {}, {}, 0
        for p in g["players"]:
            g["hands"][p["id"]] = [g["deck"].pop(), g["deck"].pop()]
            g["status"][p["id"]] = "stand" if hand_total(g["hands"][p["id"]]) == 21 else "play"
        if g["vs_bot"]:
            g["dealer"] = [g["deck"].pop(), g["deck"].pop()]
        await bj_advance(g)

    def arm_timer(g):
        g["token"] += 1
        asyncio.create_task(bj_timeout(g, g["token"]))

    async def bj_timeout(g, token):
        await asyncio.sleep(TURN_TTL)
        async with g["lock"]:
            if g["state"] != "play" or g["token"] != token:
                return
            g["status"][g["players"][g["turn"]]["id"]] = "stand"
            g["turn"] += 1
            await bj_advance(g)

    async def bj_advance(g):
        while g["turn"] < len(g["players"]) and g["status"][g["players"][g["turn"]]["id"]] != "play":
            g["turn"] += 1
        if g["turn"] >= len(g["players"]):
            await bj_finish(g)
            return
        arm_timer(g)
        await edit(g, play_text(g), play_buttons(g))

    async def bj_finish(g):
        players, stake = g["players"], g["stake"]
        if g["vs_bot"]:
            p = players[0]
            h, d = g["hands"][p["id"]], g["dealer"]
            pt = hand_total(h)
            if pt <= 21:
                while hand_total(d) < 17:
                    d.append(g["deck"].pop())
            dt = hand_total(d)
            natural = len(h) == 2 and pt == 21 and not (len(d) == 2 and dt == 21)
            if pt > 21 or (dt <= 21 and dt > pt):
                res, pay = "💥 باختی" if pt > 21 else "😔 ربات برد", 0
            elif dt > 21 or pt > dt:
                pay = stake * 5 // 2 if natural else stake * 2
                res = "🎉 بردی" + (" (بلک‌جک ×۲٫۵)" if natural else "")
            else:
                res, pay = "🤝 مساوی؛ شرط برگشت", stake
            text = (f"{TITLES['bj']}\n\n👤 {mention(p)}: {fmt_hand(h)} = <b>{pt}</b>\n"
                    f"🤖 ربات: {fmt_hand(d)} = <b>{dt}</b>\n\n{res}\n"
                    f"💰 {pay - stake:+d} سکه | موجودی: {wallet.get(p['id']) + pay}")
            await finish(g, text, {p["id"]: pay})
            return
        scores = {p["id"]: (-1 if hand_total(g["hands"][p["id"]]) > 21 else hand_total(g["hands"][p["id"]]))
                  for p in players}
        best = max(scores.values())
        pot = stake * len(players)
        if best < 0:
            res, payouts = "💥 همه سوختن؛ شرط‌ها برگشت", {p["id"]: stake for p in players}
        else:
            winners = [i for i, s in scores.items() if s == best]
            payouts = split_pot(pot, winners)
            wn = ", ".join(mention(p) for p in players if p["id"] in winners)
            res = f"🏆 برنده: {wn}\n💰 جایزه: {pot // len(winners)} سکه" if len(winners) == 1 else \
                  f"🤝 مساوی بین: {wn}\n💰 سهم هر نفر: {pot // len(winners)} سکه"
        rows = "\n".join(
            f"• {mention(p)}: {fmt_hand(g['hands'][p['id']])} = <b>{hand_total(g['hands'][p['id']])}</b>"
            f"{' 💥' if scores[p['id']] < 0 else ''}" for p in players)
        await finish(g, f"{TITLES['bj']}\n\n{rows}\n\n{res}", payouts)

    # ---- دوئل تاس ----
    async def dice_run(g):
        stake, players = g["stake"], g["players"]
        contenders = list(players) + ([{"id": 0, "name": "ربات"}] if g["vs_bot"] else [])
        log = []
        winner = None
        for rnd in range(3):
            vals = {}
            for p in contenders:
                await edit(g, f"{TITLES['dice']}\n💰 شرط: {stake}\n\n🎲 نوبت {mention(p)} ...", [])
                m = await bot.send_file(g["chat"], types.InputMediaDice("🎲"))
                vals[p["id"]] = m.media.value
                await asyncio.sleep(3.5)
            log.append(" | ".join(f"{html.escape(p['name'])}: {vals[p['id']]}" for p in contenders))
            best = max(vals.values())
            tied = [p for p in contenders if vals[p["id"]] == best]
            if len(tied) == 1:
                winner = tied[0]
                break
            contenders = tied
        pot = stake * (2 if g["vs_bot"] else len(players))
        if winner is None:
            payouts = {p["id"]: stake for p in players}
            res = "🤝 چند دور مساوی شد؛ شرط‌ها برگشت"
        elif winner["id"] == 0:
            payouts, res = {}, "😔 ربات برد"
        else:
            payouts, res = {winner["id"]: pot}, f"🏆 برنده: {mention(winner)}\n💰 جایزه: {pot} سکه"
        await finish(g, f"{TITLES['dice']}\n\n" + "\n".join(log) + f"\n\n{res}", payouts)

    # ---- شروع بازی ----
    async def begin(g, vs_bot):
        g["vs_bot"] = vs_bot
        if vs_bot and len(g["players"]) > 1:
            g["players"] = g["players"][:1]
        lacking = wallet.lock(g["id"], [p["id"] for p in g["players"]], g["stake"])
        if lacking:
            names = ", ".join(p["name"] for p in g["players"] if p["id"] in lacking)
            return f"موجودی کافی نیست: {names}"
        g["state"] = "play"
        if g["type"] == "bj":
            await bj_start(g)
        else:
            asyncio.create_task(dice_run_safe(g))
        return None

    async def dice_run_safe(g):
        try:
            await dice_run(g)
        except Exception as ex:  # شرط‌ها رو برگردون
            print("dice error:", ex)
            if g["state"] != "done":
                wallet.pay(g["id"], {p["id"]: g["stake"] for p in g["players"]})
                close(g)

    async def lobby_timeout(g):
        await asyncio.sleep(LOBBY_TTL)
        async with g["lock"]:
            if g["state"] == "lobby":
                close(g)
                await edit(g, f"{TITLES[g['type']]}\n\n⌛ کسی شروع نکرد؛ بازی لغو شد.", [])

    # ---- هندلرها ----
    async def create(ev, gtype, stake):
        if stake < MIN_STAKE or stake > MAX_STAKE:
            return await ev.reply(f"شرط باید بین {MIN_STAKE} تا {MAX_STAKE} سکه باشه.")
        if ev.chat_id in by_chat:
            return await ev.reply("توی این چت یه بازی فعال داریم؛ اول اون تموم بشه.")
        s = await ev.get_sender()
        me = {"id": ev.sender_id, "name": (getattr(s, "first_name", None) or "کاربر")[:25]}
        if wallet.get(me["id"], me["name"]) < stake:
            return await ev.reply(f"موجودیت کمه ({wallet.get(me['id'])} سکه).")
        g = {"id": uuid.uuid4().hex[:8], "type": gtype, "chat": ev.chat_id, "stake": stake,
             "owner": me["id"], "players": [me], "state": "lobby", "lock": asyncio.Lock(),
             "token": 0, "vs_bot": False}
        games[g["id"]], by_chat[ev.chat_id] = g, g["id"]
        g["msg"] = await ev.reply(lobby_text(g), buttons=lobby_buttons(g), parse_mode="html")
        asyncio.create_task(lobby_timeout(g))

    def allowed(chat_id):
        return not GAME_CHATS or chat_id in GAME_CHATS

    async def on_msg(ev):
        if not allowed(ev.chat_id):
            return
        raw = (ev.raw_text or "").strip()
        if not raw or len(raw) > 60:
            return
        slash = raw.startswith("/")
        t = raw.lstrip("/").translate(FA2EN).replace("‌", " ")
        t = re.sub(r"@\w+", "", t, count=1).strip()
        m = re.match(r"^(.*?)(?:\s+(\d+))?$", t)
        word, arg = m.group(1).strip().lower(), m.group(2)
        stake = int(arg) if arg else DEFAULT_STAKE
        if slash:
            table = {"21": "bj", "bj": "bj", "dice": "dice", "balance": "bal", "bal": "bal",
                     "daily": "daily", "top": "top", "games": "help", "help": "help"}
        else:
            table = {"بازی 21": "bj", "دوئل تاس": "dice", "موجودی": "bal", "جایزه روزانه": "daily",
                     "برترین ها": "top", "راهنمای بازی": "help"}
        act = table.get(word)
        if not act and arg and f"{word} {arg}" in table:   # «بازی 21» (عدد جزو اسم دستوره)
            act, stake = table[f"{word} {arg}"], DEFAULT_STAKE
        if not act:
            return
        if act in ("bj", "dice"):
            await create(ev, act, stake)
        elif act == "bal":
            s = await ev.get_sender()
            name = (getattr(s, "first_name", None) or "کاربر")[:25]
            await ev.reply(f"💰 موجودی {html.escape(name)}: <b>{wallet.get(ev.sender_id, name)}</b> سکه",
                           parse_mode="html")
        elif act == "daily":
            s = await ev.get_sender()
            wallet.get(ev.sender_id, (getattr(s, "first_name", None) or "کاربر")[:25])
            wait = wallet.daily(ev.sender_id)
            if wait:
                await ev.reply(f"⏳ جایزه‌ی بعدی تا {wait // 3600} ساعت و {wait % 3600 // 60} دقیقه‌ی دیگه")
            else:
                await ev.reply(f"🎁 {DAILY_COINS} سکه گرفتی! موجودی: {wallet.get(ev.sender_id)}")
        elif act == "top":
            rows = [f"{i}. {html.escape(n or '؟')} — {c}" for i, (n, c) in enumerate(wallet.top(), 1)]
            await ev.reply("🏆 <b>برترین‌ها</b>\n" + ("\n".join(rows) or "هنوز کسی نیست"), parse_mode="html")
        else:
            await ev.reply(HELP, parse_mode="html")

    async def on_cb(ev):
        if not allowed(ev.chat_id):
            return
        try:
            _, gid, act = ev.data.decode().split(":")
        except ValueError:
            return
        g = games.get(gid)
        if not g:
            await ev.answer("این بازی تموم شده.", alert=True)
            return
        uid = ev.sender_id
        async with g["lock"]:
            if g["state"] == "done":
                await ev.answer("این بازی تموم شده.", alert=True)
                return
            if g["state"] == "lobby":
                if act == "join":
                    if any(p["id"] == uid for p in g["players"]):
                        return await ev.answer("تو توی بازی هستی.", alert=True)
                    if len(g["players"]) >= MAX_PLAYERS:
                        return await ev.answer("ظرفیت پره.", alert=True)
                    s = await ev.get_sender()
                    name = (getattr(s, "first_name", None) or "کاربر")[:25]
                    if wallet.get(uid, name) < g["stake"]:
                        return await ev.answer(f"موجودیت کمه ({wallet.get(uid)} سکه).", alert=True)
                    g["players"].append({"id": uid, "name": name})
                    await ev.answer("پیوستی ✅")
                    if len(g["players"]) == MAX_PLAYERS:
                        err = await begin(g, False)
                        if err:
                            await ev.respond(err)
                    else:
                        await edit(g, lobby_text(g), lobby_buttons(g))
                    return
                if uid != g["owner"]:
                    return await ev.answer("فقط سازنده‌ی بازی می‌تونه.", alert=True)
                if act == "cancel":
                    close(g)
                    await ev.answer()
                    await edit(g, f"{TITLES[g['type']]}\n\n❌ بازی لغو شد.", [])
                elif act in ("start", "bot"):
                    if act == "start" and len(g["players"]) < 2:
                        return await ev.answer("حداقل ۲ نفر لازمه؛ یا «با ربات» رو بزن.", alert=True)
                    err = await begin(g, act == "bot")
                    if err:
                        return await ev.answer(err, alert=True)
                    await ev.answer()
                return
            # --- بازی در جریان (بلک‌جک) ---
            if g["type"] != "bj":
                return await ev.answer("بازی در جریانه…")
            ids = [p["id"] for p in g["players"]]
            if uid not in ids:
                return await ev.answer("تو توی این بازی نیستی.", alert=True)
            if act == "hand":
                h = g["hands"][uid]
                return await ev.answer(f"{fmt_hand(h)}  = {hand_total(h)}", alert=True)
            if g["players"][g["turn"]]["id"] != uid:
                return await ev.answer("نوبت تو نیست.", alert=True)
            if act == "hit":
                g["hands"][uid].append(g["deck"].pop())
                h = g["hands"][uid]
                tot = hand_total(h)
                await ev.answer(f"{fmt_hand(h)}  = {tot}", alert=True)
                if tot > 21:
                    g["status"][uid] = "bust"
                elif tot == 21:
                    g["status"][uid] = "stand"
            elif act == "stand":
                g["status"][uid] = "stand"
                await ev.answer()
            else:
                return
            if g["status"][uid] != "play":
                g["turn"] += 1
            await bj_advance(g)

    bot.on(events.NewMessage(incoming=True))(on_msg)
    bot.on(events.CallbackQuery(pattern=rb"g:"))(on_cb)
    return {"on_msg": on_msg, "on_cb": on_cb, "wallet": wallet, "games": games}
