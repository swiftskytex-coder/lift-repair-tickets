"""
Примеры API запросов для мобильного приложения
API examples for mobile app integration
"""

import requests
import json

# Базовый URL API
BASE_URL = "http://localhost:8081"


def create_ticket_from_mobile():
    """
    Пример создания заявки с мобильного приложения
    """
    url = f"{BASE_URL}/api/mobile/tickets"
    
    payload = {
        "client_name": "Петров Петр Петрович",
        "client_phone": "+7 999 555-44-33",
        "client_email": "petrov@example.com",
        "organization": "ТСЖ 'Солнечный'",
        "address": "г. Москва, ул. Солнечная, д. 15, подъезд 3",
        "elevator_id": "Лифт-003",
        "elevator_type": "пассажирский",
        "problem_description": "Лифт остановился между этажами, люди внутри. Срочно нужна помощь!",
        "priority": "срочный",
        "operator_notes": "Клиент очень взволнован, требует немедленного реагирования"
    }
    
    headers = {
        "Content-Type": "application/json",
        # В реальном приложении здесь будет API ключ:
        # "X-API-Key": "your-api-key-here"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 201:
            data = response.json()
            print("✅ Заявка успешно создана!")
            print(f"Номер заявки: #{data['ticket']['ticket_number']}")
            print(f"ID: {data['ticket']['id']}")
            print(f"Статус: {data['ticket']['status']}")
            return data['ticket']
        else:
            print(f"❌ Ошибка: {response.status_code}")
            print(response.json())
            return None
            
    except Exception as e:
        print(f"❌ Ошибка соединения: {e}")
        return None


def track_tickets_by_phone(phone_number):
    """
    Отслеживание заявок клиента по номеру телефона
    Используется в мобильном приложении для проверки статуса
    """
    url = f"{BASE_URL}/api/mobile/tickets/track"
    
    params = {
        "phone": phone_number
    }
    
    try:
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n📱 Найдено заявок: {data['count']}")
            print("="*60)
            
            for ticket in data['tickets']:
                print(f"\n📝 Заявка #{ticket['ticket_number']}")
                print(f"   Статус: {ticket['status']}")
                print(f"   Приоритет: {ticket['priority']}")
                print(f"   Проблема: {ticket['problem_description'][:50]}...")
                print(f"   Создана: {ticket['created_at'][:10]}")
            
            return data['tickets']
        else:
            print(f"❌ Ошибка: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка соединения: {e}")
        return None


def get_ticket_details(ticket_id):
    """
    Получение деталей заявки по ID
    """
    url = f"{BASE_URL}/api/tickets/{ticket_id}"
    
    try:
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            ticket = data['ticket']
            
            print(f"\n📝 Детали заявки #{ticket['ticket_number']}")
            print("="*60)
            print(f"Статус: {ticket['status']}")
            print(f"Приоритет: {ticket['priority']}")
            print(f"Клиент: {ticket['client_name']}")
            print(f"Адрес: {ticket['address']}")
            print(f"Проблема: {ticket['problem_description']}")
            
            return ticket
        else:
            print(f"❌ Заявка не найдена")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None


def get_statistics():
    """
    Получение статистики (для админ-панели мобильного приложения)
    """
    url = f"{BASE_URL}/api/stats"
    
    try:
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            stats = data['statistics']
            
            print("\n📊 Статистика системы")
            print("="*60)
            print(f"Всего заявок: {stats['total']}")
            print(f"Новых: {stats['new']}")
            print(f"В работе: {stats['in_progress']}")
            print(f"Выполнено: {stats['completed']}")
            
            return stats
        else:
            print(f"❌ Ошибка: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка соединения: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# Примеры использования
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("📱 Примеры API для мобильного приложения")
    print("="*60)
    
    # 1. Создание заявки
    print("\n1. Создание заявки с мобильного приложения...")
    new_ticket = create_ticket_from_mobile()
    
    if new_ticket:
        ticket_id = new_ticket['id']
        phone = new_ticket['client_phone']
        
        # 2. Получение деталей
        print("\n2. Получение деталей заявки...")
        get_ticket_details(ticket_id)
        
        # 3. Отслеживание по телефону
        print("\n3. Отслеживание заявок по номеру телефона...")
        track_tickets_by_phone(phone)
    
    # 4. Получение статистики
    print("\n4. Получение статистики...")
    get_statistics()
