"""
Max Bot для механиков
Аналогично Telegram боту
"""

import os
import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

import json
import requests
from datetime import datetime, timedelta

# Max API
MAX_API_URL = 'https://api.max.ru/v1/'

# Токен бота
MAX_BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', '')

# База данных
from ticket_db import db

# Хранилище данных пользователей
max_user_data = {}


def max_api(method, params):
    """Вызов Max API"""
    params['access_token'] = MAX_BOT_TOKEN
    response = requests.post(MAX_API_URL + method, params, timeout=10)
    return response.json()


def send_message(user_id, text, keyboard=None, attachment=None):
    """Отправка сообщения в Max"""
    params = {
        'user_id': user_id,
        'message': text
    }
    if keyboard:
        params['keyboard'] = json.dumps(keyboard)
    if attachment:
        params['attachment'] = attachment
    
    return max_api('messages.send', params)


def get_main_keyboard():
    """Клавиатура с основными командами"""
    return {
        'one_time': False,
        'buttons': [
            [{'action': {'type': 'text', 'label': '🛗 Мои лифты'}},
             {'action': {'type': 'text', 'label': '📋 Мои заявки'}}],
            [{'action': {'type': 'text', 'label': '❓ Помощь'}},
             {'action': {'type': 'text', 'label': '✅ Завершить заявку'}}]
        ]
    }


def get_ticket_keyboard(ticket_id, status='new'):
    """Клавиатура для работы с заявкой"""
    if status == 'new':
        return {
            'one_time': False,
            'buttons': [
                [{'action': {'type': 'text', 'label': '✅ Принять в работу'}}],
                [{'action': {'type': 'text', 'label': '📋 Все заявки'}}]
            ]
        }
    elif status == 'in_progress':
        return {
            'one_time': False,
            'buttons': [
                [{'action': {'type': 'text', 'label': '✅ Завершить'}}],
                [{'action': {'type': 'text', 'label': '📋 Все заявки'}}]
            ]
        }
    return None


def get_mechanic_by_max(user_id):
    """Получение механика по Max ID"""
    return db.get_mechanic_by_vk(user_id)


def register_mechanic_max(user_id, phone):
    """Регистрация механика по телефону"""
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name FROM mechanics WHERE phone = ?', (phone,))
    row = cursor.fetchone()
    
    if row:
        cursor.execute('UPDATE mechanics SET vk_id = ? WHERE id = ?', (str(user_id), row[0]))
        conn.commit()
        conn.close()
        return True, cursor.execute('SELECT name FROM mechanics WHERE id = ?', (row[0],)).fetchone()[0]
    
    conn.close()
    return False, None


