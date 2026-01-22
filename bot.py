import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from groq import AsyncGroq
from aiohttp import web

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN or not GROQ_API_KEY:
    raise RuntimeError("❌ Токены не заданы в Render Environment Variables.")

# === HEALTH CHECK ДЛЯ RENDER ===
async def health_check(request):
    return web.Response(text="OK")

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    port = int(os.getenv("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Health server слушает порт {port}")

# === ИНИЦИАЛИЗАЦИЯ БОТА ===
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = AsyncGroq(api_key=GROQ_API_KEY)

# === ПРОМПТ ===
SYSTEM_PROMPT = (
    "Ты — справочник по семейному праву Республики Беларусь. "
    "Стиль: сдержанно, точно, по делу. "
    "1. Начни с краткого признания сложности (1 предложение). "
    "2. Назови конкретные статьи Кодекса о браке и семье РБ. "
    "3. Объясни простым языком, без метафор. "
    "4. Укажи шаги: куда обращаться, какие документы. "
    "ЗАПРЕЩЕНО: 'гарантирую', 'точно', 'вы должны', 'судья', 'как компас'. "
    "Всегда завершай мысль полностью."
)

seen_users = set()

# === ОБРАБОТЧИК СООБЩЕНИЙ ===
@dp.message(F.text)
async def handle(message: Message):
    user_id = message.from_user.id
    full_name = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
    text = message.text.strip()
    
    # 🔹 ЛОГИРОВАНИЕ ВХОДЯЩЕГО СООБЩЕНИЯ
    print(f"[{user_id}] {full_name}: {text}")
    
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
        
        # 🔹 ЛОГИРОВАНИЕ ОТВЕТА (опционально, можно закомментировать)
        print(f"→ Ответ отправлен пользователю {user_id}")
        
        await message.answer(full_answer + disclaimer)
        
    except Exception as e:
        print(f"❌ Ошибка Groq для [{user_id}]: {e}")
        await message.answer("⚠️ Сервер временно недоступен.")

@dp.message(F.command("start"))
async def start(message: Message):
    user_id = message.from_user.id
    full_name = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
    print(f"[{user_id}] {full_name}: /start")
    await message.answer("👋 Справочник по семейному праву РБ.\n\nℹ️ Только закон. Без консультаций.")

# === ЗАПУСК ===
async def main():
    asyncio.create_task(start_health_server())
    print("✅ Бот запущен (polling)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
