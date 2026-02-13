"""
Обновление ID лифтов с LIFT-xxx на xxx (только цифры)
"""

import sys
sys.path.insert(0, '/Users/swiftpanaev/KIRO/test4')

from ticket_db import db

def update_elevator_ids():
    """Обновление существующих ID лифтов"""
    print("🔄 Обновление ID лифтов...")
    
    elevators = db.get_all_elevators(limit=200)
    
    for elevator in elevators:
        old_id = elevator['elevator_id']
        
        # Проверяем, начинается ли ID с "LIFT-"
        if old_id.startswith('LIFT-'):
            # Извлекаем номер (001, 002 и т.д.)
            new_id = old_id.replace('LIFT-', '')
            
            try:
                # Создаем новую запись с числовым ID
                new_data = {
                    'elevator_id': new_id,
                    'address': elevator['address'],
                    'elevator_type': elevator['elevator_type'],
                    'status': elevator['status']
                }
                
                # Добавляем новую запись
                db.add_elevator(new_data)
                
                # Удаляем старую запись
                db.delete_elevator(old_id)
                
                print(f"  ✓ {old_id} → {new_id}")
            except Exception as e:
                print(f"  ✗ {old_id}: {e}")
        else:
            print(f"  ⏭️  {old_id} (уже числовой)")
    
    print("\n✅ Обновление завершено!")

if __name__ == "__main__":
    update_elevator_ids()
