import asyncio
import json
import os
import base64
import aiohttp
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.enums import ChatType
from aiogram.client.default import DefaultBotProperties

# ====== НАСТРОЙКИ (ВПИШИ СВОИ ДАННЫЕ СЮДА) ======
BOT_TOKEN = "ТВОЙ_ТОКЕН_ОТ_BOTFATHER"
ADMIN_ID = 922545502
GROUP_ID = -1004291975368

# Токен для автосохранения базы в GitHub (если не нужен, оставь пустым "")
GITHUB_TOKEN = "ТВОЙ_GITHUB_ТОКЕН_ЕСЛИ_ЕСТЬ"
GITHUB_REPO = "evgeniyaagzholova-commits/anon_bot"

LOG_CHANNEL_ID = -1004378039855
DB_BACKUP_CHANNEL_ID = -1004378039855 
# ================================================

# Ссылки
LINK_ANKETA = "http://t.me/Just_my_thoughts_anketa_bot"
LINK_CHANNEL = "https://t.me/+aG7myjG7KG5jYTFi"
LINK_SUPPORT = "https://t.me/Tehpodderzka_sweethome_bot"
LINK_REVIEWS = "https://t.me/+7yar-PgEeDAxN2Ey"

# Баннеры
BANNER_TOPIC = "https://i.ibb.co.com/Z42GnWK/photo-2026-09-24-22-57-48.jpg"
BANNER_GENDER = "https://i.ibb.co.com/ymsM3sDd/photo-2026-09-24-22-57-34.jpg"

WELCOME_TEXT = (
    "✧ Добро пожаловать в бот поддержки и общения «Милый дом» ♡\n\n"
    "Здесь тебя всегда выслушают и поймут.\n\n"
    "✉ Напиши «Привет» — и с тобой свяжется первый свободный администратор.\n\n"
    "❋ Бот полностью анонимен.\n"
    "Можешь не указывать тег — просто будь собой.\n\n"
    "♡ Если тебе некомфортно с текущим админом — напиши:\n"
    "«Хочу другого админа»\n\n"
    "✦ Дом всегда рад тебе. Добро пожаловать ♡\n\n"
    "↓ Выбери, что тебе нужно:"
)

DB_FILE = "users.json"
STATS_FILE = "stats.json"
FLUD_FILE = "flud.json"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# =====================================================================
# 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =====================================================================
def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_db(): return load_json(DB_FILE, {})
def save_db(d): save_json(DB_FILE, d)
def load_stats(): return load_json(STATS_FILE, {"incoming": 0, "outgoing": 0, "blocked_us": 0})
def save_stats(d): save_json(STATS_FILE, d)
def load_flud(): return load_json(FLUD_FILE, {})
def save_flud(d): save_json(FLUD_FILE, d)

async def save_db_to_github():
    if not GITHUB_TOKEN:
        return
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DB_FILE}"
        headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                sha = (await resp.json()).get("sha") if resp.status == 200 else None
            payload = {"message": f"Auto-backup: {datetime.now().strftime('%d.%m %H:%M')}", "content": encoded_content}
            if sha: payload["sha"] = sha
            async with session.put(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 201): print("✅ База в GitHub!")
    except Exception as e:
        print(f"❌ GitHub: {e}")

def inc_incoming():
    s = load_stats(); s["incoming"] = s.get("incoming", 0) + 1; save_stats(s)

def inc_outgoing():
    s = load_stats(); s["outgoing"] = s.get("outgoing", 0) + 1; save_stats(s)

def find_user_by_topic(topic_id):
    db = load_db()
    for uid, info in db.items():
        if isinstance(info, dict) and info.get("topic_id") == topic_id:
            return int(uid)
    return None

def get_next_number(db):
    nums = [i.get("number", 0) for i in db.values() if isinstance(i, dict) and i.get("number")]
    return max(nums, default=0) + 1

def find_user_by_number(number):
    db = load_db()
    for uid, info in db.items():
        if isinstance(info, dict) and info.get("number") == number:
            return int(uid), info
    return None, None

