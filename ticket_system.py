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

app = Flask(__name__, template_folder='templates', static_folder='static', static_url_path='/static')
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
    
    # Исключаем только отмененные заявки
    recent_tickets = db.search_tickets(exclude_status=['отменена'])
    
    # Добавляем дату и время для группировки и фильтрации
    for ticket in recent_tickets:
        if ticket.get('created_at'):
            try:
                created = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
                created = created + timedelta(hours=4)
                ticket['ticket_date'] = created.strftime('%Y-%m-%d')
                ticket['created_time'] = created.strftime('%Y-%m-%d %H:%M')
            except:
                pass
        # Добавляем время завершения
        if ticket.get('status') == 'выполнена':
            completed_at = ticket.get('completed_at') or ticket.get('updated_at')
            if completed_at:
                try:
                    completed = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                    completed = completed + timedelta(hours=4)
                    ticket['completed_time'] = completed.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
    
    # Добавляем подъезд и ID лифта к каждой заявке
    for ticket in recent_tickets:
        if ticket.get('elevator_id'):
            elevator = db.get_elevator(ticket['elevator_id'])
            if elevator:
                if elevator.get('entrance'):
                    ticket['entrance'] = f"п.{elevator['entrance']}"
                ticket['elevator_id_display'] = ticket['elevator_id']
        
        # Получаем фото заявки
        ticket_id = ticket.get('id')
        if ticket_id:
            try:
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT text FROM comments WHERE ticket_id = ? AND text LIKE '[ФОТО]%' LIMIT 4",
                    (ticket_id,)
                )
                photos = [row[0].replace('[ФОТО] ', '') for row in cursor.fetchall()]
                conn.close()
                if photos:
                    ticket['photos'] = photos
                
                # Получаем описание работ механика
                try:
                    conn = db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT text FROM comments WHERE ticket_id = ? AND author = 'mechanic' AND text LIKE '📝%' ORDER BY created_at DESC LIMIT 1",
                        (ticket_id,)
                    )
                    work_row = cursor.fetchone()
                    conn.close()
                    if work_row:
                        ticket['last_work'] = work_row[0].replace('📝 ', '')
                except:
                    pass
            except:
                pass
    
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
        
        # Рассчитываем время: для выполненных - с created_at до updated_at, для остальных - с created_at до сейчас
        in_work_duration = None
        if ticket.get('created_at'):
            try:
                created = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
                created = created + timedelta(hours=4)
                
                # Для выполненных заявок используем updated_at как конечное время
                if ticket.get('status') == 'выполнена' and ticket.get('updated_at'):
                    end_time = datetime.fromisoformat(ticket['updated_at'].replace('Z', '+00:00'))
                    end_time = end_time + timedelta(hours=4)
                else:
                    end_time = datetime.now()
                
                diff = end_time - created
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
                if tm and tm.get('status'):
                    if tm.get('status') == 'accepted':
                        mech_info['tg_status'] = 'accepted'
                    elif tm.get('status') == 'rejected':
                        mech_info['tg_status'] = 'rejected'
                    elif tm.get('status') == 'sent':
                        mech_info['tg_status'] = 'sent'
                # Если нет записи в ticket_mechanics - не показываем статус (сообщение еще не отправлено)
            # Если mech_id None - тоже ничего не показываем
        
        # Добавляем принявшего механика, если его нет в списке
        if ticket.get('assigned_to'):
            already_in_list = any(str(m.get('id')) == str(ticket['assigned_to']) for m in elevator_mechanics)
            if not already_in_list:
                try:
                    mech = db.get_mechanic(int(ticket['assigned_to']))
                    if mech:
                        tm = ticket_mech_statuses.get(str(mech['id']))
                        tg_status = None
                        if tm and tm.get('status'):
                            if tm.get('status') == 'accepted':
                                tg_status = 'accepted'
                            elif tm.get('status') == 'rejected':
                                tg_status = 'rejected'
                            elif tm.get('status') == 'sent':
                                tg_status = 'sent'
                        mechanics_list.append({
                            'name': mech['name'],
                            'id': mech['id'],
                            'has_telegram': bool(mech.get('telegram_chat_id')),
                            'is_oncall': False,
                            'status': 'Принял',
                            'tg_status': tg_status
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
    
    tickets = db.search_tickets(filters=filters if filters else None)
    
    # Добавляем дату (день) для группировки
    for ticket in recent_tickets:
        if ticket.get('created_at'):
            try:
                created = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
                created = created + timedelta(hours=4)
                ticket['ticket_date'] = created.strftime('%Y-%m-%d')
            except:
                pass
        # Добавляем время завершения для фильтрации
        if ticket.get('status') == 'выполнена' and ticket.get('completed_at'):
            try:
                completed = datetime.fromisoformat(ticket['completed_at'].replace('Z', '+00:00'))
                completed = completed + timedelta(hours=4)
                ticket['completed_time'] = completed
            except:
                pass
        elif ticket.get('status') == 'выполнена' and ticket.get('updated_at'):
            try:
                completed = datetime.fromisoformat(ticket['updated_at'].replace('Z', '+00:00'))
                completed = completed + timedelta(hours=4)
                ticket['completed_time'] = completed
            except:
                pass
    
    # Добавляем фото и работы к каждой заявке
    for ticket in tickets:
        ticket_id = ticket.get('id')
        if ticket_id:
            try:
                conn = db.get_connection()
                cursor = conn.cursor()
                # Фото
                cursor.execute(
                    "SELECT text FROM comments WHERE ticket_id = ? AND text LIKE '[ФОТО]%' LIMIT 4",
                    (ticket_id,)
                )
                photos = [row[0].replace('[ФОТО] ', '') for row in cursor.fetchall()]
                # Путь уже содержит uploads/
                if photos:
                    ticket['photos'] = photos
                # Работы
                cursor.execute(
                    "SELECT text FROM comments WHERE ticket_id = ? AND author = 'mechanic' AND text LIKE '📝%' ORDER BY created_at DESC LIMIT 1",
                    (ticket_id,)
                )
                work_row = cursor.fetchone()
                if work_row:
                    ticket['last_work'] = work_row[0].replace('📝 ', '')
                conn.close()
            except:
                pass
    
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
    
    # Получить всех механиков, которым отправлялась заявка
    ticket_mechanics = []
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT m.name, m.phone, tm.status, tm.sent_at, tm.responded_at
            FROM ticket_mechanics tm
            JOIN mechanics m ON tm.mechanic_id = m.id
            WHERE tm.ticket_id = ?
            ORDER BY tm.sent_at DESC
        ''', (ticket_id,))
        for row in cursor.fetchall():
            ticket_mechanics.append({
                'name': row[0],
                'phone': row[1],
                'status': row[2],
                'sent_at': row[3],
                'responded_at': row[4]
            })
    
    # Отделить фото и видео от обычных комментариев
    photo_comments = []
    video_comments = []
    mechanic_work = []
    for c in comments:
        if c.get('text', '').startswith('[ФОТО]'):
            photo_comments.append(c)
        elif c.get('text', '').startswith('[ВИДЕО]'):
            video_comments.append(c)
        elif c.get('text', '').startswith('📝'):
            mechanic_work.append(c)
    
    # Рассчитать время: для выполненных - с created_at до updated_at, для остальных - с created_at до сейчас
    in_work_duration = None
    if ticket.get('created_at'):
        try:
            created = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
            created = created + timedelta(hours=4)  # Самара
            
            if ticket.get('status') == 'выполнена' and ticket.get('updated_at'):
                end_time = datetime.fromisoformat(ticket['updated_at'].replace('Z', '+00:00'))
                end_time = end_time + timedelta(hours=4)
            else:
                end_time = datetime.now()
            
            diff = end_time - created
            hours = diff.total_seconds() // 3600
            minutes = (diff.total_seconds() % 3600) // 60
            if hours > 0:
                in_work_duration = f"{int(hours)}ч {int(minutes)}мин"
            else:
                in_work_duration = f"{int(minutes)}мин"
        except:
            pass
    
    # Создать объединённую историю (timeline)
    timeline = []
    
    # 1. История изменений статуса
    import json
    history_data = ticket.get('history', '[]')
    if isinstance(history_data, str):
        try:
            history_data = json.loads(history_data)
        except:
            history_data = []
    elif not history_data:
        history_data = []
    
    # Обрабатываем историю - объединяем связанные события
    processed_history = []
    i = 0
    while i < len(history_data):
        h = history_data[i]
        action = h.get('action', '')
        
        # Объединяем "Обновление заявки" + "Изменение статуса: новая → в работу" -> "Заявка в работе"
        if action == 'Обновление заявки' and i + 1 < len(history_data):
            next_h = history_data[i + 1]
            next_action = next_h.get('action', '')
            if 'Изменение статуса' in next_action and '→' in next_action:
                # Объединяем в "Заявка в работе"
                h = {
                    'timestamp': h.get('timestamp', ''),
                    'action': 'Заявка в работе',
                    'user': h.get('user', '')
                }
                i += 2  # Пропускаем оба события
            else:
                i += 1
        else:
            i += 1
        
        processed_history.append(h)
    
    for h in processed_history:
        ts = h.get('timestamp', '')
        if ts:
            try:
                if '.' in ts:
                    dt = datetime.strptime(ts[:26], '%Y-%m-%dT%H:%M:%S.%f')
                else:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                ts_sort = dt.timestamp()
                ts_display = dt.strftime('%Y-%m-%d %H:%M')
            except:
                ts_sort = 0
                ts_display = ts[:16]
        else:
            ts_sort = 0
            ts_display = ''
        
        # Определяем иконку по типу события
        action = h.get('action', '')
        if 'в работе' in action:
            icon = 'bi-wrench'
            color = 'status-work'
        elif 'выполнена' in action or 'завершена' in action:
            icon = 'bi-check-circle'
            color = 'status-done'
        elif 'создание' in action.lower():
            icon = 'bi-plus-circle'
            color = 'status-new'
        else:
            icon = 'bi-arrow-repeat'
            color = 'status-work'
        
        timeline.append({
            'timestamp': ts_display,
            'timestamp_sort': ts_sort,
            'type': 'status',
            'action': action,
            'user': h.get('user', ''),
            'icon': icon,
            'color': color
        })
    
    # 2. Отправка механикам
    for mech in ticket_mechanics:
        if mech.get('sent_at'):
            ts = mech['sent_at']
            try:
                dt = datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
                dt = dt + timedelta(hours=4)  # Конвертируем local в UTC
                ts_sort = dt.timestamp()
                ts_display = dt.strftime('%Y-%m-%d %H:%M')
            except:
                ts_sort = 0
                ts_display = ts[:16]
            timeline.append({
                'timestamp': ts_display,
                'timestamp_sort': ts_sort,
                'type': 'mechanic_sent',
                'action': f'📤 Отправлена {mech["name"]}',
                'user': 'system',
                'icon': 'bi-send',
                'color': 'status-sent'
            })
        if mech.get('responded_at') and mech['status'] == 'accepted':
            ts = mech['responded_at']
            try:
                dt = datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
                dt = dt + timedelta(hours=4)  # Конвертируем local в UTC
                ts_sort = dt.timestamp()
                ts_display = dt.strftime('%Y-%m-%d %H:%M')
            except:
                ts_sort = 0
                ts_display = ts[:16]
            timeline.append({
                'timestamp': ts_display,
                'timestamp_sort': ts_sort,
                'type': 'mechanic_accepted',
                'action': f'👤 {mech["name"]} принял заявку',
                'user': 'system',
                'icon': 'bi-check-circle',
                'color': 'status-accepted'
            })
    
    # 3. Фотоотчёты
    for p in photo_comments:
        ts = p.get('created_at', '')
        if ts:
            try:
                dt = datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
                dt = dt + timedelta(hours=4)  # Конвертируем local в UTC
                ts_sort = dt.timestamp()
                ts_display = dt.strftime('%Y-%m-%d %H:%M')
            except:
                ts_sort = 0
                ts_display = ts[:16]
        else:
            ts_sort = 0
            ts_display = ''
        timeline.append({
            'timestamp': ts_display,
            'timestamp_sort': ts_sort,
            'type': 'photo',
            'action': '📸 Фотоотчёт',
            'user': p.get('author', ''),
            'icon': 'bi-camera',
            'color': 'status-photo',
            'photo_path': '/' + p.get('text', '').replace('[ФОТО] ', '')
        })
    
    # 3.1. Видеоотчёты
    for v in video_comments:
        ts = v.get('created_at', '')
        if ts:
            try:
                dt = datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
                dt = dt + timedelta(hours=4)
                ts_sort = dt.timestamp()
                ts_display = dt.strftime('%Y-%m-%d %H:%M')
            except:
                ts_sort = 0
                ts_display = ts[:16]
        else:
            ts_sort = 0
            ts_display = ''
        timeline.append({
            'timestamp': ts_display,
            'timestamp_sort': ts_sort,
            'type': 'video',
            'action': '🎥 Видеоотчёт',
            'user': v.get('author', ''),
            'icon': 'bi-camera-video',
            'color': 'status-photo',
            'video_path': '/' + v.get('text', '').replace('[ВИДЕО] ', '')
        })
    
    # 4. Текстовые описания работ
    for w in mechanic_work:
        ts = w.get('created_at', '')
        if ts:
            try:
                dt = datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
                dt = dt + timedelta(hours=4)  # Конвертируем local в UTC
                ts_sort = dt.timestamp()
                ts_display = dt.strftime('%Y-%m-%d %H:%M')
            except:
                ts_sort = 0
                ts_display = ts[:16]
        else:
            ts_sort = 0
            ts_display = ''
        # Обрезаем текст для отображения
        text = w.get('text', '').replace('📝 ', '')
        text_display = text[:50] + '...' if len(text) > 50 else text
        timeline.append({
            'timestamp': ts_display,
            'timestamp_sort': ts_sort,
            'type': 'work',
            'action': f'📝 {text_display}',
            'user': w.get('author', ''),
            'icon': 'bi-tools',
            'color': 'status-work'
        })
    
    # Сортируем по времени (старые сверху)
    timeline.sort(key=lambda x: x['timestamp_sort'], reverse=False)
    
    # Timestamp уже в правильном формате для отображения
    
    return render_template('ticket_detail.html', 
                         ticket=ticket, 
                         comments=comments,
                         photo_comments=photo_comments,
                         video_comments=video_comments,
                         mechanic_work=mechanic_work,
                         timeline=timeline,
                         in_work_duration=in_work_duration)


@app.route('/new-ticket')
def new_ticket_form():
    """Форма создания новой заявки"""
    elevators = db.get_all_elevators(limit=200)
    return render_template('new_ticket.html', elevators=elevators)


@app.route('/m')
@app.route('/mobile')
def mechanic_mobile():
    """Мобильная версия для механиков (PWA)"""
    return render_template('mechanic_mobile.html')


# ═══════════════════════════════════════════════════════════════
# VK Bot Callback (Max messenger)
# ═══════════════════════════════════════════════════════════════

@app.route('/vk/callback', methods=['POST'])
def vk_callback():
    """Обработка callback от VK"""
    import json
    
    data = request.get_json()
    
    if not data:
        return 'ok'
    
    event_type = data.get('type')
    
    # Подтверждение сервера
    if event_type == 'confirmation':
        return os.getenv('VK_CONFIRMATION_CODE', '')
    
    # Сообщение
    if event_type == 'message_new':
        msg = data.get('object', {}).get('message', {})
        user_id = msg.get('user_id')
        text = msg.get('text', '')
        
        # Импортируем VK bot functions
        try:
            from vk_bot import (
                send_message, get_main_keyboard, get_ticket_keyboard,
                handle_my_tickets, handle_accept_ticket, handle_complete_ticket,
                register_mechanic_vk, db as vk_db
            )
            
            # Проверяем зарегистрирован ли механик
            mechanic = vk_db.get_mechanic_by_vk(user_id)
            
            # Обработка команд
            if text == '🛗 Мои лифты':
                if mechanic:
                    elevators = vk_db.get_mechanic_elevators(mechanic['id'])
                    if elevators:
                        message = f"🛗 Ваши лифты ({len(elevators)}):\n\n"
                        for e in elevators:
                            message += f"• {e['elevator_id']} - {e['address']}\n"
                    else:
                        message = "ℹ️ За вами не закреплены лифты"
                else:
                    message = "❌ Вы не зарегистрированы"
                send_message(user_id, message, get_main_keyboard())
            
            elif text == '📋 Мои заявки':
                import asyncio
                message = asyncio.run(handle_my_tickets(user_id))
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
                import asyncio
                from vk_bot import vk_user_data
                if str(user_id) in vk_user_data and 'ticket_id' in vk_user_data[str(user_id)]:
                    ticket_id = vk_user_data[str(user_id)]['ticket_id']
                    message = asyncio.run(handle_complete_ticket(user_id, ticket_id))
                    send_message(user_id, message)
                else:
                    send_message(user_id, "❌ Нет активной заявки для завершения")
            
            elif 'accept_' in text:
                try:
                    ticket_id = int(text.split('_')[1])
                    import asyncio
                    message = asyncio.run(handle_accept_ticket(user_id, ticket_id))
                    send_message(user_id, message, get_ticket_keyboard(ticket_id, 'in_progress'))
                    
                    from vk_bot import vk_user_data
                    vk_user_data[str(user_id)] = {'ticket_id': ticket_id}
                except:
                    send_message(user_id, "❌ Неверный формат команды")
            
            else:
                # Неизвестная команда
                if not mechanic:
                    if text.startswith('+'):
                        success, name = register_mechanic_vk(user_id, text)
                        if success:
                            send_message(user_id, f"✅ Регистрация успешна!\n\nДобро пожаловать, {name}!\n\nТеперь вы будете получать заявки на ремонт.", get_main_keyboard())
                        else:
                            send_message(user_id, "❌ Механик с таким номером не найден. Обратитесь к администратору.")
                    else:
                        send_message(user_id, "👋 Для регистрации отправьте ваш номер телефона:\n\nПример: +79991234567")
                else:
                    send_message(user_id, "ℹ️ Используйте кнопки меню", get_main_keyboard())
        
        except Exception as e:
            print(f"VK Callback error: {e}")
    
    return 'ok'


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
    """О программе - редирект на главную с открытием модального окна"""
    return '''
    <!DOCTYPE html>
    <html>
    <script>
        window.location.href = "/?about=1";
    </script>
    </html>
    '''


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
    # Получаем фильтр из параметра
    filter_type = request.args.get('filter', 'all')
    
    # Вычисляем время 8:00 для фильтрации
    now = datetime.now()
    if now.hour < 8:
        today8am = (now - timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    else:
        today8am = now.replace(hour=8, minute=0, second=0, microsecond=0)
    
    # Базовая выборка
    recent_tickets = db.search_tickets(exclude_status=['отменена'])
    
    # Фильтруем на сервере если указан фильтр
    if filter_type == 'new':
        filtered = []
        for ticket in recent_tickets:
            created = ticket.get('created_at')
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                    dt = dt + timedelta(hours=4)
                    # Новая или в работе - поступила с 8:00
                    if (ticket.get('status') == 'новая' or ticket.get('status') == 'в работе') and dt >= today8am:
                        filtered.append(ticket)
                    # Выполнена сегодня - тоже показываем
                    elif ticket.get('status') == 'выполнена':
                        completed = ticket.get('completed_at') or ticket.get('updated_at')
                        if completed:
                            try:
                                ct = datetime.fromisoformat(completed.replace('Z', '+00:00'))
                                ct = ct + timedelta(hours=4)
                                if ct >= today8am:
                                    filtered.append(ticket)
                            except:
                                pass
                except:
                    pass
        recent_tickets = filtered
    elif filter_type == 'work':
        recent_tickets = [t for t in recent_tickets if t.get('status') == 'в работе']
    elif filter_type == 'done':
        filtered = []
        for ticket in recent_tickets:
            if ticket.get('status') == 'выполнена':
                completed = ticket.get('completed_at') or ticket.get('updated_at')
                if completed:
                    try:
                        dt = datetime.fromisoformat(completed.replace('Z', '+00:00'))
                        dt = dt + timedelta(hours=4)
                        if dt >= today8am:
                            filtered.append(ticket)
                    except:
                        pass
        recent_tickets = filtered
    
    # Добавляем дату (день) для группировки и время для фильтрации
    for ticket in recent_tickets:
        if ticket.get('created_at'):
            try:
                created = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
                created = created + timedelta(hours=4)
                ticket['ticket_date'] = created.strftime('%Y-%m-%d')
                ticket['created_time'] = created.strftime('%Y-%m-%d %H:%M')
            except:
                pass
        # Добавляем время завершения
        if ticket.get('status') == 'выполнена':
            completed_at = ticket.get('completed_at') or ticket.get('updated_at')
            if completed_at:
                try:
                    completed = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                    completed = completed + timedelta(hours=4)
                    ticket['completed_time'] = completed.strftime('%Y-%m-%d %H:%M')
                except:
                    pass
    
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
        
        # Время: для выполненных - с created_at до updated_at, для остальных - с created_at до сейчас
        if ticket.get('created_at'):
            try:
                created = datetime.fromisoformat(ticket['created_at'].replace('Z', '+00:00'))
                created = created + timedelta(hours=4)
                
                if ticket.get('status') == 'выполнена' and ticket.get('updated_at'):
                    end_time = datetime.fromisoformat(ticket['updated_at'].replace('Z', '+00:00'))
                    end_time = end_time + timedelta(hours=4)
                else:
                    end_time = datetime.now()
                
                diff = end_time - created
                hours = diff.total_seconds() // 3600
                minutes = (diff.total_seconds() % 3600) // 60
                if hours > 0:
                    ticket['in_work_duration'] = f"{int(hours)}ч {int(minutes)}м"
                else:
                    ticket['in_work_duration'] = f"{int(minutes)}м"
            except:
                pass
        
        # Получаем фото заявки
        ticket_id = ticket.get('id')
        if ticket_id:
            try:
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT text FROM comments WHERE ticket_id = ? AND text LIKE '[ФОТО]%' LIMIT 4",
                    (ticket_id,)
                )
                photos = [row[0].replace('[ФОТО] ', '') for row in cursor.fetchall()]
                conn.close()
                if photos:
                    ticket['photos'] = photos
                
                # Получаем видео
                try:
                    conn = db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT text FROM comments WHERE ticket_id = ? AND text LIKE '[ВИДЕО]%' LIMIT 2",
                        (ticket_id,)
                    )
                    videos = [row[0].replace('[ВИДЕО] ', '') for row in cursor.fetchall()]
                    conn.close()
                    if videos:
                        ticket['videos'] = videos
                except:
                    pass
                
                # Получаем описание работ механика
                try:
                    conn = db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT text FROM comments WHERE ticket_id = ? AND author = 'mechanic' AND text LIKE '📝%' ORDER BY created_at DESC LIMIT 1",
                        (ticket_id,)
                    )
                    work_row = cursor.fetchone()
                    conn.close()
                    if work_row:
                        ticket['last_work'] = work_row[0].replace('📝 ', '')
                except:
                    pass
            except:
                pass
        
        # Загружаем механиков для каждой заявки
        from datetime import date
        today = date.today().strftime('%Y-%m-%d')
        
        for ticket in recent_tickets:
            mechanics_list = []
            elevator_id = ticket.get('elevator_id')
            
            try:
                # Получаем механиков для лифта
                if elevator_id:
                    elevator_mechanics = db.get_mechanics_for_elevator(elevator_id)
                else:
                    elevator_mechanics = []
                
                # Получаем дежурного
                oncall_today = db.get_oncall_mechanic_for_date(today)
                if not oncall_today:
                    oncall_today = db.get_next_oncall_mechanic()
                oncall_today_id = oncall_today['id'] if oncall_today else None
                
                assigned_id = ticket.get('assigned_to')
                
                # Добавляем механиков с лифта
                for mech in elevator_mechanics:
                    is_oncall = bool(oncall_today_id and mech['id'] == oncall_today_id)
                    mech_info = {
                        'name': mech['name'],
                        'id': mech.get('id'),
                        'has_telegram': bool(mech.get('telegram_chat_id')),
                        'is_oncall': is_oncall,
                        'status': 'Принял' if assigned_id and str(assigned_id) == str(mech['id']) else ('Аварийный' if is_oncall else 'Линейный'),
                        'tg_status': 'accepted' if assigned_id and str(assigned_id) == str(mech['id']) else None
                    }
                    if not any(m['id'] == mech['id'] for m in mechanics_list):
                        mechanics_list.append(mech_info)
                
                # Добавляем дежурного если не добавлен
                if oncall_today and oncall_today_id:
                    if not any(m['id'] == oncall_today_id for m in mechanics_list):
                        mechanics_list.append({
                            'name': oncall_today['name'],
                            'id': oncall_today.get('id'),
                            'has_telegram': bool(oncall_today.get('telegram_chat_id')),
                            'is_oncall': True,
                            'status': 'Аварийный',
                            'tg_status': None
                        })
                
                # Если есть assigned_to - обновляем статус существующего механика
                if assigned_id:
                    for m in mechanics_list:
                        if m.get('id') and str(m['id']) == str(assigned_id):
                            m['status'] = 'Принял'
                            m['tg_status'] = 'accepted'
                            break
                    else:
                        # Механик не в списке - добавляем
                        try:
                            assigned_mechanic = db.get_mechanic(assigned_id)
                            if assigned_mechanic:
                                mechanics_list.append({
                                    'name': assigned_mechanic['name'],
                                    'id': assigned_mechanic.get('id'),
                                    'has_telegram': bool(assigned_mechanic.get('telegram_chat_id')),
                                    'is_oncall': False,
                                    'status': 'Принял',
                                    'tg_status': 'accepted'
                                })
                        except:
                            pass
                
                ticket['mechanics_list'] = mechanics_list
            except Exception as e:
                print(f"Error loading mechanics: {e}")
                ticket['mechanics_list'] = []
    
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
                    print(f"🔔 Запуск отправки уведомления для заявки #{ticket['ticket_number']}")
                    asyncio.run(notify_mechanics_about_ticket(ticket['id']))
                except Exception as e:
                    print(f"❌ Ошибка отправки уведомления: {e}")
                    import traceback
                    traceback.print_exc()
            
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


@app.route('/api/tickets/<int:ticket_id>/accept', methods=['POST'])
def api_accept_ticket_mobile(ticket_id):
    """Принять заявку в работу (мобильная версия)"""
    ticket = db.update_ticket_status(ticket_id, 'в работе', 'mobile')
    if not ticket:
        return jsonify({'success': False, 'error': 'Ticket not found'}), 404
    return jsonify({'success': True})


@app.route('/api/tickets/<int:ticket_id>/complete', methods=['POST'])
def api_complete_ticket_mobile(ticket_id):
    """Завершить заявку (мобильная версия)"""
    ticket = db.update_ticket_status(ticket_id, 'выполнена', 'mobile')
    if not ticket:
        return jsonify({'success': False, 'error': 'Ticket not found'}), 404
    return jsonify({'success': True})
    
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
        'version': '3.0',
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


@app.route('/api/elevators/upload-photo', methods=['POST'])
def api_upload_elevator_photo():
    """Загрузка фото подъезда"""
    if 'photo' not in request.files:
        return jsonify({'success': False, 'error': 'No photo provided'}), 400
    
    photo = request.files['photo']
    if photo.filename == '':
        return jsonify({'success': False, 'error': 'No photo selected'}), 400
    
    import os
    from PIL import Image
    import uuid
    
    upload_dir = 'static/uploads/entrances'
    os.makedirs(upload_dir, exist_ok=True)
    
    ext = os.path.splitext(photo.filename)[1].lower() if photo.filename else '.jpg'
    if ext not in ['.jpg', '.jpeg', '.png']:
        ext = '.jpg'
    
    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(upload_dir, filename)
    
    try:
        img = Image.open(photo)
        
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
        
        max_size = 1200
        if img.width > max_size or img.height > max_size:
            ratio = min(max_size / img.width, max_size / img.height)
            new_width = int(img.width * ratio)
            new_height = int(img.height * ratio)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        img.save(filepath, 'JPEG', quality=85, optimize=True)
    except Exception as e:
        print(f"Error compressing image: {e}")
        photo.save(filepath)
    
    return jsonify({
        'success': True,
        'path': f'/static/uploads/entrances/{filename}'
    })


@app.route('/api/elevators/apply-photo-to-address', methods=['POST'])
def api_apply_photo_to_address():
    """Применить фото ко всем лифтам с одинаковым адресом"""
    data = request.get_json()
    
    if not data or not data.get('address') or not data.get('photoPath'):
        return jsonify({'success': False, 'error': 'Не указан адрес или фото'}), 400
    
    address = data['address']
    photo_path = data['photoPath']
    
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE elevators SET key_photo = ? WHERE address = ?",
            (photo_path, address)
        )
        count = cursor.rowcount
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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
    from notification_service import start_scheduler
    start_scheduler()
    
    print("=" * 60)
    print("🛠️  Система заявок на ремонт лифтов")
    print("=" * 60)
    print("📞 Веб-интерфейс оператора: http://localhost:8081")
    print("📚 API документация: http://localhost:8081/api/docs")
    print("🏥 Health check: http://localhost:8081/api/health")
    print("⏰ Утренняя рассылка: 8:00 (пн-пт)")
    print("=" * 60)
    
    app.run(
        host='0.0.0.0',
        port=8081,
        debug=False,
        use_reloader=False
    )
