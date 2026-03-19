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
import subprocess
from datetime import datetime, timedelta
from PIL import Image
from io import BytesIO
from ticket_db import db

# Загрузка переменных окружения
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Импорты для Telegram Bot
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
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


def create_key_thumbnail(image_path, size=(240, 80)):
    """Создаёт узкое превью для фото подъезда (горизонтальная полоска) с центральным кропом"""
    try:
        img = Image.open(image_path)
        
        # Учитываем ориентацию из EXIF
        try:
            exif = img.getexif()
            orientation = exif.get(0x0112)  # Orientation tag
            if orientation == 2:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            elif orientation == 3:
                img = img.rotate(180, expand=True)
            elif orientation == 4:
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
            elif orientation == 5:
                img = img.transpose(Image.FLIP_LEFT_RIGHT).rotate(90, expand=True)
            elif orientation == 6:
                img = img.rotate(270, expand=True)
            elif orientation == 7:
                img = img.transpose(Image.FLIP_LEFT_RIGHT).rotate(270, expand=True)
            elif orientation == 8:
                img = img.rotate(90, expand=True)
        except Exception:
            pass
        
        target_w, target_h = size
        orig_w, orig_h = img.size
        
        # Центральный кроп - вычисляем квадрат из центра
        crop_size = min(orig_w, orig_h)
        left = (orig_w - crop_size) // 2
        top = (orig_h - crop_size) // 2
        right = left + crop_size
        bottom = top + crop_size
        
        # Обрезаем центр
        img = img.crop((left, top, right, bottom))
        
        # Теперь растягиваем/сжимаем до нужного размера
        img = img.resize(size, Image.Resampling.LANCZOS)
        
        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=80)
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f"⚠️ Ошибка создания миниатюры: {e}")
        return None


def create_video_thumbnail(video_path, output_path, size=(100, 100)):
    """Создаёт превью из видео с помощью ffmpeg"""
    try:
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-ss', '00:00:01',  # Кадр на 1 секунде
            '-vframes', '1',
            '-vf', f'scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease,pad={size[0]}:{size[1]}:(ow-iw)/2:(oh-ih)/2',
            '-q:v', '3',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        return None
    except Exception as e:
        print(f"⚠️ Ошибка создания превью видео: {e}")
        return None


# Хранилище временных данных
user_data = {}

# URL базы знаний
KB_URL = os.getenv('KNOWLEDGE_BASE_URL', 'http://knowledge.lift-system.crazedns.ru')