async def log_action(text):
    try: await bot.send_message(LOG_CHANNEL_ID, text)
    except: pass

def check_flood(user_id):
    flud = load_flud()
    now = time.time()
    uid = str(user_id)
    if uid not in flud: flud[uid] = []
    flud[uid] = [t for t in flud[uid] if now - t < 60]
    flud[uid].append(now)
    save_flud(flud)
    return len(flud[uid]) >= 10

# =====================================================================
# 2. КЛАВИАТУРЫ
# =====================================================================
def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✧ Анкета", url=LINK_ANKETA)],
        [InlineKeyboardButton(text="✦ Канал", url=LINK_CHANNEL)],
        [InlineKeyboardButton(text="♡ Поддержка", url=LINK_SUPPORT)],
        [InlineKeyboardButton(text="❋ Отзывы", url=LINK_REVIEWS)],
    ])

def kb_topics():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✧ Поддержка", callback_data="topic:Поддержка")],
        [InlineKeyboardButton(text="❋ Общение", callback_data="topic:Общение")],
        [InlineKeyboardButton(text="✦ Поддержка/Общение", callback_data="topic:Поддержка/Общение")],
        [InlineKeyboardButton(text="♡ Ролка", callback_data="topic:Ролка")],
        [InlineKeyboardButton(text="❥ Флирт", callback_data="topic:Флирт")],
    ])

def kb_gender():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✧ Парень", callback_data="gender:Парень")],
        [InlineKeyboardButton(text="❋ Девушка", callback_data="gender:Девушка")],
        [InlineKeyboardButton(text="✦ Без разницы", callback_data="gender:Без разницы")],
    ])

# =====================================================================
# 3. ОБРАБОТЧИКИ КОМАНД
# =====================================================================

@dp.message(F.chat.type == ChatType.PRIVATE, F.text == "/reset")
async def cmd_reset(message: Message):
    uid = message.from_user.id
    db = load_db()
    if str(uid) not in db:
        await message.answer("❋ Вас нет в базе. Напишите /start.")
        return
    old_number = db[str(uid)].get("number", "?")
    del db[str(uid)]
    save_db(db)
    await save_db_to_github()
    await message.answer(
        "✧ Ваша регистрация сброшена.\n\n"
        f"№ Был номер: <b>#{old_number}</b>\n\n"
        "Напишите /start, чтобы зарегистрироваться заново и получить новую тему."
    )

@dp.message(F.chat.type == ChatType.PRIVATE, F.text == "/start")
async def cmd_start(message: Message):
    uid = message.from_user.id
    if uid == ADMIN_ID:
        await message.answer(
            "✧ <b>Команды админа:</b>\n\n"
            "/stats — статистика\n"
            "/blocked — список заблокированных\n"
            "/find НОМЕР — найти по номеру\n"
            "/unban НОМЕР — разблокировать\n"
            "/broadcast — сделать рассылку (текст/фото)\n"
            "/help — эта справка"
        )
        return
    db = load_db()
    if str(uid) in db and db[str(uid)].get("registered"):
        await message.answer("✧ Вы уже зарегистрированы. Напишите сообщение.", reply_markup=kb_main())
        return
    try:
        await bot.send_photo(chat_id=uid, photo=BANNER_TOPIC, caption=WELCOME_TEXT, reply_markup=kb_topics())
    except:
        await message.answer(WELCOME_TEXT, reply_markup=kb_topics())

