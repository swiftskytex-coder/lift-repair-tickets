"""
MCP Сервер для системы заявок на ремонт лифтов
Model Context Protocol server for AI integration
"""

import json
import sys
import asyncio
from typing import Any
from contextlib import asynccontextmanager
from datetime import datetime
from ticket_db import db

# Импорты MCP SDK
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        Resource,
        Tool,
        TextContent,
        ErrorData,
        INTERNAL_ERROR,
        INVALID_PARAMS
    )
except ImportError:
    print("❌ MCP SDK не установлен. Установите: pip install mcp", file=sys.stderr)
    sys.exit(1)


# Создание MCP сервера
app = Server("lift-repair-tickets")


# ═══════════════════════════════════════════════════════════════
# Ресурсы (данные, доступные ИИ)
# ═══════════════════════════════════════════════════════════════

@app.list_resources()
async def list_resources() -> list[Resource]:
    """Список доступных ресурсов"""
    return [
        Resource(
            uri="tickets://statistics",
            name="Статистика заявок",
            description="Общая статистика по заявкам на ремонт",
            mimeType="application/json"
        ),
        Resource(
            uri="tickets://schema",
            name="Схема базы данных",
            description="Структура таблиц базы данных заявок",
            mimeType="application/json"
        ),
        Resource(
            uri="tickets://new",
            name="Новые заявки",
            description="Список новых заявок",
            mimeType="application/json"
        ),
        Resource(
            uri="tickets://urgent",
            name="Срочные заявки",
            description="Список срочных заявок",
            mimeType="application/json"
        ),
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    """Чтение ресурса"""
    
    if uri == "tickets://statistics":
        stats = db.get_statistics()
        return json.dumps(stats, ensure_ascii=False, indent=2)
    
    elif uri == "tickets://schema":
        schema = {
            "tables": {
                "tickets": {
                    "description": "Основная таблица заявок на ремонт",
                    "fields": {
                        "id": "INTEGER PRIMARY KEY - Уникальный ID заявки",
                        "ticket_number": "TEXT - Номер заявки (формат: YYYYMMDD-XXXX)",
                        "created_at": "TIMESTAMP - Дата создания",
                        "source": "TEXT - Источник (phone, mobile_app, operator)",
                        "client_name": "TEXT - ФИО клиента",
                        "client_phone": "TEXT - Телефон клиента",
                        "address": "TEXT - Адрес",
                        "elevator_id": "TEXT - ID лифта",
                        "problem_description": "TEXT - Описание проблемы",
                        "priority": "TEXT - Приоритет (срочный, высокий, обычный, низкий)",
                        "status": "TEXT - Статус (новая, в работе, выполнена, отменена)",
                        "assigned_to": "TEXT - Назначенный исполнитель",
                        "operator_notes": "TEXT - Заметки оператора"
                    }
                }
            }
        }
        return json.dumps(schema, ensure_ascii=False, indent=2)
    
    elif uri == "tickets://new":
        tickets = db.search_tickets(filters={"status": "новая"}, limit=50)
        return json.dumps(tickets, ensure_ascii=False, indent=2, default=str)
    
    elif uri == "tickets://urgent":
        tickets = db.search_tickets(filters={"priority": "срочный"}, limit=50)
        return json.dumps(tickets, ensure_ascii=False, indent=2, default=str)
    
    else:
        raise ValueError(f"Неизвестный ресурс: {uri}")


# ═══════════════════════════════════════════════════════════════
# Инструменты (функции, которые может вызывать ИИ)
# ═══════════════════════════════════════════════════════════════

@app.list_tools()
async def list_tools() -> list[Tool]:
    """Список доступных инструментов"""
    return [
        Tool(
            name="create_ticket",
            description="Создание новой заявки на ремонт лифтового оборудования",
            inputSchema={
                "type": "object",
                "properties": {
                    "client_name": {
                        "type": "string",
                        "description": "ФИО клиента"
                    },
                    "client_phone": {
                        "type": "string",
                        "description": "Номер телефона клиента"
                    },
                    "address": {
                        "type": "string",
                        "description": "Адрес объекта с лифтом"
                    },
                    "problem_description": {
                        "type": "string",
                        "description": "Описание проблемы"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["срочный", "высокий", "обычный", "низкий"],
                        "description": "Приоритет заявки",
                        "default": "обычный"
                    },
                    "elevator_id": {
                        "type": "string",
                        "description": "Идентификатор лифта (опционально)"
                    },
                    "client_email": {
                        "type": "string",
                        "description": "Email клиента (опционально)"
                    },
                    "organization": {
                        "type": "string",
                        "description": "Название организации (опционально)"
                    },
                    "operator_notes": {
                        "type": "string",
                        "description": "Заметки оператора (опционально)"
                    }
                },
                "required": ["client_name", "client_phone", "address", "problem_description"]
            }
        ),
        
        Tool(
            name="get_ticket",
            description="Получение информации о заявке по ID или номеру",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "ID заявки в базе данных"
                    },
                    "ticket_number": {
                        "type": "string",
                        "description": "Номер заявки (формат: YYYYMMDD-XXXX)"
                    }
                },
                "oneOf": [
                    {"required": ["ticket_id"]},
                    {"required": ["ticket_number"]}
                ]
            }
        ),
        
        Tool(
            name="search_tickets",
            description="Поиск заявок по различным критериям",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["новая", "в работе", "выполнена", "отменена"],
                        "description": "Фильтр по статусу"
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["срочный", "высокий", "обычный", "низкий"],
                        "description": "Фильтр по приоритету"
                    },
                    "client_phone": {
                        "type": "string",
                        "description": "Поиск по номеру телефона клиента"
                    },
                    "client_name": {
                        "type": "string",
                        "description": "Поиск по имени клиента"
                    },
                    "address": {
                        "type": "string",
                        "description": "Поиск по адресу"
                    },
                    "elevator_id": {
                        "type": "string",
                        "description": "Поиск по ID лифта"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Максимальное количество результатов",
                        "default": 50
                    }
                }
            }
        ),
        
        Tool(
            name="update_ticket_status",
            description="Изменение статуса заявки",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "ID заявки"
                    },
                    "new_status": {
                        "type": "string",
                        "enum": ["новая", "в работе", "выполнена", "отменена"],
                        "description": "Новый статус заявки"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Примечания к изменению статуса (опционально)"
                    }
                },
                "required": ["ticket_id", "new_status"]
            }
        ),
        
        Tool(
            name="get_statistics",
            description="Получение статистики по заявкам",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        
        Tool(
            name="add_comment",
            description="Добавление комментария к заявке",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "ID заявки"
                    },
                    "text": {
                        "type": "string",
                        "description": "Текст комментария"
                    },
                    "author": {
                        "type": "string",
                        "description": "Автор комментария",
                        "default": "AI Assistant"
                    }
                },
                "required": ["ticket_id", "text"]
            }
        ),
        
        Tool(
            name="assign_ticket",
            description="Назначение исполнителя на заявку",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "ID заявки"
                    },
                    "assigned_to": {
                        "type": "string",
                        "description": "Имя или ID исполнителя"
                    },
                    "scheduled_date": {
                        "type": "string",
                        "description": "Запланированная дата выполнения (формат: YYYY-MM-DD HH:MM)"
                    }
                },
                "required": ["ticket_id", "assigned_to"]
            }
        ),
        
        # Инструменты для механика
        Tool(
            name="get_mechanic_tickets",
            description="Получить заявки механика по номеру телефона",
            inputSchema={
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Номер телефона механика (например: +79001234567)"
                    }
                },
                "required": ["phone"]
            }
        ),
        
        Tool(
            name="accept_ticket",
            description="Принять заявку в работу (для механика)",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "ID заявки"
                    },
                    "phone": {
                        "type": "string",
                        "description": "Номер телефона механика"
                    }
                },
                "required": ["ticket_id", "phone"]
            }
        ),
        
        Tool(
            name="complete_ticket",
            description="Завершить заявку (для механика)",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "ID заявки"
                    },
                    "phone": {
                        "type": "string",
                        "description": "Номер телефона механика"
                    },
                    "work_done": {
                        "type": "string",
                        "description": "Описание выполненных работ"
                    }
                },
                "required": ["ticket_id", "phone"]
            }
        ),
        
        Tool(
            name="get_mechanic_info",
            description="Получить информацию о механике по телефону",
            inputSchema={
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Номер телефона"
                    }
                },
                "required": ["phone"]
            }
        ),
        
        Tool(
            name="get_mechanic_elevators",
            description="Получить лифты закрепленные за механиком",
            inputSchema={
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Номер телефона механика"
                    }
                },
                "required": ["phone"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Вызов инструмента"""
    
    try:
        if name == "create_ticket":
            # Создание заявки
            data = {
                **arguments,
                "source": "ai_agent",
                "operator": "AI Assistant"
            }
            ticket = db.create_ticket(data)
            
            return [TextContent(
                type="text",
                text=f"✅ Заявка успешно создана!\n\n" +
                     f"Номер: #{ticket['ticket_number']}\n" +
                     f"Клиент: {ticket['client_name']}\n" +
                     f"Телефон: {ticket['client_phone']}\n" +
                     f"Адрес: {ticket['address']}\n" +
                     f"Приоритет: {ticket['priority']}\n" +
                     f"Статус: {ticket['status']}\n\n" +
                     f"ID заявки: {ticket['id']}"
            )]
        
        elif name == "get_ticket":
            # Получение заявки
            ticket_id = arguments.get("ticket_id")
            ticket_number = arguments.get("ticket_number")
            
            if ticket_id:
                ticket = db.get_ticket(ticket_id)
            elif ticket_number:
                ticket = db.get_ticket_by_number(ticket_number)
            else:
                raise ValueError("Необходимо указать ticket_id или ticket_number")
            
            if not ticket:
                return [TextContent(
                    type="text",
                    text=f"❌ Заявка не найдена"
                )]
            
            comments = db.get_comments(ticket['id'])
            
            text = f"📝 Заявка #{ticket['ticket_number']}\n" + \
                   f"{'='*50}\n\n" + \
                   f"📅 Создана: {ticket['created_at']}\n" + \
                   f"📊 Статус: {ticket['status']}\n" + \
                   f"⚡ Приоритет: {ticket['priority']}\n\n" + \
                   f"👤 Клиент: {ticket['client_name']}\n" + \
                   f"📞 Телефон: {ticket['client_phone']}\n" + \
                   f"📧 Email: {ticket.get('client_email', 'не указан')}\n" + \
                   f"🏢 Организация: {ticket.get('organization', 'не указана')}\n\n" + \
                   f"📍 Адрес: {ticket['address']}\n" + \
                   f"🛗 Лифт: {ticket.get('elevator_id', 'не указан')} ({ticket.get('elevator_type', 'тип не указан')})\n\n" + \
                   f"🔧 Проблема:\n{ticket['problem_description']}\n\n"
            
            if comments:
                text += f"💬 Комментарии ({len(comments)}):\n"
                for comment in comments:
                    text += f"  • {comment['author']} ({comment['created_at'][:16]}): {comment['text']}\n"
            
            if ticket.get('operator_notes'):
                text += f"\n📝 Заметки оператора:\n{ticket['operator_notes']}\n"
            
            return [TextContent(type="text", text=text)]
        
        elif name == "search_tickets":
            # Поиск заявок
            filters = {}
            limit = arguments.pop("limit", 50)
            
            if "status" in arguments and arguments["status"]:
                filters["status"] = arguments["status"]
            if "priority" in arguments and arguments["priority"]:
                filters["priority"] = arguments["priority"]
            if "client_phone" in arguments and arguments["client_phone"]:
                filters["client_phone"] = arguments["client_phone"]
            if "client_name" in arguments and arguments["client_name"]:
                filters["client_name"] = arguments["client_name"]
            if "address" in arguments and arguments["address"]:
                filters["address"] = arguments["address"]
            if "elevator_id" in arguments and arguments["elevator_id"]:
                filters["elevator_id"] = arguments["elevator_id"]
            
            tickets = db.search_tickets(filters=filters if filters else None, limit=limit)
            
            if not tickets:
                return [TextContent(
                    type="text",
                    text="🔍 Заявки не найдены по указанным критериям"
                )]
            
            text = f"🔍 Найдено заявок: {len(tickets)}\n{'='*50}\n\n"
            
            for ticket in tickets:
                text += f"#{ticket['ticket_number']} | {ticket['status']} | {ticket['priority']}\n"
                text += f"  Клиент: {ticket['client_name']}\n"
                text += f"  Адрес: {ticket['address'][:50]}...\n"
                text += f"  ID: {ticket['id']}\n\n"
            
            return [TextContent(type="text", text=text)]
        
        elif name == "update_ticket_status":
            # Обновление статуса
            ticket_id = arguments["ticket_id"]
            new_status = arguments["new_status"]
            notes = arguments.get("notes", "")
            
            ticket = db.update_ticket_status(ticket_id, new_status, "AI Assistant", notes)
            
            if ticket:
return [TextContent(
                type="text",
                text=f"✅ Заявка #{ticket['ticket_number']} назначена на: {assigned_to}"
            )]
        
        # ==== Инструменты для механика ====
        elif name == "get_mechanic_tickets":
            # Получить заявки механика
            phone = arguments["phone"]
            mechanic = db.get_mechanic_by_phone(phone)
            
            if not mechanic:
                return [TextContent(
                    type="text",
                    text=f"❌ Механик с телефоном {phone} не найден"
                )]
            
            tickets = db.get_all_mechanic_tickets(mechanic['id'])
            
            text = f"🛠️ Заявки механика: {mechanic['name']}\n{'='*50}\n\n"
            
            active = [t for t in tickets if t.get('status') in ('новая', 'в работе')]
            if active:
                text += f"🔴 Активных: {len(active)}\n"
                for t in active:
                    text += f"  #{t['ticket_number']} | {t['status']} | {t['address'][:40]}\n"
                text += "\n"
            
            completed = [t for t in tickets if t.get('status') == 'выполнена']
            if completed:
                text += f"✅ Выполнено: {len(completed)}"
            
            return [TextContent(type="text", text=text if text else "Заявок нет")]
        
        elif name == "accept_ticket":
            # Принять заявку
            ticket_id = arguments["ticket_id"]
            phone = arguments["phone"]
            mechanic = db.get_mechanic_by_phone(phone)
            
            if not mechanic:
                return [TextContent(
                    type="text",
                    text=f"❌ Механик не найден"
                )]
            
            ticket = db.get_ticket(ticket_id)
            if not ticket:
                return [TextContent(
                    type="text",
                    text=f"❌ Заявка не найдена"
                )]
            
            db.update_ticket_status(ticket_id, 'в работе', f'max_bot (принял {mechanic["name"]})')
            db.assign_ticket(ticket_id, mechanic['id'])
            
            return [TextContent(
                type="text",
                text=f"✅ Заявка #{ticket['ticket_number']} принята в работу!\n\n📍 {ticket['address']}\n📝 {ticket['problem_description'][:100]}..."
            )]
        
        elif name == "complete_ticket":
            # Завершить заявку
            ticket_id = arguments["ticket_id"]
            phone = arguments["phone"]
            work_done = arguments.get("work_done", "")
            mechanic = db.get_mechanic_by_phone(phone)
            
            if not mechanic:
                return [TextContent(
                    type="text",
                    text=f"❌ Механик не найден"
                )]
            
            ticket = db.get_ticket(ticket_id)
            if not ticket:
                return [TextContent(
                    type="text",
                    text=f"❌ Заявка не найдена"
                )]
            
            db.update_ticket_status(ticket_id, 'выполнена', f'max_bot (завершил {mechanic["name"]})')
            
            if work_done:
                db.add_comment(ticket_id, 'mechanic', f'📝 {work_done}')
            
            return [TextContent(
                type="text",
                text=f"✅ Заявка #{ticket['ticket_number']} завершена!"
            )]
        
        elif name == "get_mechanic_info":
            # Информация о механике
            phone = arguments["phone"]
            mechanic = db.get_mechanic_by_phone(phone)
            
            if not mechanic:
                return [TextContent(
                    type="text",
                    text=f"❌ Механик не найден"
                )]
            
            text = f"🛠️ Механик: {mechanic['name']}\n" + \
                  f"📞 Телефон: {mechanic['phone']}\n" + \
                  f"✅ Статус: {mechanic['status']}\n" + \
                  f"🆔 ID: {mechanic['id']}"
            
            return [TextContent(type="text", text=text)]
        
        elif name == "get_mechanic_elevators":
            # Лифты механика
            phone = arguments["phone"]
            mechanic = db.get_mechanic_by_phone(phone)
            
            if not mechanic:
                return [TextContent(
                    type="text",
                    text=f"❌ Механик не найден"
                )]
            
            elevators = db.get_mechanic_elevators(mechanic['id'])
            
            text = f"🛗 Лифты механика {mechanic['name']}\n{'='*50}\n\n"
            
            for e in elevators:
                text += f"• {e['elevator_id']}: {e['address']}\n"
            
            if not elevators:
                text += "Лифтов не закреплено"
            
            return [TextContent(type="text", text=text)]
        
        else:
            raise ValueError(f"Неизвестный инструмент: {name}")
    
    except Exception as e:
        return [TextContent(
            type="text",
            text=f"❌ Ошибка: {str(e)}"
        )]


# ═══════════════════════════════════════════════════════════════
# Запуск сервера
# ═══════════════════════════════════════════════════════════════

async def main():
    """Главная функция запуска MCP сервера"""
    print("🚀 Запуск MCP сервера системы заявок на ремонт лифтов", file=sys.stderr)
    print("="*60, file=sys.stderr)
    print("📡 Протокол: stdio", file=sys.stderr)
    print("🛠️  Сервер: lift-repair-tickets", file=sys.stderr)
    print("="*60, file=sys.stderr)
    
    async with stdio_server(server=app) as streams:
        await app.run(
            streams[0],
            streams[1],
            app.create_initialization_options()
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 MCP сервер остановлен", file=sys.stderr)
    except Exception as e:
        print(f"\n❌ Ошибка: {e}", file=sys.stderr)
        sys.exit(1)
