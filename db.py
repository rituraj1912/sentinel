"""
db.py — SQLite database layer for the Face Attendance system.

Stores:
  - employees(id, name, department, encoding, photo_path, created_at)
  - attendance(id, employee_id, timestamp, type)
"""

import sqlite3
import pickle
import os
from utils.timezone import now_utc_iso

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "attendance.db")


def get_connection():
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            entry_type TEXT NOT NULL DEFAULT 'entry',
            FOREIGN KEY (employee_id) REFERENCES employees(id)
        )
    """)
    conn.commit()
    conn.close()


def add_employee(emp_code, name, department, encoding, photo_path=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO employees (emp_code, name, department, encoding, photo_path, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (emp_code, name, department, pickle.dumps(encoding), photo_path,
         now_utc_iso()),
    )
    conn.commit()
    conn.close()


def get_all_employees():
    """Returns list of dicts: {id, emp_code, name, department, encoding}"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, emp_code, name, department, encoding FROM employees")
    rows = cur.fetchall()
    conn.close()

    employees = []
    for row in rows:
        employees.append({
            "id": row["id"],
            "emp_code": row["emp_code"],
            "name": row["name"],
            "department": row["department"],
            "encoding": pickle.loads(row["encoding"]),
        })
    return employees


def get_employee_by_code(emp_code):
    """Returns a single employee dict (with photo_path) or None."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, emp_code, name, department, photo_path FROM employees WHERE emp_code = ?", (emp_code,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def delete_employee(employee_id):
    """Removes an employee and their attendance history. Returns the
    photo_path that was on record (so the caller can delete the file too)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT photo_path FROM employees WHERE id = ?", (employee_id,))
    row = cur.fetchone()
    photo_path = row["photo_path"] if row else None

    cur.execute("DELETE FROM attendance WHERE employee_id = ?", (employee_id,))
    cur.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
    conn.commit()
    conn.close()
    return photo_path


def clear_attendance_log():
    """Wipes all attendance history but keeps enrolled employees."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM attendance")
    conn.commit()
    conn.close()


def log_attendance(employee_id, entry_type="entry"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO attendance (employee_id, timestamp, entry_type) VALUES (?, ?, ?)",
        (employee_id, now_utc_iso(), entry_type),
    )
    conn.commit()
    conn.close()


def get_last_seen(employee_id):
    """Returns the timestamp (str) of the last attendance log for this employee, or None."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT timestamp FROM attendance WHERE employee_id = ? ORDER BY timestamp DESC LIMIT 1",
        (employee_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row["timestamp"] if row else None


def get_attendance_log(limit=50):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.timestamp, a.entry_type, e.name, e.department, e.emp_code
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        ORDER BY a.timestamp DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]
