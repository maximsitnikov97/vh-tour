import logging
import secrets

import httpx
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from config import ADMIN_PASSWORD, BOT_TOKEN
from db import get_stats, get_bookings_by_date, get_booking_by_id, cancel_booking_by_id
from helpers import format_day

logger = logging.getLogger("excursion_bot")

app = FastAPI(title="Excursion Admin")
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not secrets.compare_digest(credentials.password, ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, username: str = Depends(verify_admin)):
    stats = get_stats()
    dates = []
    for row in stats:
        dates.append({
            "date": row["date"],
            "date_fmt": format_day(row["date"]),
            "booked": row["booked"],
            "capacity": row["capacity_day"],
            "pct": int(row["booked"] / row["capacity_day"] * 100) if row["capacity_day"] else 0,
        })
    return templates.TemplateResponse("index.html", {"request": request, "dates": dates})


@app.get("/date/{date}", response_class=HTMLResponse)
async def date_view(request: Request, date: str, username: str = Depends(verify_admin)):
    bookings = get_bookings_by_date(date)
    items = []
    for b in bookings:
        items.append({
            "id": b["id"],
            "name": b["name"],
            "phone": b["phone"] or "—",
            "persons": b["persons"],
            "time": b["time"],
        })
    total = sum(b["persons"] for b in bookings)
    return templates.TemplateResponse("date.html", {
        "request": request,
        "date": date,
        "date_fmt": format_day(date),
        "bookings": items,
        "total": total,
    })


@app.post("/cancel/{booking_id}")
async def cancel_booking(booking_id: int, username: str = Depends(verify_admin)):
    booking = get_booking_by_id(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    user_id = booking["telegram_user_id"]
    date_fmt = format_day(booking["date"])
    time_str = booking["time"]

    cancel_booking_by_id(booking_id)
    logger.info("Admin cancelled booking #%s (user=%s) via web", booking_id, user_id)

    # Notify user via Telegram Bot API
    text = (
        f"❌ Ваша запись на экскурсию {date_fmt} в {time_str} "
        "отменена администратором.\nВы можете записаться снова."
    )
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": user_id, "text": text},
                timeout=10,
            )
    except Exception as e:
        logger.error("Failed to notify user %s about cancellation: %s", user_id, e)

    return RedirectResponse(url=f"/date/{booking['date']}", status_code=303)
