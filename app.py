import os
import threading
import asyncio
from flask import Flask
import subprocess

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return "Bot is running", 200

def run_bot():
    # Запускаем ваш оригинальный bot.py как отдельный процесс
    subprocess.run(["python", "bot.py"])

if __name__ == "__main__":
    # Запускаем бота в фоновом потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Запускаем Flask, который слушает порт (нужен для Render)
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
