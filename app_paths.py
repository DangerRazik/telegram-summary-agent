"""External configuration and persistent user data, outside the bundle."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

FROZEN = getattr(sys, 'frozen', False)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TelegramSummaryAgent' if FROZEN else APP_DIR


def data_path(name):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / name


def load_config():
    load_dotenv(APP_DIR / '.env')
