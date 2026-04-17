"""
База данных заявок на ремонт лифтового оборудования
PostgreSQL-only backend
"""

import os
import json
from datetime import datetime
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor


def get_db():
    """Получение экземпляра базы данных"""
    return PostgreSQLDB()


class PostgreSQLDB:
    """PostgreSQL база данных"""

    def __init__(self):
        self._dsn = os.environ['DATABASE_URL']
        self.init_db()

    def get_connection(self):
        conn = psycopg2.connect(self._dsn)
        conn.autocommit = False
        return conn

    def query(self, sql, params=None):
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params or [])
                return [dict(row) for row in cursor.fetchall()]

    def query_one(self, sql, params=None):
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params or [])
                row = cursor.fetchone()
                return dict(row) if row else None

    def execute(self, sql, params=None):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params or [])
            conn.commit()

    def init_db(self):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                tables = {row[0] for row in cursor.fetchall()}

            def create_table(name, sql):
                if name not in tables:
                    with conn.cursor() as cur:
                        try:
                            cur.execute(sql)
                            conn.commit()
                        except psycopg2.errors.DuplicateTable:
                            conn.rollback()

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

        create_table('comments', '''
            CREATE TABLE comments (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                author TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

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

        create_table('elevator_mechanics', '''
            CREATE TABLE elevator_mechanics (
                elevator_id TEXT NOT NULL REFERENCES elevators(elevator_id) ON DELETE CASCADE,
                mechanic_id INTEGER NOT NULL REFERENCES mechanics(id) ON DELETE CASCADE,
                is_primary BOOLEAN DEFAULT TRUE,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (elevator_id, mechanic_id)
            )
        ''')

        create_table('oncall_mechanics', '''
            CREATE TABLE oncall_mechanics (
                id SERIAL PRIMARY KEY,
                mechanic_id INTEGER NOT NULL REFERENCES mechanics(id) ON DELETE CASCADE,
                date DATE UNIQUE NOT NULL,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        create_table('ticket_mechanics', '''
            CREATE TABLE ticket_mechanics (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                mechanic_id INTEGER NOT NULL REFERENCES mechanics(id) ON DELETE CASCADE,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'sent',
                responded_at TIMESTAMP,
                UNIQUE(ticket_id, mechanic_id)
            )
        ''')

        create_table('repair_reports', '''
            CREATE TABLE repair_reports (
                id SERIAL PRIMARY KEY,
                ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                mechanic_id INTEGER REFERENCES mechanics(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                problem_description TEXT,
                elevator_id TEXT,
                address TEXT,
                work_done TEXT NOT NULL,
                parts_used TEXT,
                time_spent INTEGER,
                notes TEXT,
                photos TEXT
            )
        ''')

        create_table('settings', '''
            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Indexes
        with conn.cursor() as cursor:
            for idx_sql in [
                'CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)',
                'CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority)',
                'CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at)',
                'CREATE INDEX IF NOT EXISTS idx_elevators_elevator_id ON elevators(elevator_id)',
                'CREATE INDEX IF NOT EXISTS idx_elevators_address ON elevators(address)',
            ]:
                try:
                    cursor.execute(idx_sql)
                except Exception:
                    conn.rollback()
                    break
            else:
                conn.commit()

        # Default settings
        try:
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO settings (key, value) VALUES ('notification_linear', 'true') ON CONFLICT (key) DO NOTHING")
                cursor.execute("INSERT INTO settings (key, value) VALUES ('notification_oncall', 'true') ON CONFLICT (key) DO NOTHING")
            conn.commit()
        except Exception:
            conn.rollback()


class TicketDatabase:
    """Основной класс для работы с БД заявок"""

    def __init__(self):
        self._db = get_db()

    def get_connection(self):
        return self._db.get_connection()

    def generate_ticket_number(self):
        now = datetime.now()
        prefix = now.strftime('%Y%m%d')
        row = self._db.query_one(
            "SELECT COUNT(*) as count FROM tickets WHERE ticket_number LIKE %s",
            (f"{prefix}%",)
        )
        count = row['count'] if row else 0
        return f"{prefix}-{count + 1:04d}"

    def create_ticket(self, data):
        ticket_number = self.generate_ticket_number()
        history = [{'timestamp': datetime.now().isoformat(), 'action': 'Создание заявки', 'user': data.get('source', 'system')}]

        fields = ['ticket_number', 'source', 'address', 'problem_description', 'history', 'priority', 'status']
        values = [ticket_number, data.get('source', 'web'), data.get('address'), data.get('problem_description'),
                  json.dumps(history, ensure_ascii=False), data.get('priority', 'обычный'), 'новая']

        for f in ['client_name', 'client_phone', 'client_email', 'organization', 'elevator_id', 'elevator_type', 'operator_notes']:
            if f in data:
                fields.append(f)
                values.append(data[f])

        placeholders = ', '.join(['%s'] * len(values))
        sql = f"INSERT INTO tickets ({', '.join(fields)}) VALUES ({placeholders}) RETURNING id"

        with self._db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, values)
                result = cursor.fetchone()
            conn.commit()
        return self.get_ticket(result['id']) if result else None

    def get_ticket(self, ticket_id):
        return self._db.query_one("SELECT * FROM tickets WHERE id = %s", (ticket_id,))

    def get_ticket_by_number(self, ticket_number):
        return self._db.query_one("SELECT * FROM tickets WHERE ticket_number = %s", (ticket_number,))

    def search_tickets(self, filters=None, limit=200, offset=0, exclude_status=None):
        query = 'SELECT * FROM tickets WHERE 1=1'
        params = []

        if filters:
            for key in ['status', 'priority', 'elevator_id']:
                if key in filters:
                    query += f' AND {key} = %s'
                    params.append(filters[key])
            if 'address' in filters:
                query += ' AND address ILIKE %s'
                params.append(f"%{filters['address']}%")
            if 'client_phone' in filters:
                query += ' AND client_phone ILIKE %s'
                params.append(f"%{filters['client_phone']}%")
            if 'client_name' in filters:
                query += ' AND client_name ILIKE %s'
                params.append(f"%{filters['client_name']}%")
            if 'date_from' in filters:
                query += ' AND created_at >= %s'
                params.append(filters['date_from'])
            if 'date_to' in filters:
                query += ' AND created_at <= %s'
                params.append(filters['date_to'])

        if exclude_status:
            if isinstance(exclude_status, list):
                placeholders = ', '.join(['%s'] * len(exclude_status))
                query += f' AND status NOT IN ({placeholders})'
                params.extend(exclude_status)
            else:
                query += ' AND status != %s'
                params.append(exclude_status)

        query += ' ORDER BY created_at DESC LIMIT %s OFFSET %s'
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
            except Exception:
                history_data = []

        history_data.append({'timestamp': datetime.now().isoformat(), 'action': 'Обновление заявки', 'user': user, 'changes': list(data.keys())})
        data['history'] = json.dumps(history_data, ensure_ascii=False)
        data['updated_at'] = datetime.now().isoformat()

        fields = ', '.join([f"{k} = %s" for k in data.keys()])
        values = list(data.values()) + [ticket_id]
        self._db.execute(f'UPDATE tickets SET {fields} WHERE id = %s', values)
        return self.get_ticket(ticket_id)

    def update_ticket_status(self, ticket_id, new_status, user='system', notes=None):
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return None

        history_data = ticket.get('history', [])
        if isinstance(history_data, str):
            try:
                history_data = json.loads(history_data)
            except Exception:
                history_data = []

        history_data.append({'timestamp': datetime.now().isoformat(), 'action': f"Изменение статуса: {ticket.get('status', 'новая')} → {new_status}", 'user': user, 'notes': notes})

        sql = "UPDATE tickets SET status = %s, history = %s, updated_at = %s"
        params = [new_status, json.dumps(history_data, ensure_ascii=False), datetime.now().isoformat()]

        if new_status == 'выполнена':
            sql += ", completed_at = %s"
            params.append(datetime.now().isoformat())

        params.append(ticket_id)
        self._db.execute(sql + " WHERE id = %s", params)
        return self.get_ticket(ticket_id)

    def add_comment(self, ticket_id, author, text):
        self._db.execute("INSERT INTO comments (ticket_id, author, text) VALUES (%s, %s, %s)", (ticket_id, author, text))

    def get_comments(self, ticket_id):
        return self._db.query("SELECT * FROM comments WHERE ticket_id = %s ORDER BY created_at ASC", (ticket_id,))

    def reject_ticket(self, ticket_id, mechanic_id):
        self.add_comment(ticket_id, 'system', "механик отказался от заявки")
        self._db.execute(
            "UPDATE ticket_mechanics SET status = 'rejected', responded_at = %s WHERE ticket_id = %s AND mechanic_id = %s",
            (datetime.now().isoformat(), ticket_id, mechanic_id)
        )

    def get_ticket_mechanics(self, ticket_id):
        return self._db.query("SELECT * FROM ticket_mechanics WHERE ticket_id = %s", (ticket_id,))

    def get_statistics(self):
        stats = {}
        for key, cond in [
            ('total', "status != 'отменена'"),
            ('new', "status = 'новая'"),
            ('in_progress', "status = 'в работе'"),
            ('done', "status = 'выполнена'"),
            ('urgent', "priority = 'срочный'"),
            ('urgent_new', "priority = 'срочный' AND status = 'новая'"),
            ('urgent_work', "priority = 'срочный' AND status = 'в работе'"),
            ('urgent_done', "priority = 'срочный' AND status = 'выполнена'"),
        ]:
            row = self._db.query_one(f"SELECT COUNT(*) as count FROM tickets WHERE {cond}")
            stats[key] = row['count'] if row else 0
        return stats

    def get_shift_statistics(self, shift_start, shift_end):
        stats = {}
        for key, cond in [
            ('created', "created_at >= %s AND created_at < %s"),
            ('completed', "status = 'выполнена' AND completed_at >= %s AND completed_at < %s"),
        ]:
            row = self._db.query_one(f"SELECT COUNT(*) as count FROM tickets WHERE {cond}", (shift_start, shift_end))
            stats[key] = row['count'] if row else 0
        return stats

    # ── Elevators ──────────────────────────────────────────────

    def get_elevator(self, elevator_id):
        return self._db.query_one("SELECT * FROM elevators WHERE elevator_id = %s", (elevator_id,))

    def get_all_elevators(self, limit=100):
        return self._db.query("SELECT * FROM elevators ORDER BY address LIMIT %s", (limit,))

    def search_elevators(self, query_text=None, limit=200):
        if query_text:
            return self._db.query(
                "SELECT * FROM elevators WHERE address ILIKE %s OR elevator_id ILIKE %s ORDER BY address LIMIT %s",
                (f"%{query_text}%", f"%{query_text}%", limit)
            )
        return self._db.query("SELECT * FROM elevators ORDER BY address LIMIT %s", (limit,))

    def create_elevator(self, data):
        fields = ', '.join(data.keys())
        placeholders = ', '.join(['%s'] * len(data))
        with self._db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(f"INSERT INTO elevators ({fields}) VALUES ({placeholders}) RETURNING elevator_id", list(data.values()))
                result = cursor.fetchone()
            conn.commit()
        return self.get_elevator(result['elevator_id']) if result else None

    def add_elevator(self, data):
        """Алиас для create_elevator, возвращает elevator_id"""
        elevator = self.create_elevator(data)
        return elevator['elevator_id'] if elevator else None

    def update_elevator(self, elevator_id, data):
        data['updated_at'] = datetime.now().isoformat()
        fields = ', '.join([f"{k} = %s" for k in data.keys()])
        self._db.execute(f"UPDATE elevators SET {fields} WHERE elevator_id = %s", list(data.values()) + [elevator_id])
        return self.get_elevator(elevator_id)

    def delete_elevator(self, elevator_id):
        existing = self.get_elevator(elevator_id)
        if not existing:
            return False
        self._db.execute("DELETE FROM elevators WHERE elevator_id = %s", (elevator_id,))
        return True

    # ── Mechanics ──────────────────────────────────────────────

    def get_all_mechanics(self, limit=100):
        return self._db.query("SELECT * FROM mechanics ORDER BY name LIMIT %s", (limit,))

    def get_mechanic(self, mechanic_id):
        return self._db.query_one("SELECT * FROM mechanics WHERE id = %s", (mechanic_id,))

    def get_mechanic_by_phone(self, phone):
        return self._db.query_one("SELECT * FROM mechanics WHERE phone = %s", (phone,))

    def get_mechanic_by_max(self, max_chat_id):
        return self._db.query_one("SELECT * FROM mechanics WHERE max_chat_id = %s", (str(max_chat_id),))

    def create_mechanic(self, data):
        fields = ', '.join(data.keys())
        placeholders = ', '.join(['%s'] * len(data))
        with self._db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(f"INSERT INTO mechanics ({fields}) VALUES ({placeholders}) RETURNING id", list(data.values()))
                result = cursor.fetchone()
            conn.commit()
        return self.get_mechanic(result['id']) if result else None

    def add_mechanic(self, data):
        """Алиас для create_mechanic, возвращает id"""
        mechanic = self.create_mechanic(data)
        return mechanic['id'] if mechanic else None

    def update_mechanic(self, mechanic_id, data):
        fields = ', '.join([f"{k} = %s" for k in data.keys()])
        self._db.execute(f"UPDATE mechanics SET {fields} WHERE id = %s", list(data.values()) + [mechanic_id])
        return self.get_mechanic(mechanic_id)

    def delete_mechanic(self, mechanic_id):
        existing = self.get_mechanic(mechanic_id)
        if not existing:
            return False
        self._db.execute("DELETE FROM mechanics WHERE id = %s", (mechanic_id,))
        return True

    def get_all_mechanic_tickets(self, mechanic_id):
        return self._db.query("SELECT * FROM tickets WHERE assigned_to = %s ORDER BY created_at DESC", (str(mechanic_id),))

    # ── Elevator ↔ Mechanic ────────────────────────────────────

    def get_mechanics_for_elevator(self, elevator_id):
        return self._db.query(
            "SELECT m.* FROM mechanics m JOIN elevator_mechanics em ON m.id = em.mechanic_id WHERE em.elevator_id = %s",
            (elevator_id,)
        )

    def get_mechanics_for_elevator_by_mechanic(self, mechanic_id):
        return self._db.query(
            "SELECT e.* FROM elevators e JOIN elevator_mechanics em ON e.elevator_id = em.elevator_id WHERE em.mechanic_id = %s",
            (mechanic_id,)
        )

    def get_mechanic_elevators(self, mechanic_id):
        return self.get_mechanics_for_elevator_by_mechanic(mechanic_id)

    def assign_elevator_to_mechanic(self, elevator_id, mechanic_id, is_primary=True):
        self._db.execute(
            "INSERT INTO elevator_mechanics (elevator_id, mechanic_id, is_primary) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (elevator_id, mechanic_id, is_primary)
        )

    def assign_mechanic_to_elevator(self, elevator_id, mechanic_id, is_primary=True):
        self.assign_elevator_to_mechanic(elevator_id, mechanic_id, is_primary)

    def remove_elevator_from_mechanic(self, elevator_id, mechanic_id):
        self._db.execute("DELETE FROM elevator_mechanics WHERE elevator_id = %s AND mechanic_id = %s", (elevator_id, mechanic_id))

    def remove_mechanic_from_elevator(self, elevator_id, mechanic_id):
        self.remove_elevator_from_mechanic(elevator_id, mechanic_id)

    # ── On-call ────────────────────────────────────────────────

    def get_oncall_mechanic(self, date_str):
        return self._db.query_one(
            "SELECT m.* FROM mechanics m JOIN oncall_mechanics om ON m.id = om.mechanic_id WHERE om.date = %s",
            (date_str,)
        )

    def get_oncall_mechanic_for_date(self, date_str):
        return self.get_oncall_mechanic(date_str)

    def set_oncall_mechanic(self, mechanic_id, date_str):
        self._db.execute(
            "INSERT INTO oncall_mechanics (mechanic_id, date) VALUES (%s, %s) ON CONFLICT (date) DO UPDATE SET mechanic_id = %s",
            (mechanic_id, date_str, mechanic_id)
        )

    def get_next_oncall_mechanic(self):
        return self._db.query_one("SELECT * FROM mechanics WHERE status = 'active' ORDER BY id LIMIT 1")

    # ── Ticket mechanics ───────────────────────────────────────

    def send_ticket_to_mechanic(self, ticket_id, mechanic_id):
        self._db.execute(
            "INSERT INTO ticket_mechanics (ticket_id, mechanic_id, status) VALUES (%s, %s, 'sent') ON CONFLICT DO NOTHING",
            (ticket_id, mechanic_id)
        )

    # ── Repair reports ─────────────────────────────────────────

    def create_repair_report(self, data):
        fields = ', '.join(data.keys())
        placeholders = ', '.join(['%s'] * len(data))
        with self._db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(f"INSERT INTO repair_reports ({fields}) VALUES ({placeholders}) RETURNING id", list(data.values()))
                result = cursor.fetchone()
            conn.commit()
        return result['id'] if result else None

    # ── Settings ───────────────────────────────────────────────

    def get_setting(self, key, default=None):
        row = self._db.query_one("SELECT value FROM settings WHERE key = %s", (key,))
        return row['value'] if row else default

    def set_setting(self, key, value):
        self._db.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = CURRENT_TIMESTAMP",
            (key, value, value)
        )

    def get_all_settings(self):
        return self._db.query("SELECT key, value FROM settings")


db = TicketDatabase()
