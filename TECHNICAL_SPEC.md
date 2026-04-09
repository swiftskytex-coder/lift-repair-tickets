# Технические требования - Система заявок на ремонт лифтов

## Дата документа: 09.04.2026

---

## 1. Общая архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                    Flask Server                         │
│                 http://localhost:8081                   │
│                      │                                │
│    ┌───────────────┬──┴────┬───────────────┐           │
│    │             │       │               │             │
│  Web UI      API        Webhook      Mobile API        │
│  (HTML)    (REST)     (Max)       (REST)           │
│    │             │       │               │             │
└────┼─────────────┼───────┼───────────────┼─────────────┘
     │             │       │               │
     ▼             ▼       ▼               ▼
┌─────────┐  ┌────────┐ ┌─────────┐  ┌──────────┐
│Browser  │  │Client  │ │Max Bot  │  │ Mobile  │
│        │  │(curl) │ │        │  │   App   │
└─────────┘  └────────┘ └─────────┘  └──────────┘
```

### Компоненты

| Компонент | Технология | Описание |
|----------|------------|----------|
| Backend | Python 3.13 + Flask 3.0 | HTTP сервер |
| Database | SQLite (WAL) | Хранение данных |
| Web UI | Bootstrap 5 + Jinja2 | Веб-интерфейс |
| Chat Bot | Max API | Мессенджер для механиков |
| Mobile API | REST JSON | Мобильные приложения |

---

## 2. Требования к серверу

### 2.1 Аппаратные требования

| Параметр | Минимум | Рекомендуется |
|----------|---------|--------------|
| CPU | 1 core | 2+ cores |
| RAM | 512 MB | 1 GB |
| Disk | 5 GB | 10+ GB |
| OS | macOS / Linux | Linux (Ubuntu 22.04) |

### 2.2 Программное обеспечение

- **Python:** 3.13+
- **Flask:** 3.0+
- **SQLite:** 3.x (встроен)
- **OpenSSL:** для HTTPS

### 2.3 Сетевые требования

| Параметр | Значение |
|----------|---------|
| Порт HTTP | 8081 |
| Порт HTTPS | 8443 (опционально) |
| Время зоны | UTC+4 (Самара) |
| Таймаут запроса | 30 сек |

### 2.4 Переменные окружения

```bash
# Max Bot
MAX_BOT_TOKEN=f9LHodD0cOJr6-3caEEtEU-KqU42RaPXLpz3wkHbJMQc0vANY8fVYJfXn0bsZh7IdSq0sNqBkyGwfySDPS8l
MAX_CONFIRMATION_CODE=confirmation_code

# Server
FLASK_ENV=production
SECRET_KEY=random_secret_key
```

---

## 3. База данных

### 3.1 Структура БД

**Файл:** `instance/tickets.db`

#### Таблицы

```sql
-- Основная таблица заявок
tickets (
    id INTEGER PRIMARY KEY,
    ticket_number TEXT UNIQUE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    source TEXT,           -- phone, mobile_app, web, operator
    
    -- Информация о клиенте
    client_name TEXT,
    client_phone TEXT,
    client_email TEXT,
    organization TEXT,
    
    -- Адрес и лифт
    address TEXT NOT NULL,
    elevator_id TEXT,
    elevator_type TEXT,
    
    -- Описание
    problem_description TEXT,
    priority TEXT DEFAULT 'обычный',  -- срочный, высокий, обычный, низкий
    
    -- Статус
    status TEXT DEFAULT 'новая',  -- новая, в работе, выполнена, отменена
    
    -- Назначение
    assigned_to TEXT,
    scheduled_date TIMESTAMP,
    
    -- История изменений (JSON)
    history TEXT DEFAULT '[]',
    
    -- Заметки оператора
    operator_notes TEXT,
    
    -- Время выполнения
    completed_at TIMESTAMP,
    
    -- Оценка
    rating INTEGER,  -- 1-5
    client_feedback TEXT
)

-- Лифты (объекты)
elevators (
    id INTEGER PRIMARY KEY,
    elevator_id TEXT UNIQUE,
    address TEXT NOT NULL,
    entrance TEXT,
    elevator_type TEXT DEFAULT 'пассажирский',
    mechanic TEXT,
    description TEXT,
    photo TEXT,
    entrance_photo TEXT,
    coordinates TEXT
)

-- Механики
mechanics (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    max_chat_id TEXT,
    max_username TEXT,
    status TEXT DEFAULT 'active'
)

