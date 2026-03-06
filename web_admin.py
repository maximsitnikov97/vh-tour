import asyncio
import logging
import os
import secrets
import uuid

import httpx
from fastapi import FastAPI, Request, Depends, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from config import ADMIN_PASSWORD, BOT_TOKEN, BROADCAST_UPLOAD_DIR
from db import (
    get_stats, get_bookings_by_date, get_booking_by_id, cancel_booking_by_id,
    get_subscribers, create_broadcast, get_broadcast_history, _utc_to_msk,
)
from broadcast_sender import send_broadcast
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


@app.get("/subscribers", response_class=HTMLResponse)
async def subscribers_view(request: Request, filter: str = "all", username: str = Depends(verify_admin)):
    rows = get_subscribers(filter)
    subs = []
    for s in rows:
        subs.append({
            "first_name": s["first_name"] or "",
            "last_name": s["last_name"] or "",
            "username": s["username"] or "",
            "phone": s["phone"] or "—",
            "status": s["status"],
            "created_at": s["created_at"][:10] if s["created_at"] else "",
        })
    return templates.TemplateResponse("subscribers.html", {
        "request": request,
        "subscribers": subs,
        "total": len(subs),
        "current_filter": filter,
    })


# ── Broadcast ──

@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_form(request: Request, username: str = Depends(verify_admin)):
    return templates.TemplateResponse("broadcast.html", {"request": request})


@app.post("/broadcast")
async def broadcast_create(
    request: Request,
    text: str = Form(...),
    button_text: str = Form(""),
    button_url: str = Form(""),
    send_mode: str = Form("now"),
    scheduled_at: str = Form(""),
    image: UploadFile = File(None),
    username: str = Depends(verify_admin),
):
    # Save image if provided (resize if too large for Telegram)
    image_path = None
    if image and image.filename:
        os.makedirs(BROADCAST_UPLOAD_DIR, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.jpg"
        image_path = os.path.join(BROADCAST_UPLOAD_DIR, filename)
        content = await image.read()

        from PIL import Image
        import io
        img = Image.open(io.BytesIO(content))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        # Telegram limit: width+height <= 10000, each side <= 5000
        max_side = 2000
        if img.width > max_side or img.height > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        img.save(image_path, "JPEG", quality=90)

    schedule_dt = None
    if send_mode == "scheduled" and scheduled_at:
        schedule_dt = scheduled_at.replace("T", " ")

    btn_text = button_text.strip() or None
    btn_url = button_url.strip() or None

    broadcast_id = create_broadcast(
        text=text,
        image_path=image_path,
        button_text=btn_text,
        button_url=btn_url,
        scheduled_at_msk=schedule_dt,
    )

    if send_mode == "now":
        asyncio.create_task(send_broadcast(broadcast_id))
        logger.info("Broadcast #%s started immediately", broadcast_id)
    else:
        logger.info("Broadcast #%s scheduled at %s", broadcast_id, schedule_dt)

    return RedirectResponse(url="/broadcast/history", status_code=303)


@app.get("/broadcast/history", response_class=HTMLResponse)
async def broadcast_history_view(request: Request, username: str = Depends(verify_admin)):
    rows = get_broadcast_history()
    broadcasts = []
    for b in rows:
        broadcasts.append({
            "id": b["id"],
            "text": b["text"][:80] + ("..." if len(b["text"]) > 80 else ""),
            "has_image": bool(b["image_path"]),
            "has_button": bool(b["button_text"]),
            "status": b["status"],
            "scheduled_at": _utc_to_msk(b["scheduled_at"]),
            "completed_at": _utc_to_msk(b["completed_at"]),
            "total": b["total"],
            "success": b["success"],
            "failed": b["failed"],
        })
    return templates.TemplateResponse("broadcast_history.html", {
        "request": request,
        "broadcasts": broadcasts,
    })
