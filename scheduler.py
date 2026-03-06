import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db import get_pending_reminders, mark_reminder_sent, claim_pending_broadcasts
from broadcast_sender import send_broadcast

logger = logging.getLogger("excursion_bot")


async def send_reminders(bot):
    now = datetime.now()
    from_dt = (now + timedelta(hours=23)).strftime("%Y-%m-%d %H:%M")
    to_dt = (now + timedelta(hours=25)).strftime("%Y-%m-%d %H:%M")

    rows = get_pending_reminders(from_dt, to_dt)

    for r in rows:
        text = (
            "⏰ Напоминание о записи\n\n"
            "Завтра у вас экскурсия в теплицы «Верёвкин Хутор» 🌷\n\n"
            f"📅 Дата: {r['date']}\n"
            f"🕘 Время: {r['time']}\n"
            f"👥 Количество человек: {r['persons']}\n\n"
            "📍 Адрес:\n"
            "Симферопольский р-н, с. Молодёжное,\n"
            "Московское ш., 11-й км, КрымТеплица\n\n"
            "🗺 Яндекс Карты:\n"
            "https://yandex.ru/maps/-/CPE3zSma\n\n"
            "⚠️ Просим приходить вовремя.\n"
            "При опоздании более 15 минут вход может быть ограничен."
        )

        try:
            await bot.send_message(chat_id=r["telegram_user_id"], text=text)
            mark_reminder_sent(r["id"])
            logger.info("Reminder sent to user=%s booking=%s", r["telegram_user_id"], r["id"])
        except Exception as e:
            logger.error("Failed to send reminder to user=%s: %s", r["telegram_user_id"], e)


async def process_scheduled_broadcasts():
    rows = claim_pending_broadcasts()
    for b in rows:
        logger.info("Starting scheduled broadcast #%s", b["id"])
        await send_broadcast(b["id"])


def setup_scheduler(application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_reminders,
        "interval",
        minutes=30,
        args=[application.bot],
        id="send_reminders",
    )
    scheduler.add_job(
        process_scheduled_broadcasts,
        "interval",
        minutes=1,
        id="process_broadcasts",
    )
    scheduler.start()
    logger.info("Scheduler started (reminders every 30 min, broadcasts every 1 min)")
