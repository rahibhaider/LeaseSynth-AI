"""
config.py — Central configuration for LeaseSynth AI.

Everything that varies between machines or environments (API keys, ports,
file paths) lives here and nowhere else. The rest of the app imports
`Config` and reads attributes off it; nothing else calls os.getenv directly.
"""

import os
from dotenv import load_dotenv

# Load variables from a .env file in the project root, if one exists.
# On a teammate's machine without a .env, this is a no-op and we fall
# back to the defaults below.
load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    """Read an environment variable as a boolean (accepts 1/true/yes/on)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # ---------------------------------------------------------------
    # Flask
    # ---------------------------------------------------------------
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    DEBUG = _get_bool("FLASK_DEBUG", True)
    HOST = os.getenv("FLASK_HOST", "127.0.0.1")
    PORT = int(os.getenv("FLASK_PORT", "5000"))

    # ---------------------------------------------------------------
    # Groq / Generative AI
    # ---------------------------------------------------------------
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

    # Verify this is still a currently-supported model id in the Groq
    # console (https://console.groq.com/docs/models) before relying on
    # it — Groq periodically retires model ids. Override via .env
    # without touching any code.
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()

    GROQ_TIMEOUT_SECONDS = float(os.getenv("GROQ_TIMEOUT_SECONDS", "20"))
    GROQ_MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "2"))

    # Computed once at import time: True only if a key was actually provided.
    AI_ENABLED = bool(GROQ_API_KEY)

    # ---------------------------------------------------------------
    # Storage paths
    # ---------------------------------------------------------------
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATASET_DIR = os.path.join(BASE_DIR, "generated_datasets")
    DATA_DIR = os.path.join(BASE_DIR, "data")
    DB_PATH = os.path.join(DATA_DIR, "leasesynth.db")

    # ---------------------------------------------------------------
    # Generation limits
    # ---------------------------------------------------------------
    MIN_RECORDS = int(os.getenv("MIN_RECORDS", "1"))
    MAX_RECORDS = int(os.getenv("MAX_RECORDS", "20000"))


# Make sure the folders we write to actually exist on first run.
os.makedirs(Config.DATASET_DIR, exist_ok=True)
os.makedirs(Config.DATA_DIR, exist_ok=True)
