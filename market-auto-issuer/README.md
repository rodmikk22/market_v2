# 🛒 Market Auto Issuer

**Полностью автоматическая выдача цифровых товаров на Яндекс Маркете (DBS).**

Получает вебхуки от Маркета → забирает ключ/аккаунт со склада → отправляет покупателю через официальный API. Без участия человека, без задержек.

[![CI/CD](https://github.com/YOUR_USER/market-auto-issuer/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USER/market-auto-issuer/actions)

---

## ✨ Что умеет

| Возможность | Описание |
|---|---|
| 🔔 Вебхуки | Принимает PING / ORDER\_CREATED / ORDER\_STATUS\_UPDATED |
| 📦 Склад | Хранит ключи/аккаунты/коды, статусы: free → reserved → issued |
| 🚀 Автовыдача | Вызывает `deliverDigitalGoods` API сразу при поступлении заказа |
| 🔢 Кол-во > 1 | Если заказали 3 единицы — выдаёт ровно 3 кода |
| 🔒 Идемпотентность | Повторная обработка одного заказа ничего не ломает |
| 🖥️ Админ-панель | Веб-интерфейс: добавлять товары, смотреть заказы, выдачи, события |
| 📥 CSV-импорт | Загрузка склада из файла одной кнопкой |
| 🗄️ БД | PostgreSQL — полный аудит всех событий и выдач |
| 🔄 CI/CD | GitHub Actions: lint → тесты → Docker build → deploy |

---

## 🏗️ Архитектура

```
Яндекс Маркет
     │  HTTPS webhook
     ▼
 ┌────────┐      ┌──────────┐      ┌──────────────┐
 │ nginx  │─────▶│   api    │─────▶│  PostgreSQL  │
 │ :8080  │      │ FastAPI  │      │  (4 таблицы) │
 └────────┘      └────┬─────┘      └──────────────┘
                      │ enqueue
                      ▼
                 ┌──────────┐      ┌──────────────┐
                 │  Redis   │─────▶│   worker     │
                 │  queue   │      │ (RQ + Python)│
                 └──────────┘      └──────┬───────┘
                                          │
                                 Partner API + Digital Delivery API
```

### Контейнеры Docker Compose

| Сервис | Роль |
|---|---|
| `nginx` | Reverse proxy, порт 8080 |
| `api` | FastAPI + Uvicorn (вебхуки + админка) |
| `worker` | RQ worker (обработка заказов в фоне) |
| `db` | PostgreSQL 16 |
| `redis` | Redis 7 (брокер очереди) |

### Таблицы БД

| Таблица | Назначение |
|---|---|
| `incoming_events` | Каждый вебхук от Маркета |
| `market_orders` | Снимок заказа из Partner API |
| `stock_items` | Склад цифровых товаров |
| `issuances` | Журнал всех выдач |

---

## 🚀 Быстрый старт (локально / VPS)

### 1. Клонировать и настроить

```bash
git clone https://github.com/YOUR_USER/market-auto-issuer.git
cd market-auto-issuer
cp .env.example .env
nano .env          # Вписать токен и ID кампании
```

Минимально нужно заполнить в `.env`:
```env
MARKET_API_TOKEN=ACMA:xxxxxxxxxxxxxxxxxxxxxxxx
MARKET_CAMPAIGN_ID=12345678
MARKET_BUSINESS_ID=87654321
ADMIN_SECRET=придумайте_пароль
DELIVERY_MODE=yandex_digital
```

### 2. Запустить

```bash
docker compose up -d
docker compose ps        # Все контейнеры должны быть healthy
curl http://localhost:8080/health
```

### 3. Открыть админ-панель

Перейти в браузере: **http://localhost:8080/admin**

---

## 📦 Наполнить склад

### Через веб-интерфейс (рекомендуется)

1. Открыть **Склад товаров** в меню
2. Либо добавить по одному через форму
3. Либо загрузить CSV-файл кнопкой **Импортировать**

Формат CSV (без заголовка — одна запись на строку):
```
KEY-ABCD-1234-5678
KEY-EFGH-9012-3456
login@example.com:password123
```

Или с заголовком:
```csv
secret_payload,label
KEY-ABCD-1234,batch-jan
KEY-EFGH-9012,batch-jan
```

### Через командную строку

```bash
# Скопировать CSV в контейнер
docker cp accounts.csv market_worker:/app/accounts.csv

# Импортировать (offerId должен совпадать с артикулом на Маркете)
docker compose exec -T \
  -e IMPORT_PRODUCT_CODE=MRKT-H5D87B1O \
  -e IMPORT_CSV_PATH=/app/accounts.csv \
  worker python -m app.scripts.import_accounts
```

---

## 🔗 Настройка вебхука на Яндекс Маркете

Маркет должен знать, куда слать уведомления. Нужен HTTPS URL.

### Вариант A — trycloudflare.com (быстро, для теста)

```bash
# Установить cloudflared (один раз)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
     -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

# Запустить туннель (в фоне)
nohup cloudflared tunnel --url http://localhost:8080 > /root/cloudflared.log 2>&1 &

# Получить URL
grep -o 'https://[a-zA-Z0-9.-]*trycloudflare.com' /root/cloudflared.log | tail -1
```

URL будет вида: `https://something-random.trycloudflare.com`

⚠️ После каждого перезапуска URL меняется — нужно обновить в настройках Маркета.

### Вариант B — собственный домен (production)

Если у вас есть домен и SSL:
1. Настроить nginx с сертификатом Let's Encrypt
2. Указать порт 443 вместо 8080

### Регистрация вебхука в Маркете

В личном кабинете Маркета → **Настройки партнёра → Push-уведомления**:

```
URL: https://YOUR_DOMAIN/api/market/webhook/notification
```

Нажать **Проверить** — Маркет пошлёт PING, вы должны увидеть его в разделе **Вебхуки** админки.

---

## 🖥️ Админ-панель

| Раздел | Что показывает |
|---|---|
| **Дашборд** | Остатки по артикулам, статистика выдач, последние исполнения |
| **Склад товаров** | Список всех позиций, фильтры, добавление/редактирование/удаление/импорт CSV |
| **Заказы** | Снимки заказов из Partner API с JSON-деталями |
| **Выдачи** | Журнал всех доставок, статус sent/failed, что именно отдано |
| **Вебхуки** | Все входящие события с полными payload |

---

## ⚙️ Операционные команды

```bash
# Логи в реальном времени
docker compose logs -f api
docker compose logs -f worker

# Состояние склада
docker compose exec db psql -U marketuser -d marketdb \
  -c "SELECT product_code, status, count(*) FROM stock_items GROUP BY 1,2 ORDER BY 1,2;"

# Последние выдачи
docker compose exec db psql -U marketuser -d marketdb \
  -c "SELECT id, order_id, delivery_status, left(error_text,80) err FROM issuances ORDER BY id DESC LIMIT 20;"

# Последние события
docker compose exec db psql -U marketuser -d marketdb \
  -c "SELECT id, notification_type, order_id, received_at FROM incoming_events ORDER BY id DESC LIMIT 20;"

# Перезапуск после обновления кода
docker compose up -d --build

# Полная остановка
docker compose down

# Остановка с удалением данных (ОСТОРОЖНО!)
docker compose down -v
```

---

## 🧪 Тесты

```bash
# Установить зависимости для разработки
pip install -r requirements-dev.txt

# Запустить все тесты
pytest

# С покрытием
pytest --cov=app --cov-report=term-missing

# Конкретный модуль
pytest tests/test_inventory.py -v
pytest tests/test_order_processor.py -v
```

Тесты используют SQLite in-memory — не нужен ни PostgreSQL, ни Redis.

### Что тестируется

| Файл | Что проверяет |
|---|---|
| `test_webhook.py` | Вебхук PING, сохранение событий, корректный формат ответа |
| `test_inventory.py` | Резервирование, финализация, освобождение стока, счётчики |
| `test_order_processor.py` | Полный пайплайн: fetch → reserve → deliver → finalize |
| `test_market_client.py` | HTTP-вызовы к API, заголовок Api-Key, коды и slip |
| `test_delivery_service.py` | Создание issuances, dry-run режим |
| `test_admin_api.py` | CRUD склада, импорт CSV, пагинация, фильтры |

---

## 🔄 CI/CD (GitHub Actions)

При каждом пуше в `main`:
1. **Lint** — black, isort, flake8
2. **Tests** — pytest с покрытием ≥ 70%
3. **Docker build & push** → `ghcr.io/YOUR_USER/market-auto-issuer:latest`
4. **Deploy** — SSH на сервер (опционально, если настроены секреты)

### Секреты для автодеплоя

В настройках репозитория → **Secrets and variables → Actions**:

| Секрет | Значение |
|---|---|
| `DEPLOY_HOST` | IP или домен вашего сервера |
| `DEPLOY_USER` | Пользователь SSH (напр. `root`) |
| `DEPLOY_KEY` | Приватный SSH-ключ |

---

## 🛠️ Разработка

```bash
# Клонировать, создать venv
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# Запустить только DB и Redis (API локально)
docker compose up -d db redis

# Запустить API локально
DATABASE_URL=postgresql://marketuser:marketpass@localhost:5432/marketdb \
REDIS_URL=redis://localhost:6379/0 \
MARKET_API_TOKEN=ACMA:test \
DELIVERY_MODE=dry_run \
uvicorn app.main:app --reload

# Запустить worker локально
DATABASE_URL=postgresql://marketuser:marketpass@localhost:5432/marketdb \
REDIS_URL=redis://localhost:6379/0 \
python worker_main.py

# Alembic — создать новую миграцию
alembic revision --autogenerate -m "add_field"
alembic upgrade head
```

---

## 🐛 Частые проблемы

| Симптом | Причина | Решение |
|---|---|---|
| `INVALID_RESPONSE: name must not be null` | Неверный формат ответа вебхука | Ответ всегда содержит `name`, `version`, `time` — уже встроено |
| `403 OAuth token is invalid` | Неверный заголовок авторизации | Используется `Api-Key:`, не `Authorization: Bearer` — уже встроено |
| `BAD_REQUEST: Required=2, found=1` | Кодов меньше чем `item.count` | Прога резервирует ровно `count` единиц — покупайте достаточно товара на складе |
| `502 Bad Gateway` | API не поднялся | `docker compose logs api` — проверьте ошибки |
| Товары не выдаются | Нет свободных позиций | Пополнить склад через Склад → Добавить / Импорт CSV |
| URL трycloudflare изменился | После перезапуска cloudflared | Получить новый URL и обновить в настройках Маркета |

---

## 📁 Структура проекта

```
market-auto-issuer/
├── app/
│   ├── api/
│   │   ├── webhook.py          # Вебхук Яндекс Маркета
│   │   ├── admin_api.py        # REST API для админки
│   │   └── admin_ui.py         # HTML страницы (Jinja2)
│   ├── models/
│   │   └── models.py           # SQLAlchemy модели
│   ├── services/
│   │   ├── market_client.py    # Partner API клиент
│   │   ├── inventory_service.py# Управление стоком
│   │   ├── delivery_service.py # Выдача товаров
│   │   └── order_processor.py  # Оркестратор заказа
│   ├── scripts/
│   │   └── import_accounts.py  # CLI импорт CSV
│   ├── templates/              # HTML шаблоны
│   ├── config.py               # Pydantic settings
│   ├── database.py             # SQLAlchemy engine
│   └── main.py                 # FastAPI app
├── tests/                      # Автотесты (pytest)
├── migrations/                 # Alembic миграции
├── nginx/nginx.conf            # Nginx конфиг
├── docker-compose.yml
├── Dockerfile
├── .env.example
└── .github/workflows/ci.yml    # CI/CD
```

---

## 📄 Лицензия

MIT
