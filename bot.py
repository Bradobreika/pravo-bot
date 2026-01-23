import asyncio
import json
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

from groq import AsyncGroq

# ──────────────────────────────────────────────
# Настройки (из переменных окружения)
BOT_TOKEN    = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not BOT_TOKEN or not GROQ_API_KEY:
    raise RuntimeError("❌ Отсутствуют обязательные переменные: BOT_TOKEN и/или GROQ_API_KEY")

# Параметры бота
DATA_FILE       = Path("bot_data.json")          # временно, теряется при рестарте на free
MAX_HISTORY     = 10                             # пар сообщений в памяти
MAX_ANSWER_LEN  = 4000
MODEL           = "llama-3.1-8b-instant"

SYSTEM_PROMPT = """Ты — справочник по законодательству Республики Беларусь.

ВАЖНО:
— Если вопрос касается **брака, развода, алиментов, отцовства, усыновления, опеки** — ссылайся на **Кодекс Республики Беларусь о браке и семье**.
— Если вопрос касается **наследства, завещаний, очередности наследников** — ссылайся на **Гражданский кодекс Республики Беларусь (раздел IV «Наследственное право»)**.
— НИКОГДА не называй статьи Кодекса о браке и семье в контексте наследства.
— НЕ выдумывай номера статей. Если не уверен — скажи: «Обратитесь к юристу для уточнения нормы».

Стиль:
— Сдержанный, точный, нейтральный.
— Начни с краткого признания сложности ситуации (1 предложение).
— Если вопрос неконкретный («А что насчёт алиментов?», «Что делать дальше?») — вежливо попроси уточнить: «Уточните, пожалуйста, о какой ситуации идёт речь?»
— Запрещено использовать: «гарантирую», «точно», «вы должны», «судья», «выиграете», «рекомендую».
— Всегда завершай мысль полностью."""
# ──────────────────────────────────────────────
# Логирование
Path("logs").mkdir(parents=True, exist_ok=True)

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

# Временное хранение в памяти
data = {"seen_users": set(), "histories": {}}

# Попытка загрузки при старте
if DATA_FILE.exists():
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        data["seen_users"] = set(raw.get("seen_users", []))
        data["histories"]  = raw.get("histories", {})
        logger.info("Загружены данные из bot_data.json")
    except Exception as e:
        logger.warning(f"Не удалось загрузить bot_data.json: {e}")

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
        "ℹ️ Только текст закона. Никаких консультаций.\n"
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
    await message.answer("История диалога очищена.")
    logger.info(f"[{user_id}] История очищена")


@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if len(text) < 4:
        await message.answer("Уточните, пожалуйста, вопрос.")
        return

    forbidden = {"забудь", "адвокат", "гарантирую", "судья", "юрист", "консультация"}
    if any(w in text.lower() for w in forbidden):
        await message.answer("Я предоставляю только справочную информацию из закона.")
        return

    logger.info(f"[{user_id}] → {text}")
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

        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": answer})

        if len(history) > MAX_HISTORY * 2:
            history = history[-MAX_HISTORY * 2:]

        data["histories"][str(user_id)] = history

        # Пытаемся сохранить (на free Render потеряется при сне)
        try:
            DATA_FILE.write_text(json.dumps({
                "seen_users": list(data["seen_users"]),
                "histories": data["histories"]
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Сохранение bot_data.json не удалось: {e}")

        disclaimer = "\n\nℹ️ Справочная информация. Не является юридической консультацией."
        full = answer + disclaimer

        if user_id not in data["seen_users"]:
            data["seen_users"].add(user_id)

        if len(full) > MAX_ANSWER_LEN:
            full = full[:MAX_ANSWER_LEN - 3] + "…"

        await message.answer(full)
        logger.info(f"[{user_id}] Ответ отправлен")

    except Exception as e:
        logger.error(f"[{user_id}] Groq error: {type(e).__name__} {e}")
        await message.answer("⚠️ Временная проблема с сервером. Попробуйте позже.")


# ──────────────────────────────────────────────
async def polling_main():
    logger.info("🚀 Бот запущен в polling-режиме")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook удалён")
    except Exception as e:
        logger.debug(f"Webhook уже не был: {e}")

    while True:
        try:
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                handle_signals=False,
            )
        except Exception as e:
            logger.error(f"Polling упал: {type(e).__name__} {e}. Перезапуск через 5 сек...")
            await asyncio.sleep(5)


# ──────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(polling_main())
