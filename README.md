# FrixiHack Key Server

Сервер для управления лицензионными ключами FrixiHack.  
Управление через Telegram-бота: создание, просмотр и отзыв ключей.

---

## Структура

```
frixihack-server/
├── server.py        # FastAPI сервер
├── bot.py           # Telegram бот
├── requirements.txt
├── .env.example     # Шаблон переменных окружения
└── .gitignore
```

---

## Установка

```bash
git clone https://github.com/you/frixihack-server
cd frixihack-server
pip install -r requirements.txt
```

---

## Настройка

1. Скопируй `.env.example` в `.env`:
   ```bash
   cp .env.example .env
   ```

2. Заполни `.env`:
   - `BOT_TOKEN` — токен от [@BotFather](https://t.me/BotFather)
   - `ADMIN_IDS` — твой Telegram ID (узнать у [@userinfobot](https://t.me/userinfobot))
   - `INTERNAL_SECRET` — любая длинная случайная строка
   - `SERVER_URL` — адрес сервера (при локальном запуске: `http://localhost:8000`)

---

## Запуск

Запускать нужно **два процесса одновременно**.

**Терминал 1 — сервер:**
```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

**Терминал 2 — бот:**
```bash
python bot.py
```

---

## Команды бота

| Команда   | Описание                             |
|-----------|--------------------------------------|
| `/newkey` | Создать ключ (1 / 7 / 30 дней)       |
| `/keys`   | Список всех ключей                   |
| `/revoke` | Отозвать активный ключ               |

---

## Настройка FrixiHack клиента

В файле `cfg/general_config.toml` смени:
```toml
api_base_url = "твой-домен.com"
```
*(без `https://` — клиент добавит сам)*

---

## Деплой на сервер (опционально)

Рекомендую [Railway](https://railway.app) или [Render](https://render.com) — оба бесплатны для маленьких проектов.

На Railway:
1. Создай новый проект → Deploy from GitHub
2. Добавь переменные из `.env` в настройках (Environment Variables)
3. Start command: `uvicorn server:app --host 0.0.0.0 --port $PORT`
4. Бота запускай отдельно (второй сервис) с командой: `python bot.py`

> ⚠️ Файл `.env` в репозиторий **не загружается** — он в `.gitignore`.
> Переменные вводятся вручную в панели хостинга.
