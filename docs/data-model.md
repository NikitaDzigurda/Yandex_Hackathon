# Модель данных PostgreSQL (MVP)

Документ описывает базовую схему БД для платформы автоматизации проектной деятельности.  
Фокус Фазы 1: хранение заявок, состояний проекта, логов агентов, задач Трекера и документов.

---

## Общие принципы

- СУБД: PostgreSQL 16+
- Таймстемпы: `TIMESTAMPTZ` (UTC)
- Идентификаторы: `UUID`
- Поля с переменной структурой: `JSONB`
- Статусы фиксируются явно через `VARCHAR`/`TEXT` с ограничениями на уровне приложения (и далее через migrations можно добавить `CHECK`/`ENUM`)

---

## 1) Таблица `projects`

**Назначение**  
Хранит карточку проекта и его текущий жизненный статус.

### Поля

- `id UUID PRIMARY KEY`
- `title TEXT NOT NULL`
- `description TEXT`
- `status VARCHAR(64) NOT NULL`
- `created_by VARCHAR(255) NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

### Что хранится и зачем

- Базовые метаданные проекта (`title`, `description`)
- Текущее состояние процесса (`status`) для оркестрации агентов
- Аудит создания/обновления (`created_by`, `created_at`, `updated_at`)

---

## 2) Таблица `applications`

**Назначение**  
Хранит входящие заявки от инициаторов и результаты первичной оценки Intake Agent.

### Поля

- `id UUID PRIMARY KEY`
- `project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE`
- `initiator_name VARCHAR(255) NOT NULL`
- `initiator_email VARCHAR(255) NOT NULL`
- `text TEXT NOT NULL`
- `attachments_url TEXT`
- `status VARCHAR(32) NOT NULL`  
  Допустимые значения: `draft | submitted | scoring | approved | rejected`
- `scorecard JSONB`  
  Структура: оценки по 5 критериям + пояснения
- `summary TEXT`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

### Что хранится и зачем

- Полный текст заявки и контакт инициатора
- Статус рассмотрения заявки
- Результаты автоматической оценки (`scorecard`) и резюме для РП (`summary`)

---

## 3) Таблица `agent_logs`

**Назначение**  
Технический аудит действий агентов и Orchestrator для трассировки решений и отладки.

### Поля

- `id UUID PRIMARY KEY`
- `project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE`
- `correlation_id UUID NOT NULL`
- `agent_name VARCHAR(64) NOT NULL`
- `stage VARCHAR(64) NOT NULL`
- `action VARCHAR(128) NOT NULL`
- `input_payload JSONB`
- `output_payload JSONB`
- `status VARCHAR(16) NOT NULL`  
  Допустимые значения: `success | error | pending`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

### Что хранится и зачем

- Сквозной контекст операции (`correlation_id`, `stage`, `action`)
- Вход/выход шага агента (`input_payload`, `output_payload`)
- Результат шага для мониторинга и ретраев (`status`)

---

## 4) Таблица `tasks`

**Назначение**  
Хранит внутренние и синхронизированные с Яндекс Трекером задачи по проекту.

### Поля

- `id UUID PRIMARY KEY`
- `project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE`
- `tracker_issue_id VARCHAR(64)`
- `title TEXT NOT NULL`
- `description TEXT`
- `assigned_to VARCHAR(255)`
- `status VARCHAR(64) NOT NULL`
- `due_date DATE`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

### Что хранится и зачем

- Технические и бизнес-задачи проекта
- Связь с внешней задачей в Трекере (`tracker_issue_id`)
- Исполнитель, сроки и статус для мониторинга прогресса

---

## 5) Таблица `documents`

**Назначение**  
Хранит артефакты, формируемые агентами: резюме, research-отчёты, черновики публикаций.

### Поля

- `id UUID PRIMARY KEY`
- `project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE`
- `agent_name VARCHAR(64) NOT NULL`
- `doc_type VARCHAR(64) NOT NULL`
- `title TEXT NOT NULL`
- `content TEXT`
- `storage_url TEXT`
- `version INTEGER NOT NULL DEFAULT 1`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

### Что хранится и зачем

- Тип и автор артефакта (`doc_type`, `agent_name`)
- Текст содержимого (`content`) или ссылка на внешнее хранилище (`storage_url`)
- Версионирование документов (`version`)

---

## Связи между таблицами

- `projects (1) -> (N) applications`  
  Один проект может иметь несколько заявок/версий подачи.

- `projects (1) -> (N) agent_logs`  
  Каждый шаг агентов в рамках проекта логируется отдельно.

- `projects (1) -> (N) tasks`  
  У проекта множество задач, включая синхронизированные с Трекером.

- `projects (1) -> (N) documents`  
  По проекту хранится несколько документов разных типов и версий.

---

## Рекомендуемые индексы (для следующих миграций)

- `applications(project_id, status)`
- `agent_logs(project_id, correlation_id, created_at)`
- `tasks(project_id, status, due_date)`
- `tasks(tracker_issue_id)` (уникальность можно добавить при стабильной синхронизации)
- `documents(project_id, doc_type, version)`
