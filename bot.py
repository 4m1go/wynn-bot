import os
import requests
import sqlite3
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Переменные окружения ---
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 5000))
WEBHOOK_URL = f"https://srv-d3f2uss9c44c73eca990.onrender.com/{TOKEN}"

# --- База данных ---
conn = sqlite3.connect("tracked.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS tracked (user_id INTEGER, item TEXT, threshold INTEGER)")
conn.commit()

API_URL = "https://api.wynncraft.com/v3/market/item/{}"

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Используй:\n"
        "/track <item> <threshold> — отслеживать предмет\n"
        "/untrack <item> — убрать отслеживание\n"
        "/list — список отслеживаемых\n"
        "/price <item> — текущие цены (min/avg/max)"
    )

async def track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /track <item> <threshold>")
        return
    item = " ".join(context.args[:-1])
    threshold = int(context.args[-1])
    cursor.execute("INSERT INTO tracked VALUES (?, ?, ?)", (update.effective_user.id, item, threshold))
    conn.commit()
    await update.message.reply_text(f"Теперь слежу за {item}, лимит {threshold}.")

async def untrack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    item = " ".join(context.args)
    cursor.execute("DELETE FROM tracked WHERE user_id=? AND item=?", (update.effective_user.id, item))
    conn.commit()
    await update.message.reply_text(f"Больше не слежу за {item}.")

async def list_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT item, threshold FROM tracked WHERE user_id=?", (update.effective_user.id,))
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("Ты пока ничего не отслеживаешь.")
    else:
        text = "\n".join([f"{r[0]} (лимит {r[1]})" for r in rows])
        await update.message.reply_text("📌 Отслеживаемые предметы:\n" + text)

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Формат: /price <item>")
        return
    item = " ".join(context.args)
    try:
        r = requests.get(API_URL.format(item.replace(" ", "%20")))
        data = r.json()
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
        await update.message.reply_text("Ошибка при получении цены.")
        print("Ошибка /price:", e)

# --- Периодическая проверка цен через asyncio ---
async def periodic_price_check(app: Application):
    while True:
        cursor.execute("SELECT user_id, item, threshold FROM tracked")
        rows = cursor.fetchall()
        for user_id, item, threshold in rows:
            try:
                r = requests.get(API_URL.format(item.replace(" ", "%20")))
                data = r.json()
                if "listings" in data and data["listings"]:
                    min_price = min(l["price"] for l in data["listings"])
                    if min_price < threshold:
                        await app.bot.send_message(
                            chat_id=user_id,
                            text=f"⚡ {item} найден за {min_price} (ниже {threshold})!"
                        )
            except Exception as e:
                print("Ошибка check_prices:", e)
        await asyncio.sleep(120)  # каждые 2 минуты

# --- Создание приложения и регистрация команд ---
app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("track", track))
app.add_handler(CommandHandler("untrack", untrack))
app.add_handler(CommandHandler("list", list_items))
app.add_handler(CommandHandler("price", price))

# --- Запуск периодической проверки внутри event loop ---
asyncio.create_task(periodic_price_check(app))

# --- Запуск webhook для Render ---
app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path=TOKEN,
    webhook_url=WEBHOOK_URL
)
