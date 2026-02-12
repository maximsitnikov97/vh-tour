import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
DB_PATH = os.getenv("DB_PATH", "excursions.db")
