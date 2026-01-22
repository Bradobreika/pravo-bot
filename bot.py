import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from groq import AsyncGroq
from aiohttp import web

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN or not GROQ_API_KEY:
    raise RuntimeError("❌ Токены не заданы.")

WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "your-secret-here")  # можно оставить как есть
BASE_URL = os.getenv("RENDER_EXTERNAL_URL")  # Render автоматически задаёт этот env var

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = AsyncGroq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = (
    "Ты — справочник по семейному праву РБ. "
    "Если вопрос неполный (например: 'А что насчёт алиментов?'), вежливо попроси уточнить: "
    "'Уточните, пожалуйста, о какой ситуации идёт речь?'. "
    "Стиль: сдержанно, точно, по делу. "
    "Назови статьи Кодекса о браке и семье РБ. "
    "ЗАПРЕЩЕНО: 'гарантирую', 'точно', 'вы должны', 'судья'. "
    "Всегда завершай мысль полностью."
)

seen_users = set()

@dp.message(F.text)
async def handle(message: Message):
    user_id = message.from_user.id
    full_name = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
    text = message.text.strip()
    print(f"[{user_id}] {full_name}: {text}", flush=True)
    
    if len(text) < 5:
        await message.answer("Уточните вопрос.")
        return

    if any(w in text.lower() for w in ["забудь", "адвокат", "гарантирую", "судья"]):
        await message.answer("Я не даю юридических консультаций.")
        return

    try:
        resp = await client.chat.completions.create(
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
            model="llama-3.1-8b-instant",
            max_tokens=600,
            temperature=0.15
        )
        answer = resp.choices[0].message.content.strip()
        disclaimer = "\n\nℹ️ Справочная информация по законам РБ." if user_id not in seen_users else ""
        if disclaimer:
            seen_users.add(user_id)
        full_answer = (answer[:3950] + "...") if len(answer) > 3950 else answer
        print(f"→ Ответ отправлен [{user_id}]", flush=True)
        await message.answer(full_answer + disclaimer)
    except Exception as e:
        print(f"❌ Ошибка Groq [{user_id}]: {e}", flush=True)
        await message.answer("⚠️ Сервер временно недоступен.")

@dp.message(F.command("start"))
async def start(message: Message):
    user_id = message.from_user.id
    full_name = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
    print(f"[{user_id}] {full_name}: /start", flush=True)
    await message.answer("👋 Справочник по семейному праву РБ.\n\nℹ️ Только закон. Без консультаций.")

# === WEBHOOK HANDLER ===
async def telegram_webhook(request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return web.Response(status=403)
    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return web.Response()

# === ЗАПУСК ===
async def main():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, telegram_webhook)
    
    # Устанавливаем webhook при старте
    webhook_url = f"{BASE_URL}{WEBHOOK_PATH}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True
    )
    print(f"✅ Webhook установлен: {webhook_url}", flush=True)
    
    port = int(os.getenv("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Сервер слушает порт {port}", flush=True)
    
    # Держим приложение живым
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
