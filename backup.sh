#!/bin/bash

# Скрипт автоматического бэкапа базы данных
# Автоматический запуск через cron: 0 0 * * * /path/to/backup.sh

BACKUP_DIR="/Users/swiftpanaev/KIRO/backups"
DB_FILE="/Users/swiftpanaev/KIRO/test4/instance/tickets.db"
DATE=$(date +%Y%m%d_%H%M%S)

# Создаем папку для бэкапов если её нет
mkdir -p "$BACKUP_DIR"

# Проверяем существование базы данных
if [ ! -f "$DB_FILE" ]; then
    echo "❌ Ошибка: База данных не найдена: $DB_FILE"
    exit 1
fi

# Создаем бэкап
cp "$DB_FILE" "$BACKUP_DIR/tickets_backup_$DATE.db"

if [ $? -eq 0 ]; then
    echo "✅ Бэкап создан: tickets_backup_$DATE.db"
    
    # Удаляем бэкапы старше 30 дней
    find "$BACKUP_DIR" -name "tickets_backup_*.db" -mtime +30 -delete
    echo "🗑️  Удалены старые бэкапы (старше 30 дней)"
else
    echo "❌ Ошибка при создании бэкапа"
    exit 1
fi
