"""
Placeholder - не используется
Используйте max_bot.py для Max
"""
print("Используйте max_bot.py")

# Хранилище данных пользователей
vk_user_data = {}


def vk_api(method, params):
    """Вызов VK API"""
    params['access_token'] = VK_GROUP_TOKEN
    params['v'] = VK_API_VERSION
    response = requests.post(VK_API_URL + method, params)
    return response.json()


def send_message(user_id, text, keyboard=None, attachment=None):
    """Отправка сообщения в VK"""
    params = {
        'user_id': user_id,
        'message': text,
        'random_id': int(datetime.now().timestamp() * 1000)
    }
    if keyboard:
        params['keyboard'] = json.dumps(keyboard)
    if attachment:
        params['attachment'] = attachment
    
    return vk_api('messages.send', params)


def get_main_keyboard():
    """Клавиатура с основными командами"""
    return {
        'one_time': False,
        'buttons': [
            [{
                'action': {'type': 'text', 'label': '🛗 Мои лифты'}
            }, {
                'action': {'type': 'text', 'label': '📋 Мои заявки'}
            }],
            [{
                'action': {'type': 'text', 'label': '❓ Помощь'}
            }, {
                'action': {'type': 'text', 'label': '✅ Завершить заявку'}
            }]
        ]
    }


def get_ticket_keyboard(ticket_id, status='new'):
    """Клавиатура для работы с заявкой"""
    if status == 'new':
        return {
            'one_time': False,
            'buttons': [
                [{
                    'action': {'type': 'text', 'label': '✅ Принять в работу'}
                }],
                [{
                    'action': {'type': 'text', 'label': '📋 Все заявки'}
                }]
            ]
        }
    elif status == 'in_progress':
        return {
            'one_time': False,
            'buttons': [
                [{
                    'action': {'type': 'text', 'label': '✅ Завершить'}
                }],
                [{
                    'action': {'type': 'text', 'label': '📋 Все заявки'}
                }]
            ]
        }
    return None