def save_to_knowledge_base(ticket, mechanic_name=None, work_details=None):
    """Сохраняет отчёт о ремонте в базу знаний"""
    try:
        # Собираем фото
        photos = []
        videos = []
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT text FROM comments WHERE ticket_id = ? AND author = 'mechanic' AND text LIKE '[ФОТО]%'",
                (ticket['id'],)
            )
            for row in cursor.fetchall():
                photo_path = row[0].replace('[ФОТО] ', '')
                photos.append(photo_path)
            
            # Собираем видео
            cursor.execute(
                "SELECT text FROM comments WHERE ticket_id = ? AND author = 'mechanic' AND text LIKE '[ВИДЕО]%'",
                (ticket['id'],)
            )
            for row in cursor.fetchall():
                video_path = row[0].replace('[ВИДЕО] ', '')
                videos.append(video_path)
        
        # Получаем серийный номер и тип лифта
        serial_number = None
        elevator_type = 'пассажирский'
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT serial_number FROM elevators WHERE elevator_id = ?",
                (ticket.get('elevator_id'),)
            )
            row = cursor.fetchone()
            if row:
                serial_number = row[0]
        
        # Формируем решение (все текстовые описания работ)
        all_work_details = []
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT text FROM comments WHERE ticket_id = ? AND author = 'mechanic' AND text LIKE '📝%' ORDER BY id",
                (ticket['id'],)
            )
            for row in cursor.fetchall():
                text = row[0].replace('📝 ', '')
                all_work_details.append(text)
        
        solution = '\n\n'.join(all_work_details) if all_work_details else (work_details if work_details else 'Ремонт выполнен')
        
        # Формируем симптомы (проблема)
        symptoms = [ticket.get('problem_description', '')]
        
        # Формируем данные для KB
        data = {
            'title': f"{ticket.get('problem_description', 'Ремонт лифта')[:50]}",
            'content': ticket.get('problem_description', ''),
            'symptoms': symptoms,
            'solution': solution,
            'category': 'ремонт',
            'serial_number': serial_number,
            'photos': photos,
            'videos': videos,
            'tags': ['ремонт'],
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


async def notify_other_mechanics_about_accept(ticket_id, accepted_mechanic_id, accepted_name, accepted_chat_id):
    """Уведомление других механиков о принятии заявки"""
    try:
        # Получаем всех механиков, которым отправлялась заявка
        ticket_mechs = db.get_ticket_mechanics(ticket_id)
        
        if not ticket_mechs:
            return
        
        ticket = db.get_ticket(ticket_id)
        if not ticket:
            return
        
        # Адрес для уведомления
        address_clean = ticket['address']
        for prefix in ['подъезд ', 'Подъезд ', 'п. ', 'П. ']:
            if prefix in address_clean.lower():
                address_clean = address_clean.split(prefix)[0].rstrip()
        
        message = f"⚠️ Заявка принята другим механиком\n\n"
        message += f"📍 {address_clean}\n"
        message += f"👤 Принял: {accepted_name}\n\n"
        message += f"Заявка уже в работе"
        
        bot = Bot(token=BOT_TOKEN)
        
        # Отправляем всем, кроме принявшего
        for tm in ticket_mechs:
            if tm['mechanic_id'] == accepted_mechanic_id:
                continue
            
            mech = db.get_mechanic(tm['mechanic_id'])
            if mech and mech.get('telegram_chat_id'):
                try:
                    await bot.send_message(
                        chat_id=mech['telegram_chat_id'],
                        text=message
                    )
                except Exception as e:
                    print(f"⚠️ Не удалось уведомить {mech['name']}: {e}")
    
    except Exception as e:
        print(f"⚠️ Ошибка уведомления других механиков: {e}")


async def notify_all_mechanics_about_completion(ticket_id, completed_by_name):
    """Уведомление всех участников о завершении заявки"""
    try:
        # Получаем всех механиков, которым отправлялась заявка
        ticket_mechs = db.get_ticket_mechanics(ticket_id)
        
        if not ticket_mechs:
            return
        
        ticket = db.get_ticket(ticket_id)
        if not ticket:
            return
        
        # Адрес для уведомления
        address_clean = ticket['address']
        for prefix in ['подъезд ', 'Подъезд ', 'п. ', 'П. ']:
            if prefix in address_clean.lower():
                address_clean = address_clean.split(prefix)[0].rstrip()
        
        # Получаем фото и описание
        comments = db.get_comments(ticket_id)
        photos_count = sum(1 for c in comments if c.get('text', '').startswith('[ФОТО]'))
        videos_count = sum(1 for c in comments if c.get('text', '').startswith('[ВИДЕО]'))
        
        work_comments = [c.get('text', '').replace('📝 ', '') for c in comments if c.get('text', '').startswith('📝')]
        work_text = work_comments[0][:100] if work_comments else "Нет описания"
        
        message = f"✅ Заявка завершена!\n\n"
        message += f"📍 {address_clean}\n"
        message += f"👤 Завершил: {completed_by_name}\n"
        if photos_count > 0:
            message += f"📷 Фото: {photos_count}\n"
        if videos_count > 0:
            message += f"🎥 Видео: {videos_count}\n"
        if work_text:
            message += f"📝 {work_text}..."
        
        bot = Bot(token=BOT_TOKEN)
        
        # Отправляем всем участникам
        for tm in ticket_mechs:
            mech = db.get_mechanic(tm['mechanic_id'])
            if mech and mech.get('telegram_chat_id'):
                try:
                    await bot.send_message(
                        chat_id=mech['telegram_chat_id'],
                        text=message
                    )
                except Exception as e:
                    print(f"⚠️ Не удалось уведомить {mech['name']}: {e}")
    
    except Exception as e:
        print(f"⚠️ Ошибка уведомления о завершении: {e}")


async def send_ticket_to_mechanic(ticket_id, mechanic_chat_id):
    """Отправка заявки механику"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return False
    
    # Получаем информацию о лифте
    elevator = db.get_elevator(ticket.get('elevator_id'))
    
    # Формируем дату в формате "15 марта 22:01"
    try:
        dt = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
        dt = dt + timedelta(hours=4)  # Самара
        months = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
        created_at_formatted = f"{dt.day} {months[dt.month]} {dt.hour:02d}:{dt.minute:02d}"
    except:
        created_at_formatted = ticket['created_at'][5:16].replace('T', ' ')
    
    message = f"🚨 <b>НОВАЯ ЗАЯВКА</b>\n"
    message += f"⏰ <b>{created_at_formatted}</b>\n\n"
    
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
        
        # Отправляем фото подъезда с текстом как caption (фото внутри карточки)
        if elevator and elevator.get('key_photo'):
            key_photo_path = elevator['key_photo'].lstrip('/')
            full_path = f"/Users/swiftpanaev/KIRO/test4/{key_photo_path}"
            try:
                # Быстрое уменьшение до маленького размера
                img = Image.open(full_path)
                w, h = img.size
                
                # Если изображение слишком большое, уменьшаем его сразу
                max_size = 400
                if w > max_size or h > max_size:
                    if w > h:
                        new_w = max_size
                        new_h = int(h * (max_size / w))
                    else:
                        new_h = max_size
                        new_w = int(w * (max_size / h))
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                
                buffer = BytesIO()
                img.save(buffer, format='JPEG', quality=60, optimize=True)
                buffer.seek(0)
                
                await bot.send_photo(
                    chat_id=mechanic_chat_id,
                    photo=buffer,
                    caption=message,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return True
            except Exception as e:
                print(f"⚠️ Ошибка отправки фото подъезда: {e}")
        
        # Если нет фото или ошибка - отправляем текст
        await bot.send_message(
            chat_id=mechanic_chat_id,
            text=message,
            parse_mode='HTML',
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
        
        # Проверяем, не принята ли уже заявка
        ticket = db.get_ticket(ticket_id)
        if ticket and ticket.get('status') == 'в работе':
            await query.answer("Заявка уже принята", show_alert=True)
            return
        
        # Получаем данные текущего механика
        mechanic = db.get_mechanic_by_telegram(chat_id)
        print(f"DEBUG: mechanic = {mechanic}")
        
        if not mechanic:
            print(f"DEBUG: mechanic not found!")
            return
        
        name = mechanic['name']
        
        # Обновляем статус заявки на "в работу" (не меняем assigned_to - несколько механиков могут работать)
        db.update_ticket_status(ticket_id, 'в работе', 'telegram_bot')
        
        # Логируем принятие
        db.accept_ticket(ticket_id, mechanic['id'])
        db.add_comment(ticket_id, 'system', f"👤 Механик {name} принял заявку в работу")
        
        # Уведомляем других механиков о принятии
        await notify_other_mechanics_about_accept(ticket_id, mechanic['id'], name, chat_id)
        
        message = f"✅ Заявка принята в работу!\n\n📸 Отправьте фото, видео или описание работ"
        
        keyboard = [
            [InlineKeyboardButton("✅ Завершить", callback_data=f"quick_ready_{ticket_id}")]
        ]
        
        # Отправляем новое сообщение (не редактируем)
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
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
        
        user_data[chat_id] = {'selected_ticket': ticket_id, 'ticket_id': ticket_id, 'status': 'awaiting_photos'}
        
        await query.edit_message_text(
            f"✅ Выбрана заявка #{ticket['ticket_number']}\n\n"
            f"📍 {ticket['address']}\n"
            f"⚠️ {ticket['priority']}\n\n"
            f"Отправьте фото, видео или описание работ:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Завершить", callback_data=f"quick_ready_{ticket_id}")]
            ])
        )

    elif data.startswith("cant_fix_"):
        # Функция возврата заявки отключена
        await query.answer("Функция недоступна", show_alert=True)

    elif data.startswith("back_to_tickets"):
        await my_tickets_menu(update, context)
    
    # Новые обработчики для меню заявок
    elif data == "status_new" or data == "tickets_new":
        # Очищаем данные пользователя
        if chat_id in user_data:
            user_data[chat_id]['ticket_id'] = None
            user_data[chat_id]['status'] = None
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
    
    elif data == "my_tickets":
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
        
        mechanic = db.get_mechanic_by_telegram(chat_id)
        name = mechanic['name'] if mechanic else "Механик"
        
        if ticket:
            # Уведомляем участников
            await notify_all_mechanics_about_completion(ticket_id, name)
            
            await query.edit_message_text(
                f"✅ Заявка #{ticket['ticket_number']} выполнена, завершил {name}\n\n"
                "Спасибо за работу! 💪"
            )
            if chat_id in user_data:
                del user_data[chat_id]
            # Показываем заявки механика
            await my_tickets_menu(update, context)
    
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
                f"✅ Заявка выполнена, завершил {name}{kb_msg}\n\n"
                f"📍 {address}\n"
                f"⏰ {created}\n\n"
                "📚 Фото и отчет сохранены для анализа и помощи в будущих ремонтах.\n\n"
                "Спасибо за работу! 💪"
            )
            
            # Очищаем данные
            if chat_id in user_data:
                del user_data[chat_id]
            
            # Уведомляем участников
            await notify_all_mechanics_about_completion(ticket_id, name)
            
            # Показываем заявки механика
            await my_tickets_menu(update, context)
            
            # Уведомляем всех участников о завершении
            await notify_all_mechanics_about_completion(ticket_id, name)
        
        elif action == "photo":
            if chat_id not in user_data:
                user_data[chat_id] = {}
            if 'ticket_id' not in user_data[chat_id]:
                user_data[chat_id]['ticket_id'] = ticket_id
            user_data[chat_id]['status'] = 'awaiting_photos'
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=f"ticket_{ticket_id}")]]
            await query.edit_message_text(
                "📸 Отправьте фото выполненной работы",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif action == "video":
            if chat_id not in user_data:
                user_data[chat_id] = {}
            if 'ticket_id' not in user_data[chat_id]:
                user_data[chat_id]['ticket_id'] = ticket_id
            user_data[chat_id]['status'] = 'awaiting_photos'
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=f"ticket_{ticket_id}")]]
            await query.edit_message_text(
                "🎥 Отправьте видео выполненной работы",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif action == "desc":
            # Запрашиваем описание ремонта - сохраняем существующие данные
            if chat_id not in user_data:
                user_data[chat_id] = {}
            # Сохраняем существующие данные
            if 'ticket_id' not in user_data[chat_id]:
                user_data[chat_id]['ticket_id'] = ticket_id
            user_data[chat_id]['status'] = 'awaiting_work_details'
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
    
    # Генерируем имя файла: photo_12032026_194430.jpg (с секундами)
    timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
    file_path = f"{ticket_dir}/photo_{timestamp}.jpg"
    
    # Скачиваем
    await file.download_to_drive(file_path)
    
    # Сохраняем путь в БД вместо file_id
    db.add_comment(ticket_id, 'mechanic', f'[ФОТО] {file_path}')
    
    # Увеличиваем счётчик фото
    if 'photo_count' not in user_data[chat_id]:
        user_data[chat_id]['photo_count'] = 0
    user_data[chat_id]['photo_count'] += 1
    user_data[chat_id]['status'] = 'awaiting_photos_complete'
    
    photo_count = user_data[chat_id]['photo_count']
    
    # Показываем подтверждение с кнопками
    keyboard = [
        [InlineKeyboardButton("✅ Завершить", callback_data=f"quick_ready_{ticket_id}")]
    ]
    
    await update.message.reply_text(
        f"📸 Фото #{photo_count} сохранено!\n\n"
        "Нажмите 'Завершить' когда всё будет готово.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка видео от механика"""
    chat_id = update.effective_chat.id
    
    if chat_id not in user_data or user_data[chat_id].get('status') not in ['awaiting_photos', 'awaiting_photos_complete']:
        await update.message.reply_text("ℹ️ Отправьте /start для регистрации")
        return
    
    ticket_id = user_data[chat_id]['ticket_id']
    
    # Получаем видео
    video = update.message.video
    file_id = video.file_id
    
    # Скачиваем видео
    bot = Bot(token=BOT_TOKEN)
    file = await bot.get_file(file_id)
    
    # Создаем папку для заявки
    ticket_dir = f"uploads/ticket_{ticket_id}"
    os.makedirs(ticket_dir, exist_ok=True)
    
    # Генерируем имя файла с секундами
    timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
    file_path = f"{ticket_dir}/video_{timestamp}.mp4"
    
    # Скачиваем
    await file.download_to_drive(file_path)
    
    # Создаём превью видео
    thumb_path = file_path.replace('.mp4', '_thumb.jpg')
    create_video_thumbnail(file_path, thumb_path, size=(100, 100))
    
    # Сохраняем путь в БД (видео + превью через |)
    thumb_comment = f'[ВИДЕО] {file_path}|{thumb_path}' if os.path.exists(thumb_path) else f'[ВИДЕО] {file_path}'
    db.add_comment(ticket_id, 'mechanic', thumb_comment)
    
    # Увеличиваем счётчик
    if 'video_count' not in user_data[chat_id]:
        user_data[chat_id]['video_count'] = 0
    user_data[chat_id]['video_count'] += 1
    user_data[chat_id]['status'] = 'awaiting_photos_complete'
    
    video_count = user_data[chat_id]['video_count']
    
    # Показываем подтверждение
    keyboard = [
        [InlineKeyboardButton("✅ Завершить", callback_data=f"quick_ready_{ticket_id}")]
    ]
    
    await update.message.reply_text(
        f"🎥 Видео #{video_count} сохранено!\n\n"
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
    print(f"DEBUG handle_work_details: chat_id={chat_id}, user_data={user_data.get(chat_id)}")
    
    if chat_id not in user_data or user_data[chat_id].get('status') not in ['awaiting_work_details', 'awaiting_photos_complete']:
        print(f"DEBUG: status not awaiting_work_details/awaiting_photos_complete, got: {user_data.get(chat_id, {}).get('status')}")
        return
    
    new_text = update.message.text
    ticket_id = user_data[chat_id]['ticket_id']
    print(f"DEBUG: saving text for ticket {ticket_id}: {new_text[:30]}")
    
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
    
    # Показываем подтверждение с кнопками
    keyboard = [
        [InlineKeyboardButton("✅ Завершить", callback_data=f"quick_ready_{ticket_id}")]
    ]
    
    await update.message.reply_text(
        f"📝 Сохранено! (часть {lines})\n\n"
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
    
    mechanic = db.get_mechanic_by_telegram(chat_id)
    name = mechanic['name'] if mechanic else "Механик"
    
    # Проверяем, есть ли фото через комментарии
    has_photos = False
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM comments WHERE ticket_id = ? AND text LIKE '[ФОТО] %'", (ticket_id,))
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
        f"✅ Заявка выполнена, завершил {name}{photo_text}\n\n"
        f"📍 {address}\n"
        f"⏰ {created}\n\n"
        "📚 Фото и отчет будут сохранены в базу знаний для анализа и помощи в будущих ремонтах.\n\n"
        "Спасибо за работу! 💪"
    )
    
    # Очищаем данные пользователя
    del user_data[chat_id]
    
    # Показываем заявки механика
    await my_tickets_menu(update, context)


async def skip_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропустить фото и завершить заявку"""
    chat_id = update.effective_chat.id
    
    if chat_id not in user_data or user_data[chat_id].get('status') != 'awaiting_photos_complete':
        await update.message.reply_text("❌ Нет заявки для завершения")
        return
    
    ticket_id = user_data[chat_id]['ticket_id']
    ticket = db.get_ticket(ticket_id)
    
    mechanic = db.get_mechanic_by_telegram(chat_id)
    name = mechanic['name'] if mechanic else "Механик"
    
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
        f"✅ Заявка выполнена, завершил {name}\n\n"
        f"📍 {address}\n"
        f"⏰ {created}\n\n"
        "📚 Фото и отчет будут сохранены в базу знаний для анализа и помощи в будущих ремонтах.\n\n"
        "Спасибо за работу! 💪"
    )
    
    # Очищаем данные пользователя
    del user_data[chat_id]
    
    # Показываем заявки механика
    await my_tickets_menu(update, context)


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
    
    await update.message.reply_text(message)


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
    
    # Очищаем данные пользователя
    if chat_id in user_data:
        user_data[chat_id] = {}
    
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
        elif status in ['awaiting_photos', 'awaiting_photos_complete']:
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
        # Обрабатываем как номер телефона
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
    application.add_handler(CommandHandler("stop", lambda u, c: u.message.reply_text("Меню скрыто", reply_markup=ReplyKeyboardRemove())))
    application.add_handler(CommandHandler("menu", lambda u, c: u.message.reply_text("Используйте кнопки в сообщениях", reply_markup=ReplyKeyboardRemove())))
    application.add_handler(CommandHandler("complete", complete_ticket))
    application.add_handler(CommandHandler("done", complete_ticket))
    application.add_handler(CommandHandler("skip", skip_photos))
    application.add_handler(CommandHandler("skip_work", skip_work_details))
    application.add_handler(CommandHandler("my_lifts", my_lifts))
    application.add_handler(CommandHandler("my_tickets", my_tickets))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons))
    
    print("🤖 Telegram бот запущен!")
    print("Отправьте /start боту для регистрации")
    
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
