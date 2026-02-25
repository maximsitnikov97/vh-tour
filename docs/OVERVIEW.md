# Верёвкин Хутор — Telegram-бот экскурсий

## Описание

Telegram-бот для записи на бесплатные экскурсии в теплицы «Верёвкин Хутор» (Крым, Молодёжное). Пользователи выбирают количество человек, дату и время, вводят имя и телефон. Бот подтверждает запись и автоматически отправляет напоминание за сутки.

## Стек

- **Python 3.11+**, `python-telegram-bot` v22.5
- **SQLite** с WAL-режимом (`excursions.db`)
- **FastAPI** — веб-админка
- **APScheduler** — фоновые напоминания
- **Docker + Docker Compose** — деплой
- **Nginx + Let's Encrypt** — HTTPS на сервере (`vh.d4o.tech`)

## Архитектура

```
┌──────────────┐     polling     ┌─────────────────┐
│  Telegram API │ ◄────────────► │    bot.py        │
└──────────────┘                 │  (обработчики)   │
                                 └────────┬─────────┘
                                          │
              ┌───────────────────────────┼──────────────────────┐
              │                           │                      │
        ┌─────▼──────┐           ┌────────▼───────┐   ┌─────────▼────────┐
        │   db.py     │           │  scheduler.py  │   │    admin.py      │
        │  (SQLite)   │           │  (APScheduler) │   │ (Telegram /admin)│
        └─────┬───────┘           └────────────────┘   └──────────────────┘
              │
        ┌─────▼───────┐
        │ web_admin.py │
        │  (FastAPI)   │
        └─────────────┘
```

Два Docker-контейнера на одном `bot-data` volume (общая БД):
- `bot` — Telegram-бот + APScheduler
- `admin` — FastAPI веб-админка на порту 8080, проксируется через Nginx

---

## Фичи

### Запись на экскурсию

Пошаговый диалог через inline-кнопки:
1. Количество человек (1 / 2 / 3 / 10+)
2. Дата (только будущие, только где хватает мест)
3. Время (только где хватает мест и время не прошло)
4. Имя (2–50 символов, буквы/пробелы/дефисы)
5. Телефон (+7/8 → нормализуется в `+7XXXXXXXXXX`)

Ограничение: **один пользователь — одна активная запись** (`UNIQUE INDEX` на `telegram_user_id`).

Защита от гонок: `BEGIN IMMEDIATE` + повторная проверка вместимости перед INSERT в `create_booking()`.

**Реализация:** `bot.py:61–214`, `db.py:152–184`, `helpers.py`

---

### Напоминания

APScheduler каждые 30 минут ищет записи в окне **+23h — +25h** и отправляет сообщение с датой, временем, адресом.

Флаг `reminder_sent` в таблице `bookings` предотвращает повторную отправку.

**Реализация:** `scheduler.py`, `db.py:259–274`

---

### Отслеживание подписчиков

При каждом `/start` — `upsert_subscriber()`. При блокировке/разблокировке бота (`MY_CHAT_MEMBER`) — обновление статуса (`active` / `left`). После бронирования — сохранение телефона.

**Реализация:** `bot.py:53`, `bot.py:332–341`, `db.py:277–328`

---

### Telegram-админка

Команда `/admin` (только для `ADMIN_IDS`):
- Просмотр записей по дате
- Статистика заполненности с прогресс-баром

**Реализация:** `admin.py`

---

### Веб-админка

FastAPI на `https://vh.d4o.tech` (HTTP Basic Auth, пароль = `ADMIN_PASSWORD`):
- `/` — список дат с заполненностью
- `/date/{date}` — записи на дату
- `/cancel/{booking_id}` — отмена записи + уведомление пользователю в Telegram
- `/subscribers` — список подписчиков (фильтры: all / active / with_phone)

**Реализация:** `web_admin.py`, `templates/`

---

### Расписание

Слоты хранятся в БД. Текущая логика:
- **Пн–чт:** 15:00
- **Пятница:** 09:00, 15:00
- **Сб–вс:** 09:00, 15:00
- Вместимость: **30 человек** на каждый временной слот

**Реализация:** `db_set_schedule.py`

---

## Схема БД

```sql
days         (id, date UNIQUE, capacity_day)
time_slots   (id, day_id → days, time, capacity_time)
bookings     (id, telegram_user_id UNIQUE, name, persons, day_id, time_slot_id,
              created_at, reminder_sent, phone)
subscribers  (id, telegram_user_id UNIQUE, username, first_name, last_name,
              phone, status, created_at, updated_at)
```

---

## Конфигурация (env)

| Переменная | Описание | Обязательная |
|-----------|----------|-------------|
| `BOT_TOKEN` | Токен Telegram-бота | да |
| `ADMIN_IDS` | Telegram user_id админов через запятую | да |
| `ADMIN_PASSWORD` | Пароль для веб-админки (HTTP Basic) | да |
| `DB_PATH` | Путь к SQLite (по умолчанию `excursions.db`) | нет |

---

## Деплой

Сервер: `root@194.87.250.87`, проект в `/root/vh-tour/`.

**CI/CD:** GitHub Actions при пуше в `main`:
1. `git pull` на сервере
2. Копирует `nginx/vh-tour.conf` → `/etc/nginx/sites-available/` и перезагружает Nginx
3. `docker compose up --build -d`

**SSL:** Let's Encrypt, сертификат `vh.d4o.tech` (`/etc/letsencrypt/live/vh.d4o.tech/`), автообновление.

**Изменение расписания на живой БД:**
```bash
ssh root@194.87.250.87
docker compose -f /root/vh-tour/docker-compose.yml exec -T bot python db_set_schedule.py
```

---

*Обновлено: 2026-02-25*