async def handle_new_tickets(user_id):
    """Показать новые заявки механику"""
    mechanic = db.get_mechanic_by_vk(user_id)
    if not mechanic:
        return "❌ Вы не зарегистрированы. Отправьте номер телефона."
    
    # Получаем заявки для этого механика
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
        LIMIT 5
    ''', (mechanic['id'], mechanic['id']))
    
    tickets = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]
    conn.close()
    
    if not tickets:
        return "📭 Новых заявок нет.\n\nНажмите '📋 Мои заявки' чтобы увидеть все."
    
    message = f"📋 Новые заявки ({len(tickets)}):\n\n"
    
    for i, ticket in enumerate(tickets, 1):
        status_icon = "🆕" if ticket['status'] == 'новая' else "🔧"
        priority = ticket.get('priority', 'обычный')
        priority_icon = "🚨" if priority == 'срочный' else "⚠️" if priority == 'высокий' else ""
        
        created = ticket.get('created_at', '')
        if created:
            try:
                dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                dt = dt + timedelta(hours=4)
                created = dt.strftime('%H:%M')
            except:
                created = ''
        
        message += f"{i}. {status_icon} {priority_icon}#{ticket.get('ticket_number', ticket['id'])}\n"
        message += f"   📍 {ticket.get('address', 'Адрес не указан')[:50]}\n"
        if created:
            message += f"   🕐 {created}\n"
        message += f"   [Принять](callback:accept_{ticket['id']})\n\n"
    
    message += "\n📋 Все заявки"
    return message


async def handle_my_tickets(user_id, filter_type='active'):
    """Показать заявки механика"""
    mechanic = db.get_mechanic_by_vk(user_id)
    if not mechanic:
        return "❌ Вы не зарегистрированы."
    
    if filter_type == 'active':
        status_filter = "IN ('новая', 'в работе')"
    elif filter_type == 'completed':
        status_filter = "= 'выполнена'"
    else:
        status_filter = "IS NOT NULL"
    
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(f'''
        SELECT DISTINCT t.* FROM tickets t
        LEFT JOIN ticket_mechanics tm ON t.id = tm.ticket_id
        WHERE (tm.mechanic_id = ? OR t.elevator_id IN (
            SELECT elevator_id FROM elevator_mechanics WHERE mechanic_id = ?
        ))
        {'AND t.status ' + status_filter if status_filter != "IS NOT NULL" else ""}
        ORDER BY t.created_at DESC
        LIMIT 10
    ''', (mechanic['id'], mechanic['id']))
    
    tickets = [dict(zip([col[0] for col in cursor.description], row)) for row in cursor.fetchall()]
    conn.close()
    
    if not tickets:
        return "📭 Заявок не найдено."
    
    message = f"📋 Ваши заявки ({len(tickets)}):\n\n"
    
    for ticket in tickets:
        status = ticket['status']
        if status == 'новая':
            icon = "🆕"
        elif status == 'в работе':
            icon = "🔧"
        elif status == 'выполнена':
            icon = "✅"
        else:
            icon = "📌"
        
        message += f"{icon} #{ticket.get('ticket_number', ticket['id'])}\n"
        message += f"   📍 {ticket.get('address', 'Адрес не указан')[:50]}\n"
        message += f"   📌 {status}\n\n"
    
    return message


async def handle_accept_ticket(user_id, ticket_id):
    """Принять заявку в работу"""
    mechanic = db.get_mechanic_by_vk(user_id)
    if not mechanic:
        return "❌ Вы не зарегистрированы."
    
    ticket = db.update_ticket_status(ticket_id, 'в работе', 'vk_bot')
    
    if ticket:
        return (f"✅ Заявка #{ticket.get('ticket_number', ticket_id)} принята в работу!\n\n"
                f"📍 {ticket.get('address', '')}\n\n"
                f"Отправьте фото и описание выполненных работ.")
    else:
        return "❌ Заявка не найдена."


async def handle_complete_ticket(user_id, ticket_id=None):
    """Завершить заявку"""
    mechanic = db.get_mechanic_by_vk(user_id)
    if not mechanic:
        return "❌ Вы не зарегистрированы."
    
    if not ticket_id:
        return "❌ Укажите номер заявки для завершения."
    
    ticket = db.update_ticket_status(ticket_id, 'выполнена', 'vk_bot')
    
    if ticket:
        return (f"✅ Заявка #{ticket.get('ticket_number', ticket_id)} выполнена!\n\n"
                f"📍 {ticket.get('address', '')}\n\n"
                f"Спасибо за работу! 💪")
    else:
        return "❌ Заявка не найдена."


async def handle_photo_upload(user_id, photo_data, ticket_id=None):
    """Обработка загруженного фото"""
    if ticket_id:
        # Сохраняем фото
        upload_dir = f"uploads/ticket_{ticket_id}"
        os.makedirs(upload_dir, exist_ok=True)
        
        filename = f"photo_{datetime.now().strftime('%d%m%Y_%H%M%S')}.jpg"
        filepath = os.path.join(upload_dir, filename)
        
        with open(filepath, 'wb') as f:
            f.write(photo_data)
        
        db.add_comment(ticket_id, 'mechanic', f'[ФОТО] {filepath}')
        
        return f"📸 Фото сохранено для заявки #{ticket_id}"
    
    return "📸 Фото получено. Укажите заявку."


def register_mechanic_vk(user_id, phone):
    """Регистрация механика по телефону"""
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name FROM mechanics WHERE phone = ?', (phone,))
    row = cursor.fetchone()
    
    if row:
        # Обновляем VK ID
        cursor.execute('UPDATE mechanics SET vk_id = ? WHERE id = ?', (user_id, row[0]))
        conn.commit()
        conn.close()
        return True, cursor.execute('SELECT name FROM mechanics WHERE id = ?', (row[0],)).fetchone()[0]
    
    conn.close()
    return False, None


async def process_vk_event(event):
    """Обработка события от VK"""
    event_type = event.get('type')
    
    if event_type == 'confirmation':
        return VK_CONFIRMATION_CODE
    
    if event_type == 'message_new':
        msg = event.get('object', {}).get('message', {})
        user_id = msg.get('user_id')
        text = msg.get('text', '')
        
        # Проверяем зарегистрирован ли механик
        mechanic = db.get_mechanic_by_vk(user_id)
        
        # Обработка команд
        if text == '🛗 Мои лифты':
            # Показать лифты механика
            if mechanic:
                elevators = db.get_mechanic_elevators(mechanic['id'])
                if elevators:
                    message = f"🛗 Ваши лифты ({len(elevators)}):\n\n"
                    for e in elevators:
                        message += f"• {e['elevator_id']} - {e['address']}\n"
                else:
                    message = "ℹ️ За вами не закреплены лифты"
            else:
                message = "❌ Вы не зарегистрированы"
            send_message(user_id, message)
        
        elif text == '📋 Мои заявки':
            message = await handle_my_tickets(user_id)
            send_message(user_id, message, get_main_keyboard())
        
        elif text == '❓ Помощь':
            help_text = """📖 Справка по боту:

🛗 Мои лифты - список закрепленных лифтов
📋 Мои заявки - ваши заявки
✅ Завершить заявку - завершить текущую заявку

📸 Отправьте фото для прикрепления к заявке
❓ Помощь - показать эту справку"""
            send_message(user_id, help_text, get_main_keyboard())
        
        elif text == '✅ Завершить заявку':
            # Завершаем последнюю принятую заявку
            if user_id in vk_user_data and 'ticket_id' in vk_user_data[user_id]:
                ticket_id = vk_user_data[user_id]['ticket_id']
                message = await handle_complete_ticket(user_id, ticket_id)
                send_message(user_id, message)
            else:
                send_message(user_id, "❌ Нет активной заявки для завершения")
        
        elif text.startswith('Принять') or 'accept' in text.lower():
            # Извлекаем ID заявки
            if '_' in text:
                try:
                    ticket_id = int(text.split('_')[1])
                    message = await handle_accept_ticket(user_id, ticket_id)
                    send_message(user_id, message, get_ticket_keyboard(ticket_id, 'in_progress'))
                    
                    # Сохраняем ID заявки
                    if user_id not in vk_user_data:
                        vk_user_data[user_id] = {}
                    vk_user_data[user_id]['ticket_id'] = ticket_id
                except:
                    send_message(user_id, "❌ Неверный формат команды")
        else:
            # Неизвестная команда
            if not mechanic:
                # Регистрация по номеру телефона
                if text.startswith('+'):
                    success, name = register_mechanic_vk(user_id, text)
                    if success:
                        send_message(user_id, f"✅ Регистрация успешна!\n\nДобро пожаловать, {name}!\n\nТеперь вы будете получать заявки на ремонт.", get_main_keyboard())
                    else:
                        send_message(user_id, "❌ Механик с таким номером не найден. Обратитесь к администратору.")
                else:
                    send_message(user_id, "👋 Для регистрации отправьте ваш номер телефона:\n\nПример: +79991234567")
            else:
                send_message(user_id, "ℹ️ Используйте кнопки меню или команды:\n• 🛗 Мои лифты\n• 📋 Мои заявки\n• ❓ Помощь", get_main_keyboard())
    
    return 'ok'


def setup_vk_callback_server():
    """Настройка callback сервера VK"""
    if not VK_GROUP_TOKEN:
        print("⚠️ VK_GROUP_TOKEN не установлен!")
        return False
    
    # Получаем информацию о сервере
    response = vk_api('groups.getById', {})
    if 'response' in response:
        group_id = response['response'][0]['id']
        print(f"✅ VK Bot настроен для группы ID: {group_id}")
        return True
    
    print(f"❌ Ошибка настройки VK: {response}")
    return False


def main():
    """Запуск VK Bot (Long Polling)"""
    print("=" * 50)
    print("🚀 VK Bot для механиков лифтов")
    print("=" * 50)
    
    if not VK_GROUP_TOKEN:
        print("❌ VK_GROUP_TOKEN не установлен!")
        print("Установите переменную окружения: export VK_GROUP_TOKEN='your_token'")
        return
    
    # Настройка callback сервера
    setup_vk_callback_server()
    
    print("✅ VK Bot запущен!")
    print("📱 Ожидание событий...")


if __name__ == '__main__':
    main()
