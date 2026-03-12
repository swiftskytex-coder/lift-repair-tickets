"""
Telegram Bot для механиков
Отправляет заявки и принимает отчеты с фото
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

import os
import asyncio
import json
import requests
from datetime import datetime, timedelta
from ticket_db import db

# Загрузка переменных окружения
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Импорты для Telegram Bot
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot, ReplyKeyboardMarkup, KeyboardButton
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
except ImportError:
    print("❌ Установите: pip install python-telegram-bot")
    sys.exit(1)

# Клавиатура с основными командами
def get_main_keyboard():
    """Возвращает главную клавиатуру с кнопками"""
    keyboard = [
        [KeyboardButton("🛗 Мои лифты"), KeyboardButton("📋 Мои заявки")],
        [KeyboardButton("❓ Помощь"), KeyboardButton("✅ Завершить заявку")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# Токен бота из переменных окружения
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')

# Хранилище временных данных
user_data = {}

# URL базы знаний
KB_URL = os.getenv('KNOWLEDGE_BASE_URL', 'http://localhost:8082')


def save_to_knowledge_base(ticket, mechanic_name=None, work_details=None):
    """Сохраняет отчёт о ремонте в базу знаний"""
    try:
        # Собираем фото
        photos = []
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT text FROM comments WHERE ticket_id = ? AND author = 'mechanic' AND text LIKE '[ФОТО]%'",
                (ticket['id'],)
            )
            for row in cursor.fetchall():
                photo_path = row[0].replace('[ФОТО] ', '')
                photos.append(photo_path)
        
        # Получаем серийный номер и тип лифта
        serial_number = None
        elevator_type = 'пассажирский'
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT serial_number, elevator_type FROM elevators WHERE elevator_id = ?",
                (ticket.get('elevator_id'),)
            )
            row = cursor.fetchone()
            if row:
                serial_number = row[0]
                elevator_type = row[1] or 'пассажирский'
        
        # Формируем решение (что было сделано)
        solution = work_details if work_details else 'Ремонт выполнен'
        
        # Формируем симптомы (проблема)
        symptoms = [ticket.get('problem_description', '')]
        
        # Формируем данные для KB
        data = {
            'title': f"{ticket.get('problem_description', 'Ремонт лифта')[:50]}",
            'content': ticket.get('problem_description', ''),
            'symptoms': symptoms,
            'solution': solution,
            'category': 'ремонт',
            'equipment_type': elevator_type,
            'serial_number': serial_number,
            'photos': photos,
            'tags': [elevator_type, 'ремонт'],
            'estimated_time': 60,
            'difficulty_level': 3
        }
        
        # Отправляем в KB
        response = requests.post(
            f"{KB_URL}/api/integration/ticket/{ticket['id']}/create-knowledge",
            json=data,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                return True, result.get('article_id')
        return False, None
    except Exception as e:
        print(f"❌ Ошибка сохранения в KB: {e}")
        return False, None
    except Exception as e:
        print(f"❌ Ошибка сохранения в KB: {e}")
        return False, None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие и регистрация механика"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    
    await update.message.reply_text(
        "🛠️ Бот для механиков лифтов\n\n"
        "Отправьте ваш номер телефона для регистрации:\n"
        "Пример: +79991234567",
        reply_markup=get_main_keyboard()
    )


async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка номера телефона и регистрация"""
    phone = update.message.text.strip()
    chat_id = update.effective_chat.id
    username = update.effective_user.username
    
    # Проверяем формат телефона
    if not phone.startswith('+') or len(phone) < 10:
        await update.message.reply_text("❌ Неверный формат. Отправьте: +79991234567")
        return
    
    # Ищем механика в базе
    mechanic = db.get_mechanic_by_phone(phone)
    
    if mechanic:
        # Обновляем telegram_chat_id
        db.update_mechanic(mechanic['id'], {
            'telegram_chat_id': str(chat_id),
            'telegram_username': username
        })
        
        await update.message.reply_text(
            f"✅ {mechanic['name']} зарегистрирован!\n\n"
            "Вы будете получать заявки на ремонт лифтов.\n"
            "Доступные команды:\n"
            "/my_lifts - Мои лифты\n"
            "/status - Мои текущие заявки"
        )
    else:
        await update.message.reply_text(
            "❌ Механик с таким номером не найден.\n"
            "Обратитесь к администратору для добавления в систему."
        )


