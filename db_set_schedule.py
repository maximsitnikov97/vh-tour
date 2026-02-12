"""Reset and populate the excursion schedule (days + time_slots).

Usage:
    python db_set_schedule.py
    # or inside Docker:
    docker compose exec bot python db_set_schedule.py
"""

import sqlite3
from datetime import date, timedelta

from config import DB_PATH

CAPACITY_PER_EXCURSION = 30


def daterange(start_ymd: str, end_ymd: str):
    y1, m1, d1 = map(int, start_ymd.split("-"))
    y2, m2, d2 = map(int, end_ymd.split("-"))
    start = date(y1, m1, d1)
    end = date(y2, m2, d2)
    cur = start
    while cur <= end:
        yield cur.isoformat()
        cur += timedelta(days=1)


def main():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Ensure tables exist
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS days (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL UNIQUE,
        capacity_day INTEGER NOT NULL
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS time_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day_id INTEGER NOT NULL,
        time TEXT NOT NULL,
        capacity_time INTEGER NOT NULL,
        FOREIGN KEY (day_id) REFERENCES days(id)
    )
    """)

    # Clear current schedule (days/time_slots only)
    cursor.execute("DELETE FROM time_slots")
    cursor.execute("DELETE FROM days")
    conn.commit()

    # Schedule rules
    schedule_rules = []

    # 16–20 февраля: 11:00, 13:00, 15:00
    times_3 = ["11:00", "13:00", "15:00"]
    for ymd in daterange("2026-02-16", "2026-02-20"):
        schedule_rules.append((ymd, times_3))

    # 21 и 23 февраля: 9:00, 11:00, 13:00, 15:00
    times_4 = ["09:00", "11:00", "13:00", "15:00"]
    schedule_rules.append(("2026-02-21", times_4))
    schedule_rules.append(("2026-02-23", times_4))

    # 24–27 февраля: 11:00, 13:00, 15:00
    for ymd in daterange("2026-02-24", "2026-02-27"):
        schedule_rules.append((ymd, times_3))

    # 28 февраля и 01 марта: 9:00, 11:00, 13:00, 15:00
    schedule_rules.append(("2026-02-28", times_4))
    schedule_rules.append(("2026-03-01", times_4))

    # 02 и 03 марта: 11:00, 13:00, 15:00
    schedule_rules.append(("2026-03-02", times_3))
    schedule_rules.append(("2026-03-03", times_3))

    # Insert days + time_slots
    for ymd, times in schedule_rules:
        capacity_day = CAPACITY_PER_EXCURSION * len(times)
        cursor.execute(
            "INSERT INTO days (date, capacity_day) VALUES (?, ?)",
            (ymd, capacity_day),
        )
        day_id = cursor.lastrowid
        for t in times:
            cursor.execute(
                "INSERT INTO time_slots (day_id, time, capacity_time) VALUES (?, ?, ?)",
                (day_id, t, CAPACITY_PER_EXCURSION),
            )

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM days")
    days_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM time_slots")
    slots_count = cursor.fetchone()[0]

    conn.close()

    print(f"Готово: дней = {days_count}, временных слотов = {slots_count}")
    print(f"Вместимость: {CAPACITY_PER_EXCURSION} мест на каждый слот времени")


if __name__ == "__main__":
    main()
