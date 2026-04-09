# Отчет о выполнении Фазы 9: Интеграция API

## Проделанная работа

1. **JWT Аутентификация**
   - Установлены зависимости: `python-jose[cryptography]`, `passlib[bcrypt]`, `python-multipart`, `bcrypt`.
   - Обновлен файл `src/core/config.py` с переменными для настройки JWT (`jwt_secret_key`, `jwt_algorithm`, `jwt_expire_hours`).
   - Реализованы утилиты для шифрования паролей и генерации JWT токенов в `src/core/security.py`.
   - Созданы зависимости (dependencies) `get_current_user`, `require_submitter`, `require_reviewer`, `require_admin` для контроля ролевого доступа (RBAC).
   - Реализован роутер `src/api/auth.py` с методами `/register`, `/login`, и `/me`.

2. **Обновление моделей БД (Статусный автомат)**
   - Полностью переписан `src/db/models.py`.
   - Добавлены/использованы новые типы `Enum`: `UserRole`, `ProjectStatus`, `RunType`, `RunStatus`.
   - Добавлены новые сущности: `User`, `AgentRun`, `Message`, `TelegramSubscriber`.
   - Модель `Project` расширена новыми полями: `task`, `stage`, `deadlines`, `submitter_id`, `reviewer_id`, `human_decision`, `reviewer_comment`.
   - Добавлены необходимые `relationship` между моделями для работы каскадного удаления и подгрузки связей.

3. **Миграции Alembic**
   - Сгенерирован пустой файл миграции `Alembic` и вручную написан код миграции для применения новой архитектуры к БД (определение `ENUN`, создание таблиц и добавление колонок).

4. **API Управления Проектами**
   - Обновлены Pydantic-схемы проектов в `src/schemas/project.py`.
   - Полностью переписаны методы CRUD проектов в `src/api/projects.py`. 
   - Реализованы новые методы: `/mine` (мои проекты), `/review-queue` (очередь на ревью), `/submit` (подача проекта), `/review` (ревью проекта), `/publish-showcase` (публикация).
   - Внедрена проверка прав доступа на чтение, радактирование и изменение статусов согласно роли пользователя.

5. **Runs API**
   - Созданы схемы в `src/schemas/runs.py`.
   - Реализован `src/api/runs.py` с ручками для асинхронного запуска Intake (Evaluation) и Deep-Research агентов через `BackgroundTasks`. 
   - Созданы ручки для получения логов выполнения агентов.

6. **Messages & Showcase APIs**
   - Написаны Pydantic-схемы для сообщений.
   - Реализованы методы создания сообщений и списка сообщений для проекта в `src/api/messages.py`.
   - Реализована ручка `GET /api/showcase` для вывода проектов с нужным статусом в публичный доступ в `src/api/showcase.py`.

7. **Telegram Admin API**
   - Добавлены эндпоинты в `src/api/telegram_admin.py` для конфигурации бота.
   - Написана асинхронная задача `notify_new_project_submitted`, интегрированная в процесс `submit` проекта для рассылки уведомлений администраторам об ожидающих заявках.

8. **Конфигурация роутеров**
   - Обновлен `src/main.py`. Подключены все новые роутеры (`auth_router`, `projects_router`, `runs_router`, `messages_router`, `showcase_router`, `telegram_admin_router`).

9. **Frontend (UI)**
   - Обновлен `index.html` (добавлена секция авторизации для получения и сохранения JWT-токена). 
   - Обновлены пути запросов для совместимости с новыми API (используются эндпоинты `/api/projects/{id}/runs` вместо `applications`).
   - Функция `request` расширена для переиспользования сохраненного JWT токена в Header (`Authorization: Bearer <token>`).

## Итог
Архитектура API полностью интегрирована, переработаны структуры сущностей БД, добавлены авторизация, RBAC и все запланированные модули. Все соответствует Phase 9. Приложение готово к запуску (docker-compose up).
