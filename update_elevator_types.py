"""
Обновление типа лифта с "панорамный" на "подъёмник"
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

from ticket_db import db

def update_elevator_types():
    """Обновление типов лифтов"""
    print("🔄 Обновление типов лифтов...")
    
    elevators = db.get_all_elevators(limit=200)
    updated = 0
    
    for elevator in elevators:
        if elevator['elevator_type'] == 'панорамный':
            try:
                db.update_elevator(elevator['elevator_id'], {'elevator_type': 'подъёмник'})
                print(f"  ✓ {elevator['elevator_id']}: панорамный → подъёмник")
                updated += 1
            except Exception as e:
                print(f"  ✗ {elevator['elevator_id']}: {e}")
    
    print(f"\n✅ Обновлено: {updated} лифтов")

if __name__ == "__main__":
    update_elevator_types()
