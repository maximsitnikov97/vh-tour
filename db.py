import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DB_PATH


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS days (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                capacity_day INTEGER NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS time_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_id INTEGER NOT NULL,
                time TEXT NOT NULL,
                capacity_time INTEGER NOT NULL,
                FOREIGN KEY (day_id) REFERENCES days(id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                persons INTEGER NOT NULL,
                day_id INTEGER NOT NULL,
                time_slot_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                reminder_sent INTEGER DEFAULT 0,
                phone TEXT,
                FOREIGN KEY (day_id) REFERENCES days(id),
                FOREIGN KEY (time_slot_id) REFERENCES time_slots(id)
            )
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_user
            ON bookings(telegram_user_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_bookings_day_id
            ON bookings(day_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_bookings_time_slot_id
            ON bookings(time_slot_id)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                phone TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Drop legacy table if exists
        cur.execute("DROP TABLE IF EXISTS slots")
        conn.commit()


# ── Booking queries ──

def user_has_booking(user_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM bookings WHERE telegram_user_id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
        return row is not None


def get_available_days(persons: int):
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        return conn.execute("""
            SELECT
                d.id,
                d.date,
                d.capacity_day -
                    COALESCE((SELECT SUM(b.persons) FROM bookings b WHERE b.day_id = d.id), 0)
                    AS remaining
            FROM days d
            WHERE d.date >= ?
              AND EXISTS (
                SELECT 1 FROM time_slots ts
                LEFT JOIN bookings b2 ON b2.time_slot_id = ts.id
                WHERE ts.day_id = d.id
                GROUP BY ts.id
                HAVING ts.capacity_time - COALESCE(SUM(b2.persons), 0) >= ?
              )
            ORDER BY d.date
        """, (today, persons)).fetchall()


def get_available_times(day_id: int, persons: int):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")

    with get_db() as conn:
        return conn.execute("""
            SELECT
                ts.id,
                ts.time,
                ts.capacity_time - COALESCE(SUM(b.persons), 0) AS remaining,
                d.date AS day_date
            FROM time_slots ts
            JOIN days d ON d.id = ts.day_id
            LEFT JOIN bookings b ON b.time_slot_id = ts.id
            WHERE ts.day_id = ?
            GROUP BY ts.id
            HAVING remaining >= ?
               AND (d.date > ? OR (d.date = ? AND ts.time > ?))
            ORDER BY ts.time
        """, (day_id, persons, today, today, current_time)).fetchall()


def get_user_booking(user_id: int):
    with get_db() as conn:
        return conn.execute("""
            SELECT b.name, b.persons, b.phone, d.date, ts.time
            FROM bookings b
            JOIN days d ON d.id = b.day_id
            JOIN time_slots ts ON ts.id = b.time_slot_id
            WHERE b.telegram_user_id = ?
        """, (user_id,)).fetchone()


def create_booking(user_id: int, name: str, persons: int, day_id: int, time_slot_id: int, phone: str):
    """Insert booking inside BEGIN IMMEDIATE transaction. Returns (success, date_str, time_str)."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""
            SELECT ts.capacity_time - COALESCE(SUM(b.persons), 0) AS remaining
            FROM time_slots ts
            LEFT JOIN bookings b ON b.time_slot_id = ts.id
            WHERE ts.id = ?
            GROUP BY ts.id
        """, (time_slot_id,)).fetchone()
        remaining = row["remaining"] if row and row["remaining"] is not None else 0

        if remaining < persons:
            conn.rollback()
            return False, None, None

        conn.execute("""
            INSERT INTO bookings
                (telegram_user_id, name, persons, day_id, time_slot_id, phone, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """, (user_id, name, persons, day_id, time_slot_id, phone))
        conn.commit()

        day_date = conn.execute("SELECT date FROM days WHERE id = ?", (day_id,)).fetchone()["date"]
        slot_time = conn.execute("SELECT time FROM time_slots WHERE id = ?", (time_slot_id,)).fetchone()["time"]
        return True, day_date, slot_time
    finally:
        conn.close()


def cancel_user_booking(user_id: int) -> bool:
    with get_db() as conn:
        deleted = conn.execute(
            "DELETE FROM bookings WHERE telegram_user_id = ?", (user_id,)
        ).rowcount
        conn.commit()
        return deleted > 0


# ── Admin queries ──

def get_all_bookings():
    with get_db() as conn:
        return conn.execute("""
            SELECT b.id, b.telegram_user_id, b.name, b.phone, b.persons,
                   d.date, ts.time, b.created_at
            FROM bookings b
            JOIN days d ON d.id = b.day_id
            JOIN time_slots ts ON ts.id = b.time_slot_id
            ORDER BY d.date, ts.time
        """).fetchall()


def get_bookings_by_date(date_str: str):
    with get_db() as conn:
        return conn.execute("""
            SELECT b.id, b.telegram_user_id, b.name, b.phone, b.persons,
                   d.date, ts.time, b.created_at
            FROM bookings b
            JOIN days d ON d.id = b.day_id
            JOIN time_slots ts ON ts.id = b.time_slot_id
            WHERE d.date = ?
            ORDER BY ts.time, b.created_at
        """, (date_str,)).fetchall()


def get_booking_by_id(booking_id: int):
    with get_db() as conn:
        return conn.execute("""
            SELECT b.id, b.telegram_user_id, b.name, b.phone, b.persons,
                   d.date, ts.time
            FROM bookings b
            JOIN days d ON d.id = b.day_id
            JOIN time_slots ts ON ts.id = b.time_slot_id
            WHERE b.id = ?
        """, (booking_id,)).fetchone()


def cancel_booking_by_id(booking_id: int) -> bool:
    with get_db() as conn:
        deleted = conn.execute("DELETE FROM bookings WHERE id = ?", (booking_id,)).rowcount
        conn.commit()
        return deleted > 0


def get_stats():
    """Return list of (date, booked, capacity) for future dates."""
    today = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        return conn.execute("""
            SELECT d.date, d.capacity_day,
                   COALESCE(SUM(b.persons), 0) AS booked
            FROM days d
            LEFT JOIN bookings b ON b.day_id = d.id
            WHERE d.date >= ?
            GROUP BY d.id
            ORDER BY d.date
        """, (today,)).fetchall()


# ── Reminder queries ──

def get_pending_reminders(from_dt: str, to_dt: str):
    with get_db() as conn:
        return conn.execute("""
            SELECT b.id, b.telegram_user_id, b.persons, d.date, ts.time
            FROM bookings b
            JOIN days d ON d.id = b.day_id
            JOIN time_slots ts ON ts.id = b.time_slot_id
            WHERE b.reminder_sent = 0
              AND datetime(d.date || ' ' || ts.time) BETWEEN ? AND ?
        """, (from_dt, to_dt)).fetchall()


def mark_reminder_sent(booking_id: int):
    with get_db() as conn:
        conn.execute("UPDATE bookings SET reminder_sent = 1 WHERE id = ?", (booking_id,))
        conn.commit()


# ── Subscriber queries ──

def upsert_subscriber(user_id: int, username: str | None, first_name: str | None, last_name: str | None):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO subscribers (telegram_user_id, username, first_name, last_name, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                status = 'active',
                updated_at = excluded.updated_at
        """, (user_id, username, first_name, last_name, now, now))
        conn.commit()


def update_subscriber_phone(user_id: int, phone: str):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE subscribers SET phone = ?, updated_at = ? WHERE telegram_user_id = ?",
            (phone, now, user_id),
        )
        conn.commit()


def update_subscriber_status(user_id: int, status: str):
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE subscribers SET status = ?, updated_at = ? WHERE telegram_user_id = ?",
            (status, now, user_id),
        )
        conn.commit()


def get_subscribers(filter_type: str = "all"):
    with get_db() as conn:
        if filter_type == "active":
            return conn.execute(
                "SELECT * FROM subscribers WHERE status = 'active' ORDER BY created_at DESC"
            ).fetchall()
        elif filter_type == "with_phone":
            return conn.execute(
                "SELECT * FROM subscribers WHERE phone IS NOT NULL AND phone != '' ORDER BY created_at DESC"
            ).fetchall()
        else:
            return conn.execute(
                "SELECT * FROM subscribers ORDER BY created_at DESC"
            ).fetchall()
