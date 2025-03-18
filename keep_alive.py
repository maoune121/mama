from flask import Flask
import threading
import logging

app = Flask(__name__)

# Suppress unnecessary logs
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host="0.0.0.0", port=5000)  # Changed from 8080 to 5000

def keep_alive():
    t = threading.Thread(target=run)
    t.start()
