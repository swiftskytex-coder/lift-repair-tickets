"""
Главный сервер системы заявок на ремонт лифтов
Flask-based web server for lift repair tickets
"""

import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory
from ticket_db import db

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['JSON_AS_ASCII'] = False


# ═══════════════════════════════════════════════════════════════
# Веб-интерфейс для оператора
# ═══════════════════════════════════════════════════════════════

@app.route('/')
def index():
    """Главная страница - дашборд оператора"""
    stats = db.get_statistics()
    recent_tickets = db.search_tickets(limit=10)
    return render_template('operator_dashboard.html', 
                         stats=stats, 
                         tickets=recent_tickets,
                         now=datetime.now())


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
    return render_template('ticket_detail.html', 
                         ticket=ticket, 
                         comments=comments)


@app.route('/new-ticket')
def new_ticket_form():
    """Форма создания новой заявки"""
    return render_template('new_ticket.html')


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
    
    # Создание заявки
    ticket = db.create_ticket(data)
    
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
        debug=True
    )
