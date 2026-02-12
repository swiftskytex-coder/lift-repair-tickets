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
                    text=f"✅ Статус заявки #{ticket['ticket_number']} обновлён на: {new_status}"
                )]
            else:
                return [TextContent(
                    type="text",
                    text=f"❌ Заявка с ID {ticket_id} не найдена"
                )]
        
        elif name == "get_statistics":
            # Получение статистики
            stats = db.get_statistics()
            
            text = f"📊 Статистика заявок\n{'='*50}\n\n" + \
                   f"Всего заявок: {stats['total']}\n" + \
                   f"Новых: {stats['new']}\n" + \
                   f"В работе: {stats['in_progress']}\n" + \
                   f"Выполнено: {stats['completed']}\n\n" + \
                   f"По приоритетам:\n"
            
            for priority, count in stats['by_priority'].items():
                text += f"  • {priority}: {count}\n"
            
            text += f"\nПо источникам:\n"
            for source, count in stats['by_source'].items():
                text += f"  • {source}: {count}\n"
            
            return [TextContent(type="text", text=text)]
        
        elif name == "add_comment":
            # Добавление комментария
            ticket_id = arguments["ticket_id"]
            text = arguments["text"]
            author = arguments.get("author", "AI Assistant")
            
            ticket = db.get_ticket(ticket_id)
            if not ticket:
                return [TextContent(
                    type="text",
                    text=f"❌ Заявка с ID {ticket_id} не найдена"
                )]
            
            comment_id = db.add_comment(ticket_id, author, text)
            
            return [TextContent(
                type="text",
                text=f"✅ Комментарий добавлен к заявке #{ticket['ticket_number']}"
            )]
        
        elif name == "assign_ticket":
            # Назначение исполнителя
            ticket_id = arguments["ticket_id"]
            assigned_to = arguments["assigned_to"]
            scheduled_date = arguments.get("scheduled_date")
            
            ticket = db.get_ticket(ticket_id)
            if not ticket:
                return [TextContent(
                    type="text",
                    text=f"❌ Заявка с ID {ticket_id} не найдена"
                )]
            
            update_data = {
                "assigned_to": assigned_to
            }
            if scheduled_date:
                update_data["scheduled_date"] = scheduled_date
            
            db.update_ticket(ticket_id, update_data, "AI Assistant")
            
            text = f"✅ Заявка #{ticket['ticket_number']} назначена на: {assigned_to}"
            if scheduled_date:
                text += f"\n📅 Запланировано на: {scheduled_date}"
            
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
