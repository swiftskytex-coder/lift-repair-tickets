"""
Интеграция заявок с Telegram
Автоматическая отправка уведомлений механикам
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

import asyncio
from ticket_db import db
from telegram_bot import send_ticket_to_mechanic, BOT_TOKEN


async def notify_mechanics_about_ticket(ticket_id):
    """
    Отправка уведомления механикам при создании заявки
    Вызывать после создания заявки
    """
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        print(f"❌ Заявка {ticket_id} не найдена")
        return False
    
    elevator_id = ticket.get('elevator_id')
    if not elevator_id:
        print(f"⚠️ Заявка {ticket_id} без привязки к лифту")
        return False
    
    # Получаем механиков, закрепленных за этим лифтом
    mechanics = db.get_mechanics_for_elevator(elevator_id)
    
    if not mechanics:
        print(f"⚠️ Нет механиков для лифта {elevator_id}")
        return False
    
    # Отправляем уведомление каждому механику
    sent_count = 0
    for mechanic in mechanics:
        telegram_chat_id = mechanic.get('telegram_chat_id')
        if telegram_chat_id:
            success = await send_ticket_to_mechanic(ticket_id, telegram_chat_id)
            if success:
                sent_count += 1
                print(f"✅ Отправлено механику {mechanic['name']}")
            else:
                print(f"❌ Не удалось отправить механику {mechanic['name']}")
        else:
            print(f"⚠️ Механик {mechanic['name']} не привязал Telegram")
    
    print(f"\n📊 Отправлено {sent_count}/{len(mechanics)} механикам")
    return sent_count > 0


# Пример использования в ticket_system.py:
# @app.route('/api/tickets', methods=['POST'])
# def api_create_ticket():
#     ... создание заявки ...
#     
#     # Отправляем уведомление механикам
#     import asyncio
#     asyncio.create_task(notify_mechanics_about_ticket(ticket['id']))
#     
#     return jsonify({...})


if __name__ == "__main__":
    # Тест отправки
    if BOT_TOKEN == "ВАШ_ТОКЕН_БОТА":
        print("❌ Укажите BOT_TOKEN в telegram_bot.py")
    else:
        # Отправить заявку #1 всем механикам
        asyncio.run(notify_mechanics_about_ticket(1))