-- Связь лифтов и механиков
elevator_mechanics (
    elevator_id TEXT,
    mechanic_id INTEGER,
    is_primary BOOLEAN DEFAULT 1,
    PRIMARY KEY (elevator_id, mechanic_id)
)

-- Аварийные дежурства
oncall_mechanics (
    id INTEGER PRIMARY KEY,
    mechanic_id INTEGER,
    date DATE UNIQUE
)

-- Отправка заявок механикам
ticket_mechanics (
    ticket_id INTEGER,
    mechanic_id INTEGER,
    sent_at TIMESTAMP,
    status TEXT DEFAULT 'sent',
    responded_at TIMESTAMP
)

-- Комментарии
comments (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER,
    author TEXT,
    text TEXT,
    created_at TIMESTAMP
)

-- Настройки системы
settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP
)

-- Отчёты о ремонте (База знаний)
repair_reports (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER,
    mechanic_id INTEGER,
    problem_description TEXT,
    work_done TEXT,
    parts_used TEXT,
    time_spent INTEGER,
    photos TEXT
)
```

### 3.2 Индексы

```sql
CREATE INDEX idx_tickets_status ON tickets(status);
CREATE INDEX idx_tickets_priority ON tickets(priority);
CREATE INDEX idx_tickets_created ON tickets(created_at);
CREATE INDEX idx_elevators_elevator_id ON elevators(elevator_id);
CREATE INDEX idx_elevators_address ON elevators(address);
```

### 3.3 Режим работы

| Параметр | Значение |
|----------|---------|
| Режим | WAL (Write-Ahead Logging) |
| Таймаут блокировки | 5 сек |
| Автовакуум | Включён |

---

## 4. API Endpoints

### 4.1 Основной API

| Метод | Путь | Описание | Тело запроса |
|-------|------|----------|--------------|
| GET | `/api/tickets` | Список заявок | - |
| POST | `/api/tickets` | Создать заявку | JSON |
| GET | `/api/tickets/<id>` | Детали заявки | - |
| PUT | `/api/tickets/<id>` | Обновить заявку | JSON |
| DELETE | `/api/tickets/<id>` | Удалить заявку | - |
| GET | `/api/elevators` | Список лифтов | - |
| POST | `/api/elevators` | Добавить лифт | JSON |
| PUT | `/api/elevators/<id>` | Обновить лифт | JSON |
| GET | `/api/mechanics` | Список механиков | - |
| POST | `/api/mechanics` | Добавить механика | JSON |
| PUT | `/api/mechanics/<id>` | Обновить механика | JSON |
| POST | `/api/oncall` | Назначить дежурного | JSON |
| POST | `/api/backup` | Создать бэкап | - |
| POST | `/api/backup/restore` | Восстановить | Form-data |
| GET | `/api/settings` | Получить настройки | - |
| POST | `/api/settings` | Сохранить настройки | JSON |

#### Примеры запросов

```bash
# Создать заявку
curl -X POST http://localhost:8081/api/tickets \
  -H "Content-Type: application/json" \
  -d '{
    "address": "ул. Ленина 10",
    "elevator_id": "Л1-01",
    "problem_description": "Лифт не работает",
    "priority": "обычный",
    "source": "web"
  }'

# Получить настройки
curl http://localhost:8081/api/settings

# Сохранить настройки
curl -X POST http://localhost:8081/api/settings \
  -H "Content-Type: application/json" \
  -d '{"notification_linear": "true", "notification_oncall": "true"}'
```

### 4.2 Мобильный API

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/mobile/tickets` | Создать заявку |
| GET | `/api/mobile/tickets/track` | Отслеживание |

### 4.3 Ответы API

#### Успешный ответ

```json
{
  "success": true,
  "data": { ... }
}
```

#### Ошибка

```json
{
  "success": false,
  "error": "Сообщение об ошибке"
}
```

---

## 5. Веб-интерфейс

### 5.1 Страницы

| Маршрут | Описание |
|---------|----------|
| `/` | Главная (дашборд) |
| `/tickets` | Список заявок |
| `/ticket/<id>` | Детали заявки |
| `/new-ticket` | Новая заявка |
| `/elevators` | Справочник лифтов |
| `/mechanics` | Справочник механиков |
| `/oncall` | Аварийные дежурства |
| `/settings` | Настройки уведомлений |
| `/help` | Справка |
| `/about` | О программе |

