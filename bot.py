from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN
from db import (
    init_db,
    user_has_booking,
    get_available_days,
    get_available_times,
    get_user_booking,
    create_booking,
    cancel_user_booking,
)
from helpers import format_day, decline_places, validate_phone, validate_name
from logger import setup_logging
from admin import admin_command, admin_callback
from scheduler import setup_scheduler

logger = setup_logging()

# ===== Главное меню =====
MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton("✅ Записаться на экскурсию")],
        [KeyboardButton("📍 Как проехать"), KeyboardButton("⚠️ Важная информация")],
        [KeyboardButton("🌷 Получить каталог")],
        [KeyboardButton("📄 Моя запись"), KeyboardButton("❌ Отменить запись")],
    ],
    resize_keyboard=True,
)

# ===== /start =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🌷 Добро пожаловать в Верёвкин Хутор!\n\n"
        "Запишитесь на бесплатную экскурсию 👇",
        reply_markup=MAIN_MENU,
    )

# ===== старт записи =====
async def start_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if user_has_booking(update.effective_user.id):
        await update.message.reply_text(
            "❗ У вас уже есть активная запись.\n"
            "Отмените её, чтобы записаться снова.",
            reply_markup=MAIN_MENU,
        )
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("1", callback_data="persons_1"),
        InlineKeyboardButton("2", callback_data="persons_2"),
        InlineKeyboardButton("3", callback_data="persons_3"),
    ]])
    await update.message.reply_text(
        "👥 Сколько человек придёт на экскурсию?",
        reply_markup=keyboard,
    )

# ===== выбор количества =====
async def persons_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    persons = int(q.data.split("_")[1])
    context.user_data["persons"] = persons

    days = get_available_days(persons)
    if not days:
        await q.edit_message_text("❌ Сейчас нет доступных дат.")
        return

    buttons = []
    for d in days:
        buttons.append([
            InlineKeyboardButton(
                f"{format_day(d['date'])} ({decline_places(d['remaining'])})",
                callback_data=f"day_{d['id']}",
            )
        ])
    await q.edit_message_text(
        "📅 Выберите дату:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

# ===== выбор даты =====
async def day_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    day_id = int(q.data.replace("day_", ""))
    context.user_data["day_id"] = day_id
    persons = context.user_data["persons"]

    times = get_available_times(day_id, persons)
    if not times:
        await q.edit_message_text("❌ На выбранную дату нет доступного времени.")
        return

    buttons = []
    for t in times:
        buttons.append([
            InlineKeyboardButton(
                f"{t['time']} ({decline_places(t['remaining'])})",
                callback_data=f"time_{t['id']}",
            )
        ])
    await q.edit_message_text(
        "🕒 Выберите время:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

# ===== выбор времени =====
async def time_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    context.user_data["time_slot_id"] = int(q.data.replace("time_", ""))
    context.user_data["waiting_name"] = True

    await q.edit_message_text("👤 Введите имя для бронирования:")

# ===== ввод имени =====
async def name_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not validate_name(name):
        await update.message.reply_text(
            "❌ Имя должно содержать от 2 до 50 символов (буквы, пробелы, дефисы).\n"
            "Попробуйте ещё раз:"
        )
        return

    context.user_data["name"] = name
    context.user_data["waiting_name"] = False
    context.user_data["waiting_phone"] = True

    await update.message.reply_text(
        "📞 Введите номер телефона (например, +79001234567 или 89001234567):"
    )

# ===== ввод телефона + бронирование =====
async def phone_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = validate_phone(update.message.text.strip())
    if not phone:
        await update.message.reply_text(
            "❌ Неверный формат телефона.\n"
            "Введите номер в формате +79001234567 или 89001234567:"
        )
        return

    context.user_data["waiting_phone"] = False

    name = context.user_data["name"]
    persons = context.user_data["persons"]
    day_id = context.user_data["day_id"]
    time_slot_id = context.user_data["time_slot_id"]
    user_id = update.effective_user.id

    success, day_date, slot_time = create_booking(
        user_id, name, persons, day_id, time_slot_id, phone,
    )

    if not success:
        context.user_data.clear()
        await update.message.reply_text(
            "❌ Это время только что заняли. Выберите другое.",
            reply_markup=MAIN_MENU,
        )
        return

    logger.info(
        "Booking created: user=%s name=%s persons=%d date=%s time=%s phone=%s",
        user_id, name, persons, day_date, slot_time, phone,
    )

    context.user_data.clear()
    await update.message.reply_text(
        "✅ Запись подтверждена!\n\n"
        f"👤 {name}\n"
        f"📞 {phone}\n"
        f"👥 {persons} человек\n"
        f"📅 Дата: {format_day(day_date)}\n"
        f"🕒 Время: {slot_time}\n\n"
        "Кнопки «Как проехать» и «Важная информация» доступны в меню ⬇️",
        reply_markup=MAIN_MENU,
    )

# ===== единый роутер текстового ввода =====
async def text_input_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_name"):
        await name_entered(update, context)
    elif context.user_data.get("waiting_phone"):
        await phone_entered(update, context)

# ===== моя запись =====
async def my_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    booking = get_user_booking(update.effective_user.id)
    if not booking:
        await update.message.reply_text(
            "📄 У вас нет активной записи.",
            reply_markup=MAIN_MENU,
        )
        return

    phone_line = f"📞 Телефон: {booking['phone']}\n" if booking["phone"] else ""
    await update.message.reply_text(
        "📄 Моя запись\n\n"
        f"👤 Имя: {booking['name']}\n"
        f"{phone_line}"
        f"👥 Количество: {booking['persons']}\n"
        f"📅 Дата: {format_day(booking['date'])}\n"
        f"🕒 Время: {booking['time']}",
        reply_markup=MAIN_MENU,
    )

# ====== отмена записи ======
async def cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    deleted = cancel_user_booking(update.effective_user.id)
    if not deleted:
        await update.message.reply_text(
            "ℹ️ У вас нет активной записи.",
            reply_markup=MAIN_MENU,
        )
        return

    logger.info("Booking cancelled by user=%s", update.effective_user.id)
    await update.message.reply_text(
        "❌ Ваша запись отменена.\nВы можете записаться снова.",
        reply_markup=MAIN_MENU,
    )

# ===== каталог =====
CATALOG_URL = "https://drive.google.com/file/d/1vxViARDD9mcjXnqDJr2L31G6RzReoR3c/view?usp=sharing"

async def send_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Открыть каталог (PDF)", url=CATALOG_URL)]
    ])
    await update.message.reply_text(
        "🌷 Актуальный каталог Верёвкин Хутор\n\n"
        "Нажмите кнопку ниже, чтобы открыть PDF:",
        reply_markup=keyboard,
    )

