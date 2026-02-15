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
            
            # Таблица лифтов (объектов)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS elevators (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    elevator_id TEXT UNIQUE NOT NULL,
                    address TEXT NOT NULL,
                    entrance TEXT,
                    elevator_type TEXT DEFAULT 'пассажирский',
                    mechanic TEXT,
                    description TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Миграция: добавляем колонку mechanic если её нет
            try:
                cursor.execute('ALTER TABLE elevators ADD COLUMN mechanic TEXT')
            except sqlite3.OperationalError:
                pass  # Колонка уже существует
            
            # Таблица механиков
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS mechanics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT UNIQUE NOT NULL,
                    telegram_chat_id TEXT,
                    telegram_username TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица связи лифтов и механиков
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS elevator_mechanics (
                    elevator_id TEXT NOT NULL,
                    mechanic_id INTEGER NOT NULL,
                    is_primary BOOLEAN DEFAULT 1,
                    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (elevator_id, mechanic_id),
                    FOREIGN KEY (elevator_id) REFERENCES elevators(elevator_id) ON DELETE CASCADE,
                    FOREIGN KEY (mechanic_id) REFERENCES mechanics(id) ON DELETE CASCADE
                )
            ''')
            
            # Индексы для быстрого поиска
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_elevators_elevator_id ON elevators(elevator_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_elevators_address ON elevators(address)')
            
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
        
        # Обновляем историю (history может быть уже списком или строкой)
        history_data = ticket.get('history', '[]')
        if isinstance(history_data, str):
            history = json.loads(history_data)
        else:
            history = history_data
        
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

    # ═══════════════════════════════════════════════════════════════
    # Методы для работы с лифтами (объектами)
    # ═══════════════════════════════════════════════════════════════

    def add_elevator(self, data):
        """Добавление нового лифта в справочник"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO elevators 
                (elevator_id, address, entrance, elevator_type, mechanic, description, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('elevator_id'),
                data.get('address'),
                data.get('entrance'),
                data.get('elevator_type', 'пассажирский'),
                data.get('mechanic'),
                data.get('description', ''),
                data.get('status', 'active')
            ))
            conn.commit()
            return cursor.lastrowid

    def get_elevator(self, elevator_id):
        """Получение информации о лифте по ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM elevators WHERE elevator_id = ?', (elevator_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None

    def search_elevators(self, query=None, limit=50):
        """Поиск лифтов по адресу, ID или механику"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if query:
                cursor.execute('''
                    SELECT * FROM elevators 
                    WHERE elevator_id LIKE ? OR address LIKE ? OR mechanic LIKE ?
                    ORDER BY address
                    LIMIT ?
                ''', (f'%{query}%', f'%{query}%', f'%{query}%', limit))
            else:
                cursor.execute('SELECT * FROM elevators ORDER BY address LIMIT ?', (limit,))
            
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]

    def get_all_elevators(self, limit=200):
        """Получение всех лифтов"""
        return self.search_elevators(limit=limit)

    def update_elevator(self, elevator_id, data):
        """Обновление данных лифта"""
        fields = []
        values = []
        
        for key, value in data.items():
            if key != 'id' and key != 'elevator_id':
                fields.append(f"{key} = ?")
                values.append(value)
        
        if not fields:
            return None
        
        values.append(elevator_id)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE elevators 
                SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP
                WHERE elevator_id = ?
            ''', values)
            conn.commit()
            return self.get_elevator(elevator_id)

    def delete_elevator(self, elevator_id):
        """Удаление лифта из справочника"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM elevators WHERE elevator_id = ?', (elevator_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ═══════════════════════════════════════════════════════════════
    # Методы для работы с механиками
    # ═══════════════════════════════════════════════════════════════

    def get_mechanic_by_phone(self, phone):
        """Получение механика по номеру телефона"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM mechanics WHERE phone = ?', (phone,))
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None

    def get_mechanic_by_telegram(self, telegram_chat_id):
        """Получение механика по ID чата Telegram"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM mechanics WHERE telegram_chat_id = ?', (str(telegram_chat_id),))
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None

    def update_mechanic(self, mechanic_id, data):
        """Обновление данных механика"""
        fields = []
        values = []
        
        for key, value in data.items():
            if key != 'id':
                fields.append(f"{key} = ?")
                values.append(value)
        
        if not fields:
            return None
        
        values.append(mechanic_id)
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE mechanics 
                SET {', '.join(fields)}
                WHERE id = ?
            ''', values)
            conn.commit()
            
            cursor.execute('SELECT * FROM mechanics WHERE id = ?', (mechanic_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None

    def get_mechanic_elevators(self, mechanic_id):
        """Получение лифтов, закрепленных за механиком"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT e.* FROM elevators e
                JOIN elevator_mechanics em ON e.elevator_id = em.elevator_id
                WHERE em.mechanic_id = ?
                ORDER BY e.address
            ''', (mechanic_id,))
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]

    def assign_mechanic_to_elevator(self, elevator_id, mechanic_id, is_primary=True):
        """Закрепление механика за лифтом"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO elevator_mechanics (elevator_id, mechanic_id, is_primary)
                VALUES (?, ?, ?)
            ''', (elevator_id, mechanic_id, is_primary))
            conn.commit()
            return True

    def get_mechanics_for_elevator(self, elevator_id):
        """Получение механиков, закрепленных за лифтом"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT m.*, em.is_primary FROM mechanics m
                JOIN elevator_mechanics em ON m.id = em.mechanic_id
                WHERE em.elevator_id = ? AND m.status = 'active'
                ORDER BY em.is_primary DESC
            ''', (elevator_id,))
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]


# Синглтон для доступа к БД
db = TicketDatabase()
