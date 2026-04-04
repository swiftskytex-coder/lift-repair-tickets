"""
Max Bot для механиков
Отправляет заявки и принимает отчеты с фото
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

import os
import json
import requests
from datetime import datetime
from PIL import Image
from io import BytesIO
from ticket_db import db

MAX_API_URL = 'https://platform-api.max.ru'
MAX_BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', '')


def max_api(method, params=None):
    """Вызов Max API"""
    if params is None:
        params = {}
    headers = {'Authorization': MAX_BOT_TOKEN}
    try:
        response = requests.post(
            f"{MAX_API_URL}/{method}",
            headers=headers,
            json=params,
            timeout=10
        )
        return response.json()
    except Exception as e:
        print(f"Max API error: {e}")
        return {'error': str(e)}


def send_message(user_id, text, keyboard=None):
    """Отправка сообщения в Max"""
    params = {'text': text}
    
    if keyboard:
        params['attachments'] = [
            {
                'type': 'inline_keyboard',
                'payload': {
                    'buttons': keyboard
                }
            }
        ]
    
    return max_api(f'messages?user_id={user_id}', params)


def get_main_keyboard():
    """Основная клавиатура"""
    return [
        [
            {'type': 'callback', 'text': '🛗 Мои лифты', 'payload': 'my_elevators'},
            {'type': 'callback', 'text': '📋 Мои заявки', 'payload': 'my_tickets'}
        ],
        [
            {'type': 'callback', 'text': '❓ Помощь', 'payload': 'help'},
            {'type': 'callback', 'text': '✅ Завершить заявку', 'payload': 'complete_ticket'}
        ]
    ]


def get_ticket_keyboard(ticket_id, status='new'):
    """Клавиатура для работы с заявкой"""
    if status == 'new':
        return [
            [{'type': 'callback', 'text': '✅ Принять в работу', 'payload': f'accept_{ticket_id}'}]
        ]
    elif status == 'in_progress':
        return [
            [{'type': 'callback', 'text': '✅ Завершить', 'payload': f'complete_{ticket_id}'}]
        ]
    return None


def process_callback(user_id, payload):
    """Обработка callback от кнопок"""
    if not user_id or not payload:
        return
    
    from max_bot import send_message, get_main_keyboard
    
    if payload == 'my_elevators':
        process_message(user_id, '🛗 Мои лифты')
    elif payload == 'my_tickets':
        process_message(user_id, '📋 Мои заявки')
    elif payload == 'help':
        process_message(user_id, '❓ Помощь')
    elif payload == 'complete_ticket':
        process_message(user_id, '✅ Завершить заявку')
    elif payload.startswith('accept_'):
        try:
            ticket_id = int(payload.split('_')[1])
            message = handle_accept_ticket(user_id, ticket_id)
            send_message(user_id, message, get_ticket_keyboard(ticket_id, 'in_progress'))
        except:
            send_message(user_id, "❌ Команда не распознана")
    elif payload.startswith('complete_'):
        try:
            ticket_id = int(payload.split('_')[1])
            message = handle_complete_ticket(user_id, ticket_id)
            send_message(user_id, message, get_main_keyboard())
        except:
            send_message(user_id, "❌ Команда не распознана")
    else:
        send_message(user_id, "ℹ️ Используйте кнопки меню", get_main_keyboard())


def process_message(user_id, text):
    """Обработка сообщения от пользователя"""
    if not user_id or not text:
        return
    
    mechanic = get_mechanic_by_max(user_id)
    
    if not mechanic:
        if text.startswith('+'):
            register_mechanic_max(user_id, text)
        else:
            send_message(user_id, "👋 Отправьте ваш номер телефона для регистрации:\n\nПример: +79991234567", get_main_keyboard())
        return
    
    if text.lower() in ('/start', 'start', 'меню', 'главная'):
        show_main_menu(user_id, mechanic)
    elif text == '🛗 Мои лифты' or text.lower() == 'мои лифты':
        show_elevators(user_id, mechanic)
    elif text == '📋 Мои заявки' or text.lower() == 'мои заявки':
        show_tickets(user_id, mechanic)
    elif text == '❓ Помощь' or text.lower() == 'помощь':
        show_help(user_id)
    elif text == '✅ Завершить заявку' or text.lower() == 'завершить заявку':
        show_complete_ticket(user_id, mechanic)
    elif text.startswith('accept_'):
        try:
            ticket_id = int(text.split('_')[1])
            message = handle_accept_ticket(user_id, ticket_id)
            send_message(user_id, message, get_ticket_keyboard(ticket_id, 'in_progress'))
        except:
            send_message(user_id, "❌ Команда не распознана")
    elif text.startswith('complete_'):
        try:
            ticket_id = int(text.split('_')[1])
            message = handle_complete_ticket(user_id, ticket_id)
            send_message(user_id, message, get_main_keyboard())
        except:
            send_message(user_id, "❌ Команда не распознана")
    else:
        send_message(user_id, "Используйте кнопки меню", get_main_keyboard())


def get_mechanic_by_max(max_chat_id):
    """Получение механика по ID чата Max"""
    return db.get_mechanic_by_max(max_chat_id)


def register_mechanic_max(user_id, phone):
    """Регистрация механика по номеру телефона"""
    mechanic = db.get_mechanic_by_phone(phone)
    if not mechanic:
        send_message(user_id, "❌ Механик с таким номером телефона не найден в базе. Обратитесь к администратору.")
        return False
    
    db.update_mechanic(mechanic['id'], {
        'max_chat_id': str(user_id)
    })
    
    send_message(user_id, f"✅ Добро пожаловать, {mechanic['name']}!\n\nТеперь вы будете получать заявки в Max.", get_main_keyboard())
    return True


def handle_accept_ticket(user_id, ticket_id):
    """Принятие заявки в работу"""
    mechanic = get_mechanic_by_max(user_id)
    if not mechanic:
        return "❌ Вы не зарегистрированы. Отправьте номер телефона."
    
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return "❌ Заявка не найдена"
    
    if ticket.get('assigned_to') and ticket.get('assigned_to') != str(mechanic['id']):
        return "❌ Заявка уже назначена другому механику"
    
    db.update_ticket_status(ticket_id, 'в работе', f"max_bot (принял {mechanic['name']})")
    db.assign_ticket(ticket_id, mechanic['id'])
    
    return f"✅ Заявка #{ticket.get('ticket_number', ticket_id)} принята в работу!\n\n📍 {ticket.get('address')}\n📝 {ticket.get('problem_description', '')[:200]}"


def handle_complete_ticket(user_id, ticket_id):
    """Завершение заявки"""
    mechanic = get_mechanic_by_max(user_id)
    if not mechanic:
        return "❌ Вы не зарегистрированы. Отправьте номер телефона."
    
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return "❌ Заявка не найдена"
    
    if ticket.get('assigned_to') != str(mechanic['id']):
        return "❌ Заявка не назначена вам"
    
    db.update_ticket_status(ticket_id, 'выполнена', f"max_bot (завершил {mechanic['name']})")
    
    return f"✅ Заявка #{ticket.get('ticket_number', ticket_id)} завершена!\n\nСпасибо за работу!"


def show_main_menu(user_id, mechanic):
    """Показать главное меню"""
    send_message(user_id, f"👋 Привет, {mechanic['name']}!\n\nВыберите действие:", get_main_keyboard())


def show_elevators(user_id, mechanic):
    """Показать лифты механика"""
    elevators = db.get_mechanics_for_elevator_by_mechanic(mechanic['id'])
    if not elevators:
        send_message(user_id, "🛗 У вас нет закрепленных лифтов", get_main_keyboard())
        return
    
    msg = "🛗 Ваши лифты:\n\n"
    for e in elevators[:5]:
        msg += f"• {e.get('address', 'Адрес не указан')}\n"
    
    if len(elevators) > 5:
        msg += f"\n... и ещё {len(elevators) - 5}"
    
    send_message(user_id, msg, get_main_keyboard())


def show_tickets(user_id, mechanic):
    """Показать заявки механика"""
    tickets = db.get_all_mechanic_tickets(mechanic['id'])
    active_tickets = [t for t in tickets if t.get('status') in ('новая', 'в работе')]
    
    if not active_tickets:
        send_message(user_id, "📋 У вас нет активных заявок", get_main_keyboard())
        return
    
    msg = "📋 Ваши заявки:\n\n"
    for t in active_tickets[:5]:
        status_emoji = "🆕" if t.get('status') == 'новая' else "🔧"
        msg += f"{status_emoji} #{t.get('ticket_number', t['id'])}\n"
        msg += f"   📍 {t.get('address', 'Адрес не указан')}\n"
        msg += f"   📝 {t.get('problem_description', '')[:50]}...\n\n"
    
    send_message(user_id, msg, get_main_keyboard())


def show_help(user_id):
    """Показать справку"""
    msg = """❓ Справка по боту