async def send_ticket_to_mechanic(ticket_id, mechanic_chat_id):
    """Отправка заявки механику"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return False
    
    # Получаем информацию о лифте
    elevator = db.get_elevator(ticket.get('elevator_id'))
    
    # Формируем дату в формате "01 марта 2026 12:00"
    try:
        dt = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
        dt = dt + timedelta(hours=4)  # Самара
        months = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
        created_at_formatted = f"{dt.day} {months[dt.month]} {dt.year} {dt.hour:02d}:{dt.minute:02d}"
    except:
        created_at_formatted = ticket['created_at'][:16].replace('T', ' ')
    
    message = f"🚨 НОВАЯ ЗАЯВКА\n"
    message += f"⏰ {created_at_formatted}\n\n"
    
    # Адрес без подъезда
    address_clean = ticket['address']
    for prefix in ['подъезд ', 'Подъезд ', 'п. ', 'П. ']:
        if prefix in address_clean.lower():
            address_clean = address_clean.split(prefix)[0].rstrip()
    message += f"📍 Адрес: {address_clean}\n"
    
    # Подъезд и тип
    if elevator and elevator.get('entrance'):
        message += f"Подъезд: {elevator['entrance']} {elevator.get('elevator_type', 'лифт')}\n"
    
    message += f"📝 Проблема:\n{ticket['problem_description']}\n"
    
    # Кнопки действий
    keyboard = [
        [InlineKeyboardButton("✅ Принять в работу", callback_data=f"accept_{ticket_id}")]
    ]
    
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=mechanic_chat_id,
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return True
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return False


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    query = update.callback_query
    data = query.data
    
    chat_id = update.effective_chat.id
    
    if data.startswith("accept_"):
        ticket_id = int(data.split("_")[1])
        print(f"DEBUG: accept_ pressed for ticket {ticket_id}, chat_id={chat_id}")
        
        # Получаем данные текущего механика
        mechanic = db.get_mechanic_by_telegram(chat_id)
        print(f"DEBUG: mechanic = {mechanic}")
        
        if not mechanic:
            print(f"DEBUG: mechanic not found!")
            return
        
        name = mechanic['name']
        
        # Обновляем статус заявки
        db.update_ticket(ticket_id, {'assigned_to': str(mechanic['id'])}, 'telegram_bot')
        db.update_ticket_status(ticket_id, 'в работе', 'telegram_bot')
        
        # Логируем принятие
        db.accept_ticket(ticket_id, mechanic['id'])
        db.add_comment(ticket_id, 'system', f"👤 Механик {name} принял заявку в работу")
        
        # Формируем сообщение с кнопками
        ticket = db.get_ticket(ticket_id)
        
        # Адрес без подъезда
        address_clean = ticket['address']
        for prefix in ['подъезд ', 'Подъезд ', 'п. ', 'П. ']:
            if prefix in address_clean.lower():
                address_clean = address_clean.split(prefix)[0].rstrip()
        
        # Подъезд и тип
        elevator = db.get_elevator(ticket.get('elevator_id'))
        elevator_info = ""
        if elevator and elevator.get('entrance'):
            elevator_info = f"Подъезд: {elevator['entrance']} {elevator.get('elevator_type', 'лифт')}\n"
        
        message = f"✅ ЗАЯВКА ПРИНЯТА В РАБОТУ\n\n"
        message += f"📍 Адрес: {address_clean}\n"
        message += elevator_info
        message += f"📝 Проблема: {ticket['problem_description']}\n\n"
        message += "📸 Отправьте фото выполненной работы и использованных запчастей\n"
        message += "📝 Опишите, что было сделано?\n"
        
        keyboard = [
            [InlineKeyboardButton("✅ Завершить", callback_data=f"quick_ready_{ticket_id}")]
        ]
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
        
        # Сохраняем ID заявки для приёма фото и описания
        user_data[chat_id] = {'ticket_id': ticket_id, 'status': 'awaiting_photos'}
    
    elif data.startswith("reject_"):
        ticket_id = int(data.split("_")[1])
        # Отказ от заявки - больше не используется
        await query.answer("Функция отказа недоступна", show_alert=True)
    
    elif data.startswith("select_"):
        ticket_id = int(data.split("_")[1])
        ticket = db.get_ticket(ticket_id)
        
        if not ticket:
            await query.edit_message_text("❌ Заявка не найдена")
            return
        
        # Сохраняем выбранную заявку
        user_data[chat_id] = {'selected_ticket': ticket_id, 'status': 'ticket_selected'}
        
        await query.edit_message_text(
            f"✅ Выбрана заявка #{ticket['ticket_number']}\n\n"
            f"📍 {ticket['address']}\n"
            f"⚠️ {ticket['priority']}\n\n"
            f"Отправьте фото ремонта или нажмите /complete для завершения.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📷 Отправить фото", callback_data=f"photo_{ticket_id}")],
                [InlineKeyboardButton("✅ Завершить", callback_data=f"complete_{ticket_id}")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_tickets")]
            ])
        )

    elif data.startswith("cant_fix_"):
        # Функция возврата заявки отключена
        await query.answer("Функция недоступна", show_alert=True)

    elif data.startswith("back_to_tickets"):
        await my_tickets_menu(update, context)
    
    # Новые обработчики для меню заявок
    elif data == "tickets_new":
        await show_tickets_by_status(update, context, 'new')
    
    elif data == "tickets_inwork":
        await show_tickets_by_status(update, context, 'inwork')
    
    elif data == "tickets_done":
        await show_tickets_by_status(update, context, 'done')
    
    elif data == "tickets_all":
        await show_tickets_by_status(update, context, 'all')
    
    elif data == "back_tickets_menu":
        await my_tickets_menu(update, context)
    
    elif data == "back_my_tickets":
        await my_tickets_menu(update, context)
    
    elif data.startswith("ticket_"):
        await show_ticket_details(update, context)
    
    elif data.startswith("back_tickets_"):
        status = data.replace("back_tickets_", "")
        await show_tickets_by_status(update, context, status)
    
    elif data.startswith("photo_"):
        ticket_id = int(data.split("_")[1])
        user_data[chat_id] = {'ticket_id': ticket_id, 'status': 'awaiting_photos'}
        await query.edit_message_text(
            "📸 Отправьте фото ремонта.\n"
            "После отправки нажмите /complete."
        )
    
    elif data.startswith("complete_"):
        ticket_id = int(data.split("_")[1])
        ticket = db.update_ticket_status(ticket_id, 'выполнена', 'telegram_bot')
        
        if ticket:
            await query.edit_message_text(
                f"✅ Заявка #{ticket['ticket_number']} завершена!\n\n"
                "Спасибо за работу! 💪"
            )
            if chat_id in user_data:
                del user_data[chat_id]
    
    # Быстрые ответы
    elif data.startswith("quick_"):
        parts = data.split("_")
        action = parts[1]
        ticket_id = int(parts[2])
        
        mechanic = db.get_mechanic_by_telegram(chat_id)
        name = mechanic['name'] if mechanic else "Механик"
        
        ticket = db.get_ticket(ticket_id)
        if not ticket:
            await query.edit_message_text("❌ Заявка не найдена")
            return
        
        if action == "onway":
            db.add_comment(ticket_id, 'system', f"🚗 {name} в пути")
            await query.edit_message_text(
                f"✅ Отправлено оператору: 'В пути'\n\n"
                f"Заявка #{ticket['ticket_number']}"
            )
        elif action == "parts":
            db.add_comment(ticket_id, 'system', f"🔧 {name} - нужны запчасти")
            await query.edit_message_text(
                f"✅ Отправлено оператору: 'Нужны запчасти'\n\n"
                f"Заявка #{ticket['ticket_number']}"
            )
        elif action == "ready":
            # Завершаем заявку и сохраняем в базу знаний
            work_details = user_data.get(chat_id, {}).get('work_details', '')
            
            # Обновляем статус
            db.update_ticket_status(ticket_id, 'выполнена', 'telegram_bot')
            
            # Сохраняем в базу знаний
            kb_saved, article_id = save_to_knowledge_base(ticket, work_details=work_details if work_details else None)
            
            address = ticket['address'].replace('подъезд', 'п').replace('Подъезд', 'П')
            months = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
            try:
                dt = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
                dt = dt + timedelta(hours=4)
                created = f"{dt.day} {months[dt.month]} {dt.hour:02d}:{dt.minute:02d}"
            except:
                created = ticket['created_at'][:16].replace('T', ' ')
            
            kb_msg = f"\n📚 Сохранено в базу знаний (статья #{article_id})" if kb_saved else ""
            
            await query.edit_message_text(
                f"✅ Завершена!{kb_msg}\n\n"
                f"📍 {address}\n"
                f"⏰ {created}\n\n"
                "📚 Фото и отчет сохранены для анализа и помощи в будущих ремонтах.\n\n"
                "Спасибо за работу! 💪"
            )
            
            # Очищаем данные
            if chat_id in user_data:
                del user_data[chat_id]
        
        elif action == "photo":
            # Запрашиваем фотоотчёт
            user_data[chat_id] = {'ticket_id': ticket_id, 'status': 'awaiting_photos'}
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=f"ticket_{ticket_id}")]]
            await query.edit_message_text(
                "📸 Отправьте фото выполненной работы",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif action == "desc":
            # Запрашиваем описание ремонта
            user_data[chat_id] = {'ticket_id': ticket_id, 'status': 'awaiting_work_details'}
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=f"ticket_{ticket_id}")]]
            await query.edit_message_text(
                f"📝 Введите описание выполненных работ для заявки #{ticket['ticket_number']}:\n\n"
                f"Проблема: {ticket.get('problem_description', 'N/A')[:100]}...\n\n"
                "Что было сделано?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото от механика: скачивает и сохраняет локально"""
    chat_id = update.effective_chat.id
    
    if chat_id not in user_data or user_data[chat_id].get('status') not in ['awaiting_photos', 'awaiting_photos_complete']:
        await update.message.reply_text("ℹ️ Отправьте /start для регистрации")
        return
    
    ticket_id = user_data[chat_id]['ticket_id']
    
    # Получаем фото (самое большое разрешение)
    photo = update.message.photo[-1]
    file_id = photo.file_id
    
    # Скачиваем фото
    bot = Bot(token=BOT_TOKEN)
    file = await bot.get_file(file_id)
    
    # Создаем папку для заявки
    ticket_dir = f"uploads/ticket_{ticket_id}"
    os.makedirs(ticket_dir, exist_ok=True)
    
    # Генерируем имя файла: before_17022026_1234.jpg или after_...
    timestamp = datetime.now().strftime("%d%m%Y_%H%M")
    file_path = f"{ticket_dir}/photo_{timestamp}.jpg"
    
    # Скачиваем
    await file.download_to_drive(file_path)
    
    # Сохраняем путь в БД вместо file_id
    db.add_comment(ticket_id, 'mechanic', f'[ФОТО] {file_path}')
    
    # Увеличиваем счётчик фото
    if 'photo_count' not in user_data[chat_id]:
        user_data[chat_id]['photo_count'] = 0
    user_data[chat_id]['photo_count'] += 1
    
    photo_count = user_data[chat_id]['photo_count']
    
    # Показываем подтверждение с кнопкой завершить
    keyboard = [[InlineKeyboardButton("✅ Завершить", callback_data=f"quick_ready_{ticket_id}")]]
    
    await update.message.reply_text(
        f"📸 Фото #{photo_count} сохранено!\n\n"
        "Можете отправить ещё фото или описание работ.\n"
        "Нажмите 'Завершить' когда всё будет готово.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def complete_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение заявки - запрос деталей ремонта"""
    chat_id = update.effective_chat.id
    
    if chat_id not in user_data or 'ticket_id' not in user_data[chat_id]:
        await update.message.reply_text("❌ Нет активной заявки")
        return
    
    ticket_id = user_data[chat_id]['ticket_id']
    ticket = db.get_ticket(ticket_id)
    
    # Запрашиваем описание выполненных работ
    user_data[chat_id]['status'] = 'awaiting_work_details'
    
    await update.message.reply_text(
        f"📝 Введите описание выполненных работ для заявки #{ticket['ticket_number']}:\n\n"
        f"Проблема: {ticket.get('problem_description', 'N/A')[:100]}...\n\n"
        "Что было сделано? (или нажмите /skip для пропуска)"
    )


async def handle_work_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода деталей ремонта"""
    chat_id = update.effective_chat.id
    
    if chat_id not in user_data or user_data[chat_id].get('status') != 'awaiting_work_details':
        return
    
    new_text = update.message.text
    ticket_id = user_data[chat_id]['ticket_id']
    
    # Накапливаем описание работ
    if 'work_details' not in user_data[chat_id]:
        user_data[chat_id]['work_details'] = ""
    
    if user_data[chat_id]['work_details']:
        user_data[chat_id]['work_details'] += "\n" + new_text
    else:
        user_data[chat_id]['work_details'] = new_text
    
    # Сохраняем в БД как комментарий
    db.add_comment(ticket_id, 'mechanic', f'📝 {new_text}')
    
    work_details = user_data[chat_id]['work_details']
    lines = work_details.count('\n') + 1
    
    # Показываем подтверждение с кнопкой завершить
    keyboard = [[InlineKeyboardButton("✅ Завершить", callback_data=f"quick_ready_{ticket_id}")]]
    
    await update.message.reply_text(
        f"📝 Сохранено! (часть {lines})\n\n"
        "Можете отправить ещё фото или описание.\n"
        "Нажмите 'Завершить' когда всё будет готово.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def skip_work_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропустить ввод деталей и завершить"""
    chat_id = update.effective_chat.id
    
    if chat_id not in user_data or user_data[chat_id].get('status') != 'awaiting_work_details':
        await update.message.reply_text("❌ Нет активной операции")
        return
    
    ticket_id = user_data[chat_id]['ticket_id']
    ticket = db.get_ticket(ticket_id)
    work_details = user_data[chat_id].get('work_details', '')
    
    # Проверяем, есть ли фото
    has_photos = False
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM ticket_photos WHERE ticket_id = ?", (ticket_id,))
        has_photos = cursor.fetchone()[0] > 0
    
    # Обновляем статус
    db.update_ticket_status(ticket_id, 'выполнена', 'telegram_bot')
    
    # Сохраняем в базу знаний
    kb_saved, article_id = save_to_knowledge_base(ticket, work_details=work_details if work_details else None)
    
    address = ticket['address'].replace('подъезд', 'п').replace('Подъезд', 'П')
    months = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
    try:
        dt = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
        dt = dt + timedelta(hours=4)
        created = f"{dt.day} {months[dt.month]} {dt.hour:02d}:{dt.minute:02d}"
    except:
        created = ticket['created_at'][:16].replace('T', ' ')
    
    photo_text = " с фотоотчётом" if has_photos else ""
    await update.message.reply_text(
        f"✅ Завершена!{photo_text}\n\n"
        f"📍 {address}\n"
        f"⏰ {created}\n\n"
        "📚 Фото и отчет будут сохранены в базу знаний для анализа и помощи в будущих ремонтах.\n\n"
        "Спасибо за работу! 💪"
    )
    
    # Очищаем данные пользователя
    del user_data[chat_id]


async def skip_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропустить фото и завершить заявку"""
    chat_id = update.effective_chat.id
    
    if chat_id not in user_data or user_data[chat_id].get('status') != 'awaiting_photos_complete':
        await update.message.reply_text("❌ Нет заявки для завершения")
        return
    
    ticket_id = user_data[chat_id]['ticket_id']
    ticket = db.get_ticket(ticket_id)
    
    # Обновляем статус
    db.update_ticket_status(ticket_id, 'выполнена', 'telegram_bot')
    
    # Сохраняем в базу знаний
    kb_saved, article_id = save_to_knowledge_base(ticket)
    
    address = ticket['address'].replace('подъезд', 'п').replace('Подъезд', 'П')
    months = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
    try:
        dt = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
        dt = dt + timedelta(hours=4)
        created = f"{dt.day} {months[dt.month]} {dt.hour:02d}:{dt.minute:02d}"
    except:
        created = ticket['created_at'][:16].replace('T', ' ')
    
    await update.message.reply_text(
        f"✅ Завершена!\n\n"
        f"📍 {address}\n"
        f"⏰ {created}\n\n"
        "📚 Фото и отчет будут сохранены в базу знаний для анализа и помощи в будущих ремонтах.\n\n"
        "Спасибо за работу! 💪"
    )
    
    # Очищаем данные пользователя
    del user_data[chat_id]


async def my_lifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать лифты механика"""
    chat_id = update.effective_chat.id
    mechanic = db.get_mechanic_by_telegram(chat_id)
    
    if not mechanic:
        await update.message.reply_text("❌ Вы не зарегистрированы. Отправьте /start")
        return
    
    elevators = db.get_mechanic_elevators(mechanic['id'])
    
    if elevators:
        message = f"🛗 Ваши лифты ({len(elevators)}):\n\n"
        for elevator in elevators:
            message += f"• {elevator['elevator_id']} - {elevator['address']}\n"
    else:
        message = "ℹ️ За вами не закреплены лифты"
    
    await update.message.reply_text(message, reply_markup=get_main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать справку по командам"""
    help_text = (
        "📋 *Доступные команды:*\n\n"
        "🛠️ *Основные:*\n"
        "/start - Регистрация в боте\n"
        "/help - Показать эту справку\n\n"
        "📍 *Работа с заявками:*\n"
        "/my_lifts - Список моих лифтов\n"
        "/my_tickets - Мои текущие заявки\n"
        "/complete - Завершить текущую заявку\n\n"
        "📸 *Отчеты:*\n"
        "Отправьте фото для прикрепления к заявке\n\n"
        "❓ *Помощь:*\n"
        "При проблемах обратитесь к администратору"
    )
    
    await update.message.reply_text(help_text, reply_markup=get_main_keyboard())


async def my_tickets_menu(update, context, filter_type='active'):
    """Показать заявки механика"""
    chat_id = update.effective_chat.id
    
    # Проверяем что это callback query (кнопка нажата)
    if hasattr(update, 'callback_query') and update.callback_query:
        reply_func = update.callback_query.message.edit_text
        query = update.callback_query
        await query.answer()
    else:
        reply_func = update.message.reply_text
    
    mechanic = db.get_mechanic_by_telegram(chat_id)
    
    if not mechanic:
        await reply_func("❌ Вы не зарегистрированы. Отправьте /start")
        return
    
    # Получаем все заявки механика
    all_tickets = db.get_all_mechanic_tickets(mechanic['id'])
    
    # Фильтруем только активные (в работе)
    if filter_type == 'active':
        tickets = [t for t in all_tickets if t.get('status') == 'в работе']
        title = "🔧 Заявки в работе"
    else:
        tickets = all_tickets
        title = "📋 Все заявки"
    
    if not tickets:
        await reply_func(f"{title}\n\nЗаявок нет", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data="back_main_menu")]
        ]))
        return
    
    message = f"{title}\n\n"
    keyboard = []
    
    # Ограничиваем 5 заявками
    display_tickets = tickets[:5]
    
    for ticket in display_tickets:
        status_emoji = "⏳"
        if ticket.get('status') == 'в работе':
            status_emoji = "🔧"
        elif ticket.get('status') == 'выполнена':
            status_emoji = "✅"
        
        address = ticket['address'].replace('подъезд', 'п').replace('Подъезд', 'П').replace(' п.', 'п').replace(' П.', 'П').replace(' ', '').replace('ул.', 'ул.')
        
        # Кнопка без нумерации, эмодзи в начале
        short_addr = address[:20] + "..." if len(address) > 20 else address
        btn_text = f"{status_emoji} {short_addr}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"ticket_{ticket['id']}")])
    
    await reply_func(message, reply_markup=InlineKeyboardMarkup(keyboard))


async def show_tickets_by_status(update, context, status_filter):
    """Показать заявки по статусу"""
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    mechanic = db.get_mechanic_by_telegram(chat_id)
    
    if not mechanic:
        await query.edit_message_text("❌ Вы не зарегистрированы. Отправьте /start")
        return
    
    # Получаем заявки по статусу
    if status_filter == 'new':
        tickets = db.get_mechanic_tickets_by_status(mechanic['id'], 'новая')
        title = "⏳ Новые заявки"
    elif status_filter == 'inwork':
        tickets = db.get_mechanic_tickets_by_status(mechanic['id'], 'в работе')
        title = "🔧 Заявки в работе"
    elif status_filter == 'done':
        tickets = db.get_mechanic_tickets_by_status(mechanic['id'], 'выполнена')
        title = "✅ Завершённые заявки"
    else:
        tickets = db.get_all_mechanic_tickets(mechanic['id'])
        title = "📋 Все заявки"
    
    if not tickets:
        await query.edit_message_text(f"{title}\n\nЗаявок нет", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data="back_tickets_menu")]
        ]))
        return
    
    message = f"{title}\n\n"
    
    # Ограничиваем 3 заявками
    display_tickets = tickets[:3]
    all_dates = []
    
    for ticket in display_tickets:
        status_emoji = "⏳"
        status_text = "Новая"
        if ticket.get('status') == 'в работе':
            status_emoji = "🔧"
            status_text = "В работе"
        elif ticket.get('status') == 'выполнена':
            status_emoji = "✅"
            status_text = "Выполнена"
        
        # Форматируем дату
        try:
            dt = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
            dt = dt + timedelta(hours=4)
            months = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
            created_at_formatted = f"{dt.day} {months[dt.month]} {dt.hour:02d}:{dt.minute:02d}"
            all_dates.append(created_at_formatted)
        except:
            created_at_formatted = ticket['created_at'][:16].replace('T', ' ')
            all_dates.append(created_at_formatted)
        
        address = ticket['address'].replace('подъезд', 'п').replace('Подъезд', 'П').replace(' п.', 'п').replace(' П.', 'П').replace(' ', '').replace('ул.', 'ул.').replace('39', ' 39')
        message += f"{len(all_dates)}. 📍 {address[:35]}\n"
        message += f"   ⚠️ {ticket['priority']} | {status_emoji} {status_text}\n\n"
    
    # Кнопки с адресами всех заявок (до 3-х)
    keyboard = []
    for i, ticket in enumerate(display_tickets):
        address = ticket['address'].replace('подъезд', 'п').replace('Подъезд', 'П').replace(' п.', 'п').replace(' П.', 'П').replace(' ', '').replace('ул.', 'ул.').replace('39', ' 39')
        # Сокращаем адрес и добавляем эмодзи статуса
        short_addr = address[:20] + "..." if len(address) > 20 else address
        status_emoji = "⏳" if ticket.get('status') == 'новая' else "🔧" if ticket.get('status') == 'в работе' else "✅"
        btn_text = f"{i+1}. {short_addr} {status_emoji}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"ticket_{ticket['id']}")])
    
    if len(tickets) > 3:
        message += f"\n... и ещё {len(tickets) - 3} заявок"
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_tickets_menu")])
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))


async def show_ticket_details(update, context):
    """Показать детали заявки"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    ticket_id = int(data.split("_")[1])
    
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        await query.edit_message_text("❌ Заявка не найдена")
        return
    
    # Отмечаем как прочитанное
    chat_id = update.effective_chat.id
    mechanic = db.get_mechanic_by_telegram(chat_id)
    if mechanic:
        db.add_comment(ticket_id, 'system', f'👁️ Заявка просмотрена механиком {mechanic["name"]}')
    
    # Формируем детали
    address = ticket['address'].replace('подъезд', 'п').replace('Подъезд', 'П').replace(' п.', 'п').replace(' П.', 'П').replace(' ', '').replace('ул.', 'ул.').replace('39', ' 39')
    
    # Форматируем дату
    try:
        dt = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
        dt = dt + timedelta(hours=4)
        months = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
        created_at_formatted = f"{dt.day} {months[dt.month]} {dt.year} {dt.hour:02d}:{dt.minute:02d}"
    except:
        created_at_formatted = ticket['created_at'][:16].replace('T', ' ')
    
    message = f"🚨 ЗаЯВКА\n"
    message += f"⏰ {created_at_formatted}\n\n"
    message += f"📍 Адрес: {address}\n"
    message += f"⚠️ Приоритет: {ticket['priority']}\n"
    message += f"📊 Статус: {ticket['status']}\n"
    
    if ticket.get('client_phone'):
        message += f"📞 Телефон: {ticket['client_phone']}\n"
    
    if ticket.get('problem_description'):
        message += f"\n📝 Проблема:\n{ticket['problem_description']}\n"
    
    # Кнопки действий
    keyboard = []
    
    if ticket['status'] == 'новая':
        keyboard.append([InlineKeyboardButton("✅ Принять", callback_data=f"accept_{ticket_id}")])
    elif ticket['status'] == 'в работе':
        keyboard.append([
            InlineKeyboardButton("📸 Добавить фото", callback_data=f"quick_photo_{ticket_id}"),
            InlineKeyboardButton("📝 Описание ремонта", callback_data=f"quick_desc_{ticket_id}")
        ])
        keyboard.append([
            InlineKeyboardButton("🚗 В пути", callback_data=f"quick_onway_{ticket_id}"),
            InlineKeyboardButton("🔧 Запчасти", callback_data=f"quick_parts_{ticket_id}")
        ])
        keyboard.append([InlineKeyboardButton("✅ Завершить", callback_data=f"quick_ready_{ticket_id}")])
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))


