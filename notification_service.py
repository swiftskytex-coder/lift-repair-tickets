"""
Уведомления для Max Bot
Placeholder - будет реализовано после настройки Max API
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

from ticket_db import db
import os


MAX_BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', '')


def send_message(user_id, text, keyboard=None):
    """Отправка сообщения в Max"""
    import requests
    import json
    
    if not MAX_BOT_TOKEN:
        print(f"⚠️ MAX_BOT_TOKEN не установлен")
        return False
    
    params = {
        'access_token': MAX_BOT_TOKEN,
        'user_id': user_id,
        'message': text
    }
    
    try:
        response = requests.post(
            'https://api.max.ru/v1/messages/send',
            params=params,
            timeout=10
        )
        return response.ok
    except Exception as e:
        print(f"❌ Ошибка отправки в Max: {e}")
        return False


async def send_morning_summaries():
    """Отправка утренних сводок"""
    from datetime import datetime
    
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, vk_id FROM mechanics WHERE status = "active"')
    
    for row in cursor.fetchall():
        mechanic_id, name, vk_id = row
        if vk_id:
            print(f"📱 Отправка сводки механику {name}...")
            # TODO: Реализовать отправку через Max API
    
    conn.close()
    print("✅ Утренние сводки отправлены")


async def notify_mechanics_about_ticket(ticket_id):
    """Уведомление механиков о новой заявке"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return False
    
    conn = db.get_connection()
    cursor = conn.cursor()
    
    # Получаем механиков для этого лифта
    elevator_id = ticket.get('elevator_id')
    if elevator_id:
        cursor.execute('''
            SELECT m.id, m.name, m.vk_id FROM mechanics m
            JOIN elevator_mechanics em ON m.id = em.mechanic_id
            WHERE em.elevator_id = ? AND m.status = 'active'
        ''', (elevator_id,))
    else:
        cursor.execute('SELECT id, name, vk_id FROM mechanics WHERE status = "active"')
    
    sent_count = 0
    for row in cursor.fetchall():
        mechanic_id, name, vk_id = row
        if vk_id:
            print(f"📱 Отправка заявки #{ticket_id} механику {name} ({vk_id})")
            # TODO: Реализовать отправку через Max API
            db.send_ticket_to_mechanic(ticket_id, mechanic_id)
            sent_count += 1
    
    conn.close()
    print(f"✅ Отправлено {sent_count} механикам")
    return sent_count > 0


async def notify_ticket_completed(ticket_id):
    """Уведомление о завершении заявки"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return False
    
    print(f"✅ Заявка #{ticket.get('ticket_number', ticket_id)} завершена")
    return True


if __name__ == "__main__":
    if not MAX_BOT_TOKEN:
        print("❌ MAX_BOT_TOKEN не установлен")
    else:
        print("Max Bot готов к работе")