📋 Команды:
• Мои лифты - показать закрепленные лифты
• Мои заявки - показать активные заявки
• Завершить заявку - завершить работу

📞 Поддержка: @admin
"""
    send_message(user_id, msg, get_main_keyboard())


def show_complete_ticket(user_id, mechanic):
    """Показать заявки для завершения"""
    tickets = db.get_all_mechanic_tickets(mechanic['id'])
    in_progress_tickets = [t for t in tickets if t.get('status') == 'в работе']
    
    if not in_progress_tickets:
        send_message(user_id, "✅ Нет заявок в работе", get_main_keyboard())
        return
    
    msg = "✅ Выберите заявку для завершения:\n\n"
    for t in in_progress_tickets[:5]:
        msg += f"#{t.get('ticket_number', t['id'])} - {t.get('address', 'Адрес не указан')}\n"
    
    send_message(user_id, msg, get_main_keyboard())


if __name__ == '__main__':
    if not MAX_BOT_TOKEN:
        print("❌ Установите MAX_BOT_TOKEN в переменных окружения")
        sys.exit(1)
    
    print("=" * 50)
    print("Max Bot для механиков")
    print("=" * 50)
    print(f"Bot URL: https://max.ru/id732606860856_bot")
    print("=" * 50)
    
    while True:
        try:
            updates = max_api('updates', {'timeout': 30})
            if 'error' in updates:
                print(f"❌ Error: {updates.get('error')}")
                continue
            
            for update in updates.get('updates', []):
                update_type = update.get('update_type')
                user_id = None
                text = None
                
                if update_type == 'message_created':
                    user_id = update.get('message', {}).get('sender', {}).get('user_id')
                    text = update.get('message', {}).get('body', {}).get('text', '')
                    print(f"📩 Max: сообщение от {user_id}: {text[:50]}")
                    if user_id:
                        process_message(user_id, text)
                
                elif update_type == 'callback_query':
                    user_id = update.get('callback', {}).get('user_id')
                    payload = update.get('callback', {}).get('payload', '')
                    print(f"🔘 Max: callback от {user_id}: {payload}")
                    if user_id:
                        process_callback(user_id, payload)
                
                elif update_type == 'bot_started':
                    user = update.get('user', {})
                    user_id = user.get('user_id')
                    print(f"🚀 Max: бот запущен пользователем {user_id}")
                    if user_id:
                        send_message(user_id, "👋 Привет! Отправьте ваш номер телефона для регистрации:\n\nПример: +79991234567", get_main_keyboard())
        
        except KeyboardInterrupt:
            print("\n🔴 Bot stopped")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            import time
            time.sleep(5)
