# 🚀 ЗАПУСК ПОСЛЕ ПЕРЕЗАГРУЗКИ

**Команды для запуска и остановки:**

```bash
# Остановка всех процессов
pkill -f "python.*ticket_system"
pkill -f "python.*telegram_bot"
pkill -f "python.*dev_runner"

# Запуск
cd /Users/swiftpanaev/KIRO/test4
source venv/bin/activate
python3 dev_runner.py
```

**После запуска:**
- Веб-интерфейс: http://localhost:8081
- Telegram бот: найдите своего бота в Telegram и отправьте /start

**Горячая перезагрузка:**
`dev_runner.py` автоматически перезапускает Flask и бота при изменении `.py` или `.html` файлов.

---

# 🛠️ Система заявок на ремонт лифтового оборудования

Интеллектуальная система управления заявками на ремонт с MCP сервером для интеграции с ИИ.

## ✨ Возможности

### 📞 Приём заявок
- **Веб-интерфейс оператора** — для приёма заявок по телефону
- **Внешний API** — для создания заявок с мобильных устройств
- **Автоматическая регистрация** — дата, время, источник заявки

### 🤖 MCP Сервер
- **Интеграция с ИИ** — стандартизированный протокол MCP
- **Доступ к данным** — заявки, клиенты, история ремонтов
- **Инструменты** — создание, обновление, поиск заявок

### 📊 Управление
- **Статусы заявок** — новая, в работе, выполнена, отменена
- **Приоритеты** — срочный, высокий, обычный, низкий
- **История** — полный журнал изменений

## 🚀 Быстрый старт

### 1. Установка

```bash
# Клонирование
cd lift-repair-system

# Виртуальное окружение
python -m venv venv
source venv/bin/activate

# Зависимости
pip install -r requirements.txt
```

### 2. Запуск

```bash
# Запуск веб-сервера заявок
python ticket_system.py

# Запуск MCP сервера (в отдельном терминале)
python mcp_server.py
```

### 3. Доступ

- **Веб-интерфейс оператора**: http://localhost:8081
- **API документация**: http://localhost:8081/api/docs
- **MCP сервер**: stdio transport

## 📱 API для внешних заявок

### Создание заявки (мобильное приложение)

```bash
curl -X POST http://localhost:8081/api/tickets \
  -H "Content-Type: application/json" \
  -d '{
    "source": "mobile_app",
    "client_name": "Иванов Иван",
    "client_phone": "+7 999 123-45-67",
    "address": "ул. Ленина, д. 1, кв. 10",
    "elevator_id": "Лифт-001",
    "problem_description": "Не работает кнопка вызова",
    "priority": "высокий"
  }'
```

### Получение списка заявок

```bash
curl http://localhost:8081/api/tickets
```

### Обновление статуса

```bash
curl -X PUT http://localhost:8081/api/tickets/123/status \
  -H "Content-Type: application/json" \
  -d '{"status": "в работе"}'
```

## 🔧 MCP Инструменты

Сервер предоставляет следующие инструменты для ИИ:

### `create_ticket`
Создание новой заявки на ремонт

### `get_ticket`
Получение информации о заявке

### `search_tickets`
Поиск заявок по критериям

### `update_ticket_status`
Обновление статуса заявки

### `get_statistics`
Статистика заявок

## 📁 Структура проекта

```
lift-repair-system/
├── ticket_system.py       # Главный Flask сервер
├── ticket_db.py          # База данных SQLite
├── mcp_server.py         # MCP сервер для ИИ
├── mcp_tools.py          # MCP инструменты
├── templates/
│   └── operator_dashboard.html  # Интерфейс оператора
├── static/
│   └── style.css         # Стили
├── requirements.txt      # Зависимости
└── README.md            # Документация
```

## 🛠️ Технологии

- **Flask** — веб-фреймворк
- **SQLite** — база данных
- **MCP SDK** — протокол для ИИ
- **Bootstrap** — UI компоненты

## 📞 Контакты

Для вопросов и поддержки создавайте Issues в репозитории.
