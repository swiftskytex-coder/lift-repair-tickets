import sys
import time
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class ReloadHandler(FileSystemEventHandler):
    def __init__(self, process_name, restart_callback):
        self.process_name = process_name
        self.restart_callback = restart_callback
        self.last_reload = time.time()

    def on_modified(self, event):
        # Отслеживаем изменения Python-кода и HTML-шаблонов
        if event.src_path.endswith(".py") or event.src_path.endswith(".html"):
            # Дебаунс (защита от частых перезапусков)
            if time.time() - self.last_reload > 1:
                print(f"🔄 Изменения в {event.src_path}. Перезапуск {self.process_name}...")
                self.restart_callback()
                self.last_reload = time.time()

class ProcessManager:
    def __init__(self):
        self.flask_process = None
        self.bot_process = None

    def start_flask(self):
        if self.flask_process:
            self.flask_process.terminate()
            self.flask_process.wait()
        print("🚀 Запуск Flask сервера...")
        self.flask_process = subprocess.Popen([sys.executable, "ticket_system.py"])

    def start_bot(self):
        if self.bot_process:
            self.bot_process.terminate()
            self.bot_process.wait()
        print("🤖 Запуск Telegram бота...")
        self.bot_process = subprocess.Popen([sys.executable, "telegram_bot.py"])

    def stop_all(self):
        if self.flask_process:
            self.flask_process.terminate()
        if self.bot_process:
            self.bot_process.terminate()

if __name__ == "__main__":
    # Проверка наличия watchdog
    try:
        import watchdog
    except ImportError:
        print("❌ Для работы авто-перезапуска нужен watchdog.")
        print("📦 Устанавливаю watchdog...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "watchdog"])
        import watchdog

    manager = ProcessManager()
    manager.start_flask()
    manager.start_bot()

    observer = Observer()
    
    # Следим за ticket_system.py и ticket_db.py для перезапуска Flask
    flask_handler = ReloadHandler("Flask", manager.start_flask)
    observer.schedule(flask_handler, path=".", recursive=False)

    # Следим за telegram_bot.py и notification_service.py для перезапуска Бота
    # (на самом деле следим за всеми .py в корне, так проще)
    bot_handler = ReloadHandler("Bot", manager.start_bot)
    
    # Чтобы не перезапускать всё подряд, можно разделить, но пока
    # перезапустим обоих при любом изменении .py, это надежнее для синхронизации
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Остановка всех процессов...")
        manager.stop_all()
        observer.stop()
    observer.join()
