"""
serve.py — Run LeaseSynth AI with a production WSGI server (Waitress).

Use this instead of `python app.py` when you want a stable, long-running
server: no debug mode, no auto-reloader, and a real multi-threaded server.

    venv\\Scripts\\python.exe serve.py

Waitress runs a single process with several threads, which is what this app
needs: the current dataset lives in the in-memory STATE dict in app.py, so it
must not be split across multiple worker processes.
"""

import logging
import os

from waitress import serve

from config import Config
from app import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    if Config.SECRET_KEY in ("dev-secret-key-change-me", "change-me-to-something-random"):
        logging.warning("SECRET_KEY is still a placeholder - set a random value in .env")

    threads = int(os.getenv("WAITRESS_THREADS", "8"))
    print(f"LeaseSynth AI (production) running on http://{Config.HOST}:{Config.PORT}")
    print(f"AI features: {'enabled (' + Config.GROQ_MODEL + ')' if Config.AI_ENABLED else 'disabled'}")
    print("Press Ctrl+C to stop.")
    serve(app, host=Config.HOST, port=Config.PORT, threads=threads)
