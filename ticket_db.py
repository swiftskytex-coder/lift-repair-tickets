"""
База данных заявок на ремонт лифтового оборудования
SQLite-based database for lift repair tickets
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path


class TicketDatabase:
    """Класс для работы с базой данных заявок"""
    
    def __init__(self, db_path='instance/tickets.db'):
        self.db_path = db_path
        Path('instance').mkdir(exist_ok=True)
        self.init_db()
    
    def get_connection(self):
        """Получение соединения с БД"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_db(self):
        """Инициализация базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица заявок
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_number TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source TEXT NOT NULL,  -- phone, mobile_app, web, operator
                    
                    -- Информация о клиенте (опционально)
                    client_name TEXT,
                    client_phone TEXT,
                    client_email TEXT,
                    organization TEXT,
                    
                    -- Адрес и лифт
                    address TEXT NOT NULL,
                    elevator_id TEXT,
                    elevator_type TEXT,
                    
                    -- Описание проблемы
                    problem_description TEXT NOT NULL,
                    priority TEXT DEFAULT 'обычный',  -- срочный, высокий, обычный, низкий
                    
                    -- Статус заявки
                    status TEXT DEFAULT 'новая',  -- новая, в работе, выполнена, отменена
                    
                    -- Назначение
                    assigned_to TEXT,  -- ID исполнителя
                    scheduled_date TIMESTAMP,  -- Запланированная дата
                    
                    -- История изменений (JSON)
                    history TEXT DEFAULT '[]',
                    
                    -- Заметки оператора
                    operator_notes TEXT,
                    
                    -- Время выполнения
                    completed_at TIMESTAMP,
                    
                    -- Оценка клиента
                    rating INTEGER,  -- 1-5
                    client_feedback TEXT
                )
            ''')
            
            # Таблица комментариев
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    author TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE
                )
            ''')
            
            # Индексы для быстрого поиска
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at)')
            
            conn.commit()
    
    def generate_ticket_number(self):
        """Генерация уникального номера заявки"""
        now = datetime.now()
        prefix = now.strftime('%Y%m%d')
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM tickets WHERE ticket_number LIKE ?",
                (f"{prefix}%",)
            )
            count = cursor.fetchone()[0]
            return f"{prefix}-{count + 1:04d}"
    
    def create_ticket(self, data):
        """Создание новой заявки"""
        ticket_number = self.generate_ticket_number()
        
        # Формируем историю
        history = [{
            'timestamp': datetime.now().isoformat(),
            'action': 'Создание заявки',
            'user': data.get('operator', 'system')
        }]
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tickets (
                    ticket_number, source, client_name, client_phone, client_email,
                    organization, address, elevator_id, elevator_type,
                    problem_description, priority, status, operator_notes, history
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ticket_number,
                data.get('source', 'operator'),
                data.get('client_name'),
                data.get('client_phone'),
                data.get('client_email'),
                data.get('organization'),
                data.get('address'),
                data.get('elevator_id'),
                data.get('elevator_type'),
                data.get('problem_description'),
                data.get('priority', 'обычный'),
                'новая',
                data.get('operator_notes'),
                json.dumps(history, ensure_ascii=False)
            ))
            
            ticket_id = cursor.lastrowid
            conn.commit()
            
        return self.get_ticket(ticket_id)
    
    def get_ticket(self, ticket_id):
        """Получение заявки по ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM tickets WHERE id = ?', (ticket_id,))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_dict(row)
            return None
    
    def get_ticket_by_number(self, ticket_number):
        """Получение заявки по номеру"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM tickets WHERE ticket_number = ?', (ticket_number,))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_dict(row)
            return None
    
    def search_tickets(self, filters=None, limit=50, offset=0):
        """Поиск заявок с фильтрами"""
        query = 'SELECT * FROM tickets WHERE 1=1'
        params = []
        
        if filters:
            if 'status' in filters:
                query += ' AND status = ?'
                params.append(filters['status'])
            
            if 'priority' in filters:
                query += ' AND priority = ?'
                params.append(filters['priority'])
            
            if 'address' in filters:
                query += ' AND address LIKE ?'
                params.append(f"%{filters['address']}%")
            
            if 'elevator_id' in filters:
                query += ' AND elevator_id = ?'
                params.append(filters['elevator_id'])
            
            if 'date_from' in filters:
                query += ' AND created_at >= ?'
                params.append(filters['date_from'])
            
            if 'date_to' in filters:
                query += ' AND created_at <= ?'
                params.append(filters['date_to'])
        
        query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    def update_ticket_status(self, ticket_id, new_status, user='system', notes=None):
        """Обновление статуса заявки"""
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return None
        
        # Обновляем историю
        history = json.loads(ticket.get('history', '[]'))
        history.append({
            'timestamp': datetime.now().isoformat(),
            'action': f'Изменение статуса: {ticket["status"]} → {new_status}',
            'user': user,
            'notes': notes
        })
        
        update_data = {
            'status': new_status,
            'history': json.dumps(history, ensure_ascii=False),
            'updated_at': datetime.now().isoformat()
        }
        
        if new_status == 'выполнена':
            update_data['completed_at'] = datetime.now().isoformat()
        
        # Формируем SQL запрос
        fields = ', '.join([f"{k} = ?" for k in update_data.keys()])
        values = list(update_data.values()) + [ticket_id]
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'UPDATE tickets SET {fields} WHERE id = ?', values)
            conn.commit()
        
        return self.get_ticket(ticket_id)
    
    def update_ticket(self, ticket_id, data, user='system'):
        """Обновление данных заявки"""
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return None
        
        # Обновляем историю
        history = json.loads(ticket.get('history', '[]'))
        history.append({
            'timestamp': datetime.now().isoformat(),
            'action': 'Обновление заявки',
            'user': user,
            'changes': list(data.keys())
        })
        
        data['history'] = json.dumps(history, ensure_ascii=False)
        data['updated_at'] = datetime.now().isoformat()
        
        # Формируем SQL запрос
        fields = ', '.join([f"{k} = ?" for k in data.keys()])
        values = list(data.values()) + [ticket_id]
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'UPDATE tickets SET {fields} WHERE id = ?', values)
            conn.commit()
        
        return self.get_ticket(ticket_id)
    
    def add_comment(self, ticket_id, author, text):
        """Добавление комментария к заявке"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO comments (ticket_id, author, text)
                VALUES (?, ?, ?)
            ''', (ticket_id, author, text))
            conn.commit()
            return cursor.lastrowid
    
    def get_comments(self, ticket_id):
        """Получение комментариев к заявке"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM comments WHERE ticket_id = ?
                ORDER BY created_at ASC
            ''', (ticket_id,))
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]
    
    def get_statistics(self):
        """Получение статистики заявок"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Общая статистика
            cursor.execute('SELECT COUNT(*) FROM tickets')
            total = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'новая'")
            new_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'в работе'")
            in_progress = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'выполнена'")
            completed = cursor.fetchone()[0]
            
            # По приоритетам
            cursor.execute('''
                SELECT priority, COUNT(*) FROM tickets
                GROUP BY priority
            ''')
            by_priority = {row[0]: row[1] for row in cursor.fetchall()}
            
            # По источникам
            cursor.execute('''
                SELECT source, COUNT(*) FROM tickets
                GROUP BY source
            ''')
            by_source = {row[0]: row[1] for row in cursor.fetchall()}
            
            return {
                'total': total,
                'new': new_count,
                'in_progress': in_progress,
                'completed': completed,
                'by_priority': by_priority,
                'by_source': by_source
            }
    
    def _row_to_dict(self, row):
        """Конвертация sqlite Row в dict"""
        result = {}
        for key in row.keys():
            value = row[key]
            if key == 'history' and value:
                try:
                    result[key] = json.loads(value)
                except:
                    result[key] = value
            else:
                result[key] = value
        return result


# Синглтон для доступа к БД
db = TicketDatabase()