@dp.message(F.chat.type == ChatType.PRIVATE)
async def user_message(message: Message):
    uid = message.from_user.id
    db = load_db()

    # --- ПРОВЕРКА РЕЖИМА РАССЫЛКИ ---
    if uid == ADMIN_ID:
        if db.get("admin_state", {}).get("action") == "waiting_for_broadcast":
            if "admin_state" in db: del db["admin_state"]
            save_db(db)
            await message.answer("↓ Начинаю рассылку...")
            users = [u for u, v in db.items() if isinstance(v, dict) and v.get("registered") and not v.get("blocked")]
            sent = 0; failed = 0; blocked_by_user = 0
            
            status_msg = await message.answer(f"↓ Отправляю... 0/{len(users)}")
            for i, u in enumerate(users, 1):
                try:
                    await bot.copy_message(chat_id=int(u), from_chat_id=message.chat.id, message_id=message.message_id)
                    sent += 1
                except Exception as e:
                    err = str(e).lower()
                    if "blocked" in err or "forbidden" in err: blocked_by_user += 1
                    else: failed += 1
                if i % 10 == 0:
                    try: await status_msg.edit_text(f"↓ Отправляю... {i}/{len(users)}")
                    except: pass
                    await asyncio.sleep(0.05)
            
            if blocked_by_user > 0:
                s = load_stats(); s["blocked_us"] = s.get("blocked_us", 0) + blocked_by_user; save_stats(s)
            await status_msg.edit_text(
                f"✦ <b>Готово</b>\n\nОтправлено: <b>{sent}</b>\nОшибок: <b>{failed}</b>\nЗаблокировали нас: <b>{blocked_by_user}</b>"
            )
            return
        elif message.text and message.text.startswith("/"):
            await handle_admin_command(message)
            return

    # --- ОБЫЧНЫЕ СООБЩЕНИЯ ---
    if check_flood(uid):
        await message.answer("🚫 Слишком много сообщений. Подожди 3 минуты.")
        return
    if str(uid) not in db or not db[str(uid)].get("registered"):
        await message.answer("✧ Сначала выбери, что тебе нужно:", reply_markup=kb_topics())
        return
    if db[str(uid)].get("blocked"):
        await message.answer("🚫 Вы заблокированы. Обратитесь к администратору.")
        return
    topic_id = db[str(uid)].get("topic_id")
    if not topic_id:
        await message.answer("❋ Тема не найдена. Напиши /start заново.")
        return
    try:
        await bot.copy_message(chat_id=GROUP_ID, from_chat_id=message.chat.id, message_id=message.message_id, message_thread_id=topic_id)
        inc_incoming()
        db = load_db(); db[str(uid)]["last_user_msg"] = time.time(); save_db(db)
    except Exception as e:
        print(f"Ошибка копирования: {e}")

# =====================================================================
# 4. ОСТАЛЬНЫЕ ФУНКЦИИ
# =====================================================================

@dp.callback_query(F.data.startswith("topic:"))
async def cb_topic(cb: CallbackQuery):
    topic_name = cb.data.split(":", 1)[1]
    uid = cb.from_user.id
    db = load_db()
    if str(uid) not in db: db[str(uid)] = {}
    db[str(uid)]["pending_topic"] = topic_name
    save_db(db)
    try:
        await bot.send_photo(chat_id=uid, photo=BANNER_GENDER, caption=f"✧ Ты выбрал: <b>{topic_name}</b>\n\n♡ Какого админа ты хочешь?", reply_markup=kb_gender())
    except:
        await cb.message.edit_text(f"✧ Ты выбрал: <b>{topic_name}</b>\n\n♡ Какого админа ты хочешь?", reply_markup=kb_gender())
    await cb.answer()

@dp.callback_query(F.data.startswith("gender:"))
async def cb_gender(cb: CallbackQuery):
    gender = cb.data.split(":", 1)[1]
    uid = cb.from_user.id
    db = load_db()
    topic_name = db.get(str(uid), {}).get("pending_topic", "Общение")
    username = cb.from_user.username or cb.from_user.first_name or "user"
    await create_topic(uid, topic_name, gender, username)
    db = load_db()
    if "pending_topic" in db.get(str(uid), {}):
        del db[str(uid)]["pending_topic"]
        save_db(db)
    final_text = f"✧ Готово!\n\n✦ Тема: <b>{topic_name}</b>\n♡ Хочешь админа: <b>{gender}</b>\n\nТеперь можешь писать сообщение — оно уйдёт администратору."
    try:
        if cb.message.caption: await cb.message.edit_caption(caption=final_text, reply_markup=kb_main())
        else: await cb.message.edit_text(final_text, reply_markup=kb_main())
    except:
        await bot.send_message(uid, final_text, reply_markup=kb_main())
    await cb.answer()

