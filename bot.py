# bot.py
import os
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import aiohttp
import aiosqlite
from dotenv import load_dotenv

# --- Настройки ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 5000))
WEBHOOK_URL = f"https://srv-d3f2uss9c44c73eca990.onrender.com/{TOKEN}"
API_URL = "https://api.wynncraft.com/v3/market/item/{}"

if not TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

# --- Логирование ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# --- Работа с БД ---
DB_FILE = "tracked.db"

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tracked (
                user_id INTEGER,
                item TEXT,
                threshold INTEGER,
                PRIMARY KEY(user_id, item)
            )
        """)
        await db.commit()

async def add_tracked(user_id: int, item: str, threshold: int):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR REPLACE INTO tracked (user_id, item, threshold) VALUES (?, ?, ?)",
            (user_id, item, threshold)
        )
        await db.commit()

async def remove_tracked(user_id: int, item: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM tracked WHERE user_id=? AND item=?", (user_id, item))
        await db.commit()

async def get_tracked(user_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT item, threshold FROM tracked WHERE user_id=?", (user_id,))
        rows = await cursor.fetchall()
        return rows

async def get_all_tracked():
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT user_id, item, threshold FROM tracked")
        rows = await cursor.fetchall()
        return rows

# --- Работа с API Wynncraft ---
async def fetch_prices(item: str):
    url = API_URL.format(item.replace(" ", "%20"))
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            return data

# --- Хэндлеры команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Используй команды:\n"
        "/track <item> <threshold> — отслеживать предмет\n"
        "/untrack <item> — убрать отслеживание\n"
        "/list — список отслеживаемых\n"
        "/price <item> — текущие цены (min/avg/max)"
    )

async def track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text("Формат: /track <item> <threshold>")
    item = " ".join(context.args[:-1])
    try:
        threshold = int(context.args[-1])
    except ValueError:
        return await update.message.reply_text("Порог должен быть числом.")
    await add_tracked(update.effective_user.id, item, threshold)
    await update.message.reply_text(f"Теперь слежу за {item}, лимит {threshold}.")

async def untrack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Формат: /untrack <item>")
    item = " ".join(context.args)
    await remove_tracked(update.effective_user.id, item)
    await update.message.reply_text(f"Больше не слежу за {item}.")

async def list_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await get_tracked(update.effective_user.id)
    if not rows:
        await update.message.reply_text("Ты пока ничего не отслеживаешь.")
    else:
        text = "\n".join([f"{r[0]} (лимит {r[1]})" for r in rows])
        await update.message.reply_text("📌 Отслеживаемые предметы:\n" + text)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Формат: /price <item>")
    item = " ".join(context.args)
    try:
        data = await fetch_prices(item)
        if "listings" in data and data["listings"]:
            prices = [l["price"] for l in data["listings"]]
            min_price = min(prices)
            avg_price = sum(prices) // len(prices)
            max_price = max(prices)
            await update.message.reply_text(
                f"💰 {item}:\nМинимум: {min_price}\nСредняя: {avg_price}\nМаксимум: {max_price}"
            )
        else:
            await update.message.reply_text(f"❌ Нет данных о {item}")
    except Exception as e:
        logging.error("Ошибка /price: %s", e)
        await update.message.reply_text("Ошибка при получении цены.")

# --- Периодическая проверка ---
async def periodic_price_check(app):
    while True:
        rows = await get_all_tracked()
        for user_id, item, threshold in rows:
            try:
                data = await fetch_prices(item)
                if "listings" in data and data["listings"]:
                    min_price = min(l["price"] for l in data["listings"])
                    if min_price < threshold:
                        await app.bot.send_message(
                            chat_id=user_id,
                            text=f"⚡ {item} найден за {min_price} (ниже {threshold})!"
                        )
            except Exception as e:
                logging.error("Ошибка check_prices: %s", e)
        await asyncio.sleep(120)  # каждые 2 минуты

# --- Главная функция ---
async def main():
    await init_db()
    app = Application.builder().token(TOKEN).build()

    # Регистрация команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("track", track))
    app.add_handler(CommandHandler("untrack", untrack))
    app.add_handler(CommandHandler("list", list_items))
    app.add_handler(CommandHandler("price", price))

    # Запуск периодической проверки
    asyncio.create_task(periodic_price_check(app))

    # Запуск webhook
    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    asyncio.run(main())
