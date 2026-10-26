import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
MEDIA_DIR = os.path.join(STORAGE_DIR, "media")
MODELS_DIR = os.path.join(STORAGE_DIR, "models")
DB_PATH = os.path.join(STORAGE_DIR, "app.db")

os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")

# GPU upscaler service (../upscaler), reached through an SSH tunnel; empty = disabled
UPSCALER_URL = os.environ.get("UPSCALER_URL", "http://127.0.0.1:12130").rstrip("/")

# Audio/video sync detection (app/avsync.py)
AVSYNC_MAX_SECONDS = float(os.environ.get("AVSYNC_MAX_SECONDS", "180"))  # total seconds analysed
AVSYNC_WINDOW_SECONDS = float(os.environ.get("AVSYNC_WINDOW_SECONDS", "30"))
AVSYNC_MAX_OFFSET = float(os.environ.get("AVSYNC_MAX_OFFSET", "2.0"))
