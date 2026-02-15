-- Миграция: добавляем таблицу механиков
-- Запуск: sqlite3 instance/tickets.db < add_mechanics.sql

-- Таблица механиков
CREATE TABLE IF NOT EXISTS mechanics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,              -- ФИО механика
    phone TEXT UNIQUE NOT NULL,      -- Телефон для связи
    telegram_chat_id TEXT,           -- ID чата в Telegram
    telegram_username TEXT,          -- @username в Telegram
    status TEXT DEFAULT 'active',    -- active, inactive, on_leave
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Связь лифтов и механиков (многие-ко-многим)
CREATE TABLE IF NOT EXISTS elevator_mechanics (
    elevator_id TEXT NOT NULL,
    mechanic_id INTEGER NOT NULL,
    is_primary BOOLEAN DEFAULT 1,    -- Основной механик (1) или резервный (0)
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (elevator_id, mechanic_id),
    FOREIGN KEY (elevator_id) REFERENCES elevators(elevator_id) ON DELETE CASCADE,
    FOREIGN KEY (mechanic_id) REFERENCES mechanics(id) ON DELETE CASCADE
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_mechanics_phone ON mechanics(phone);
CREATE INDEX IF NOT EXISTS idx_mechanics_telegram ON mechanics(telegram_chat_id);
CREATE INDEX IF NOT EXISTS idx_elevator_mechanics ON elevator_mechanics(elevator_id);

-- Пример данных
INSERT OR IGNORE INTO mechanics (name, phone, telegram_username) VALUES 
    ('Иванов А.П.', '+79991234567', '@ivanov_mechanic'),
    ('Петров В.С.', '+79992345678', '@petrov_repair'),
    ('Сидоров М.В.', '+79993456789', NULL);

-- Связываем механиков с лифтами
INSERT OR IGNORE INTO elevator_mechanics (elevator_id, mechanic_id, is_primary) 
SELECT e.elevator_id, m.id, 1 
FROM elevators e 
JOIN mechanics m ON (
    (e.elevator_id = '001' AND m.name = 'Иванов А.П.') OR
    (e.elevator_id = '002' AND m.name = 'Иванов А.П.') OR
    (e.elevator_id = '003' AND m.name = 'Петров В.С.')
);
