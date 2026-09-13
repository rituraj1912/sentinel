"""
db.py — SQLite database layer for the Face Attendance system.
Stores:
  - employees(id, emp_code, name, department, encoding, photo_path, created_at)
  - attendance(id, employee_id, timestamp, entry_type)
  - settings(key, value)
"""
import sqlite3
import pickle
import os
from datetime import datetime, timezone, timedelta
from utils.timezone import (
    now_utc_iso, now_utc, parse_stored, today_utc_range,
    to_local_time_only, to_local_display, today_local_date_str, DISPLAY_TZ
)
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "attendance.db"))
def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            department TEXT,
            encoding BLOB NOT NULL,
            photo_path TEXT,
            created_at TEXT NOT NULL
        )
    """)