# ===== важная информация =====
async def important_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚠️ Важная информация\n\n"
        "⏱ Длительность экскурсии — ~40–60 минут\n\n"
        "⏰ Начало строго по времени\n"
        "При опоздании более 15 минут вход может быть ограничен\n\n"
        "📋 Экскурсия бесплатна и проводится по предварительной записи\n\n"
        "📸 Фото и видео разрешены и приветствуются! 🌷",
        reply_markup=MAIN_MENU,
    )

# ===== как проехать =====
ROUTE_URL = "https://yandex.ru/maps/-/CPE3zSma"

async def send_route_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗺 Яндекс Карты", url=ROUTE_URL)]
    ])
    await update.message.reply_text(
        "📍 Как добраться\n\n"
        "Адрес:\n"
        "Симферопольский р-н, с. Молодёжное,\n"
        "Московское ш., 11-й км, КрымТеплица\n\n"
        "🚗 Парковка — перед теплицей\n"
        "👋 Сбор группы — у входа в офис",
        reply_markup=keyboard,
    )

# ====== post_init ======
async def post_init(application):
    setup_scheduler(application)

# ====== main ======
def main():
    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))

    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^✅?\s*Записаться на экскурсию$"), start_booking))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^📄\s*Моя запись$"), my_booking))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^❌\s*Отменить запись$"), cancel_booking))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^🌷\s*Получить каталог$"), send_catalog))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("Важная информация"), important_info))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("Как проехать"), send_route_info))

    app.add_handler(CallbackQueryHandler(persons_chosen, pattern=r"^persons_"))
    app.add_handler(CallbackQueryHandler(day_chosen, pattern=r"^day_"))
    app.add_handler(CallbackQueryHandler(time_chosen, pattern=r"^time_"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^admin_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_router))

    logger.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
