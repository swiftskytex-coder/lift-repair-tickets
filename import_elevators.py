"""
Импорт объектов (лифтов) из данных пользователя
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

from ticket_db import db

# Пример данных - замените на реальные 150 лифтов
# ID лифта только цифры (001, 002, 003 и т.д.)
# entrance - номер подъезда (можно цифрой: 1, 2, 3 или буквой: А, Б, В)
# mechanic - фамилия механика, обслуживающего лифт
ELEVATORS = [
    {"elevator_id": "001", "address": "ул. Ленина, д. 1", "entrance": "1", "elevator_type": "пассажирский", "mechanic": "Петров"},
    {"elevator_id": "002", "address": "ул. Ленина, д. 1", "entrance": "2", "elevator_type": "пассажирский", "mechanic": "Петров"},
    {"elevator_id": "003", "address": "ул. Ленина, д. 2", "entrance": "1", "elevator_type": "грузовой", "mechanic": "Сидоров"},
    {"elevator_id": "004", "address": "пр. Мира, д. 10", "entrance": "1", "elevator_type": "пассажирский", "mechanic": "Иванов"},
    {"elevator_id": "005", "address": "пр. Мира, д. 10", "entrance": "2", "elevator_type": "пассажирский", "mechanic": "Иванов"},
    {"elevator_id": "006", "address": "ул. Гагарина, д. 5", "entrance": "А", "elevator_type": "подъёмник", "mechanic": "Смирнов"},
    {"elevator_id": "007", "address": "ул. Гагарина, д. 5", "entrance": "Б", "elevator_type": "пассажирский", "mechanic": "Смирнов"},
    {"elevator_id": "008", "address": "ул. Пушкина, д. 15", "entrance": "1", "elevator_type": "больничный", "mechanic": "Козлов"},
    {"elevator_id": "009", "address": "ул. Пушкина, д. 16", "entrance": "1", "elevator_type": "пассажирский", "mechanic": "Козлов"},
    {"elevator_id": "010", "address": "ул. Чехова, д. 20", "entrance": "3", "elevator_type": "грузовой", "mechanic": "Новиков"},
    # ... добавьте остальные 140 лифтов (011, 012, 013 и т.д.)
]

def import_elevators():
    """Импорт лифтов в базу данных"""
    print(f"🛗 Импорт {len(ELEVATORS)} лифтов...")
    
    imported = 0
    for elevator in ELEVATORS:
        try:
            db.add_elevator(elevator)
            imported += 1
            print(f"  ✓ {elevator['elevator_id']} - {elevator['address']}")
        except Exception as e:
            print(f"  ✗ {elevator['elevator_id']}: {e}")
    
    print(f"\n✅ Импортировано: {imported}/{len(ELEVATORS)}")

if __name__ == "__main__":
    import_elevators()