def handle_my_tickets(user_id):
    """Показать заявки механика"""
    mechanic = get_mechanic_by_max(user_id)
    if not mechanic:
        return "❌ Вы не зарегистрированы."
    
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT t.* FROM tickets t
        LEFT JOIN ticket_mechanics tm ON t.id = tm.ticket_id
        WHERE (tm.mechanic_id = ? OR t.elevator_id IN (
            SELECT elevator_id FROM elevator_mechanics WHERE mechanic_id = ?
        ))
        AND t.status IN ('новая', 'в работе')
        ORDER BY 
            CASE t.priority 
                WHEN 'срочный' THEN 1 
                WHEN 'высокий' THEN 2 
                WHEN 'обычный' THEN 3 
                ELSE 4 
            END,
            t.created_at DESC
        LIMIT 10
    ''', (mechanic['id'], mechanic['id']))
    
    tickets = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]
    conn.close()
    
    if not tickets:
        return "📭 Новых заявок нет."
    
    message = f"📋 Ваши заявки ({len(tickets)}):\n\n"
    
    for ticket in tickets:
        status_icon = "🆕" if ticket['status'] == 'новая' else "🔧"
        
        created = ticket.get('created_at', '')
        if created:
            try:
                dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                dt = dt + timedelta(hours=4)
                created = dt.strftime('%H:%M')
            except:
                created = ''
        
        message += f"{status_icon} #{ticket.get('ticket_number', ticket['id'])}\n"
        message += f"   📍 {ticket.get('address', 'Адрес не указан')[:50]}\n"
        if created:
            message += f"   🕐 {created}\n"
        message += f"   [accept_{ticket['id']}] Принять\n\n"
    
    return message


def handle_accept_ticket(user_id, ticket_id):
    """Принять заявку в работу"""
    ticket = db.update_ticket_status(ticket_id, 'в работе', 'max_bot')
    
    if ticket:
        # Сохраняем ID заявки
        max_user_data[str(user_id)] = {'ticket_id': ticket_id}
        
        return (f"✅ Заявка #{ticket.get('ticket_number', ticket_id)} принята в работу!\n\n"
                f"📍 {ticket.get('address', '')}\n\n"
                f"Отправьте фото и описание выполненных работ.\n"
                f"После завершения нажмите 'Завершить заявку'")
    else:
        return "❌ Заявка не найдена."


def handle_complete_ticket(user_id, ticket_id=None):
    """Завершить заявку"""
    if not ticket_id:
        # Берем последнюю принятую
        if str(user_id) in max_user_data and 'ticket_id' in max_user_data[str(user_id)]:
            ticket_id = max_user_data[str(user_id)]['ticket_id']
        else:
            return "❌ Нет активной заявки для завершения"
    
    ticket = db.update_ticket_status(ticket_id, 'выполнена', 'max_bot')
    
    if ticket:
        # Очищаем
        if str(user_id) in max_user_data:
            del max_user_data[str(user_id)]
        
        return (f"✅ Заявка #{ticket.get('ticket_number', ticket_id)} выполнена!\n\n"
                f"📍 {ticket.get('address', '')}\n\n"
                f"Спасибо за работу! 💪")
    else:
        return "❌ Заявка не найдена."


def process_message(user_id, text):
    """Обработка сообщения от пользователя"""
    
    # Проверяем зарегистрирован ли механик
    mechanic = get_mechanic_by_max(user_id)
    
    # Обработка команд
    if text == '🛗 Мои лифты':
        if mechanic:
            elevators = db.get_mechanic_elevators(mechanic['id'])
            if elevators:
                message = f"🛗 Ваши лифты ({len(elevators)}):\n\n"
                for e in elevators:
                    message += f"• {e['elevator_id']} - {e['address']}\n"
            else:
                message = "ℹ️ За вами не закреплены лифты"
        else:
            message = "❌ Вы не зарегистрированы. Отправьте номер телефона."
        send_message(user_id, message, get_main_keyboard())
    
    elif text == '📋 Мои заявки':
        message = handle_my_tickets(user_id)
        send_message(user_id, message, get_main_keyboard())
    
    elif text == '❓ Помощь':
        help_text = """📖 Справка:

🛗 Мои лифты - ваши лифты
📋 Мои заявки - активные заявки
✅ Завершить заявку - завершить работу
📸 Отправьте фото для отчёта
❓ Помощь - эта справка"""
        send_message(user_id, help_text, get_main_keyboard())
    
    elif text == '✅ Завершить заявку':
        message = handle_complete_ticket(user_id)
        send_message(user_id, message, get_main_keyboard())
    
    elif 'accept_' in text:
        try:
            ticket_id = int(text.split('_')[1])
            message = handle_accept_ticket(user_id, ticket_id)
            send_message(user_id, message, get_ticket_keyboard(ticket_id, 'in_progress'))
        except:
            send_message(user_id, "❌ Команда не распознана")
    
    else:
        # Неизвестная команда - пробуем как номер телефона
        if not mechanic:
            if text.startswith('+'):
                success, name = register_mechanic_max(user_id, text)
                if success:
                    send_message(user_id, f"✅ Добро пожаловать, {name}!\n\nТеперь вы будете получать заявки.", get_main_keyboard())
                else:
                    send_message(user_id, "❌ Механик не найден. Обратитесь к администратору.")
            else:
                send_message(user_id, "👋 Отправьте номер телефона для регистрации:\n\nПример: +79991234567", get_main_keyboard())
        else:
            send_message(user_id, "ℹ️ Используйте кнопки меню", get_main_keyboard())


def setup_max_bot():
    """Настройка Max бота"""
    if not MAX_BOT_TOKEN:
        print("⚠️ MAX_BOT_TOKEN не установлен!")
        return False
    
    print(f"✅ Max Bot токен настроен")
    return True


def main():
    """Тестирование"""
    print("=" * 50)
    print("Max Bot для механиков")
    print("=" * 50)
    
    if not MAX_BOT_TOKEN:
        print("❌ Токен не установлен")
        return
    
    print("Max Bot готов к работе!")


if __name__ == '__main__':
    main()
