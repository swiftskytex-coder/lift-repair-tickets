"""
Главный сервер системы заявок на ремонт лифтов
Flask-based web server for lift repair tickets
"""

import json
import asyncio
import zipfile
import io
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, render_template, send_from_directory, send_file
import shutil
from pathlib import Path
from ticket_db import db

# Самара UTC+4
SAMARA_TZ = ZoneInfo('Europe/Samara')

def now_samara():
    """Текущее время в Самаре"""
    return datetime.now(SAMARA_TZ)

def format_samara(dt):
    """Форматирование даты для Самары"""
    if dt:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        return dt.astimezone(SAMARA_TZ).strftime('%d.%m %H:%M')
    return ''

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['JSON_AS_cii'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

@app.template_filter('samara_time')
def samara_time_filter(dt):
    """Фильтр для отображения времени в Самаре"""
    if not dt:
        return ''
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        # Добавляем 4 часа для Самары (UTC -> Самара)
        dt = dt + timedelta(hours=4)
        months = ['', 'января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
        return f"{dt.day} {months[dt.month]} {dt.hour:02d}:{dt.minute:02d}"
    except:
        return str(dt)[:16]

from werkzeug.exceptions import HTTPException

@app.errorhandler(HTTPException)
def handle_http_exception(e):
    """Обработчик HTTP-ошибок (404, 500 и др.) – всегда возвращаем JSON"""
    return jsonify({'success': False, 'error': e.description}), e.code

@app.errorhandler(Exception)
def handle_exception(e):
    """Глобальный обработчик исключений для возврата JSON"""
    import traceback
    traceback.print_exc()
    # Если запрос ожидает JSON, возвращаем JSON
    if request.is_json or request.path.startswith('/api/'):
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500
    # Иначе стандартный HTML
    return str(e), 500


# Импорт функции отправки уведомлений (если доступна)
try:
    from notification_service import notify_mechanics_about_ticket
    TELEGRAM_NOTIFICATIONS_ENABLED = True
except ImportError:
    TELEGRAM_NOTIFICATIONS_ENABLED = False
    print("⚠️ Telegram notifications not available")


# ═══════════════════════════════════════════════════════════════
# Веб-интерфейс для оператора
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def index():
    """Главная страница - дашборд оператора"""
    stats = db.get_statistics()
    
    # Расчет текущей смены (08:00 - 08:00)
    now = datetime.now()
    if now.hour < 8:
        shift_start = (now - timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    else:
        shift_start = now.replace(hour=8, minute=0, second=0, microsecond=0)
    shift_end = shift_start + timedelta(days=1)
    
    shift_stats = db.get_shift_statistics(
        shift_start.strftime('%Y-%m-%d %H:%M:%S'),
        shift_end.strftime('%Y-%m-%d %H:%M:%S')
    )
    
    # Исключаем выполненные и отмененные заявки из списка последних
    recent_tickets = db.search_tickets(limit=10, exclude_status=['выполнена', 'отменена'])
    
    # Добавляем подъезд и ID лифта к каждой заявке
    for ticket in recent_tickets:
        if ticket.get('elevator_id'):
            elevator = db.get_elevator(ticket['elevator_id'])
            if elevator:
                if elevator.get('entrance'):
                    ticket['entrance'] = f"п.{elevator['entrance']}"
                ticket['elevator_id_display'] = ticket['elevator_id']
    
    # Получить текущего аварийного механика ДО обогащения заявок
    today = datetime.now().strftime('%Y-%m-%d')
    oncall_today = db.get_oncall_mechanic_for_date(today)
    if not oncall_today:
        oncall_today = db.get_next_oncall_mechanic()
    oncall_today_id = oncall_today['id'] if oncall_today else None
    
    # Обогащаем заявки: список механиков с статусами, время в статусе
    for ticket in recent_tickets:
        ticket['is_oncall_today'] = False
        
        # Получаем последний комментарий
        try:
            comments = db.get_comments(ticket['id'])
            if comments:
                ticket['last_comment'] = comments[-1].get('text', '')[:50]
                # Проверяем, было ли просмотрено
                for c in comments:
                    if c.get('text', '').startswith('👁️'):
                        ticket['viewed'] = True
                        break
        except:
            pass
        
        # Получаем полную историю (статусы + комментарии)
        try:
            import json
            history = ticket.get('history', '[]')
            if isinstance(history, str):
                history = json.loads(history)
            
            log_entries = []
            seen = set()
            for h in reversed(history[-10:]):
                action = h.get('action', '')
                if action and action not in seen:
                    # Сокращаем сообщения
                    action = action.replace('Механик ', '').replace('Панаев Александр', 'Панаев')
                    log_entries.append(action[:50])
                    seen.add(action)
            
            # Добавляем комментарии (без дубликатов)
            try:
                comments = db.get_comments(ticket['id'])
                for c in reversed(comments[-5:]):
                    text = c.get('text', '')[:50]
                    if text and text not in seen:
                        log_entries.append(f"💬 {text}")
                        seen.add(text)
            except:
                pass
            
            ticket['ticket_log'] = log_entries[:5]
        except:
            pass
        
        # Рассчитываем время от создания заявки
        in_work_duration = None
        if ticket.get('created_at'):
            try:
                created = datetime.strptime(ticket['created_at'][:19], '%Y-%m-%d %H:%M:%S')
                now = datetime.now() - timedelta(hours=4)
                diff = now - created
                hours = diff.total_seconds() // 3600
                minutes = (diff.total_seconds() % 3600) // 60
                if hours > 0:
                    in_work_duration = f"{int(hours)}ч {int(minutes)}м"
                else:
                    in_work_duration = f"{int(minutes)}м"
                ticket['in_work_duration'] = in_work_duration
            except:
                pass
        
        # Получаем список механиков для этого лифта
        elevator_mechanics = []
        if ticket.get('elevator_id'):
            try:
                elevator_mechanics = db.get_mechanics_for_elevator(ticket['elevator_id'])
            except:
                pass
        
        # Формируем список механиков со статусами
        mechanics_list = []
        assigned_id = ticket.get('assigned_to')
        
        for mech in elevator_mechanics:
            mech_info = {
                'name': mech['name'],
                'id': mech.get('id'),
                'has_telegram': bool(mech.get('telegram_chat_id')),
                'is_oncall': bool(oncall_today_id and mech['id'] == oncall_today_id),
                'status': None  # Принял, Линейный, Аварийный
            }
            
            # Определяем статус
            if assigned_id and str(assigned_id) == str(mech['id']):
                mech_info['status'] = 'Принял'
            elif mech_info['is_oncall']:
                mech_info['status'] = 'Аварийный'
            else:
                mech_info['status'] = 'Линейный'
            
            # Проверяем на дубликат перед добавлением
            if not any(m['id'] == mech['id'] for m in mechanics_list):
                mechanics_list.append(mech_info)
        
        # Добавляем аварийного механика (сегодня или следующий по очереди)
        oncall_to_add = None
        if oncall_today and oncall_today_id:
            if not any(m['id'] == oncall_today_id for m in mechanics_list):
                oncall_to_add = oncall_today
        else:
            # Нет дежурного на сегодня - используем следующего по очереди
            next_oncall = db.get_next_oncall_mechanic()
            if next_oncall and not any(m['id'] == next_oncall['id'] for m in mechanics_list):
                oncall_to_add = next_oncall
        
        if oncall_to_add:
            mechanics_list.append({
                'name': oncall_to_add['name'],
                'id': oncall_to_add.get('id'),
                'has_telegram': bool(oncall_to_add.get('telegram_chat_id')),
                'is_oncall': True,
                'status': 'Аварийный'
            })
        
        # Получаем статусы из таблицы ticket_mechanics (реальный ответ из Telegram)
        ticket_mech_statuses = {}
        if ticket.get('id'):
            try:
                ticket_mechs = db.get_ticket_mechanics(ticket['id'])
                for tm in ticket_mechs:
                    ticket_mech_statuses[str(tm['mechanic_id'])] = tm
            except:
                pass
        
        # Обновляем статусы механиков на основе реальных данных из Telegram
        for mech_info in mechanics_list:
            mech_id = mech_info.get('id')
            if mech_id:
                tm = ticket_mech_statuses.get(str(mech_id))
                if tm:
                    if tm.get('status') == 'accepted':
                        mech_info['tg_status'] = 'accepted'
                    elif tm.get('status') == 'rejected':
                        mech_info['tg_status'] = 'rejected'
                    else:
                        mech_info['tg_status'] = 'sent'
                else:
                    mech_info['tg_status'] = 'sent'
            else:
                mech_info['tg_status'] = 'sent'
        
        # Добавляем принявшего механика, если его нет в списке
        if ticket.get('assigned_to'):
            already_in_list = any(str(m.get('id')) == str(ticket['assigned_to']) for m in elevator_mechanics)
            if not already_in_list:
                try:
                    mech = db.get_mechanic(int(ticket['assigned_to']))
                    if mech:
                        tm = ticket_mech_statuses.get(str(mech['id']), {})
                        mechanics_list.append({
                            'name': mech['name'],
                            'id': mech['id'],
                            'has_telegram': bool(mech.get('telegram_chat_id')),
                            'is_oncall': False,
                            'status': 'Принял',
                            'tg_status': tm.get('status', 'accepted') if tm else 'accepted'
                        })
                except:
                    pass
        
        ticket['mechanics_list'] = mechanics_list
        
        # Статус отправки/ответа
        ticket['was_sent'] = len(mechanics_list) > 0
        ticket['was_accepted'] = False
        ticket['accepted_by'] = None
        
        # Кто принял
        if ticket.get('assigned_to'):
            ticket['was_accepted'] = True
            try:
                mech = db.get_mechanic(int(ticket['assigned_to']))
                ticket['accepted_by'] = mech['name'] if mech else None
            except:
                pass
        
        # Проверяем отказы по комментариям
        ticket['was_rejected'] = False
        ticket['rejected_by'] = None
        if ticket.get('id'):
            try:
                comments = db.get_comments(ticket['id'])
                for c in comments:
                    text = str(c.get('text', '')).lower()
                    if 'отказался' in text:
                        ticket['was_rejected'] = True
                        # Извлекаем имя из комментария
                        import re
                        match = re.search(r'механик\s+(.+?)\s+отказался', str(c.get('text', '')), re.IGNORECASE)
                        if match:
                            ticket['rejected_by'] = match.group(1)
                        break
            except:
                pass
        
        # Расчёт времени в статусе
        try:
            created = datetime.fromisoformat(str(ticket['created_at']).replace(' ', 'T'))
            # Для статуса "в работе" используем updated_at
            if ticket['status'] == 'в работе' and ticket.get('updated_at'):
                status_time = datetime.fromisoformat(str(ticket['updated_at']).replace(' ', 'T'))
            else:
                status_time = created
                
            delta = now - status_time
            total_seconds = int(delta.total_seconds())
            
            if total_seconds < 60:
                ticket['time_in_status'] = f"{total_seconds} сек"
            elif total_seconds < 3600:
                minutes = total_seconds // 60
                ticket['time_in_status'] = f"{minutes} мин"
            elif total_seconds < 86400:
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                ticket['time_in_status'] = f"{hours} ч {minutes} мин"
            else:
                days = total_seconds // 86400
                ticket['time_in_status'] = f"{days} дн"
        except:
            ticket['time_in_status'] = ""
        
        if ticket.get('assigned_to'):
            try:
                mechanic = db.get_mechanic(int(ticket['assigned_to']))
                ticket['mechanic_name'] = mechanic['name'] if mechanic else 'Неизвестный'
                ticket['mechanic_has_telegram'] = bool(mechanic and mechanic.get('telegram_chat_id'))
                if oncall_today_id and mechanic and mechanic['id'] == oncall_today_id:
                    ticket['is_oncall_today'] = True
            except:
                ticket['mechanic_name'] = 'Ошибка ID'
                ticket['mechanic_has_telegram'] = False
    
    # Отладка: выводим информацию о заявках
    print("=== DEBUG recent_tickets ===")
    for t in recent_tickets:
        print(f"Ticket #{t['ticket_number']}: status={t['status']}, assigned_to=[{t.get('assigned_to')}], mechanic=[{t.get('mechanic_name')}]")
    print("============================")
    
    # Организуем заявки по статусу для канбана
    tickets_by_status = {'новая': [], 'в работе': [], 'выполнена': []}
    for t in recent_tickets:
        status = t.get('status', 'новая')
        if status in tickets_by_status:
            tickets_by_status[status].append(t)
    
    return render_template('operator_dashboard.html', 
                         stats=stats,
                         shift_stats=shift_stats,
                         tickets=recent_tickets,
                         tickets_by_status=tickets_by_status,
                         now=datetime.now(),
                         oncall_today=oncall_today)


@app.route('/tickets')
def tickets_list():
    """Страница списка заявок"""
    status = request.args.get('status', '')
    priority = request.args.get('priority', '')
    
    filters = {}
    if status:
        filters['status'] = status
    if priority:
        filters['priority'] = priority
    
    tickets = db.search_tickets(filters=filters if filters else None, limit=100)
    return render_template('tickets_list.html', 
                         tickets=tickets,
                         status_filter=status,
                         priority_filter=priority)


@app.route('/ticket/<int:ticket_id>')
def ticket_detail(ticket_id):
    """Страница деталей заявки"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return "Заявка не найдена", 404
    
    comments = db.get_comments(ticket_id)
    
    # Получить информацию о назначенном механике
    mechanic_info = None
    if ticket.get('assigned_to'):
        mechanic = db.get_mechanic(ticket['assigned_to'])
        if mechanic:
            # Получить статус из Telegram
            tg_status = None
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT status FROM ticket_mechanics 
                    WHERE ticket_id = ? AND mechanic_id = ?
                ''', (ticket_id, ticket['assigned_to']))
                row = cursor.fetchone()
                if row:
                    tg_status = row[0]
            
            mechanic_info = {
                'name': mechanic['name'],
                'phone': mechanic.get('phone'),
                'telegram_username': mechanic.get('telegram_username'),
                'tg_status': tg_status
            }
    
    # Рассчитать время в работе
    in_work_duration = None
    if ticket.get('status') == 'в работе' and ticket.get('updated_at'):
        try:
            updated = datetime.fromisoformat(ticket['updated_at'].replace('Z', '+00:00'))
            updated = updated + timedelta(hours=4)  # Самара
            now = datetime.now() + timedelta(hours=4)
            diff = now - updated
            hours = diff.total_seconds() // 3600
            minutes = (diff.total_seconds() % 3600) // 60
            if hours > 0:
                in_work_duration = f"{int(hours)}ч {int(minutes)}мин"
            else:
                in_work_duration = f"{int(minutes)}мин"
        except:
            pass
    
    return render_template('ticket_detail.html', 
                         ticket=ticket, 
                         comments=comments,
                         mechanic_info=mechanic_info,
                         in_work_duration=in_work_duration)


@app.route('/new-ticket')
def new_ticket_form():
    """Форма создания новой заявки"""
    elevators = db.get_all_elevators(limit=200)
    return render_template('new_ticket.html', elevators=elevators)


@app.route('/elevators')
def elevators_list():
    """Справочник лифтов"""
    elevators = db.get_all_elevators(limit=200)
    
    # Загружаем механиков для каждого лифта
    for elevator in elevators:
        mechanics = db.get_mechanics_for_elevator(elevator['elevator_id'])
        elevator['mechanics'] = mechanics
    
    return render_template('elevators.html', elevators=elevators)


@app.route('/help')
def help_page():
    """Страница справки"""
    return render_template('help.html')


@app.route('/about')
def about_page():
    """О программе"""
    return render_template('about.html')


@app.route('/mechanics')
def mechanics_list():
    """Справочник механиков"""
    mechanics = db.get_all_mechanics(limit=100)
    return render_template('mechanics.html', mechanics=mechanics)


@app.route('/oncall')
def oncall_schedule():
    """Страница расписания аварийных дежурств"""
    today = datetime.now().strftime('%Y-%m-%d')
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    oncall_today = db.get_oncall_mechanic_for_date(today)
    if not oncall_today:
        oncall_today = db.get_next_oncall_mechanic()
    oncall_tomorrow = db.get_oncall_mechanic_for_date(tomorrow)
    if not oncall_tomorrow:
        oncall_tomorrow = db.get_next_oncall_mechanic()
    
    # Получить всех активных механиков для выбора
    all_mechanics = db.get_all_mechanics(limit=100)
    
    # Получить историю дежурств (последние 10)
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT o.date, m.name, m.phone, m.telegram_username 
            FROM oncall_mechanics o
            JOIN mechanics m ON o.mechanic_id = m.id
            ORDER BY o.date DESC LIMIT 10
        ''')
        history = []
        for row in cursor.fetchall():
            history.append({
                'date': row[0],
                'name': row[1],
                'phone': row[2],
                'telegram_username': row[3]
            })
    
    return render_template('oncall_schedule.html', 
                         today=today, 
                         tomorrow=tomorrow,
                         oncall_today=oncall_today,
                         oncall_tomorrow=oncall_tomorrow,
                         mechanics=all_mechanics,
                         history=history)


@app.route('/api/oncall', methods=['POST'])
def api_set_oncall():
    """API: Назначить аварийного механика на конкретную дату"""
    data = request.get_json()
    mechanic_id = data.get('mechanic_id')
    date_str = data.get('date')
    
    if not mechanic_id or not date_str:
        return jsonify({
            'success': False,
            'error': 'mechanic_id и date обязательны'
        }), 400
    
    # Проверить, что механик существует и активен
    mechanic = db.get_mechanic(mechanic_id)
    if not mechanic or mechanic.get('status') != 'active':
        return jsonify({
            'success': False,
            'error': 'Механик не найден или не активен'
        }), 400
    
    # Назначить
    db.set_oncall_mechanic(mechanic_id, date_str)
    
    return jsonify({
        'success': True,
        'message': f'Механик {mechanic["name"]} назначен на {date_str}'
    })


# ═══════════════════════════════════════════════════════════════
# API Endpoints
# ═══════════════════════════════════════════════════════════════

@app.route('/api/tickets', methods=['GET'])
def api_get_tickets():
    """Получение списка заявок с фильтрами"""
    filters = {}
    
    # Параметры фильтрации
    if request.args.get('status'):
        filters['status'] = request.args.get('status')
    if request.args.get('priority'):
        filters['priority'] = request.args.get('priority')
    if request.args.get('address'):
        filters['address'] = request.args.get('address')
    
    # Пагинация
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    tickets = db.search_tickets(
        filters=filters if filters else None,
        limit=limit,
        offset=offset
    )
    
    return jsonify({
        'success': True,
        'count': len(tickets),
        'tickets': tickets
    })


@app.route('/api/tickets/html', methods=['GET'])
def api_tickets_html():
    """Получение HTML списка заявок для AJAX обновления"""
    recent_tickets = db.search_tickets(limit=10, exclude_status=['выполнена', 'отменена'])
    
    # Добавляем данные
    for ticket in recent_tickets:
        if ticket.get('elevator_id'):
            elevator = db.get_elevator(ticket['elevator_id'])
            if elevator:
                if elevator.get('entrance'):
                    ticket['entrance'] = f"п.{elevator['entrance']}"
                ticket['elevator_id_display'] = ticket['elevator_id']
        
        # Статус класс
        ticket['status_class'] = 'status-new' if ticket.get('status') == 'новая' else 'status-in-work' if ticket.get('status') == 'в работе' else 'status-done'
        
        # Время
        try:
            created = datetime.strptime(ticket['created_at'][:19], '%Y-%m-%d %H:%M:%S')
            now = datetime.now() - timedelta(hours=4)
            diff = now - created
            hours = diff.total_seconds() // 3600
            minutes = (diff.total_seconds() % 3600) // 60
            if hours > 0:
                ticket['in_work_duration'] = f"{int(hours)}ч {int(minutes)}м"
            else:
                ticket['in_work_duration'] = f"{int(minutes)}м"
        except:
            pass
    
    return render_template('tickets_list_partial.html', tickets=recent_tickets)


@app.route('/api/tickets', methods=['POST'])
def api_create_ticket():
    """Создание новой заявки (для внешних источников)"""
    data = request.get_json()
    
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    # Валидация обязательных полей
    required_fields = ['address', 'problem_description']
    for field in required_fields:
        if not data.get(field):
            return jsonify({
                'success': False, 
                'error': f'Missing required field: {field}'
            }), 400
            
    # ЗАЩИТА ОТ ДУБЛИКАТОВ (Backend)
    # Проверяем, создавалась ли такая же заявка за последние 5 минут
    try:
        # Ищем заявки по адресу за последние 5 минут
        recent_tickets = db.search_tickets({
            'address': data['address'],
            'date_from': (datetime.now() - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
        }, limit=5)
        
        for recent in recent_tickets:
            # Сравниваем описание (игнорируя пробелы и регистр)
            desc1 = recent['problem_description'].strip().lower()
            desc2 = data['problem_description'].strip().lower()
            
            # Если описание совпадает и заявка не закрыта
            if desc1 == desc2 and recent['status'] not in ['выполнена', 'отменена']:
                print(f"⚠️ Обнаружен дубликат заявки #{recent['ticket_number']}. Возвращаем существующую.")
                return jsonify({
                    'success': True,
                    'message': 'Такая заявка уже существует (защита от дубликатов)',
                    'ticket': recent,
                    'is_duplicate': True
                }), 200
    except Exception as e:
        print(f"⚠️ Ошибка проверки дубликатов: {e}")
    
    # Создание заявки
    ticket = db.create_ticket(data)
    
    if not ticket:
        return jsonify({'success': False, 'error': 'Ошибка создания заявки в БД'}), 500
    
    # Отправка уведомления механикам через Telegram
    if TELEGRAM_NOTIFICATIONS_ENABLED and ticket.get('elevator_id'):
        try:
            # Запускаем в отдельном потоке, чтобы не блокировать ответ
            import threading
            def send_notification():
                try:
                    asyncio.run(notify_mechanics_about_ticket(ticket['id']))
                except Exception as e:
                    print(f"❌ Ошибка отправки уведомления: {e}")
            
            notification_thread = threading.Thread(target=send_notification)
            notification_thread.daemon = True
            notification_thread.start()
            
            print(f"✅ Уведомление отправлено механикам для заявки #{ticket['ticket_number']}")
        except Exception as e:
            print(f"❌ Ошибка запуска отправки уведомления: {e}")
    
    return jsonify({
        'success': True,
        'message': 'Заявка успешно создана',
        'ticket': ticket
    }), 201


@app.route('/api/tickets/<int:ticket_id>', methods=['GET'])
def api_get_ticket(ticket_id):
    """Получение информации о заявке"""
    ticket = db.get_ticket(ticket_id)
    
    if not ticket:
        return jsonify({'success': False, 'error': 'Ticket not found'}), 404
    
    comments = db.get_comments(ticket_id)
    ticket['comments'] = comments
    
    return jsonify({
        'success': True,
        'ticket': ticket
    })


@app.route('/api/tickets/<int:ticket_id>/status', methods=['PUT'])
def api_update_status(ticket_id):
    """Обновление статуса заявки"""
    data = request.get_json()
    new_status = data.get('status')
    notes = data.get('notes', '')
    user = data.get('user', 'api')
    
    if not new_status:
        return jsonify({'success': False, 'error': 'Status is required'}), 400
    
    valid_statuses = ['новая', 'в работе', 'выполнена', 'отменена']
    if new_status not in valid_statuses:
        return jsonify({
            'success': False, 
            'error': f'Invalid status. Must be one of: {valid_statuses}'
        }), 400
    
    ticket = db.update_ticket_status(ticket_id, new_status, user, notes)
    
    if not ticket:
        return jsonify({'success': False, 'error': 'Ticket not found'}), 404
    
    # Отправляем уведомление механикам если заявка завершена
    if new_status == 'выполнена' and ticket.get('assigned_to'):
        try:
            from notification_service import notify_ticket_completed
            import asyncio
            asyncio.create_task(notify_ticket_completed(ticket_id))
        except:
            pass
    
    return jsonify({
        'success': True,
        'message': f'Статус обновлён на: {new_status}',
        'ticket': ticket
    })


@app.route('/api/tickets/<int:ticket_id>', methods=['PUT'])
def api_update_ticket(ticket_id):
    """Обновление данных заявки"""
    data = request.get_json()
    user = data.pop('user', 'api')
    
    # Убираем поля, которые нельзя менять напрямую
    protected_fields = ['id', 'ticket_number', 'created_at', 'history']
    for field in protected_fields:
        data.pop(field, None)
    
    ticket = db.update_ticket(ticket_id, data, user)
    
    if not ticket:
        return jsonify({'success': False, 'error': 'Ticket not found'}), 404
    
    return jsonify({
        'success': True,
        'message': 'Заявка обновлена',
        'ticket': ticket
    })


@app.route('/api/tickets/<int:ticket_id>/comments', methods=['POST'])
def api_add_comment(ticket_id):
    """Добавление комментария к заявке"""
    data = request.get_json()
    author = data.get('author', 'operator')
    text = data.get('text', '')
    
    if not text:
        return jsonify({'success': False, 'error': 'Comment text is required'}), 400
    
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return jsonify({'success': False, 'error': 'Ticket not found'}), 404
    
    comment_id = db.add_comment(ticket_id, author, text)
    
    return jsonify({
        'success': True,
        'message': 'Комментарий добавлен',
        'comment_id': comment_id
    })


@app.route('/api/tickets/<int:ticket_id>/comments', methods=['GET'])
def api_get_comments(ticket_id):
    """Получение комментариев к заявке"""
    ticket = db.get_ticket(ticket_id)
    if not ticket:
        return jsonify({'success': False, 'error': 'Ticket not found'}), 404
    
    comments = db.get_comments(ticket_id)
    
    return jsonify({
        'success': True,
        'count': len(comments),
        'comments': comments
    })


@app.route('/api/stats', methods=['GET'])
def api_get_statistics():
    """Получение статистики заявок"""
    stats = db.get_statistics()
    return jsonify({
        'success': True,
        'statistics': stats
    })


@app.route('/api/search', methods=['GET'])
def api_search():
    """Поиск заявок"""
    query = request.args.get('q', '')
    
    if not query or len(query) < 2:
        return jsonify({
            'success': False,
            'error': 'Query must be at least 2 characters'
        }), 400
    
    # Поиск по разным полям
    results = []
    
    # Поиск по номеру телефона
    phone_results = db.search_tickets({'client_phone': query}, limit=10)
    results.extend(phone_results)
    
    # Поиск по имени
    name_results = db.search_tickets({'client_name': query}, limit=10)
    for r in name_results:
        if r['id'] not in [x['id'] for x in results]:
            results.append(r)
    
    # Поиск по адресу
    address_results = db.search_tickets({'address': query}, limit=10)
    for r in address_results:
        if r['id'] not in [x['id'] for x in results]:
            results.append(r)
    
    return jsonify({
        'success': True,
        'query': query,
        'count': len(results),
        'tickets': results
    })


# ═══════════════════════════════════════════════════════════════
# API для мобильного приложения
# ═══════════════════════════════════════════════════════════════

@app.route('/api/mobile/tickets', methods=['POST'])
def api_mobile_create_ticket():
    """Создание заявки с мобильного приложения"""
    data = request.get_json()
    
    # Устанавливаем источник
    data['source'] = 'mobile_app'
    
    # Проверяем API ключ (в реальном приложении)
    # api_key = request.headers.get('X-API-Key')
    # if not validate_api_key(api_key):
    #     return jsonify({'success': False, 'error': 'Invalid API key'}), 401
    
    return api_create_ticket()


@app.route('/api/mobile/tickets/track', methods=['GET'])
def api_mobile_track_ticket():
    """Отслеживание заявки по номеру телефона"""
    phone = request.args.get('phone', '')
    
    if not phone:
        return jsonify({
            'success': False,
            'error': 'Phone number is required'
        }), 400
    
    tickets = db.search_tickets({'client_phone': phone}, limit=20)
    
    # Убираем чувствительные данные
    for ticket in tickets:
        ticket.pop('history', None)
        ticket.pop('operator_notes', None)
    
    return jsonify({
        'success': True,
        'phone': phone,
        'count': len(tickets),
        'tickets': tickets
    })


# ═══════════════════════════════════════════════════════════════
# Служебные endpoint'ы
# ═══════════════════════════════════════════════════════════════

@app.route('/api/docs')
def api_docs():
    """Документация API"""
    docs = {
        'name': 'Lift Repair Ticket System API',
        'version': '1.0.0',
        'endpoints': {
            'GET /api/tickets': 'Получить список заявок',
            'POST /api/tickets': 'Создать новую заявку',
            'GET /api/tickets/<id>': 'Получить заявку по ID',
            'PUT /api/tickets/<id>/status': 'Обновить статус заявки',
            'PUT /api/tickets/<id>': 'Обновить данные заявки',
            'POST /api/tickets/<id>/comments': 'Добавить комментарий',
            'GET /api/stats': 'Получить статистику',
            'GET /api/search?q=query': 'Поиск заявок',
            'POST /api/mobile/tickets': 'Создать заявку с мобильного',
            'GET /api/mobile/tickets/track?phone=...': 'Отследить заявку'
        }
    }
    return jsonify(docs)


@app.route('/api/health')
def health_check():
    """Проверка работоспособности"""
    try:
        stats = db.get_statistics()
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500


# ═══════════════════════════════════════════════════════════════
# API для управления лифтами (объектами)
# ═══════════════════════════════════════════════════════════════

@app.route('/api/elevators', methods=['GET'])
def api_get_elevators():
    """Получение списка лифтов"""
    query = request.args.get('q', '')
    limit = request.args.get('limit', 200, type=int)
    
    elevators = db.search_elevators(query=query if query else None, limit=limit)
    
    return jsonify({
        'success': True,
        'count': len(elevators),
        'elevators': elevators
    })


@app.route('/api/elevators', methods=['POST'])
def api_create_elevator():
    """Добавление нового лифта"""
    data = request.get_json()
    
    if not data or not data.get('elevator_id') or not data.get('address'):
        return jsonify({
            'success': False,
            'error': 'elevator_id and address are required'
        }), 400
    
    try:
        elevator_id = db.add_elevator(data)
        return jsonify({
            'success': True,
            'message': 'Лифт добавлен',
            'elevator_id': elevator_id
        }), 201
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/elevators/<elevator_id>', methods=['GET'])
def api_get_elevator(elevator_id):
    """Получение информации о лифте"""
    elevator = db.get_elevator(elevator_id)
    
    if not elevator:
        return jsonify({
            'success': False,
            'error': 'Elevator not found'
        }), 404
    
    return jsonify({
        'success': True,
        'elevator': elevator
    })


@app.route('/api/elevators/<elevator_id>', methods=['PUT'])
def api_update_elevator(elevator_id):
    """Обновление данных лифта"""
    data = request.get_json()
    
    elevator = db.update_elevator(elevator_id, data)
    
    if not elevator:
        return jsonify({
            'success': False,
            'error': 'Elevator not found'
        }), 404
    
    return jsonify({
        'success': True,
        'message': 'Данные обновлены',
        'elevator': elevator
    })


@app.route('/api/elevators/<elevator_id>/mechanics', methods=['GET'])
def api_get_elevator_mechanics(elevator_id):
    """Получение механиков, закрепленных за лифтом"""
    mechanics = db.get_mechanics_for_elevator(elevator_id)
    return jsonify({
        'success': True,
        'count': len(mechanics),
        'mechanics': mechanics
    })


@app.route('/api/elevators/<elevator_id>/mechanics', methods=['POST'])
def api_assign_mechanic_to_elevator(elevator_id):
    """Закрепление механика за лифтом"""
    data = request.get_json()
    mechanic_id = data.get('mechanic_id')
    is_primary = data.get('is_primary', True)
    
    if not mechanic_id:
        return jsonify({
            'success': False,
            'error': 'mechanic_id is required'
        }), 400
    
    try:
        db.assign_mechanic_to_elevator(elevator_id, mechanic_id, is_primary)
        return jsonify({
            'success': True,
            'message': 'Механик закреплен за лифтом'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/elevators/<elevator_id>/mechanics/<int:mechanic_id>', methods=['DELETE'])
def api_remove_mechanic_from_elevator(elevator_id, mechanic_id):
    """Удаление механика с лифта"""
    try:
        db.remove_mechanic_from_elevator(elevator_id, mechanic_id)
        return jsonify({
            'success': True,
            'message': 'Механик откреплен от лифта'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/elevators/<elevator_id>', methods=['DELETE'])
def api_delete_elevator(elevator_id):
    """Удаление лифта"""
    if db.delete_elevator(elevator_id):
        return jsonify({
            'success': True,
            'message': 'Лифт удален'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Elevator not found'
        }), 404


# ═══════════════════════════════════════════════════════════════
# API для управления механиками
# ═══════════════════════════════════════════════════════════════

@app.route('/api/mechanics', methods=['GET'])
def api_get_mechanics():
    """Получение списка механиков"""
    mechanics = db.get_all_mechanics()
    return jsonify({
        'success': True,
        'count': len(mechanics),
        'mechanics': mechanics
    })


@app.route('/api/mechanics', methods=['POST'])
def api_create_mechanic():
    """Добавление нового механика"""
    data = request.get_json()
    
    if not data or not data.get('name') or not data.get('phone'):
        return jsonify({
            'success': False,
            'error': 'Имя и телефон обязательны'
        }), 400
    
    try:
        mechanic_id = db.add_mechanic(data)
        return jsonify({
            'success': True,
            'message': 'Механик добавлен',
            'mechanic_id': mechanic_id
        }), 201
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/mechanics/<int:mechanic_id>', methods=['GET'])
def api_get_mechanic(mechanic_id):
    """Получение информации о механике"""
    mechanic = db.get_mechanic(mechanic_id)
    
    if not mechanic:
        return jsonify({
            'success': False,
            'error': 'Механик не найден'
        }), 404
    
    return jsonify({
        'success': True,
        'mechanic': mechanic
    })


@app.route('/api/mechanics/<int:mechanic_id>', methods=['PUT'])
def api_update_mechanic(mechanic_id):
    """Обновление данных механика"""
    data = request.get_json()
    
    mechanic = db.update_mechanic(mechanic_id, data)
    
    if not mechanic:
        return jsonify({
            'success': False,
            'error': 'Механик не найден'
        }), 404
    
    return jsonify({
        'success': True,
        'message': 'Данные обновлены',
        'mechanic': mechanic
    })


@app.route('/api/mechanics/<int:mechanic_id>', methods=['DELETE'])
def api_delete_mechanic(mechanic_id):
    """Удаление механика"""
    if db.delete_mechanic(mechanic_id):
        return jsonify({
            'success': True,
            'message': 'Механик удален'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Механик не найден'
        }), 404


# ═══════════════════════════════════════════════════════════════
# API для бэкапа базы данных
# ═══════════════════════════════════════════════════════════════

@app.route('/api/backup', methods=['POST'])
def api_create_backup():
    """Создание полного бэкапа (БД + фото)"""
    try:
        base_dir = Path(app.root_path)
        backup_dir = base_dir / 'backups'
        backup_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'full_backup_{timestamp}.zip'
        backup_path = backup_dir / backup_filename
        
        # 1. Создаем дамп базы данных
        db_path = base_dir / 'instance' / 'tickets.db'
        
        # Подключаемся к текущей БД
        source_conn = sqlite3.connect(str(db_path))
        backup_conn = sqlite3.connect(':memory:')
        source_conn.backup(backup_conn)
        source_conn.close()
        
        # Сбрасываем данные из памяти в файл
        with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            temp_db_path = backup_dir / f'temp_{timestamp}.db'
            file_conn = sqlite3.connect(str(temp_db_path))
            backup_conn.backup(file_conn)
            file_conn.close()
            backup_conn.close()
            
            # Добавляем БД в архив
            zipf.write(temp_db_path, arcname='tickets.db')
            temp_db_path.unlink()
            
            # 2. Добавляем папку uploads
            uploads_dir = base_dir / 'uploads'
            if uploads_dir.exists():
                for file_path in uploads_dir.rglob('*'):
                    if file_path.is_file():
                        zipf.write(file_path, arcname=str(file_path.relative_to(base_dir)))
        
        return jsonify({
            'success': True,
            'message': 'Полный бэкап создан успешно',
            'filename': backup_filename,
            'path': str(backup_path)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/backup/download', methods=['GET'])
def api_download_backup():
    """Скачивание полного бэкапа прямо из памяти (без записи на диск)"""
    try:
        base_dir = Path(app.root_path)
        db_path = base_dir / 'instance' / 'tickets.db'
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'full_backup_{timestamp}.zip'

        # 1. Снимаем дамп БД в память (безопасно при WAL)
        mem_db = sqlite3.connect(':memory:')
        src = sqlite3.connect(str(db_path))
        src.backup(mem_db)
        src.close()

        # Сохраняем in-memory БД во временный файл
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            tmp_path = tmp.name
        tmp_conn = sqlite3.connect(tmp_path)
        mem_db.backup(tmp_conn)
        tmp_conn.close()
        mem_db.close()

        # 2. Собираем ZIP в памяти
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(tmp_path, arcname='tickets.db')
            
            uploads_dir = base_dir / 'uploads'
            if uploads_dir.exists():
                for file_path in uploads_dir.rglob('*'):
                    if file_path.is_file():
                        zipf.write(file_path, arcname=str(file_path.relative_to(base_dir)))

        # Удаляем временный файл
        os.unlink(tmp_path)

        # 3. Отдаём ZIP из памяти
        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=backup_filename
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/backup/restore', methods=['POST'])
def api_restore_backup():
    """Восстановление из ZIP (БД + фото) или DB"""
    try:
        base_dir = Path(app.root_path)
        
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'Файл не загружен'}), 400
        
        file = request.files['file']
        filename = file.filename
        
        if not filename:
            return jsonify({'success': False, 'error': 'Файл не выбран'}), 400
            
        is_zip = filename.lower().endswith('.zip')
        is_db = filename.lower().endswith('.db')
        
        if not (is_zip or is_db):
            return jsonify({'success': False, 'error': 'Формат должен быть .zip или .db'}), 400
            
        instance_dir = base_dir / 'instance'
        instance_dir.mkdir(exist_ok=True)
        db_path = instance_dir / 'tickets.db'
        
        # Бэкап текущего состояния перед восстановлением
        if db_path.exists():
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            shutil.copy2(db_path, instance_dir / f'tickets_pre_restore_{timestamp}.db')
            
        if is_zip:
            # Работа с архивом
            backup_dir = base_dir / 'backups'
            backup_dir.mkdir(exist_ok=True)
            temp_extract_dir = backup_dir / 'temp_extract'
            
            # Удаляем старую временную папку, если есть
            if temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir)
            temp_extract_dir.mkdir(parents=True, exist_ok=True)
            
            zip_path = temp_extract_dir / 'backup.zip'
            file.save(str(zip_path))
            
            with zipfile.ZipFile(str(zip_path), 'r') as zip_ref:
                zip_ref.extractall(temp_extract_dir)
                
            # Ищем и восстанавливаем БД
            restored_db = temp_extract_dir / 'tickets.db'
            if restored_db.exists():
                # Удаляем WAL файлы чтобы не было конфликта версий
                for ext in ['.db-wal', '.db-shm']:
                    wal_file = db_path.with_suffix(ext)
                    if wal_file.exists():
                        wal_file.unlink()
                
                # Если файл базы существует, удаляем его перед перемещением нового
                if db_path.exists():
                    db_path.unlink()
                
                shutil.move(str(restored_db), str(db_path))
            else:
                return jsonify({'success': False, 'error': 'В архиве нет tickets.db'}), 400
                
            # Восстанавливаем uploads
            restored_uploads = temp_extract_dir / 'uploads'
            if restored_uploads.exists():
                target_uploads = base_dir / 'uploads'
                if target_uploads.exists():
                    shutil.rmtree(target_uploads)
                
                # Перемещаем папку (теперь точно в корень)
                shutil.move(str(restored_uploads), str(base_dir))
                
            # Чистим за собой
            if temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir)
            
        else:
            # Старый формат (.db)
            # Удаляем WAL файлы чтобы не было конфликта версий
            for ext in ['.db-wal', '.db-shm']:
                wal_file = db_path.with_suffix(ext)
                if wal_file.exists():
                    wal_file.unlink()
            
            file.save(str(db_path))
        
        # Триггер перезапуска сервера (для dev_runner.py)
        try:
            Path(__file__).touch()
        except:
            pass
            
        return jsonify({
            'success': True, 
            'message': 'Восстановление завершено. Сервер перезагружается...',
            'reload': True
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════
# Запуск сервера
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 60)
    print("🛠️  Система заявок на ремонт лифтов")
    print("=" * 60)
    print("📞 Веб-интерфейс оператора: http://localhost:8081")
    print("📚 API документация: http://localhost:8081/api/docs")
    print("🏥 Health check: http://localhost:8081/api/health")
    print("=" * 60)
    
    app.run(
        host='0.0.0.0',
        port=8081,
        debug=False,
        use_reloader=False
    )
