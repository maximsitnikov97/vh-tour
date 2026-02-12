import re
from datetime import datetime
from typing import Optional

MONTHS = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def format_day(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{dt.day} {MONTHS[dt.month]}"


def decline_places(n: int) -> str:
    if 11 <= n % 100 <= 14:
        return f"{n} мест"
    if n % 10 == 1:
        return f"{n} место"
    if 2 <= n % 10 <= 4:
        return f"{n} места"
    return f"{n} мест"


def validate_phone(raw: str) -> Optional[str]:
    """Normalize phone to +7XXXXXXXXXX format. Returns None if invalid."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if digits.startswith("7") and len(digits) == 11:
        return "+" + digits
    return None


def validate_name(name: str) -> bool:
    """2-50 chars, letters/spaces/hyphens only."""
    if not 2 <= len(name) <= 50:
        return False
    return bool(re.match(r"^[\w\s\-]+$", name, re.UNICODE))
