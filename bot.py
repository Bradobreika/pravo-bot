import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from groq import AsyncGroq

# === ЗАГЛУШКА ДЛЯ RENDER ===
if os.getenv("RENDER"):
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class HealthCheck(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

    def run_health_check():
        port = int(os.getenv("PORT", 10000))
        server = HTTPServer(("0.0.0.0", port), HealthCheck)
        server.serve_forever()

    threading.Thread(target=run_health_check, daemon=True).start()
# === КОНЕЦ ЗАГЛУШКИ ===

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN or not GROQ_API_KEY:
    raise RuntimeError("❌ Токены не заданы в Render.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = AsyncGroq(api_key=GROQ_API_KEY)

# === НОВЫЙ SYSTEM PROMPT: ФАКТЫ > ЛИРИКА ===
SYSTEM_PROMPT = (
    "Ты — справочник по семейному праву Республики Беларусь. "
    "Твой стиль: сдержанно, точно, по делу. "
    "1. Начни с краткого признания сложности ситуации (1 предложение). "
    "2. Сразу переходи к сути: назови конкретные статьи Кодекса о браке и семье РБ. "
    "3. Объясни норму простым языком, но без метафор ('компас', 'дорога' — запрещено). "
    "4. Укажи практические шаги (куда обращаться, какие документы). "
    "5. Если вопрос выходит за рамки закона — направь к юристу. "
    "ЗАПРЕЩЕНО: 'гарантирую', 'точно', 'вы должны', 'судья', 'выиграете', 'как компас'. "
    "Всегда завершай мысль полностью."
)

seen_users = set()

@dp.message(F.text)
async def handle(message: Message):
    if len(message.text.strip()) < 5:
        await message.answer("Уточните вопрос.")
        return
    user_id = message.from_user.id
    if any(w in message.text.lower() for w in ["забудь", "адвокат", "гарантирую", "судья"]):
        await message.answer("Я не даю юридических консультаций.")
        return
    try:
        resp = await client.chat.completions.create(
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": message.text}],
            model="llama-3.1-8b-instant",
            max_tokens=600,  # ← УВЕЛИЧЕНО ДО 600
            temperature=0.15  # ← ЕЩЁ БОЛЕЕ СДЕРЖАННЫЙ ТОН
        )
        answer = resp.choices[0].message.content.strip()
        disclaimer = "\n\nℹ️ Справочная информация по законам РБ." if user_id not in seen_users else ""
        if disclaimer:
            seen_users.add(user_id)
        full_answer = (answer[:3950] + "...") if len(answer) > 3950 else answer
        await message.answer(full_answer + disclaimer)
    except Exception as e:
        print(f"Ошибка Groq: {e}")
        await message.answer("⚠️ Сервер временно недоступен.")

@dp.message(F.command("start"))
async def start(message: Message):
    await message.answer(
        "👋 Справочник по семейному праву РБ.\n\n"
        "Примеры:\n• Как подать на алименты?\n• Раздел имущества при разводе?\n\n"
        "ℹ️ Только закон. Без консультаций."
    )

async def main():
    print("✅ Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
