# Lift Repair Ticket System - Mobile API Documentation

## Базовый URL
```
http://localhost:8081
```

## Аутентификация
В текущей версии API работает без аутентификации. В продакшене рекомендуется добавить:
- API ключи в заголовках
- JWT токены
- Rate limiting

## Endpoints

### 1. Создание заявки (Mobile)

**POST** `/api/mobile/tickets`

Создание новой заявки из мобильного приложения.

#### Request Body
```json
{
  "client_name": "string",          // Обязательное. ФИО клиента
  "client_phone": "string",         // Обязательное. Телефон
  "client_email": "string",         // Опционально. Email
  "organization": "string",         // Опционально. Организация
  "address": "string",              // Обязательное. Адрес
  "elevator_id": "string",          // Опционально. ID лифта
  "elevator_type": "string",        // Опционально. Тип лифта
  "problem_description": "string",  // Обязательное. Описание проблемы
  "priority": "string"              // Опционально. Приоритет (срочный, высокий, обычный, низкий)
}
```

#### Response 201
```json
{
  "success": true,
  "message": "Заявка успешно создана",
  "ticket": {
    "id": 1,
    "ticket_number": "20250211-0001",
    "status": "новая",
    "priority": "обычный",
    "client_name": "...",
    "client_phone": "...",
    "address": "...",
    "problem_description": "...",
    "created_at": "2025-02-11T10:30:00"
  }
}
```

### 2. Отслеживание заявок по телефону

**GET** `/api/mobile/tickets/track?phone={phone_number}`

Получение списка заявок клиента по номеру телефона.

#### Query Parameters
- `phone` (required): Номер телефона клиента

#### Response 200
```json
{
  "success": true,
  "phone": "+7 999 123-45-67",
  "count": 3,
  "tickets": [
    {
      "id": 1,
      "ticket_number": "20250211-0001",
      "status": "в работе",
      "priority": "высокий",
      "client_name": "Иванов Иван",
      "address": "ул. Ленина, д. 1",
      "problem_description": "...",
      "created_at": "2025-02-11T10:30:00"
    }
  ]
}
```

### 3. Получение деталей заявки

**GET** `/api/tickets/{ticket_id}`

Полная информация о заявке.

#### Response 200
```json
{
  "success": true,
  "ticket": {
    "id": 1,
    "ticket_number": "20250211-0001",
    "status": "новая",
    "priority": "обычный",
    "client_name": "Иванов Иван",
    "client_phone": "+7 999 123-45-67",
    "client_email": "ivan@example.com",
    "organization": "ООО УК",
    "address": "г. Москва, ул. Ленина, д. 1",
    "elevator_id": "Лифт-001",
    "elevator_type": "пассажирский",
    "problem_description": "Не работает кнопка",
    "operator_notes": "...",
    "created_at": "2025-02-11T10:30:00",
    "comments": []
  }
}
```

### 4. Получение статистики

**GET** `/api/stats`

Статистика по заявкам для дашборда.

#### Response 200
```json
{
  "success": true,
  "statistics": {
    "total": 150,
    "new": 12,
    "in_progress": 8,
    "completed": 130,
    "by_priority": {
      "срочный": 5,
      "высокий": 15,
      "обычный": 100,
      "низкий": 30
    },
    "by_source": {
      "phone": 80,
      "mobile_app": 40,
      "operator": 30
    }
  }
}
```

### 5. Список заявок с фильтрами

**GET** `/api/tickets?status={status}&priority={priority}&limit={limit}&offset={offset}`

Получение списка заявок с возможностью фильтрации.

#### Query Parameters
- `status` (optional): Фильтр по статусу (новая, в работе, выполнена, отменена)
- `priority` (optional): Фильтр по приоритету
- `client_phone` (optional): Поиск по телефону
- `client_name` (optional): Поиск по имени
- `address` (optional): Поиск по адресу
- `limit` (optional): Количество результатов (default: 50)
- `offset` (optional): Смещение для пагинации (default: 0)

## Примеры использования

### JavaScript/TypeScript (React Native)

```typescript
// Создание заявки
const createTicket = async (ticketData: TicketData) => {
  const response = await fetch('http://localhost:8081/api/mobile/tickets', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(ticketData),
  });
  
  return response.json();
};

// Отслеживание заявок
const trackTickets = async (phone: string) => {
  const response = await fetch(
    `http://localhost:8081/api/mobile/tickets/track?phone=${encodeURIComponent(phone)}`
  );
  
  return response.json();
};
```

### Python

```python
import requests

# Создание заявки
response = requests.post(
    'http://localhost:8081/api/mobile/tickets',
    json={
        'client_name': 'Иванов Иван',
        'client_phone': '+7 999 123-45-67',
        'address': 'ул. Ленина, д. 1',
        'problem_description': 'Не работает лифт'
    }
)

result = response.json()
print(f"Номер заявки: {result['ticket']['ticket_number']}")
```

### cURL

```bash
# Создание заявки
curl -X POST http://localhost:8081/api/mobile/tickets \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "Иванов Иван",
    "client_phone": "+7 999 123-45-67",
    "address": "ул. Ленина, д. 1",
    "problem_description": "Не работает кнопка вызова",
    "priority": "высокий"
  }'

# Отслеживание
curl "http://localhost:8081/api/mobile/tickets/track?phone=%2B7%20999%20123-45-67"
```

## Коды ошибок

- `400` - Bad Request (некорректные данные)
- `404` - Not Found (заявка не найдена)
- `500` - Internal Server Error

## Форматы данных

### Приоритеты
- `срочный` - Опасно для жизни
- `высокий` - Не работает лифт
- `обычный` - Неисправность (по умолчанию)
- `низкий` - Плановое обслуживание

### Статусы
- `новая` - Только создана
- `в работе` - Принята в работу
- `выполнена` - Ремонт завершен
- `отменена` - Отменена

### Типы лифтов
- `пассажирский`
- `грузовой`
- `больничный`
- `подъёмник`

## Интеграция с MCP

Для интеграции с ИИ через MCP:

1. MCP сервер запускается отдельно: `python mcp_server.py`
2. ИИ-агент подключается к MCP серверу
3. ИИ может создавать, искать и обновлять заявки

Примеры MCP команд:
- `create_ticket` - создание заявки
- `search_tickets` - поиск
- `get_statistics` - статистика
- `update_ticket_status` - обновление статуса
