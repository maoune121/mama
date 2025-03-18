from flask import Flask
from threading import Thread
import logging

app = Flask('')
# Suppress Flask's default logging messages
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host="0.0.0.0", port=5000)  # Changed port from 8080 to 5000

def keep_alive():
    t = Thread(target=run)
    t.start()
