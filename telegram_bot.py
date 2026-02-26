"""
Telegram Bot для механиков
Отправляет заявки и принимает отчеты с фото
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

import os
import asyncio
from datetime import datetime
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
    
    # Формируем сообщение (без markdown для безопасности)
    message = f"🚨 НОВАЯ ЗАЯВКА #{ticket['ticket_number']}\n\n"
    message += f"📍 Адрес: {ticket['address']}\n"
    
    if elevator:
        message += f"🛗 Лифт: {elevator['elevator_id']}\n"
        if elevator.get('entrance'):
            message += f"🏢 Подъезд: {elevator['entrance']}\n"
    
    message += f"⚠️ Приоритет: {ticket['priority']}\n"
    message += f"📝 Проблема:\n{ticket['problem_description']}\n\n"
    message += f"⏰ Создана: {ticket['created_at'][:16]}"
    
    # Кнопки действий
    keyboard = [
        [
            InlineKeyboardButton("✅ Принять", callback_data=f"accept_{ticket_id}"),
            InlineKeyboardButton("❌ Отказаться", callback_data=f"reject_{ticket_id}")
        ]
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
        
        # Обновляем статус заявки
        db.update_ticket(ticket_id, {'assigned_to': str(mechanic['id'])}, 'telegram_bot')
        db.update_ticket_status(ticket_id, 'в работе', 'telegram_bot')
        
        # Логируем принятие
        db.accept_ticket(ticket_id, mechanic['id'])
        
        await query.edit_message_text(
            query.message.text + "\n\n✅ ЗАЯВКА ПРИНЯТА"
        )
        
        # Сохраняем ID заявки для приема фото
        user_data[chat_id] = {'ticket_id': ticket_id, 'status': 'awaiting_photos'}
    
    elif data.startswith("reject_"):
        ticket_id = int(data.split("_")[1])
        
        # Логируем отказ
        mechanic = db.get_mechanic_by_telegram(chat_id)
        name = mechanic['name'] if mechanic else "Неизвестный"
        
        db.add_comment(ticket_id, 'system', f"❌ Механик {name} отказался от заявки")
        
        # Логируем отказ в таблице
        if mechanic:
            db.reject_ticket(ticket_id, mechanic['id'])
        
        await query.edit_message_text(
            query.message.text + "\n\n❌ ВЫ ОТКАЗАЛИСЬ ОТ ЗАЯВКИ"
        )
    
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
                [InlineKeyboardButton("❌ Не смог выполнить", callback_data=f"cant_fix_{ticket_id}")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_tickets")]
            ])
        )

    elif data.startswith("cant_fix_"):
        ticket_id = int(data.split("_")[1])
        
        # Логируем неудачу
        mechanic = db.get_mechanic_by_telegram(chat_id)
        name = mechanic['name'] if mechanic else "Неизвестный"
        
        db.add_comment(ticket_id, 'system', f"⚠️ Механик {name} не смог выполнить заявку и вернул её в очередь.")
        
        # Сбрасываем статус на "новая" и убираем исполнителя
        # ВАЖНО: assigned_to ставим NULL или пустую строку, чтобы другие могли взять
        db.update_ticket(ticket_id, {'assigned_to': None}, 'telegram_bot')
        db.update_ticket_status(ticket_id, 'новая', 'telegram_bot', notes=f"Вернута механиком {name}")
        
        await query.edit_message_text(
            f"⚠️ Заявка возвращена в статус 'Новая'.\nОператор уведомлен."
        )
        if chat_id in user_data:
            del user_data[chat_id]

    elif data.startswith("back_to_tickets"):
        await my_tickets(update, context)
    
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


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото от механика: скачивает и сохраняет локально"""
    chat_id = update.effective_chat.id
    
    if chat_id not in user_data or user_data[chat_id].get('status') != 'awaiting_photos':
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
    
    await update.message.reply_text(
        f"📸 Фото сохранено: {file_path.split('/')[-1]}\n"
        "Отправьте еще фото или нажмите /complete для завершения заявки."
    )


async def complete_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение заявки"""
    chat_id = update.effective_chat.id
    
    if chat_id not in user_data or 'ticket_id' not in user_data[chat_id]:
        await update.message.reply_text("❌ Нет активной заявки")
        return
    
    ticket_id = user_data[chat_id]['ticket_id']
    
    # Обновляем статус
    ticket = db.update_ticket_status(ticket_id, 'выполнена', 'telegram_bot')
    
    if ticket:
        await update.message.reply_text(
            f"✅ Заявка #{ticket['ticket_number']} завершена!\n\n"
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


async def my_tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать текущие заявки механика с кнопками выбора"""
    chat_id = update.effective_chat.id
    
    # Определяем объект для отправки ответа (callback или обычное сообщение)
    if update.callback_query:
        reply_func = update.callback_query.message.reply_text
    else:
        reply_func = update.message.reply_text

    mechanic = db.get_mechanic_by_telegram(chat_id)
    
    if not mechanic:
        await reply_func("❌ Вы не зарегистрированы. Отправьте /start")
        return
    
    tickets = db.get_mechanic_active_tickets(mechanic['id'])
    
    if not tickets:
        await reply_func("ℹ️ У вас нет активных заявок", reply_markup=get_main_keyboard())
        return
    
    message = "📋 Ваши активные заявки:\n\n"
    keyboard = []
    
    for i, ticket in enumerate(tickets, 1):
        status_emoji = "⏳"
        status_text = "Новая"
        if ticket.get('status') == 'в работе':
            status_emoji = "🔧"
            status_text = "В работе"
        elif ticket.get('status') == 'выполнена':
            status_emoji = "✅"
            status_text = "Выполнена"
        
        message += f"{i}. 🚨 #{ticket['ticket_number']}\n"
        message += f"   📍 {ticket['address'][:30]}...\n"
        message += f"   ⚠️ {ticket['priority']} | {status_emoji} {status_text}\n\n"
        
        # Кнопка для выбора заявки
        keyboard.append([InlineKeyboardButton(f"Выбрать #{ticket['ticket_number']}", callback_data=f"select_{ticket['id']}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await reply_func(message, reply_markup=reply_markup)


async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых кнопок меню"""
    text = update.message.text
    
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
