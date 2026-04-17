#!/usr/bin/env python3
import sqlite3, json, psycopg2

sqlite_conn = sqlite3.connect('/Users/swiftpanaev/KIRO/test4/instance/tickets.db')
sqlite_cur = sqlite_conn.cursor()

pg_conn = psycopg2.connect(host="localhost", port=5432, database="lift_repair", user="liftuser", password="liftpass123")
pg_cur = pg_conn.cursor()

print("=" * 50)
print("МИГРАЦИЯ SQLite -> PostgreSQL")
print("=" * 50)

# Механики
print("\n[1] Механики...")
sqlite_cur.execute("SELECT name, phone, max_chat_id, max_username, status, created_at FROM mechanics")
for r in sqlite_cur.fetchall():
    pg_cur.execute("INSERT INTO mechanics (name, phone, max_chat_id, max_username, status, created_at) VALUES (%s,%s,%s,%s,%s,%s)", r)
print("  OK")

# Лифты
print("\n[2] Лифты...")
sqlite_cur.execute("SELECT elevator_id, address, entrance, elevator_type, mechanic, description, status, serial_number, key_photo, created_at, updated_at FROM elevators")
for r in sqlite_cur.fetchall():
    pg_cur.execute("INSERT INTO elevators VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", r)
print("  OK")
pg_conn.commit()

# Заявки
print("\n[3] Заявки...")
sqlite_cur.execute("SELECT * FROM tickets")
for r in sqlite_cur.fetchall():
    h = r[17] if r[17] else '[]'
    try: h = json.dumps(json.loads(h))
    except: h = '[]'
    values = (r[0],r[1],r[2],r[3],r[4],r[5],r[6],r[7],r[8],r[9],r[10],r[11],r[12],r[13],r[14],r[15],r[16],h,r[18],r[19],r[20],r[21])
    pg_cur.execute("""INSERT INTO tickets VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", values)
print("  OK")
pg_conn.commit()

# Комментарии
print("\n[4] Комментарии...")
sqlite_cur.execute("SELECT ticket_id, author, text, created_at FROM comments")
for r in sqlite_cur.fetchall():
    pg_cur.execute("INSERT INTO comments VALUES (%s,%s,%s,%s)", r)
print("  OK")
pg_conn.commit()

# Связи
print("\n[5] Связи...")
sqlite_cur.execute("SELECT elevator_id, mechanic_id, is_primary, assigned_at FROM elevator_mechanics")
for r in sqlite_cur.fetchall():
    ip = bool(r[2]) if r[2] else True
    pg_cur.execute("INSERT INTO elevator_mechanics VALUES (%s,%s,%s,%s)", (r[0],r[1],ip,r[3]))
print("  OK")
pg_conn.commit()

# Настройки
print("\n[6] Настройки...")
sqlite_cur.execute("SELECT key, value, updated_at FROM settings")
for r in sqlite_cur.fetchall():
    pg_cur.execute("INSERT INTO settings VALUES (%s,%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", r)
print("  OK")
pg_conn.commit()

print("\n" + "=" * 50)
print("ПРОВЕРКА:")
pg_cur.execute("SELECT COUNT(*) FROM tickets")
print(f"  Заявок: {pg_cur.fetchone()[0]}")
pg_cur.execute("SELECT ticket_number, status FROM tickets")
for r in pg_cur.fetchall():
    print(f"  {r[0]} - {r[1]}")

sqlite_conn.close()
pg_conn.close()
print("\n✅ Миграция завершена!")