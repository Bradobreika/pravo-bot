import asyncio
import json
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

from groq import AsyncGroq

# ──────────────────────────────────────────────
# Настройки (из переменных окружения или .env)
BOT_TOKEN    = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN or not GROQ_API_KEY:
    raise RuntimeError("❌ Отсутствуют обязательные переменные: BOT_TOKEN и/или GROQ_API_KEY")

# Параметры бота
DATA_FILE       = Path("bot_data.json")          # временное хранение (теряется при рестарте)
MAX_HISTORY     = 10                             # максимум пар сообщений в памяти (user + assistant)
MAX_ANSWER_LEN  = 4000
MODEL           = "llama-3.1-8b-instant"         # можно сменить на "llama-3.1-70b-versatile" при желании

SYSTEM_PROMPT = """Ты — справочник по Кодексу Республики Беларусь о браке и семье.
Отвечай только фактами из закона, называй конкретные статьи.
Стиль: сдержанный, точный, нейтральный.
Если вопрос неконкретный — вежливо попроси уточнить.
Запрещено: "гарантирую", "точно", "вы должны", "судья", любые рекомендации действий.
Всегда завершай мысль полностью."""

# ──────────────────────────────────────────────
# Логирование (в консоль + файл logs/bot.log)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("pravo-bot")

# ──────────────────────────────────────────────
bot  = Bot(token=BOT_TOKEN)
dp   = Dispatcher()
groq = AsyncGroq(api_key=GROQ_API_KEY)

# Временное хранение в памяти (при рестарте потеряется)
data = {"seen_users": set(), "histories": {}}

# Попытка загрузить при старте (если файл чудом сохранился)
if DATA_FILE.exists():
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        data["seen_users"] = set(raw.get("seen_users", []))
        data["histories"]  = raw.get("histories", {})
        logger.info("Удалось загрузить bot_data.json при старте")
    except Exception as e:
        logger.warning(f"Не удалось загрузить bot_data.json → начинаем с чистого состояния ({e})")

# ──────────────────────────────────────────────
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Брак и условия заключения")],
        [KeyboardButton(text="Развод и расторжение брака")],
        [KeyboardButton(text="Алименты на детей")],
        [KeyboardButton(text="Раздел имущества")],
        [KeyboardButton(text="Опека и попечительство")],
        [KeyboardButton(text="Лишение родительских прав")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите тему или напишите вопрос..."
)

# ──────────────────────────────────────────────
@dp.message(F.command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    logger.info(f"[{user_id}] /start")
    await message.answer(
        "👋 Справочник по Кодексу о браке и семье Республики Беларусь.\n\n"
        "ℹ️ Только текст закона. Никаких консультаций и рекомендаций.\n"
        "Выберите тему или задайте вопрос.",
        reply_markup=main_kb
    )


@dp.message(F.command("clear", "reset"))
async def cmd_clear(message: Message):
    user_id = message.from_user.id
    str_uid = str(user_id)
    if str_uid in data["histories"]:
        del data["histories"][str_uid]
    if user_id in data["seen_users"]:
        data["seen_users"].remove(user_id)
    await message.answer("История диалога очищена. Можете начать заново.")
    logger.info(f"[{user_id}] История очищена командой")


@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if len(text) < 4:
        await message.answer("Уточните, пожалуйста, вопрос.")
        logger.warning(f"[{user_id}] Слишком короткое сообщение")
        return
    forbidden = {"забудь", "адвокат", "гарантирую", "судья", "юрист", "консультация"}
    if any(w in text.lower() for w in forbidden):
        await message.answer("Я предоставляю только справочную информацию из закона.")
        logger.warning(f"[{user_id}] Обнаружены запрещённые слова")
        return

    logger.info(f"[{user_id}] → {text}")

    # История текущей сессии
    history = data["histories"].get(str(user_id), [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": text})

    try:
        resp = await groq.chat.completions.create(
            messages=messages,
            model=MODEL,
            max_tokens=650,
            temperature=0.15,
        )

        answer = (resp.choices[0].message.content or "").strip()
        if not answer:
            raise ValueError("Пустой ответ от модели")

        # Обновляем историю
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": answer})

        # Ограничиваем длину истории
        if len(history) > MAX_HISTORY * 2:
            history = history[-MAX_HISTORY * 2:]

        data["histories"][str(user_id)] = history

        # Пытаемся сохранить (на Render free потеряется при сне, но внутри сессии полезно)
        try:
            DATA_FILE.write_text(json.dumps({
                "seen_users": list(data["seen_users"]),
                "histories": data["histories"]
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Не удалось сохранить bot_data.json: {e}")

        disclaimer = "\n\nℹ️ Справочная информация. Не является юридической консультацией."
        full = answer + disclaimer

        if user_id not in data["seen_users"]:
            data["seen_users"].add(user_id)

        if len(full) > MAX_ANSWER_LEN:
            full = full[:MAX_ANSWER_LEN - 3] + "…"

        await message.answer(full)
        logger.info(f"[{user_id}] Ответ отправлен ({len(answer)} символов)")

    except Exception as e:
        logger.error(f"[{user_id}] Ошибка Groq: {type(e).name} {e}")
        await message.answer("⚠️ Временная проблема с сервером. Попробуйте позже.")


# ──────────────────────────────────────────────
async def polling_main():
    logger.info("🚀 Бот запущен в polling-режиме")

    # Удаляем webhook на всякий случай
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook удалён (если был)")
    except Exception as e:
        logger.debug(f"Webhook уже не был установлен: {e}")

    while True:
        try:
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                handle_signals=False,
            )
        except Exception as e:
            logger.error(f"Polling упал: {type(e).name} {e}. Перезапуск через 5 секунд...")
            await asyncio.sleep(5)


# ──────────────────────────────────────────────
if name == "main":
    from dotenv import load_dotenv
    load_dotenv()  # поддержка .env-файла (опционально)

    # Создаём папку для логов
    Path("logs").mkdir(exist_ok=True)

    asyncio.run(polling_main())