async def create_topic(user_id, topic_name, gender, username):
    db = load_db()
    if str(user_id) in db and db[str(user_id)].get("topic_id"): return db[str(user_id)]["topic_id"]
    number = get_next_number(db)
    full_name = f"✧ Аноним #{number} | {topic_name} | Хочет: {gender}"
    topic = await bot.create_forum_topic(chat_id=GROUP_ID, name=full_name)
    topic_id = topic.message_thread_id
    if str(user_id) not in db: db[str(user_id)] = {}
    db[str(user_id)].update({
        "number": number, "topic_id": topic_id, "username": username,
        "topic_name": topic_name, "gender": gender, "blocked": False,
        "registered": True, "created_at": time.time(), "last_user_msg": 0, "last_auto_reply": 0,
    })
    save_db(db)
    await save_db_to_github()
    await bot.send_message(chat_id=GROUP_ID, message_thread_id=topic_id, text=f"✧ <b>Новое обращение</b>\n\n№ Номер: <b>#{number}</b>\n✦ Тема: <b>{topic_name}</b>\n♡ Хочет админа: <b>{gender}</b>")
    await log_action(f"✧ Новая тема #{number} | Тема: {topic_name} | Хочет: {gender}")
    await notify_admin_new_topic(number, topic_name, gender)
    return topic_id

async def notify_admin_new_topic(number, topic_name, gender):
    try:
        await bot.send_message(ADMIN_ID, f"✦ <b>Новая тема</b>\n\n№ <b>#{number}</b>\nТема: <b>{topic_name}</b>\nХочет админа: <b>{gender}</b>")
    except: pass

async def handle_admin_command(message: Message):
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    db = load_db()

    if cmd == "/help":
        await message.answer("✧ <b>Команды админа:</b>\n\n/stats — статистика\n/blocked — список заблокированных\n/find НОМЕР — найти по номеру\n/unban НОМЕР — разблокировать\n/broadcast — сделать рассылку (текст/фото)\n/help — эта справка")
        return
    if cmd == "/stats":
        total = len([u for u in db.values() if isinstance(u, dict) and u.get("registered")])
        blocked = sum(1 for v in db.values() if isinstance(v, dict) and v.get("blocked"))
        s = load_stats()
        await message.answer(f"✧ <b>Статистика</b>\n\n♡ Всего: <b>{total}</b>\n✦ Чистых: <b>{total - blocked}</b>\n🚫 Заблокированы нами: <b>{blocked}</b>\n🔒 Заблокировали нас: <b>{s.get('blocked_us', 0)}</b>\n\n↓ Входящих: <b>{s.get('incoming', 0)}</b>\n↑ Исходящих: <b>{s.get('outgoing', 0)}</b>")
        return
    if cmd == "/blocked":
        bl = [(u, v) for u, v in db.items() if isinstance(v, dict) and v.get("blocked")]
        if not bl:
            await message.answer("✦ Заблокированных нет.")
            return
        out = "🚫 <b>Заблокированные:</b>\n\n"
        for u, i in bl: out += f"• #{i.get('number', '?')} — ID <code>{u}</code>\n"
        out += "\nРазблокировать: <code>/unban НОМЕР</code>"
        await message.answer(out)
        return
    if cmd == "/find":
        if len(parts) < 2: await message.answer("Используй: /find НОМЕР"); return
        try: num = int(parts[1].strip().replace("#", ""))
        except: await message.answer("❋ Номер должен быть числом."); return
        uid, info = find_user_by_number(num)
        if not uid: await message.answer(f"❋ Пользователь #{num} не найден."); return
        await message.answer(f"✧ <b>Найден</b>\n\n№ Номер: <b>#{num}</b>\nID: <code>{uid}</code>\nЮзернейм: @{info.get('username', 'нет')}\n✦ Тема: <b>{info.get('topic_name', '—')}</b>\n♡ Хочет: <b>{info.get('gender', '—')}</b>\n🚫 Блок: <b>{'Да' if info.get('blocked') else 'Нет'}</b>")
        return
    if cmd == "/unban":
        if len(parts) < 2: await message.answer("Используй: /unban НОМЕР"); return
        try: num = int(parts[1].strip().replace("#", ""))
        except: await message.answer("❋ Номер должен быть числом."); return
        uid, info = find_user_by_number(num)
        if not uid: await message.answer(f"❋ Пользователь #{num} не найден."); return
        db[str(uid)]["blocked"] = False
        save_db(db); await save_db_to_github()
        await message.answer(f"✦ Пользователь #{num} разблокирован.")
        return
    if cmd == "/broadcast":
        db["admin_state"] = {"action": "waiting_for_broadcast"}
        save_db(db)
        await message.answer("✦ <b>Режим рассылки включен</b>\n\nОтправь мне сообщение (текст, фото, видео или кружок), которое нужно разослать всем пользователям.\n\nДля отмены напиши /cancel")
        return
    if cmd == "/cancel":
        if "admin_state" in db:
            del db["admin_state"]; save_db(db)
            await message.answer("✧ Рассылка отменена.")
        else: await message.answer("Нечего отменять.")
        return

