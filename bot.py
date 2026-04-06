import asyncio
import logging
import os
import sqlite3
import uuid
import urllib.parse
from decimal import Decimal, getcontext
from io import BytesIO
from datetime import datetime, timezone
import qrcode
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from flask import Flask
import threading
# Создаём простой веб-сервер для Render
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "Bot is running!", 200
    
@flask_app.route('/health')
def health():
    return "OK", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=10000)
    
# ==============================
# УВЕДОМЛЕНИЯ АДМИНИСТРАТОРУ
# ==============================
ADMIN_ID = int(os.getenv("ADMIN_ID", "973053690"))  # Ваш ID

async def notify_admin_about_new_user(user_id: int, username: str, first_name: str, last_name: str = ""):
    """Отправляет администратору уведомление о новом пользователе"""
    full_name = f"{first_name} {last_name}".strip()
    
    if username:
        profile_link = f"https://t.me/{username}"
        username_text = f"@{username}"
    else:
        profile_link = f"tg://user?id={user_id}"
        username_text = "нет username"
    
    message = (
        f"🆕 НОВЫЙ ПОЛЬЗОВАТЕЛЬ!\n\n"
        f"👤 Имя: {full_name}\n"
        f"🔗 Username: {username_text}\n"
        f"🆔 User ID: {user_id}\n"
        f"📎 Ссылка: {profile_link}\n\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )
    
    try:
        await bot.send_message(ADMIN_ID, message)  # Без parse_mode
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление админу: {e}")

# Функция для сохранения пользователя в БД (опционально)
def save_user_to_db(user_id: int, username: str, first_name: str, last_name: str = ""):
    """Сохраняет информацию о пользователе в базу данных"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    first_seen TIMESTAMP,
                    last_seen TIMESTAMP
                )''')
    
    # Проверяем, есть ли уже такой пользователь
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = c.fetchone()
    
    if exists:
        # Обновляем время последнего визита
        c.execute("UPDATE users SET last_seen = ? WHERE user_id = ?",
                  (datetime.now(timezone.utc), user_id))
    else:
        # Добавляем нового пользователя
        c.execute("INSERT INTO users (user_id, username, first_name, last_name, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, username, first_name, last_name, datetime.now(timezone.utc), datetime.now(timezone.utc)))
    
    conn.commit()
    conn.close()
    
# Запускаем Flask в отдельном потоке
threading.Thread(target=run_flask, daemon=True).start()

# ==============================
# НАСТРОЙКИ
# ==============================

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

TON_ADDRESS = "UQAQvjOaN4l2KBzStCRnSlNhxZT8zNeLavQ-IMYgytRj0bxK"
USDT_ADDRESS = "UQAQvjOaN4l2KBzStCRnSlNhxZT8zNeLavQ-IMYgytRj0bxK"
USDT_JETTON = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2b_s72"

DESCRIPTION = (
    "Сбор средств @operativnoZSU для скорейшей перемоги ЗСУ!\n\n"
    "Каждое пожертвование приближает перемогу и спасает жизни наших бойцов. Спасибо 🤝"
)

getcontext().prec = 30

# ==============================
# ЛОГИ
# ==============================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==============================
# БАЗА ДАННЫХ
# ==============================

DB_PATH = "donations.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS donations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    amount TEXT,
                    currency TEXT,
                    memo TEXT,
                    comment TEXT,
                    tx_hash TEXT,
                    status TEXT,
                    created_at TIMESTAMP,
                    confirmed_at TIMESTAMP
                )''')
    conn.commit()
    conn.close()

def save_donation_request(user_id, username, amount, currency, memo, comment):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO donations 
                 (user_id, username, amount, currency, memo, comment, status, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (user_id, username, str(amount), currency, memo, comment, "pending", datetime.now(timezone.utc)))
    conn.commit()
    conn.close()

# ==============================
# БОТ
# ==============================

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==============================
# СОСТОЯНИЕ
# ==============================

user_data = {}

# ==============================
# КЛАВИАТУРЫ
# ==============================

main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🙏 Пожертвование")],
        [KeyboardButton(text="ℹ️ О проекте")]
    ],
    resize_keyboard=True
)

currency_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="TON"), KeyboardButton(text="USDT")],
        [KeyboardButton(text="🏠 Главное меню")]
    ],
    resize_keyboard=True
)

def get_amount_kb(currency):
    amounts = ["1", "5", "10", "25", "50", "100"]
    buttons = []
    row = []
    for a in amounts:
        row.append(KeyboardButton(text=f"{a} {currency}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([KeyboardButton(text="✏️ Ввести сумму")])
    buttons.append([KeyboardButton(text="🔙 Назад")])
    buttons.append([KeyboardButton(text="🏠 Главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

skip_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Пропустить", callback_data="skip_comment")]
])

# ==============================
# ХЕНДЛЕРЫ (сокращенно для экономии места)
# ==============================

@dp.message(Command("start"))
async def start(message: types.Message):
    user = message.from_user
    user_id = user.id
    username = user.username
    first_name = user.first_name
    last_name = user.last_name or ""
    
    # Сохраняем пользователя в базу данных
    save_user_to_db(user_id, username, first_name, last_name)
    
    # Отправляем уведомление администратору
    await notify_admin_about_new_user(user_id, username, first_name, last_name)
    await message.answer(f"Приветствуем неравнодушных! 🫡\n\n{DESCRIPTION}", reply_markup=main_kb)

@dp.message(F.text == "ℹ️ О проекте")
async def about(message: types.Message):
    await message.answer(DESCRIPTION)

@dp.message(F.text == "🔙 Назад")
async def back_button(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_data:
        user_data.pop(user_id)
    await message.answer("Выберите криптовалюту для пожертвования:", reply_markup=currency_kb)

@dp.message(F.text == "🏠 Главное меню")
async def home_button(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_data:
        user_data.pop(user_id)
    await message.answer("Главное меню:", reply_markup=main_kb)

@dp.message(F.text == "🙏 Пожертвование")
async def donate_start(message: types.Message):
    user_data[message.from_user.id] = {}
    await message.answer("Выберите криптовалюту для пожертвования:", reply_markup=currency_kb)

@dp.message(F.text.in_(["TON", "USDT"]))
async def choose_currency(message: types.Message):
    user_id = message.from_user.id
    user_data[user_id]["currency"] = message.text
    await message.answer(
        f"Выбрана валюта: {message.text}\n\nВыберите сумму или введите свою:",
        reply_markup=get_amount_kb(message.text)
    )

@dp.message(F.text.regexp(r"^(\d+(?:\.\d+)?) (TON|USDT)$"))
async def choose_amount_fixed(message: types.Message):
    user_id = message.from_user.id
    data = user_data.get(user_id, {})
    currency = data.get("currency")
    if not currency:
        await message.answer("Пожалуйста, начните сначала: /start")
        return
    amount_str, currency_in_text = message.text.split()
    if currency_in_text != currency:
        await message.answer("Ошибка: выберите сумму в криптовалюте, которую вы указали.")
        return
    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("Введите положительное число.")
        return
    user_data[user_id]["amount"] = amount
    await ask_comment(message, user_id)

@dp.message(F.text == "✏️ Ввести сумму")
async def manual_amount(message: types.Message):
    user_id = message.from_user.id
    if "currency" not in user_data.get(user_id, {}):
        await message.answer("Сначала выберите валюту.")
        return
    user_data[user_id]["awaiting_amount"] = True
    await message.answer("Введите сумму числом (можно с десятичной точкой):", reply_markup=None)

@dp.message()
async def handle_all(message: types.Message):
    user_id = message.from_user.id
    data = user_data.get(user_id, {})
    if data.get("awaiting_amount"):
        try:
            amount = Decimal(message.text.replace(",", "."))
            if amount <= 0:
                raise ValueError
        except:
            await message.answer("Введите положительное число (например, 10.5).")
            return
        data["amount"] = amount
        data["awaiting_amount"] = False
        await ask_comment(message, user_id)
        return

async def ask_comment(message: types.Message, user_id: int):
    await message.answer(
        "Вы можете добавить комментарий к платежу.\n"
        "Введите текст или нажмите 'Пропустить':",
        reply_markup=skip_kb
    )
    user_data[user_id]["awaiting_comment"] = True

@dp.callback_query(F.data == "skip_comment")
async def skip_comment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_data.get(user_id, {}).get("awaiting_comment"):
        user_data[user_id]["comment"] = ""
        user_data[user_id]["awaiting_comment"] = False
        await callback.message.delete()
        await generate_payment_info(callback.message, user_id)
    await callback.answer()

@dp.message()
async def handle_comment(message: types.Message):
    user_id = message.from_user.id
    if user_data.get(user_id, {}).get("awaiting_comment"):
        comment = message.text
        user_data[user_id]["comment"] = comment
        user_data[user_id]["awaiting_comment"] = False
        await generate_payment_info(message, user_id)

async def generate_payment_info(message: types.Message, user_id: int):
    data = user_data[user_id]
    currency = data["currency"]
    amount = data["amount"]
    comment = data.get("comment", "")
    memo_base = str(uuid.uuid4())[:8]
    memo = f"{comment[:50]}_{memo_base}" if comment else memo_base
    encoded_memo = urllib.parse.quote(memo)

    # --- НОВАЯ ПРОВЕРКА: убеждаемся, что сумма положительная ---
    if amount <= 0:
        await message.answer("❌ Сумма должна быть больше нуля. Пожалуйста, начните заново.", reply_markup=main_kb)
        user_data.pop(user_id, None)
        return

    if currency == "TON":
        address = TON_ADDRESS
        amount_param = int(amount * Decimal(1e9))
        qr_link = f"ton://transfer/{address}?amount={amount_param}&text={encoded_memo}"
        tg_wallet_link = f"https://t.me/wallet?startapp=transfer_{address}_{amount_param}_{encoded_memo}"
        keeper_link = f"https://app.tonkeeper.com/transfer/{address}?amount={amount_param}&text={encoded_memo}"
    else:  # USDT
        address = USDT_ADDRESS
        amount_param = int(amount * Decimal(1e6))
        qr_link = f"ton://transfer/{USDT_JETTON}?amount={amount_param}&jetton={address}&text={encoded_memo}"
        tg_wallet_link = f"https://t.me/wallet?startapp=transfer_{USDT_JETTON}_{amount_param}_{address}_{encoded_memo}"
        keeper_link = f"https://app.tonkeeper.com/transfer/{USDT_JETTON}?amount={amount_param}&jetton={address}&text={encoded_memo}"

    text = (f"💰 *Донат*\n\nСумма: {amount} {currency}\n"
            f"Кошелёк: `{address}`\nКомментарий (memo): `{memo}`\n\n"
            f"⚠️ *ВАЖНО*: при отправке обязательно укажите комментарий (memo)!")

    payment_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Telegram Wallet", url=tg_wallet_link),
         InlineKeyboardButton(text="🌐 TON Keeper", url=keeper_link)],
        [InlineKeyboardButton(text="ℹ️ Как оплатить?", callback_data="how_to_pay"),
         InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
    ])

    # --- Генерация QR-кода ---
    qr = qrcode.make(qr_link)
    bio = BytesIO()
    qr.save(bio, format="PNG")
    bio.seek(0)
    photo = BufferedInputFile(bio.getvalue(), filename="qr.png")

    await message.answer_photo(photo=photo, caption=text, parse_mode="Markdown", reply_markup=payment_kb)

    username = message.from_user.username
    save_donation_request(user_id, username, amount, currency, memo, comment)
    logger.info(f"Donation request: {user_id} {amount} {currency} {memo}")
    user_data.pop(user_id, None)

@dp.callback_query(F.data == "how_to_pay")
async def how_to_pay(callback: types.CallbackQuery):
    await callback.message.answer(
        "🔹 *Как оплатить:*\n\n"
        "📷 *QR-код:* Отсканируйте в Telegram Wallet\n"
        "💎 *Wallet:* Скопируйте адрес кошелька, нажмите кнопку Wallet, выберите 'Вывести' и вставьте адрес\n"
        "🌐 *TON Keeper:* Нажмите кнопку и подтвердите перевод\n\n"
        "После оплаты пожертвование моментально будет зачислено на криптокошелек @operativnoZSU",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.answer("Главное меню:", reply_markup=main_kb)
    await callback.answer()

# ==============================
# ЗАПУСК (для Render.com)
# ==============================

async def main():
    if not TOKEN:
        raise ValueError("Установите BOT_TOKEN")
    if ADMIN_ID == 0:
        logger.warning("ADMIN_ID не задан, уведомления отправляться не будут")

    init_db()
    logger.info("Database initialized")
    
    # Запускаем polling вместо webhook
    logger.info("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
