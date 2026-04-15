"""
База данных заявок на ремонт лифтового оборудования
PostgreSQL/SQLite database for lift repair tickets
"""

import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor


def get_db():
    """Получение экземпляра базы данных"""
    use_pg = bool(os.getenv('DATABASE_URL'))
    if use_pg:
        return PostgreSQLDB()
    return SQLiteDB()


class SQLiteDB:
    """SQLite база данных"""
    
    def __init__(self, db_path='instance/tickets.db'):
        self.db_path = db_path
        Path('instance').mkdir(exist_ok=True)
        self.init_db()
    
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return conn
    
    def query(self, sql, params=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params or [])
            return cursor.fetchall()
    
    def query_one(self, sql, params=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params or [])
            return cursor.fetchone()
    
    def execute(self, sql, params=None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params or [])
            conn.commit()
    
    def _row_to_dict(self, row):
        if not row:
            return {}
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
    
    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_number TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source TEXT NOT NULL,
                    client_name TEXT,
                    client_phone TEXT,
                    client_email TEXT,
                    organization TEXT,
                    address TEXT NOT NULL,
                    elevator_id TEXT,
                    elevator_type TEXT,
                    problem_description TEXT NOT NULL,
                    priority TEXT DEFAULT 'обычный',
                    status TEXT DEFAULT 'новая',
                    assigned_to TEXT,
                    scheduled_date TIMESTAMP,
                    history TEXT DEFAULT '[]',
                    operator_notes TEXT,
                    completed_at TIMESTAMP,
                    rating INTEGER,
                    client_feedback TEXT
                )
            ''')
            
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
                    serial_number TEXT,
                    key_photo TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS mechanics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT UNIQUE NOT NULL,
                    max_chat_id TEXT,
                    max_username TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
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
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_elevators_elevator_id ON elevators(elevator_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_elevators_address ON elevators(address)')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS oncall_mechanics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mechanic_id INTEGER NOT NULL,
                    date DATE UNIQUE NOT NULL,
                    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (mechanic_id) REFERENCES mechanics(id) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ticket_mechanics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    mechanic_id INTEGER NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'sent',
                    responded_at TIMESTAMP,
                    FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE,
                    FOREIGN KEY (mechanic_id) REFERENCES mechanics(id) ON DELETE CASCADE,
                    UNIQUE(ticket_id, mechanic_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS repair_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    mechanic_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    problem_description TEXT,
                    elevator_id TEXT,
                    address TEXT,
                    work_done TEXT NOT NULL,
                    parts_used TEXT,
                    time_spent INTEGER,
                    notes TEXT,
                    photos TEXT,
                    FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE,
                    FOREIGN KEY (mechanic_id) REFERENCES mechanics(id) ON DELETE SET NULL
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('notification_linear', 'true')")
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('notification_oncall', 'true')")
            
            conn.commit()


class PostgreSQLDB:
    """PostgreSQL база данных"""
    
    def __init__(self):
        self.conn = None
        self.init_db()
    
    def get_connection(self):
        if self.conn is None or self.conn.closed:
            self.conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        return self.conn
    
    def query(self, sql, params=None):
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(sql, params or [])
        rows = cursor.fetchall()
        cursor.close()
        return [dict(row) for row in rows]
    
    def query_one(self, sql, params=None):
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None
    
    def execute(self, sql, params=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params or [])
            conn.commit()
        except psycopg2.errors.DuplicateTable:
            pass
        except Exception as e:
            conn.rollback()
            raise e
    
    def _row_to_dict(self, row):
        if not row:
            return {}
        return dict(row)
    
    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Проверяем существующие таблицы
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = {row[0] for row in cursor.fetchall()}
        
        def create_table(name, sql):
            if name not in tables:
                try:
                    cursor.execute(sql)
                except psycopg2.errors.DuplicateTable:
                    pass
        
        # tickets
        create_table('tickets', '''
            CREATE TABLE tickets (
                id SERIAL PRIMARY KEY,
                ticket_number TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source TEXT NOT NULL,
                client_name TEXT,
                client_phone TEXT,
                client_email TEXT,
                organization TEXT,
                address TEXT NOT NULL,
                elevator_id TEXT,
                elevator_type TEXT,
                problem_description TEXT NOT NULL,
                priority TEXT DEFAULT 'обычный',
                status TEXT DEFAULT 'новая',
                assigned_to TEXT,
                scheduled_date TIMESTAMP,
                history TEXT DEFAULT '[]',
                operator_notes TEXT,
                completed_at TIMESTAMP,
                rating INTEGER,
                client_feedback TEXT
            )
        ''')
        
        # comments
        create_table('comments', '''
            CREATE TABLE comments (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL,
                author TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (ticket_id) REFERENCES tickets (id) ON DELETE CASCADE
            )
        ''')
        
        # elevators
        create_table('elevators', '''
            CREATE TABLE elevators (
                id SERIAL PRIMARY KEY,
                elevator_id TEXT UNIQUE NOT NULL,
                address TEXT NOT NULL,
                entrance TEXT,
                elevator_type TEXT DEFAULT 'пассажирский',
                mechanic TEXT,
                description TEXT,
                status TEXT DEFAULT 'active',
                serial_number TEXT,
                key_photo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # mechanics
        create_table('mechanics', '''
            CREATE TABLE mechanics (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL,
                max_chat_id TEXT,
                max_username TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # elevator_mechanics
        create_table('elevator_mechanics', '''
            CREATE TABLE elevator_mechanics (
                elevator_id TEXT NOT NULL,
                mechanic_id INTEGER NOT NULL,
                is_primary BOOLEAN DEFAULT TRUE,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (elevator_id, mechanic_id),
                FOREIGN KEY (elevator_id) REFERENCES elevators(elevator_id) ON DELETE CASCADE,
                FOREIGN KEY (mechanic_id) REFERENCES mechanics(id) ON DELETE CASCADE
            )
        ''')
        
        # indexes
        if 'tickets' in tables:
            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at)')
            except:
                pass
        
        if 'elevators' in tables:
            try:
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_elevators_elevator_id ON elevators(elevator_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_elevators_address ON elevators(address)')
            except:
                pass
        
        # oncall_mechanics
        create_table('oncall_mechanics', '''
            CREATE TABLE oncall_mechanics (
                id SERIAL PRIMARY KEY,
                mechanic_id INTEGER NOT NULL,
                date DATE UNIQUE NOT NULL,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (mechanic_id) REFERENCES mechanics(id) ON DELETE CASCADE
            )
        ''')
        
        # ticket_mechanics
        create_table('ticket_mechanics', '''
            CREATE TABLE ticket_mechanics (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL,
                mechanic_id INTEGER NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'sent',
                responded_at TIMESTAMP,
                FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE,
                FOREIGN KEY (mechanic_id) REFERENCES mechanics(id) ON DELETE CASCADE,
                UNIQUE(ticket_id, mechanic_id)
            )
        ''')
        
        # repair_reports
        create_table('repair_reports', '''
            CREATE TABLE repair_reports (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL,
                mechanic_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                problem_description TEXT,
                elevator_id TEXT,
                address TEXT,
                work_done TEXT NOT NULL,
                parts_used TEXT,
                time_spent INTEGER,
                notes TEXT,
                photos TEXT,
                FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE,
                FOREIGN KEY (mechanic_id) REFERENCES mechanics(id) ON DELETE SET NULL
            )
        ''')
        
        # settings
        create_table('settings', '''
            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        try:
            cursor.execute("INSERT INTO settings (key, value) VALUES ('notification_linear', 'true') ON CONFLICT (key) DO NOTHING")
            cursor.execute("INSERT INTO settings (key, value) VALUES ('notification_oncall', 'true') ON CONFLICT (key) DO NOTHING")
        except:
            pass
        
        conn.commit()
        cursor.close()


# Legacy TicketDatabase class that uses the appropriate backend
class TicketDatabase:
    """Класс для работы с базой данных заявок (Legacy API)"""
    
    def __init__(self, db_path='instance/tickets.db'):
        self._db = get_db()
        self.db_path = db_path
    
    def get_connection(self):
        return self._db
    
    def init_db(self):
        pass
    
    def generate_ticket_number(self):
        now = datetime.now()
        prefix = now.strftime('%Y%m%d')
        row = self._db.query_one(
            "SELECT COUNT(*) as count FROM tickets WHERE ticket_number LIKE %s" if isinstance(self._db, PostgreSQLDB) else "SELECT COUNT(*) as count FROM tickets WHERE ticket_number LIKE ?",
            (f"{prefix}%",)
        )
        count = row['count'] if isinstance(row, dict) else row[0]
        return f"{prefix}-{count + 1:04d}"
    
    def create_ticket(self, data):
        ticket_number = self.generate_ticket_number()
        
        history = [{
            'timestamp': datetime.now().isoformat(),
            'action': 'Создание заявки',
            'user': data.get('source', 'system')
        }]
        
        fields = ['ticket_number', 'source', 'address', 'problem_description', 'history', 'priority', 'status']
        values = [ticket_number, data.get('source', 'web'), data.get('address'), data.get('problem_description'), json.dumps(history, ensure_ascii=False), data.get('priority', 'обычный'), 'новая']
        
        for f in ['client_name', 'client_phone', 'client_email', 'organization', 'elevator_id', 'elevator_type', 'operator_notes']:
            if f in data:
                fields.append(f)
                values.append(data[f])
        
        is_pg = isinstance(self._db, PostgreSQLDB)
        placeholders = ', '.join(['%s'] * len(values)) if is_pg else ', '.join(['?'] * len(values))
        field_list = ', '.join(fields)
        
        sql = f"INSERT INTO tickets ({field_list}) VALUES ({placeholders}) RETURNING id" if is_pg else f"INSERT INTO tickets ({field_list}) VALUES ({placeholders})"
        
        conn = self._db.get_connection()
        cursor = conn.cursor()
        
        if is_pg:
            cursor.execute(sql, values)
            result = cursor.fetchone()
            ticket_id = result['id'] if result else None
        else:
            cursor.execute(sql, values)
            ticket_id = cursor.lastrowid
        
        conn.commit()
        cursor.close()
        
        return self.get_ticket(ticket_id)
    
    def get_ticket(self, ticket_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT * FROM tickets WHERE id = %s" if is_pg else "SELECT * FROM tickets WHERE id = ?"
        return self._db.query_one(sql, (ticket_id,))
    
    def get_ticket_by_number(self, ticket_number):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT * FROM tickets WHERE ticket_number = %s" if is_pg else "SELECT * FROM tickets WHERE ticket_number = ?"
        return self._db.query_one(sql, (ticket_number,))
    
    def search_tickets(self, filters=None, limit=200, offset=0, exclude_status=None):
        is_pg = isinstance(self._db, PostgreSQLDB)
        query = 'SELECT * FROM tickets WHERE 1=1'
        params = []
        
        if filters:
            for key in ['status', 'priority', 'address', 'elevator_id', 'date_from', 'date_to']:
                if key in filters:
                    op = '=' if key in ['status', 'priority', 'elevator_id'] else 'LIKE' if key == 'address' else '>=' if key == 'date_from' else '<='
                    query += f' AND {key} {op} %s' if is_pg else f' AND {key} {op} ?'
                    params.append(f"%{filters[key]}%" if op == 'LIKE' else filters[key])
        
        if exclude_status:
            if isinstance(exclude_status, list):
                placeholders = ', '.join(['%s'] * len(exclude_status)) if is_pg else ', '.join(['?'] * len(exclude_status))
                query += f' AND status NOT IN ({placeholders})'
                params.extend(exclude_status)
            else:
                query += ' AND status != %s' if is_pg else ' AND status != ?'
                params.append(exclude_status)
        
        query += ' ORDER BY created_at DESC LIMIT %s OFFSET %s' if is_pg else ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])
        
        return self._db.query(query, params)
    
    def update_ticket(self, ticket_id, data, user='system'):
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return None
        
        history_data = ticket.get('history', [])
        if isinstance(history_data, str):
            try:
                history_data = json.loads(history_data)
            except:
                history_data = []
        elif not history_data:
            history_data = []
        
        history_data.append({
            'timestamp': datetime.now().isoformat(),
            'action': 'Обновление заявки',
            'user': user,
            'changes': list(data.keys())
        })
        
        data['history'] = json.dumps(history_data, ensure_ascii=False)
        data['updated_at'] = datetime.now().isoformat()
        
        is_pg = isinstance(self._db, PostgreSQLDB)
        fields = ', '.join([f"{k} = %s" if is_pg else f"{k} = ?" for k in data.keys()])
        values = list(data.values()) + [ticket_id]
        
        sql = f'UPDATE tickets SET {fields} WHERE id = %s' if is_pg else f'UPDATE tickets SET {fields} WHERE id = ?'
        self._db.execute(sql, values)
        
        return self.get_ticket(ticket_id)
    
    def update_ticket_status(self, ticket_id, new_status, user='system', notes=None):
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return None
        
        history_data = ticket.get('history', [])
        if isinstance(history_data, str):
            try:
                history_data = json.loads(history_data)
            except:
                history_data = []
        
        history_data.append({
            'timestamp': datetime.now().isoformat(),
            'action': f"Изменение статуса: {ticket.get('status', 'новая')} → {new_status}",
            'user': user,
            'notes': notes
        })
        
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "UPDATE tickets SET status = %s, history = %s, updated_at = %s" if is_pg else "UPDATE tickets SET status = ?, history = ?, updated_at = ?"
        if new_status == 'выполнена':
            sql += ", completed_at = %s" if is_pg else ", completed_at = ?"
        
        params = [new_status, json.dumps(history_data, ensure_ascii=False), datetime.now().isoformat()]
        if new_status == 'выполнена':
            params.append(datetime.now().isoformat())
        params.append(ticket_id)
        
        sql += " WHERE id = %s" if is_pg else " WHERE id = ?"
        self._db.execute(sql, params)
        
        return self.get_ticket(ticket_id)
    
    def add_comment(self, ticket_id, author, text):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "INSERT INTO comments (ticket_id, author, text) VALUES (%s, %s, %s)" if is_pg else "INSERT INTO comments (ticket_id, author, text) VALUES (?, ?, ?)"
        self._db.execute(sql, (ticket_id, author, text))
    
    def get_comments(self, ticket_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT * FROM comments WHERE ticket_id = %s ORDER BY created_at ASC" if is_pg else "SELECT * FROM comments WHERE ticket_id = ? ORDER BY created_at ASC"
        return self._db.query(sql, (ticket_id,))
    
    def reject_ticket(self, ticket_id, mechanic_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        self.add_comment(ticket_id, 'system', f"механик отказался от заявки")
        sql = "UPDATE ticket_mechanics SET status = 'rejected', responded_at = %s WHERE ticket_id = %s AND mechanic_id = %s" if is_pg else "UPDATE ticket_mechanics SET status = 'rejected', responded_at = ? WHERE ticket_id = ? AND mechanic_id = ?"
        self._db.execute(sql, (datetime.now().isoformat(), ticket_id, mechanic_id))
    
    def get_ticket_mechanics(self, ticket_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT * FROM ticket_mechanics WHERE ticket_id = %s" if is_pg else "SELECT * FROM ticket_mechanics WHERE ticket_id = ?"
        return self._db.query(sql, (ticket_id,))
    
    def get_statistics(self):
        stats = {}
        is_pg = isinstance(self._db, PostgreSQLDB)
        
        for key, cond in [
            ('total', "status != 'отменена'"),
            ('new', "status = 'новая'"),
            ('in_progress', "status = 'в работе'"),
            ('done', "status = 'выполнена'"),
            ('urgent', "priority = 'срочный'"),
            ('urgent_new', "priority = 'срочный' AND status = 'новая'"),
            ('urgent_work', "priority = 'срочный' AND status = 'в работе'"),
            ('urgent_done', "priority = 'срочный' AND status = 'выполнена'")
        ]:
            sql = f"SELECT COUNT(*) as count FROM tickets WHERE {cond}"
            row = self._db.query_one(sql)
            stats[key] = row['count'] if isinstance(row, dict) else row[0]
        
        return stats
    
    def get_shift_statistics(self, shift_start, shift_end):
        stats = {'created': 0, 'completed': 0}
        is_pg = isinstance(self._db, PostgreSQLDB)
        
        for key, sql_part in [
            ('created', f"created_at >= %s AND created_at < %s" if is_pg else f"created_at >= ? AND created_at < ?"),
            ('completed', f"status = 'выполнена' AND completed_at >= %s AND completed_at < %s" if is_pg else f"status = 'выполнена' AND completed_at >= ? AND completed_at < ?")
        ]:
            sql = f"SELECT COUNT(*) as count FROM tickets WHERE {sql_part}"
            row = self._db.query_one(sql, (shift_start, shift_end))
            stats[key] = row['count'] if isinstance(row, dict) else row[0]
        
        return stats
    
    def get_elevator(self, elevator_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT * FROM elevators WHERE elevator_id = %s" if is_pg else "SELECT * FROM elevators WHERE elevator_id = ?"
        return self._db.query_one(sql, (elevator_id,))
    
    def get_all_elevators(self, limit=100):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT * FROM elevators ORDER BY address LIMIT %s" if is_pg else "SELECT * FROM elevators ORDER BY address LIMIT ?"
        return self._db.query(sql, (limit,))
    
    def search_elevators(self, query_text):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT * FROM elevators WHERE address LIKE %s OR elevator_id LIKE %s" if is_pg else "SELECT * FROM elevators WHERE address LIKE ? OR elevator_id LIKE ?"
        return self._db.query(sql, (f"%{query_text}%", f"%{query_text}%"))
    
    def create_elevator(self, data):
        is_pg = isinstance(self._db, PostgreSQLDB)
        fields = ', '.join(data.keys())
        placeholders = ', '.join(['%s'] * len(data)) if is_pg else ', '.join(['?'] * len(data))
        sql = f"INSERT INTO elevators ({fields}) VALUES ({placeholders}) RETURNING id" if is_pg else f"INSERT INTO elevators ({fields}) VALUES ({placeholders})"
        
        conn = self._db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, list(data.values()))
        
        if is_pg:
            result = cursor.fetchone()
            elevator_id = result['id'] if result else None
        else:
            elevator_id = cursor.lastrowid
        
        conn.commit()
        cursor.close()
        
        return self.get_elevator(data['elevator_id'])
    
    def update_elevator(self, elevator_id, data):
        is_pg = isinstance(self._db, PostgreSQLDB)
        data['updated_at'] = datetime.now().isoformat()
        fields = ', '.join([f"{k} = %s" if is_pg else f"{k} = ?" for k in data.keys()])
        values = list(data.values()) + [elevator_id]
        sql = f"UPDATE elevators SET {fields} WHERE elevator_id = %s" if is_pg else f"UPDATE elevators SET {fields} WHERE elevator_id = ?"
        self._db.execute(sql, values)
        return self.get_elevator(elevator_id)
    
    def delete_elevator(self, elevator_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "DELETE FROM elevators WHERE elevator_id = %s" if is_pg else "DELETE FROM elevators WHERE elevator_id = ?"
        self._db.execute(sql, (elevator_id,))
    
    def get_all_mechanics(self, limit=100):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT * FROM mechanics ORDER BY name LIMIT %s" if is_pg else "SELECT * FROM mechanics ORDER BY name LIMIT ?"
        return self._db.query(sql, (limit,))
    
    def get_mechanic(self, mechanic_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT * FROM mechanics WHERE id = %s" if is_pg else "SELECT * FROM mechanics WHERE id = ?"
        return self._db.query_one(sql, (mechanic_id,))
    
    def create_mechanic(self, data):
        is_pg = isinstance(self._db, PostgreSQLDB)
        fields = ', '.join(data.keys())
        placeholders = ', '.join(['%s'] * len(data)) if is_pg else ', '.join(['?'] * len(data))
        sql = f"INSERT INTO mechanics ({fields}) VALUES ({placeholders}) RETURNING id" if is_pg else f"INSERT INTO mechanics ({fields}) VALUES ({placeholders})"
        
        conn = self._db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, list(data.values()))
        
        if is_pg:
            result = cursor.fetchone()
            mech_id = result['id'] if result else None
        else:
            mech_id = cursor.lastrowid
        
        conn.commit()
        cursor.close()
        
        return self.get_mechanic(mech_id)
    
    def delete_mechanic(self, mechanic_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "DELETE FROM mechanics WHERE id = %s" if is_pg else "DELETE FROM mechanics WHERE id = ?"
        self._db.execute(sql, (mechanic_id,))
    
    def get_mechanic_by_phone(self, phone):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT * FROM mechanics WHERE phone = %s" if is_pg else "SELECT * FROM mechanics WHERE phone = ?"
        return self._db.query_one(sql, (phone,))
    
    def get_mechanic_by_max(self, max_chat_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT * FROM mechanics WHERE max_chat_id = %s" if is_pg else "SELECT * FROM mechanics WHERE max_chat_id = ?"
        return self._db.query_one(sql, (str(max_chat_id),))
    
    def update_mechanic(self, mechanic_id, data):
        is_pg = isinstance(self._db, PostgreSQLDB)
        fields = ', '.join([f"{k} = %s" if is_pg else f"{k} = ?" for k in data.keys()])
        values = list(data.values()) + [mechanic_id]
        sql = f"UPDATE mechanics SET {fields} WHERE id = %s" if is_pg else f"UPDATE mechanics SET {fields} WHERE id = ?"
        self._db.execute(sql, values)
        return self.get_mechanic(mechanic_id)
    
    def get_mechanics_for_elevator(self, elevator_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = '''
            SELECT m.* FROM mechanics m
            JOIN elevator_mechanics em ON m.id = em.mechanic_id
            WHERE em.elevator_id = %s
        ''' if is_pg else '''
            SELECT m.* FROM mechanics m
            JOIN elevator_mechanics em ON m.id = em.mechanic_id
            WHERE em.elevator_id = ?
        '''
        return self._db.query(sql, (elevator_id,))
    
    def get_mechanics_for_elevator_by_mechanic(self, mechanic_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = '''
            SELECT e.* FROM elevators e
            JOIN elevator_mechanics em ON e.elevator_id = em.elevator_id
            WHERE em.mechanic_id = %s
        ''' if is_pg else '''
            SELECT e.* FROM elevators e
            JOIN elevator_mechanics em ON e.elevator_id = em.elevator_id
            WHERE em.mechanic_id = ?
        '''
        return self._db.query(sql, (mechanic_id,))
    
    def assign_elevator_to_mechanic(self, elevator_id, mechanic_id, is_primary=True):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "INSERT INTO elevator_mechanics (elevator_id, mechanic_id, is_primary) VALUES (%s, %s, %s)" if is_pg else "INSERT INTO elevator_mechanics (elevator_id, mechanic_id, is_primary) VALUES (?, ?, ?)"
        self._db.execute(sql, (elevator_id, mechanic_id, is_primary))
    
    def remove_elevator_from_mechanic(self, elevator_id, mechanic_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "DELETE FROM elevator_mechanics WHERE elevator_id = %s AND mechanic_id = %s" if is_pg else "DELETE FROM elevator_mechanics WHERE elevator_id = ? AND mechanic_id = ?"
        self._db.execute(sql, (elevator_id, mechanic_id))
    
    def get_oncall_mechanic(self, date_str):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT m.* FROM mechanics m JOIN oncall_mechanics om ON m.id = om.mechanic_id WHERE om.date = %s" if is_pg else "SELECT m.* FROM mechanics m JOIN oncall_mechanics om ON m.id = om.mechanic_id WHERE om.date = ?"
        return self._db.query_one(sql, (date_str,))
    
    def get_oncall_mechanic_for_date(self, date_str):
        return self.get_oncall_mechanic(date_str)
    
    def set_oncall_mechanic(self, mechanic_id, date_str):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "INSERT INTO oncall_mechanics (mechanic_id, date) VALUES (%s, %s) ON CONFLICT (date) DO UPDATE SET mechanic_id = %s" if is_pg else "INSERT OR REPLACE INTO oncall_mechanics (mechanic_id, date) VALUES (?, ?)"
        self._db.execute(sql, (mechanic_id, date_str, mechanic_id) if is_pg else (mechanic_id, date_str))
    
    def get_next_oncall_mechanic(self):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = '''
            SELECT m.* FROM mechanics m
            WHERE m.status = 'active'
            ORDER BY m.id
            LIMIT 1
        ''' if is_pg else '''
            SELECT m.* FROM mechanics m
            WHERE m.status = 'active'
            ORDER BY m.id
            LIMIT 1
        '''
        return self._db.query_one(sql)
    
    def send_ticket_to_mechanic(self, ticket_id, mechanic_id):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "INSERT INTO ticket_mechanics (ticket_id, mechanic_id, status) VALUES (%s, %s, 'sent')" if is_pg else "INSERT OR IGNORE INTO ticket_mechanics (ticket_id, mechanic_id, status) VALUES (?, ?, 'sent')"
        self._db.execute(sql, (ticket_id, mechanic_id))
    
    def create_repair_report(self, data):
        is_pg = isinstance(self._db, PostgreSQLDB)
        fields = ', '.join(data.keys())
        placeholders = ', '.join(['%s'] * len(data)) if is_pg else ', '.join(['?'] * len(data))
        sql = f"INSERT INTO repair_reports ({fields}) VALUES ({placeholders}) RETURNING id" if is_pg else f"INSERT INTO repair_reports ({fields}) VALUES ({placeholders})"
        
        conn = self._db.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, list(data.values()))
        
        if is_pg:
            result = cursor.fetchone()
            report_id = result['id'] if result else None
        else:
            report_id = cursor.lastrowid
        
        conn.commit()
        cursor.close()
        return report_id
    
    def get_setting(self, key):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT value FROM settings WHERE key = %s" if is_pg else "SELECT value FROM settings WHERE key = ?"
        row = self._db.query_one(sql, (key,))
        return row['value'] if row and isinstance(row, dict) else (row[0] if row else None)
    
    def set_setting(self, key, value):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = CURRENT_TIMESTAMP" if is_pg else "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)"
        self._db.execute(sql, (key, value, value) if is_pg else (key, value))
    
    def get_all_settings(self):
        is_pg = isinstance(self._db, PostgreSQLDB)
        sql = "SELECT key, value FROM settings"
        return self._db.query(sql)


db = TicketDatabase()