### 5.2 Frontend зависимости

```html
<!-- Bootstrap 5 -->
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">

<!-- Bootstrap Icons -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">

<!-- Bootstrap JS -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
```

### 5.3 Адаптивность

| Устройство | Ширина | Колонок |
|------------|--------|--------|
| Desktop | > 992px | 4 |
| Tablet | 768-992px | 2 |
| Mobile | < 768px | 1 |

### 5.4 Темы

- **Тёмная** (по умолчанию): `#0f1419`
- **Светлая**: `#ffffff`
- Переключение: кнопка в навбаре

---

## 6. Max Bot

### 6.1 Конфигурация

| Параметр | Значение |
|----------|---------|
| Bot URL | https://max.ru/id732606860856_bot |
| API Endpoint | https://platform-api.max.ru |
| Token | `f9LHodD0cOJr6-3caEEtEU-KqU42RaPXLpz3wkHbJMQc0vANY8fVYJfXn0bsZh7IdSq0sNqBkyGwfySDPS8l` |
| Webhook URL | https://tickets.lift-system.crazedns.ru/max/webhook |

### 6.2 Webhook события

| Событие | Описание |
|---------|----------|
| `confirmation` | Подтверждение вебхука |
| `message_created` | Новое сообщение от пользователя |
| `bot_started` | Пользователь запустил бота |
| `callback_query` | Нажатие на inline-кнопку |

### 6.3 API вызовы Max

#### Отправка сообщения

```python
POST https://platform-api.max.ru/messages?user_id={user_id}
Headers: Authorization: {token}

{
  "text": "Текст сообщения",
  "attachments": [
    {
      "type": "inline_keyboard",
      "payload": {
        "buttons": [
          [
            {
              "type": "callback",
              "text": "Кнопка",
              "payload": "action_123"
            }
          ]
        ]
      }
    }
  ]
}
```

#### Получение обновлений

```python
POST https://platform-api.max.ru/updates
Headers: Authorization: {token}

{
  "timeout": 30,
  "version": 1
}
```

### 6.4 Команды бота

| Команда | Описание |
|---------|----------|
| `+79991234567` | Регистрация по номеру телефона |
| Меню | Показать главное меню |
| Мои лифты | Список закреплённых лифтов |
| Мои заявки | Активные заявки |
| Помощь | Справка |
| Завершить заявку | Завершить работу |

### 6.5 Клавиатуры

#### Главное меню

```json
[
  [{"type": "callback", "text": "🛗 Мои лифты", "payload": "my_elevators"},
   {"type": "callback", "text": "📋 Мои заявки", "payload": "my_tickets"}],
  [{"type": "callback", "text": "❓ Помощь", "payload": "help"},
   {"type": "callback", "text": "✅ Завершить заявку", "payload": "complete_ticket"}]
]
```

#### Принять заявку

```json
[[{"type": "callback", "text": "✅ Принять в работу", "payload": "accept_123"}]
```

#### Завершить заявку

```json
[[{"type": "callback", "text": "✅ Завершить", "payload": "complete_123"}]
```

### 6.6 Логика работы

```
Пользователь → Бот → webhook → process_message/process_callback
                                        ↓
                        ┌────────────────────────────────────┐
                        │ Зарегистрирован?                │
                        └────────────────────────────────┘
                            ↓                  ↓
                           Да                 Нет
                            ↓             Запросить телефон
                    ┌─────────────┐
                    │ Показать   │
                    │ меню       │
                    └─────────────┘
```

### 6.7 Обработка ошибок

| Ошибка | Действие |
|-------|----------|
| Пользователь не найден | Запросить телефон |
| Заявка не найдена | Показать сообщение об ошибке |
| Заявка уже назначена | Показать "уже назначена" |
| Заявка не в работе | Показать "примите сначала" |

---

## 7. Уведомления

### 7.1 Настройки уведомлений

| Ключ | Тип | По умолчанию | Описание |
|------|-----|-------------|----------|
| `notification_linear` | boolean | true | Отправлять линейному |
| `notification_oncall` | boolean | true | Отправлять аварийному |

### 7.2 Условия отправки

#### Линейный механик

| Условие | Значение |
|---------|----------|
| notification_linear | true |
| Рабочее время | 08:00-17:00 |
| Рабочие дни | Пн-Пт |

#### Аварийный механик

| Условие | Значение |
|---------|----------|
| notification_oncall | true |
| Приоритет | Не "низкий" |
| Время | Любое |
| День | Любой |

