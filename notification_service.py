"""
Интеграция заявок с Telegram
Автоматическая отправка уведомлений механикам
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

import asyncio
from datetime import datetime, timedelta
from ticket_db import db
from telegram_bot import send_ticket_to_mechanic, BOT_TOKEN
from telegram import Bot


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
    
    # 1. Получаем механиков, закрепленных за этим лифтом
    mechanics = db.get_mechanics_for_elevator(elevator_id)
    
    # Если механиков нет, создаем пустой список (чтобы добавить аварийного)
    if not mechanics:
        mechanics = []
        print(f"ℹ️ Нет закрепленных механиков для лифта {elevator_id}")

    # 2. Добавляем АВАРИЙНОГО МЕХАНИКА, если это не плановое обслуживание
    # Приоритет 'низкий' означает плановое обслуживание
    print(f"DEBUG: priority = {ticket.get('priority')}")
    if ticket.get('priority') != 'низкий':
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            oncall_mechanic = db.get_oncall_mechanic_for_date(today)
            print(f"DEBUG: oncall for today = {oncall_mechanic}")
            
            # Если нет дежурного на сегодня - используем следующего по очереди
            if not oncall_mechanic:
                oncall_mechanic = db.get_next_oncall_mechanic()
                print(f"DEBUG: fallback to next oncall = {oncall_mechanic}")
            
            if oncall_mechanic:
                # Проверяем, нет ли его уже в списке (по ID)
                assigned_ids = [m['id'] for m in mechanics]
                print(f"DEBUG: linear ids = {assigned_ids}, oncall id = {oncall_mechanic['id']}")
                if oncall_mechanic['id'] not in assigned_ids:
                    print(f"🚨 Добавляем аварийного механика: {oncall_mechanic['name']}")
                    mechanics.append(oncall_mechanic)
                else:
                    print(f"DEBUG: oncall already in list, skipping")
        except Exception as e:
            print(f"⚠️ Ошибка получения аварийного механика: {e}")

    if not mechanics:
        print(f"⚠️ Нет получателей для уведомления")
        return False
    
    # Отправляем уведомление каждому механику
    sent_count = 0
    for mechanic in mechanics:
        telegram_chat_id = mechanic.get('telegram_chat_id')
        if telegram_chat_id:
            success = await send_ticket_to_mechanic(ticket_id, telegram_chat_id)
            if success:
                sent_count += 1
                db.send_ticket_to_mechanic(ticket_id, mechanic['id'])
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


async def notify_ticket_completed(ticket_id):
    """Уведомление о завершении заявки"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return False
    
    # Получаем механика которому была назначена заявка
    if not ticket.get('assigned_to'):
        return False
    
    try:
        mechanic = db.get_mechanic(int(ticket['assigned_to']))
    except:
        return False
    
    if not mechanic or not mechanic.get('telegram_chat_id'):
        return False
    
    try:
        bot = Bot(token=BOT_TOKEN)
        try:
            dt = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
            dt = dt + timedelta(hours=4)  # Самара
            months = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
            created_at_formatted = f"{dt.day} {months[dt.month]} {dt.year} {dt.hour:02d}:{dt.minute:02d}"
        except:
            created_at_formatted = ticket['created_at'][:16].replace('T', ' ')
        
        await bot.send_message(
            chat_id=mechanic['telegram_chat_id'],
            text=f"✅ Заявка от {created_at_formatted} ЗАВЕРШЕНА оператором!\n\n"
                 f"Спасибо за работу! 💪"
        )
        return True
    except Exception as e:
        print(f"❌ Ошибка уведомления о завершении: {e}")
        return False


if __name__ == "__main__":
    # Тест отправки
    if BOT_TOKEN == "ВАШ_ТОКЕН_БОТА":
        print("❌ Укажите BOT_TOKEN в telegram_bot.py")
    else:
        # Отправить заявку #1 всем механикам
        asyncio.run(notify_mechanics_about_ticket(1))
