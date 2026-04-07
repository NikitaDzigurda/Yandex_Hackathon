# DEPLOY.md

## 1. Клонирование репозитория

```bash
git clone https://git.sourcecraft.dev/urfu/<repo>.git
cd <repo>
```

## 2. Подготовка переменных окружения

```bash
cp .env.example .env
```

Заполните значения в `.env`:
- `YC_API_KEY`, `YC_FOLDER_ID`, `YC_AGENT_ID_INTAKE`, `YC_AGENT_ID_RESEARCH`
- `TRACKER_TOKEN`, `TRACKER_ORG_ID`, `TRACKER_QUEUE_KEY`
- `SOURCECRAFT_TOKEN`, `SOURCECRAFT_BASE_URL`

## 3. Запуск окружения

```bash
docker compose up --build
```

## 4. Проверка доступности API

```bash
curl http://localhost:8000/health
```

Ожидается успешный HTTP-ответ от health-check эндпоинта.

## 5. Применение миграций

```bash
docker compose exec api alembic upgrade head
```

## 6. Остановка

```bash
docker compose down
```
