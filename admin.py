import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from config import ADMIN_IDS
from db import get_stats, get_bookings_by_date
from helpers import format_day

logger = logging.getLogger("excursion_bot")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Записи на дату", callback_data="admin_dates")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
    ])
    await update.message.reply_text("🔧 Админ-панель", reply_markup=keyboard)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.edit_message_text("⛔ Нет доступа.")
        return

    data = q.data

    if data == "admin_dates":
        await _show_dates(q)
    elif data.startswith("admin_date_"):
        date_str = data.replace("admin_date_", "")
        await _show_bookings_for_date(q, date_str)
    elif data == "admin_stats":
        await _show_stats(q)


async def _show_dates(q):
    stats = get_stats()
    if not stats:
        await q.edit_message_text("Нет предстоящих дат.")
        return

    buttons = []
    for row in stats:
        label = f"{format_day(row['date'])} — {row['booked']}/{row['capacity_day']}"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"admin_date_{row['date']}")
        ])
    await q.edit_message_text(
        "📅 Выберите дату:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _show_bookings_for_date(q, date_str: str):
    bookings = get_bookings_by_date(date_str)
    if not bookings:
        await q.edit_message_text(
            f"На {format_day(date_str)} записей нет.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Назад", callback_data="admin_dates")]
            ]),
        )
        return

    lines = [f"📋 Записи на {format_day(date_str)}\n"]
    for b in bookings:
        phone = b["phone"] or "—"
        lines.append(
            f"  {b['time']} | {b['name']} | {b['persons']} чел. | {phone}"
        )

    lines.append(f"\nВсего: {sum(b['persons'] for b in bookings)} чел.")

    await q.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("« Назад", callback_data="admin_dates")]
        ]),
    )


async def _show_stats(q):
    stats = get_stats()
    if not stats:
        await q.edit_message_text("Нет предстоящих дат.")
        return

    lines = ["📊 Заполненность\n"]
    for row in stats:
        pct = int(row["booked"] / row["capacity_day"] * 100) if row["capacity_day"] else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(
            f"{format_day(row['date'])}: {row['booked']}/{row['capacity_day']} [{bar}] {pct}%"
        )

    await q.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("« Назад", callback_data="admin_dates")]
        ]),
    )
