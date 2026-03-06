from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx

from config import BOT_TOKEN
from db import (
    get_broadcast_by_id,
    get_active_subscriber_ids,
    update_broadcast_status,
    update_subscriber_status,
    _utc_now,
)

logger = logging.getLogger("excursion_bot")

RETRY_DELAYS = [0.05, 0.5, 1.0]  # seconds
SEND_DELAY = 0.05  # 50ms between messages (20/sec)


async def send_broadcast(broadcast_id: int):
    broadcast = get_broadcast_by_id(broadcast_id)
    if not broadcast:
        logger.error("Broadcast #%s not found", broadcast_id)
        return

    # Skip if already completed
    if broadcast["status"] == "completed":
        logger.warning("Broadcast #%s already completed, skipping", broadcast_id)
        return

    subscriber_ids = get_active_subscriber_ids()
    total = len(subscriber_ids)

    update_broadcast_status(
        broadcast_id,
        status="sending",
        sent_at=_utc_now(),
        total=total,
    )

    success = 0
    failed = 0

    # Build inline keyboard if button is set
    reply_markup = None
    if broadcast["button_text"] and broadcast["button_url"]:
        reply_markup = {
            "inline_keyboard": [[{
                "text": broadcast["button_text"],
                "url": broadcast["button_url"],
            }]]
        }

    async with httpx.AsyncClient(timeout=30) as client:
        for user_id in subscriber_ids:
            ok = await _send_to_user(client, broadcast, user_id, reply_markup)
            if ok:
                success += 1
            else:
                failed += 1
            await asyncio.sleep(SEND_DELAY)

    update_broadcast_status(
        broadcast_id,
        status="completed",
        completed_at=_utc_now(),
        success=success,
        failed=failed,
    )
    logger.info("Broadcast #%s completed: %d/%d sent", broadcast_id, success, total)


async def _send_to_user(client: httpx.AsyncClient, broadcast, user_id: int,
                        reply_markup: dict | None) -> bool:
    for attempt, delay in enumerate(RETRY_DELAYS):
        try:
            if broadcast["image_path"]:
                ok, should_retry = await _send_photo(client, broadcast, user_id, reply_markup)
            else:
                ok, should_retry = await _send_message(client, broadcast, user_id, reply_markup)

            if ok:
                return True
            if not should_retry:
                return False

        except Exception as e:
            logger.warning("Broadcast send error user=%s attempt=%d: %s", user_id, attempt, e)

        if attempt < len(RETRY_DELAYS) - 1:
            await asyncio.sleep(delay)

    return False


async def send_test_message(text: str, image_path: str | None,
                            button_text: str | None, button_url: str | None,
                            user_id: int) -> tuple[bool, str]:
    """Send a single test message. Returns (success, error_text)."""
    reply_markup = None
    if button_text and button_url:
        reply_markup = {
            "inline_keyboard": [[{"text": button_text, "url": button_url}]]
        }
    broadcast = {"text": text, "image_path": image_path}

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            if image_path:
                ok, _ = await _send_photo(client, broadcast, user_id, reply_markup)
            else:
                ok, _ = await _send_message(client, broadcast, user_id, reply_markup)
            if ok:
                return True, ""
            return False, "Telegram API отклонил запрос"
        except Exception as e:
            return False, str(e)


async def _send_message(client: httpx.AsyncClient, broadcast, user_id: int,
                        reply_markup: dict | None) -> tuple[bool, bool]:
    payload = {"chat_id": user_id, "text": broadcast["text"]}
    if reply_markup:
        payload["reply_markup"] = reply_markup

    resp = await client.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json=payload,
    )
    return await _handle_response(resp, user_id)


async def _send_photo(client: httpx.AsyncClient, broadcast, user_id: int,
                      reply_markup: dict | None) -> tuple[bool, bool]:
    import json as json_mod
    import mimetypes
    import os

    image_path = broadcast["image_path"]
    filename = os.path.basename(image_path)
    mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"

    data = {"chat_id": str(user_id)}
    if broadcast["text"]:
        data["caption"] = broadcast["text"]
    if reply_markup:
        data["reply_markup"] = json_mod.dumps(reply_markup)

    with open(image_path, "rb") as f:
        resp = await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data=data,
            files={"photo": (filename, f, mime_type)},
        )
    return await _handle_response(resp, user_id)


async def _handle_response(resp: httpx.Response, user_id: int) -> tuple[bool, bool]:
    """Returns (success, should_retry)."""
    if resp.status_code == 200:
        result = resp.json()
        if result.get("ok"):
            return True, False

    if resp.status_code == 403:
        # User blocked the bot
        update_subscriber_status(user_id, "left")
        logger.info("User %s blocked bot, marked as left", user_id)
        return False, False

    if resp.status_code == 429:
        try:
            retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
            logger.warning("Rate limited for user %s, retry_after=%s", user_id, retry_after)
            await asyncio.sleep(retry_after)
        except Exception:
            await asyncio.sleep(5)
        return False, True

    logger.warning("Telegram API error for user %s: %s %s", user_id, resp.status_code, resp.text[:200])
    return False, True
