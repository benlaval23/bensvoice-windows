import json
import logging
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "BensVoice"
CONFIG_PATH = APP_DIR / "config.json"
SAMPLE_RATE = 16_000


def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        logging.warning("Ignoring unreadable %s: %s", CONFIG_PATH, e)
        return {}