@dp.message(F.chat.id == GROUP_ID)
async def admin_group(message: Message):
    if not message.message_thread_id: return
    uid = find_user_by_topic(message.message_thread_id)
    if not uid: return
    text = (message.text or "").strip()

    if text == "/ban":
        db = load_db()
        if str(uid) in db:
            db[str(uid)]["blocked"] = True
            save_db(db); await save_db_to_github()
            await message.reply(f"🚫 #{db[str(uid)].get('number','?')} заблокирован.")
            await log_action(f"🚫 Заблокирован #{db[str(uid)].get('number','?')}")
        return
    if text == "/unban":
        db = load_db()
        if str(uid) in db:
            db[str(uid)]["blocked"] = False
            save_db(db); await save_db_to_github()
            await message.reply(f"✦ #{db[str(uid)].get('number','?')} разблокирован.")
        return
    if text.startswith("/"): return

    try:
        await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
        inc_outgoing()
    except Exception as e:
        err = str(e)
        if "blocked" in err.lower() or "forbidden" in err.lower():
            await message.reply("🔒 Пользователь заблокировал бота.")
            try: await bot.edit_forum_topic(chat_id=GROUP_ID, message_thread_id=message.message_thread_id, name=f"🔒 Заблокировал бота")
            except: pass
        print(f"Ошибка: {e}")

# =====================================================================
# 5. ФОНОВЫЕ ПРОЦЕССЫ И ЗАПУСК
# =====================================================================

async def auto_reply_loop():
    while True:
        await asyncio.sleep(60)
        try:
            now = time.time()
            db = load_db()
            for uid, info in list(db.items()):
                if not isinstance(info, dict) or not info.get("registered") or info.get("blocked"): continue
                topic_id = info.get("topic_id"); last_user = info.get("last_user_msg", 0); last_auto = info.get("last_auto_reply", 0)
                if not topic_id or not last_user or last_auto >= last_user: continue
                hour = (datetime.now().hour + 5) % 24
                is_night = hour >= 2 and hour < 9
                wait = 600 if is_night else 7200
                if now - last_user >= wait:
                    text = "🌙 Админы спят. Сладких снов! Утром обязательно ответим ♡" if is_night else "✧ Админ обязательно ответит, как только увидит. Подожди немного ♡"
                    try:
                        await bot.send_message(int(uid), text)
                        db[str(uid)]["last_auto_reply"] = now
                        save_db(db)
                    except: pass
        except Exception as e: print(f"Автоответ ошибка: {e}")

async def backup_loop():
    while True:
        await asyncio.sleep(1800)
        await save_db_to_github()

async def main():
    asyncio.create_task(auto_reply_loop())
    asyncio.create_task(backup_loop())
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
