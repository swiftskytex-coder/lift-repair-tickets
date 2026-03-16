"""
Интеграция заявок с Telegram
Автоматическая отправка уведомлений механикам
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

import asyncio
import threading
import time
from datetime import datetime, timedelta
from ticket_db import db
from telegram_bot import send_ticket_to_mechanic, BOT_TOKEN
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from PIL import Image
import io


def create_thumbnail(image_path, size=(240, 180)):
    """Создаёт маленькое превью изображения с сохранением пропорций (crop центр)"""
    try:
        img = Image.open(image_path)
        target_w, target_h = size
        orig_w, orig_h = img.size
        
        # Вычисляем размеры для crop из центра с пропорциями target
        target_ratio = target_w / target_h
        orig_ratio = orig_w / orig_h
        
        if orig_ratio > target_ratio:
            # Изображение шире - обрезаем по ширине
            new_w = int(orig_h * target_ratio)
            new_h = orig_h
            left = (orig_w - new_w) // 2
            top = 0
        else:
            # Изображение выше - обрезаем по высоте
            new_w = orig_w
            new_h = int(orig_w / target_ratio)
            left = 0
            top = (orig_h - new_h) // 2
        
        # Обрезаем центр и меняем размер
        img = img.crop((left, top, left + new_w, top + new_h))
        img = img.resize(size, Image.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=70)
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f"⚠️ Ошибка создания превью: {e}")
        return None


def send_morning_summary_to_linear_mechanics():
    """
    Отправка утренней сводки линейным механикам в 8:00
    Содержит все заявки на их лифты (включая завершённые)
    """
    print("🌅 Отправка утренней сводки линейным механикам...")
    
    try:
        # Получаем все заявки (без фильтра по статусу)
        all_tickets = db.search_tickets(limit=200)
        
        if not all_tickets:
            print("ℹ️ Нет заявок для отправки")
            return
        
        print(f"ℹ️ Найдено {len(all_tickets)} заявок")
        
        # Группируем заявки по механику
        tickets_by_mechanic = {}
        
        for ticket in all_tickets:
            elevator_id = ticket.get('elevator_id')
            if not elevator_id:
                continue
            
            # Получаем механиков для этого лифта
            mechanics = db.get_mechanics_for_elevator(elevator_id)
            
            for mech in mechanics:
                mech_id = mech['id']
                if mech_id not in tickets_by_mechanic:
                    tickets_by_mechanic[mech_id] = {
                        'mechanic': mech,
                        'tickets': []
                    }
                # Проверяем, не добавлена ли уже эта заявка
                if not any(t['id'] == ticket['id'] for t in tickets_by_mechanic[mech_id]['tickets']):
                    tickets_by_mechanic[mech_id]['tickets'].append(ticket)
        
        # Отправляем сводку каждому механику
        asyncio.run(_send_summaries_async(tickets_by_mechanic))
        
    except Exception as e:
        print(f"❌ Ошибка отправки утренней сводки: {e}")


async def _send_summaries_async(tickets_by_mechanic):
    """Асинхронная отправка сводок"""
    bot = Bot(token=BOT_TOKEN)
    
    for mech_id, data in tickets_by_mechanic.items():
        mechanic = data['mechanic']
        tickets = data['tickets']
        telegram_chat_id = mechanic.get('telegram_chat_id')
        
        if not telegram_chat_id:
            continue
        
        # Формируем сводку
        today = datetime.now().strftime('%d.%m.%Y')
        message = f"📋 *Утренняя сводка заявок на {today}*\n\n"
        
        for i, ticket in enumerate(tickets, 1):
            address = ticket.get('address', 'Адрес не указан')
            problem = ticket.get('problem_description', '')
            problem_short = problem[:50] + '...' if len(problem) > 50 else problem
            status = ticket.get('status', '')
            
            # Форматируем статус
            if status == 'выполнена':
                status_text = "✅ Выполнено"
            elif status == 'в работе':
                status_text = "🔧 В работе"
            elif status == 'новая':
                status_text = "🆕 Новая"
            else:
                status_text = status
            
            created_at = ticket.get('created_at', '')
            # Форматируем время (только часы:минуты)
            if created_at:
                try:
                    created_at = created_at[11:16]
                except:
                    created_at = ''
            
            message += f"{i}. *{address}*"
            if created_at:
                message += f" 🕐 {created_at}"
            message += "\n"
            message += f"   📝 {problem_short}\n"
            
            # Для выполненных заявок с фото - отправляем сразу с фото
            if status == 'выполнена':
                ticket_id = ticket.get('id')
                try:
                    conn = db.get_connection()
                    cursor = conn.cursor()
                    
                    # Получаем фото
                    cursor.execute(
                        "SELECT text FROM comments WHERE ticket_id = ? AND author = 'mechanic' AND text LIKE '[ФОТО]%'",
                        (ticket_id,)
                    )
                    photos = [row[0].replace('[ФОТО] ', '') for row in cursor.fetchall()]
                    
                    # Получаем описание работ
                    cursor.execute(
                        "SELECT text FROM comments WHERE ticket_id = ? AND author = 'mechanic' AND text LIKE '📝%'",
                        (ticket_id,)
                    )
                    work_texts = [row[0].replace('📝 ', '') for row in cursor.fetchall()]
                    work_text = '\n'.join(work_texts) if work_texts else ''
                    conn.close()
                    
                    if photos:
                        # Формируем текст с описанием работ
                        msg = f"{i}. {address}"
                        if created_at:
                            msg += f" 🕐 {created_at}"
                        msg += "\n"
                        msg += f"📝 {problem_short}\n"
                        msg += "✅ Выполнено"
                        if work_text:
                            msg += f"\n🔧 {work_text[:200]}"
                            if len(work_text) > 200:
                                msg += "..."
                        
                        # Отправляем первое фото с текстом в одном сообщении
                        photo_path = photos[0]
                        full_path = f"/Users/swiftpanaev/KIRO/test4/{photo_path}"
                        try:
                            thumb = create_thumbnail(full_path)
                            if thumb:
                                await bot.send_photo(
                                    chat_id=telegram_chat_id,
                                    photo=thumb,
                                    caption=msg,
                                    filename="photo.jpg"
                                )
                        except Exception as e:
                            print(f"⚠️ Ошибка отправки фото {photo_path}: {e}")
                            # Если не удалось отправить фото, отправляем просто текст
                            await bot.send_message(
                                chat_id=telegram_chat_id,
                                text=msg,
                                parse_mode='Markdown'
                            )
                        
                        # Если есть второе фото, отправляем отдельно
                        if len(photos) > 1:
                            photo_path = photos[1]
                            full_path = f"/Users/swiftpanaev/KIRO/test4/{photo_path}"
                            try:
                                thumb = create_thumbnail(full_path)
                                if thumb:
                                    await bot.send_photo(
                                        chat_id=telegram_chat_id,
                                        photo=thumb,
                                        filename="photo.jpg"
                                    )
                            except Exception as e:
                                print(f"⚠️ Ошибка отправки фото {photo_path}: {e}")
                                pass
                        continue
                except Exception as e:
                    print(f"⚠️ Ошибка получения данных о заявке {ticket.get('id')}: {e}")
                    pass
            
            message += f"   📌 {status_text}\n\n"
        
        message += f"Всего заявок: {len(tickets)}"
        
        # Кнопка для перехода к полному отчёту
        keyboard = [[InlineKeyboardButton("📋 Полный отчёт", url="http://tickets.lift-system.crazedns.ru/")]]
        
        try:
            # Отправляем остальную часть (без выполненных с фото)
            if message.strip():
                await bot.send_message(
                    chat_id=telegram_chat_id,
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            print(f"✅ Отправлена сводка механику {mechanic['name']}: {len(tickets)} заявок")
        except Exception as e:
            print(f"❌ Не удалось отправить {mechanic['name']}: {e}")


def start_scheduler():
    """Запуск планировщика для утренней рассылки"""
    
    def run_scheduler():
        while True:
            now = datetime.now()
            # Вычисляем время до следующего 8:00
            next_8am = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if now >= next_8am:
                next_8am += timedelta(days=1)
            
            seconds_until_8am = (next_8am - now).total_seconds()
            print(f"⏰ Планировщик: следующая отправка через {seconds_until_8am/3600:.1f} часов")
            
            time.sleep(seconds_until_8am)
            
            # Отправляем только в рабочие дни (пн-пт)
            if datetime.now().weekday() < 5:  # пн-пт
                send_morning_summary_to_linear_mechanics()
            else:
                print("ℹ️ Выходной день - сводка не отправляется")
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    print("✅ Планировщик утренней рассылки запущен (пн-пт 8:00)")


async def notify_mechanics_about_ticket(ticket_id):
    """
    Отправка уведомления механикам при создании заявки
    Вызывать после создания заявки
    
    Линейные механики получают заявки только:
    - В рабочее время (08:00 - 17:00)
    - В рабочие дни (пн-пт)
    
    Аварийный механик получает все заявки всегда
    """
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        print(f"❌ Заявка {ticket_id} не найдена")
        return False
    
    elevator_id = ticket.get('elevator_id')
    if not elevator_id:
        print(f"⚠️ Заявка {ticket_id} без привязки к лифту")
        return False
    
    # Проверяем рабочее время и день
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()  # 0=понедельник, 6=воскресенье
    
    is_working_hours = 8 <= hour < 17  # 08:00 - 17:00
    is_working_day = weekday < 5  # пн-пт
    
    print(f"DEBUG: now={now}, hour={hour}, weekday={weekday}, working_hours={is_working_hours}, working_day={is_working_day}")
    
    # 1. Получаем механиков, закрепленных за этим лифтом (линейные)
    mechanics = db.get_mechanics_for_elevator(elevator_id)
    
    # Если механиков нет, создаем пустой список (чтобы добавить аварийного)
    if not mechanics:
        mechanics = []
        print(f"ℹ️ Нет закрепленных механиков для лифта {elevator_id}")
    
    # Фильтруем: линейные механики получают только в рабочее время
    if is_working_hours and is_working_day:
        # Рабочее время - отправляем всем линейным
        linear_mechanics = mechanics
        print(f"ℹ️ Рабочее время - отправляем линейным механикам: {[m['name'] for m in linear_mechanics]}")
    else:
        # Не рабочее время - не отправляем линейным
        linear_mechanics = []
        if not is_working_hours:
            print(f"ℹ️ Не рабочее время (сейчас {hour}:00) - линейные механики не получат заявку")
        if not is_working_day:
            print(f"ℹ️ Выходной день - линейные механики не получат заявку")
    
    # 2. АВАРИЙНЫЙ МЕХАНИК получает ВСЕГДА (если не низкий приоритет)
    oncall_mechanic = None
    if ticket.get('priority') != 'низкий':
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            oncall_mechanic = db.get_oncall_mechanic_for_date(today)
            
            if not oncall_mechanic:
                oncall_mechanic = db.get_next_oncall_mechanic()
            
            if oncall_mechanic:
                # Проверяем, нет ли его уже в списке линейных
                linear_ids = [m['id'] for m in linear_mechanics]
                if oncall_mechanic['id'] not in linear_ids:
                    print(f"🚨 Добавляем аварийного механика: {oncall_mechanic['name']}")
                    linear_mechanics.append(oncall_mechanic)
        except Exception as e:
            print(f"⚠️ Ошибка получения аварийного механика: {e}")
    
    # ВСЕГДА отправляем хотя бы аварийному (если есть приоритет и есть аварийный)
    if not linear_mechanics:
        # Пробуем получить аварийного еще раз (вне зависимости от времени)
        if ticket.get('priority') != 'низкий':
            try:
                today = datetime.now().strftime('%Y-%m-%d')
                oncall_mechanic = db.get_oncall_mechanic_for_date(today)
                if not oncall_mechanic:
                    oncall_mechanic = db.get_next_oncall_mechanic()
                if oncall_mechanic:
                    print(f"🚨 Принудительно добавляем аварийного: {oncall_mechanic['name']}")
                    linear_mechanics = [oncall_mechanic]
            except Exception as e:
                print(f"⚠️ Ошибка принудительного добавления аварийного: {e}")
    
    if not linear_mechanics:
        print(f"⚠️ Нет получателей для уведомления")
        return False
    
    # Отправляем уведомление каждому механику
    sent_count = 0
    for mechanic in linear_mechanics:
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
    
    print(f"\n📊 Отправлено {sent_count}/{len(linear_mechanics)} механикам")
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
