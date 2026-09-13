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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            entry_type TEXT NOT NULL DEFAULT 'in',
            FOREIGN KEY (employee_id) REFERENCES employees(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    
    # Default settings
    default_settings = {
        "late_cutoff_time": "09:30",
        "webhook_url": "",
        "voice_greeting": "true",
        "sound_chime": "true",
        "cooldown_seconds": "120",
        "liveness_mode": "fast"
    }
    for k, v in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()


def get_all_settings():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings")
    rows = cur.fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


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
    """Returns list of dicts: {id, emp_code, name, department, encoding, photo_path}"""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, emp_code, name, department, encoding, photo_path FROM employees")
    rows = cur.fetchall()
    conn.close()

    employees = []
    for row in rows:
        try:
            enc = pickle.loads(row["encoding"])
        except Exception:
            enc = None
        employees.append({
            "id": row["id"],
            "emp_code": row["emp_code"],
            "name": row["name"],
            "department": row["department"],
            "encoding": enc,
            "photo_path": row["photo_path"]
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
    """Removes an employee and their attendance history. Returns photo_path."""
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


def log_attendance(employee_id, entry_type="in"):
    """Logs punch with timestamp and normalized entry_type ('in' or 'out')."""
    normalized_type = "out" if str(entry_type).lower() in ["out", "checkout", "exit"] else "in"
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO attendance (employee_id, timestamp, entry_type) VALUES (?, ?, ?)",
        (employee_id, now_utc_iso(), normalized_type),
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


def get_last_punch_today(employee_id):
    """Returns the latest punch record for an employee today (or None)."""
    start_utc, end_utc = today_utc_range()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, timestamp, entry_type 
           FROM attendance 
           WHERE employee_id = ? AND timestamp >= ? AND timestamp <= ?
           ORDER BY timestamp DESC LIMIT 1""",
        (employee_id, start_utc, end_utc),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_today_punches_for_employee(employee_id):
    """Returns all punches today for this employee in chronological order."""
    start_utc, end_utc = today_utc_range()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, timestamp, entry_type 
           FROM attendance 
           WHERE employee_id = ? AND timestamp >= ? AND timestamp <= ?
           ORDER BY timestamp ASC""",
        (employee_id, start_utc, end_utc),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_attendance_log(limit=50):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.timestamp, a.entry_type, e.name, e.department, e.emp_code, e.photo_path
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        ORDER BY a.timestamp DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_attendance_summary():
    """Returns aggregated attendance metrics for today:
       total, checked_in_today, currently_in_office, checked_out_today, late_today
    """
    start_utc, end_utc = today_utc_range()
    cutoff_str = get_setting("late_cutoff_time", "09:30")
    
    conn = get_connection()
    cur = conn.cursor()
    
    # Total employees
    cur.execute("SELECT COUNT(*) as c FROM employees")
    total_employees = cur.fetchone()["c"]
    
    # Punches today
    cur.execute("""
        SELECT a.employee_id, a.timestamp, a.entry_type, e.name, e.emp_code, e.department
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        WHERE a.timestamp >= ? AND a.timestamp <= ?
        ORDER BY a.timestamp ASC
    """, (start_utc, end_utc))
    rows = cur.fetchall()
    conn.close()

    # Group punches by employee
    emp_punches = {}
    for r in rows:
        eid = r["employee_id"]
        if eid not in emp_punches:
            emp_punches[eid] = []
        emp_punches[eid].append(dict(r))

    checked_in_count = len(emp_punches)
    in_office_count = 0
    checked_out_count = 0
    late_count = 0

    for eid, punches in emp_punches.items():
        first_punch = punches[0]
        last_punch = punches[-1]
        
        # Check if first punch was late
        dt_local = parse_stored(first_punch["timestamp"]).astimezone(DISPLAY_TZ)
        punch_time_str = dt_local.strftime("%H:%M")
        if punch_time_str > cutoff_str:
            late_count += 1
            
        if last_punch["entry_type"] == "in":
            in_office_count += 1
        else:
            checked_out_count += 1

    return {
        "total_employees": total_employees,
        "checked_in_today": checked_in_count,
        "currently_in_office": in_office_count,
        "checked_out_today": checked_out_count,
        "late_today": late_count,
        "absent_today": max(0, total_employees - checked_in_count),
        "late_cutoff_time": cutoff_str
    }


def get_employee_status_list():
    """Returns list of all employees with their real-time presence status today."""
    employees = get_all_employees()
    start_utc, end_utc = today_utc_range()
    cutoff_str = get_setting("late_cutoff_time", "09:30")
    
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT employee_id, timestamp, entry_type
        FROM attendance
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp ASC
    """, (start_utc, end_utc))
    rows = cur.fetchall()
    conn.close()

    punches_map = {}
    for r in rows:
        eid = r["employee_id"]
        if eid not in punches_map:
            punches_map[eid] = []
        punches_map[eid].append(dict(r))

    result = []
    for emp in employees:
        eid = emp["id"]
        e_punches = punches_map.get(eid, [])
        if not e_punches:
            status = "Absent"
            first_in = "—"
            last_out = "—"
            duration_str = "0h 0m"
            is_late = False
        else:
            first_in_dt = parse_stored(e_punches[0]["timestamp"]).astimezone(DISPLAY_TZ)
            first_in = first_in_dt.strftime("%I:%M %p")
            is_late = first_in_dt.strftime("%H:%M") > cutoff_str
            
            last_punch = e_punches[-1]
            if last_punch["entry_type"] == "in":
                status = "In Office"
                last_out = "Active"
                # Duration since first in
                total_secs = max(0, (now_utc() - parse_stored(e_punches[0]["timestamp"])).total_seconds())
            else:
                status = "Checked Out"
                last_out_dt = parse_stored(last_punch["timestamp"]).astimezone(DISPLAY_TZ)
                last_out = last_out_dt.strftime("%I:%M %p")
                total_secs = max(0, (parse_stored(last_punch["timestamp"]) - parse_stored(e_punches[0]["timestamp"])).total_seconds())
                
            hours = int(total_secs // 3600)
            mins = int((total_secs % 3600) // 60)
            duration_str = f"{hours}h {mins}m"

        result.append({
            "id": emp["id"],
            "emp_code": emp["emp_code"],
            "name": emp["name"],
            "department": emp["department"] or "General",
            "photo_path": emp["photo_path"],
            "status": status,
            "first_in": first_in,
            "last_out": last_out,
            "duration": duration_str,
            "is_late": is_late
        })

    return result


def get_export_rows(start_date=None, end_date=None, department=None):
    """Returns formatted rows for CSV export with local timestamps and punch details."""
    conn = get_connection()
    cur = conn.cursor()
    
    query = """
        SELECT a.timestamp, a.entry_type, e.emp_code, e.name, e.department
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        WHERE 1=1
    """
    params = []
    
    if start_date:
        query += " AND a.timestamp >= ?"
        params.append(f"{start_date}T00:00:00")
    if end_date:
        query += " AND a.timestamp <= ?"
        params.append(f"{end_date}T23:59:59")
    if department and department.strip() != "all":
        query += " AND e.department = ?"
        params.append(department.strip())
        
    query += " ORDER BY a.timestamp DESC"
    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    conn.close()

    export_data = []
    for r in rows:
        dt_local = parse_stored(r["timestamp"]).astimezone(DISPLAY_TZ)
        export_data.append({
            "Date": dt_local.strftime("%Y-%m-%d"),
            "Time": dt_local.strftime("%I:%M:%S %p"),
            "Employee ID": r["emp_code"],
            "Name": r["name"],
            "Department": r["department"] or "General",
            "Punch Type": "CHECK IN" if r["entry_type"] == "in" else "CHECK OUT",
            "Timestamp UTC": r["timestamp"]
        })
    return export_data
