# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Важные правила

- Пиши и думай на Русском языке
- Доступ к серверу где размещен проект ssh root@194.87.250.87 (ключ уже настроен на этом Mac)

## Обзор проекта

Telegram-бот для записи на бесплатные экскурсии в «Верёвкин Хутор» (теплицы, Крым). Python + `python-telegram-bot` v22.5. БД — SQLite с WAL-режимом. Веб-админка — FastAPI. Docker-ready.

## Запуск

### Docker (рекомендуется)
```bash
cp .env.example .env   # заполнить BOT_TOKEN, ADMIN_IDS, ADMIN_PASSWORD
docker compose up --build
```

### Локально
```bash
source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="..." ADMIN_IDS="123456789" ADMIN_PASSWORD="secret"
python bot.py
# Веб-админка (отдельный терминал):
python -m uvicorn web_admin:app --port 8080
```

### Настройка расписания
```bash
python db_set_schedule.py
# или в Docker:
docker compose exec bot python db_set_schedule.py
```

## Структура файлов

```
bot.py              — обработчики Telegram (~250 строк)
config.py           — конфигурация из env (BOT_TOKEN, ADMIN_IDS, ADMIN_PASSWORD, DB_PATH)
db.py               — все операции с БД (get_db, init_db, create_booking, admin-запросы)
helpers.py          — format_day, decline_places, validate_phone, validate_name
admin.py            — Telegram-команда /admin (просмотр записей, статистика)
web_admin.py        — FastAPI веб-админка (просмотр + отмена записей)
templates/          — Jinja2-шаблоны для веб-админки (base, index, date)
scheduler.py        — APScheduler — встроенные напоминания (каждые 30 мин)
logger.py           — настройка логирования
reminder.py         — [deprecated] cron-fallback для напоминаний
db_set_schedule.py  — настройка расписания (дни + временные слоты)
requirements.txt    — зависимости Python
Dockerfile          — образ для бота
docker-compose.yml  — бот + веб-админка
.env.example        — шаблон переменных окружения
```

## Архитектура

### Поток бронирования
Цепочка callback-обработчиков через `context.user_data`:
1. `start_booking` → выбор количества человек (`persons_*`)
2. `persons_chosen` → выбор даты (`day_*`)
3. `day_chosen` → выбор времени (`time_*`)
4. `time_chosen` → ввод имени (флаг `waiting_name`)
5. `name_entered` → ввод телефона (флаг `waiting_phone`)
6. `phone_entered` → `BEGIN IMMEDIATE` транзакция → INSERT → подтверждение

Текстовый ввод маршрутизируется через `text_input_router()` по флагам в `context.user_data`.

### Защита от гонок
`create_booking()` в `db.py` — `BEGIN IMMEDIATE` с повторной проверкой вместимости перед INSERT.

### Ограничение
Один пользователь = одна активная запись (UNIQUE INDEX на `telegram_user_id`).

### Админка
- **Telegram** (`/admin`): просмотр записей на дату, статистика заполненности. Доступно только `ADMIN_IDS`.
- **Веб** (`web_admin.py`): HTTP Basic Auth, просмотр + отмена записей с уведомлением пользователя в Telegram.

### Напоминания
Встроенный `AsyncIOScheduler` (каждые 30 мин) через `post_init`. Ищет записи за 23-25ч до экскурсии.

## Схема БД

- **days** (`id`, `date`, `capacity_day`)
- **time_slots** (`id`, `day_id`, `time`, `capacity_time`)
- **bookings** (`id`, `telegram_user_id`, `name`, `persons`, `day_id`, `time_slot_id`, `created_at`, `reminder_sent`, `phone`)

Индексы: `idx_bookings_user` (UNIQUE), `idx_bookings_day_id`, `idx_bookings_time_slot_id`.

## Конфигурация (env)

- `BOT_TOKEN` — токен Telegram-бота (обязательно)
- `ADMIN_IDS` — Telegram user_id администраторов через запятую
- `ADMIN_PASSWORD` — пароль для веб-админки (HTTP Basic Auth)
- `DB_PATH` — путь к SQLite (по умолчанию `excursions.db`)

## Важные паттерны

- Все тексты на русском с эмодзи
- `get_db()` в `db.py` — контекстный менеджер с автозакрытием
- Callback data: `persons_N`, `day_N`, `time_N`, `admin_*`
- Валидация: `validate_name()` (2-50 символов), `validate_phone()` (+7/8 формат → +7XXXXXXXXXX)
- Внешние ссылки (каталог Google Drive, Яндекс Карты) — константы в bot.py
