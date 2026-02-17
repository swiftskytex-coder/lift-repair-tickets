#!/bin/bash
cp -r /Users/swiftpanaev/KIRO/test4/instance/tickets.db /Users/swiftpanaev/KIRO/test4/backup/tickets.db_$(date +%Y%m%d_%H%M%S)
cp -r /Users/swiftpanaev/KIRO/test4/uploads /Users/swiftpanaev/KIRO/test4/backup/uploads_$(date +%Y%m%d_%H%M%S)
echo "✅ Бэкап создан: $(date)"
