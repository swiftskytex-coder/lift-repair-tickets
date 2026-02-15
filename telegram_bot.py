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
    await query.answer()
    
    chat_id = update.effective_chat.id
    data = query.data
    
    if data.startswith("accept_"):
        ticket_id = int(data.split("_")[1])
        
        # Обновляем статус заявки
        ticket = db.update_ticket_status(ticket_id, 'в работе', 'telegram_bot')
        
        if ticket:
            await query.edit_message_text(
                query.message.text + "\n\n✅ ЗАЯВКА ПРИНЯТА\n"
                "Отправьте фото до/после ремонта."
            )
            
            # Сохраняем ID заявки для приема фото
            user_data[chat_id] = {'ticket_id': ticket_id, 'status': 'awaiting_photos'}
    
    elif data.startswith("reject_"):
        ticket_id = int(data.split("_")[1])
        await query.edit_message_text(
            query.message.text + "\n\n❌ ЗАЯВКА ОТКЛОНЕНА"
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото от механика"""
    chat_id = update.effective_chat.id
    
    if chat_id not in user_data or user_data[chat_id].get('status') != 'awaiting_photos':
        await update.message.reply_text("ℹ️ Отправьте /start для регистрации")
        return
    
    ticket_id = user_data[chat_id]['ticket_id']
    
    # Получаем фото (самое большое разрешение)
    photo = update.message.photo[-1]
    file_id = photo.file_id
    
    # Сохраняем фото как комментарий к заявке
    db.add_comment(ticket_id, 'mechanic', f'[ФОТО] file_id: {file_id}')
    
    await update.message.reply_text(
        "📸 Фото получено!\n"
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
    """Показать текущие заявки механика"""
    chat_id = update.effective_chat.id
    mechanic = db.get_mechanic_by_telegram(chat_id)
    
    if not mechanic:
        await update.message.reply_text("❌ Вы не зарегистрированы. Отправьте /start")
        return
    
    # Получаем заявки механика со статусом 'в работе'
    tickets = db.get_mechanic_active_tickets(mechanic['id'])
    
    if tickets:
        message = f"📋 Ваши активные заявки ({len(tickets)}):\n\n"
        for ticket in tickets:
            message += f"🚨 #{ticket['ticket_number']}\n"
            message += f"📍 {ticket['address']}\n"
            message += f"⚠️ {ticket['priority']}\n"
            message += f"📝 {ticket['problem_description'][:50]}...\n\n"
    else:
        message = "ℹ️ У вас нет активных заявок"
    
    await update.message.reply_text(message, reply_markup=get_main_keyboard())


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


async def setup_bot_commands(application):
    """Установка команд меню бота"""
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
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Устанавливаем команды меню
    application.job_queue.run_once(lambda context: asyncio.create_task(setup_bot_commands(application)), when=0)
    
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
    
    application.run_polling()


if __name__ == "__main__":
    main()
