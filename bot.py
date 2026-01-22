import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from groq import AsyncGroq

# === ЗАГЛУШКА ДЛЯ RENDER (открывает порт, чтобы не падал деплой) ===
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

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN or not GROQ_API_KEY:
    raise RuntimeError("❌ BOT_TOKEN и GROQ_API_KEY должны быть заданы в Render Environment Variables.")

# === ИНИЦИАЛИЗАЦИЯ ===
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = AsyncGroq(api_key=GROQ_API_KEY)

# === СИСТЕМНЫЙ ПРОМПТ ===
SYSTEM_PROMPT = (
    "Ты помогаешь людям разбираться в семейном праве Республики Беларусь. "
    "Говори тёпло, просто, без юридического жаргона. "
    "Используй лёгкие метафоры ('закон как компас', 'процедура как дорога'). "
    "Начинай с признания чувств ('Понимаю, это тревожно...'). "
    "Объясняй норму через смысл, а не цитату. "
    "НЕЛЬЗЯ: 'гарантирую', 'точно', 'вы должны', 'судья', 'выиграете'. "
    "Если ситуация сложна — мягко направляй к лицензированному юристу."
)

# === ФИЛЬТР ОПАСНЫХ ЗАПРОСОВ ===
DANGEROUS_PHRASES = ["забудь", "притворись", "адвокат", "юрист", "гарантирую", "судья", "100%", "выиграю"]

def is_suspicious(text: str) -> bool:
    t = text.lower()
    return any(phrase in t for phrase in DANGEROUS_PHRASES)

# === ОТСЛЕЖИВАНИЕ ПЕРВОГО ОБРАЩЕНИЯ ===
seen_users = set()

# === ОБРАБОТЧИКИ ===
@dp.message(F.text)
async def handle_message(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    if len(text) < 5:
        await message.answer("Пожалуйста, уточните вопрос.")
        return

    if is_suspicious(text):
        await message.answer(
            "Я не могу давать юридические консультации или прогнозировать решения суда. "
            "Обратитесь к лицензированному юристу."
        )
        return

    try:
        response = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0.25,
            max_tokens=250,
            timeout=12
        )
        answer = response.choices[0].message.content.strip()
        
        # Дисклеймер только при первом обращении
        disclaimer = "\n\nℹ️ Это справочная информация по законам РБ. Не является юридической консультацией." if user_id not in seen_users else ""
        if disclaimer:
            seen_users.add(user_id)
            
        full_answer = (answer[:3800] + "...") if len(answer) > 3800 else answer
        await message.answer(full_answer + disclaimer)
        
    except Exception as e:
        print(f"Ошибка Groq: {e}")
        await message.answer("⚠️ Сервер временно недоступен. Попробуйте через минуту.")

@dp.message(F.command("start"))
async def start_handler(message: Message):
    await message.answer(
        "👋 Справочник по семейному праву Республики Беларусь.\n\n"
        "Примеры вопросов:\n"
        "• Как оформить развод?\n"
        "• Сколько алименты на двоих детей?\n"
        "• С кем останется ребёнок при разводе?\n\n"
        "ℹ️ Это НЕ юридическая консультация."
    )

# === ЗАПУСК ===
async def main():
    print("✅ Бот запущен на Render (polling mode)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())