### 7.3 Формат сообщения

```
🔔 Новая заявка #20260409-0001

📍 ул. Ленина 10, подъезд 1
📝 Не работает кнопка вызова
⚡ Приоритет: 🔵 Обычный
```

---

## 8. Логирование

### 8.1 Уровни логирования

| Уровень | Использование |
|---------|---------------|
| DEBUG | Отладка (только локально) |
| INFO | Основные события |
| WARNING | Не критичные ошибки |
| ERROR | Ошибки выполнения |

### 8.2 Файлы логов

| Файл | Описание |
|------|----------|
| `server.log` | Основной лог сервера |
| Max webhook | stdout процесса |

---

## 9. Безопасность

### 9.1 Требования

- [x] Токен бота хранится в переменных окружения
- [x] CORS ограничен
- [x] Таймаут запросов 30 сек
- [x] Лимиты на загрузку файлов

### 9.2 Защита от атак

- SQL инъекции: используется параметризованные запросы
- XSS: экранирование вывода в Jinja2
- CSRF: токены в формах

---

## 10. Развёртывание

### 10.1 Команды запуска

```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск сервера
python ticket_system.py

# Запуск с прокси
gunicorn -w 4 -b 0.0.0.0:8081 ticket_system:app
```

### 10.2 Проверка работоспособности

```bash
# Health check
curl http://localhost:8081/api/health

# Ответ
{"status": "ok", "time": "2026-04-09 12:00:00"}
```

---

## 11. Зависимости (requirements.txt)

```
flask>=3.0.0
Pillow>=10.0.0
requests>=2.31.0
gunicorn>=21.0.0
python-dotenv>=1.0.0
```

---

## 12. Тестирование

### 12.1 Ручное тестирование

| Тест | Ожидаемый результат |
|------|-------------------|
| Создание заявки | Заявка в БД, уведомление mechanic |
| Принятие заявки | Статус "в работе" |
| Завершение заявки | Статус "выполнена" |
| Настройки уведомлений | Переключатель работает |
| Регистрация бота | Max ID привязан |

### 12.2 Автоматические тесты

```bash
# Запустить тесты
pytest tests/

# Покрытие
pytest --cov=ticket_system tests/
```

---

## 13. Мониторинг

### 13.1 Метрики

| Метрика | Описание |
|---------|----------|
| Время отклика | /api/health |
| Количество заявок | stats.total |
| Активные заявки | stats.in_progress |
| Ошибки | Лог сервера |

### 13.2 Alerts

| Условие | Действие |
|---------|----------|
| Сервер недоступен | Email/SMS |
| Ошибка отправки | Лог |
| Диск > 90% | Email |

---

## 14. Резервное копирование

### 14.1手动备份

```
Меню → Сделать бэкап
→ ZIP: database + uploads/
```

### 14.2 Восстановление

```
Меню → Восстановить из бэкапа
→ Выбрать файл
→ Подтвердить
```

---

## 15. Версионирование

### 15.1 Нумерация версий

Формат: `MAJOR.MINOR.PATCH`

| Компонент | Описание |
|----------|----------|
| MAJOR | Несовместимые изменения API |
| MINOR | Новый функционал |
| PATCH | Исправления багов |

### 15.2 Текущая версия

```
Версия: 3.0
Дата: 09.04.2026
Git: rollback-v3.0
```

---

## 16. Контакты поддержки

| Канал | Контакт |
|-------|---------|
| Email | support@lift-system.ru |
| Telegram | @admin |
| Телефон | +7 xxx xxx xx xx |

---

## 17. Приложения

### 17.1 Структура проекта

```
lift-repair-tickets/
├── ticket_system.py      # Flask приложение
├── ticket_db.py         # База данных
├── max_bot.py          # Max бот
├── notification_service.py  # Уведомления
├── dev_runner.py       # Запуск
├── WEB_INTERFACE.md  # Документация интерфейса
├── requirements.txt  # Зависимости
├── templates/       # HTML шаблоны
├── static/         # Статические файлы
├── uploads/       # Загруженные файлы
└── instance/     # База данных
```

### 17.2 Технологический стек

| Компонент | Технология |
|----------|------------|
| Backend | Python 3.13, Flask 3.0 |
| Database | SQLite 3 |
| Web | Bootstrap 5, Jinja2 |
| Bot | Max API (VK API) |
| Images | Pillow |
| HTTP | Requests |