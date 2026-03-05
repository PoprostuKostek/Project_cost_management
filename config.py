"""Application configuration — paths and constants."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "database.db")
PREFERENCES_PATH = os.path.join(BASE_DIR, "data", "preferences.json")