# Старый обработчик для обратной совместимости
async def my_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await my_tickets_menu(update, context)


async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых кнопок меню"""
    text = update.message.text
    chat_id = update.effective_chat.id
    
    # Если ожидаем ввод деталей ремонта - обрабатываем отдельно
    if chat_id in user_data:
        status = user_data[chat_id].get('status')
        if status == 'awaiting_work_details':
            await handle_work_details(update, context)
            return
        elif status == 'awaiting_photos':
            # После фото - текст считается описанием работы
            await handle_work_details(update, context)
            return
    
    if text == "🛗 Мои лифты":
        await my_lifts(update, context)
    elif text == "📋 Мои заявки":
        await my_tickets(update, context)
    elif text == "❓ Помощь":
        await help_command(update, context)
    elif text == "✅ Завершить заявку":
        await complete_ticket(update, context)
    else:
        # Если это не кнопка меню, обрабатываем как номер телефона
        await handle_phone(update, context)


async def post_init(application):
    """Инициализация после запуска бота"""
    # Устанавливаем команды меню
    commands = [
        ("start", "Регистрация в боте"),
        ("help", "Показать справку"),
        ("my_lifts", "Мои лифты"),
        ("my_tickets", "Мои заявки"),
        ("complete", "Завершить заявку")
    ]
    await application.bot.set_my_commands(commands)
    print("✅ Команды меню установлены")


def main():
    """Запуск бота"""
    if BOT_TOKEN == "ВАШ_ТОКЕН_БОТА" or not BOT_TOKEN:
        print("❌ Укажите BOT_TOKEN в файле!")
        print("1. Создайте бота у @BotFather")
        print("2. Замените ВАШ_ТОКЕН_БОТА на реальный токен")
        return
    
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("complete", complete_ticket))
    application.add_handler(CommandHandler("done", complete_ticket))
    application.add_handler(CommandHandler("skip", skip_photos))
    application.add_handler(CommandHandler("skip_work", skip_work_details))
    application.add_handler(CommandHandler("my_lifts", my_lifts))
    application.add_handler(CommandHandler("my_tickets", my_tickets))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons))
    
    print("🤖 Telegram бот запущен!")
    print("Отправьте /start боту для регистрации")
    
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
