"""
auth.py — Minimal session-based admin authentication.

No third-party auth library needed: on first run, an admin account is
created from ADMIN_USERNAME / ADMIN_PASSWORD env vars (or defaults),
with the password stored as a salted hash in the database. Every admin
route is protected with the @login_required decorator below.
"""

import os
import sqlite3
from functools import wraps
from flask import session, redirect, url_for, request
from werkzeug.security import generate_password_hash, check_password_hash

from utils.db import get_connection, DB_PATH

DEFAULT_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme123")


def init_auth():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    conn.commit()

    cur.execute("SELECT COUNT(*) as c FROM admins")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            (DEFAULT_ADMIN_USERNAME, generate_password_hash(DEFAULT_ADMIN_PASSWORD)),
        )
        conn.commit()
        print(f"[i] Created default admin account -> username: '{DEFAULT_ADMIN_USERNAME}', "
              f"password: '{DEFAULT_ADMIN_PASSWORD}'  (change this in production!)")
    conn.close()


def verify_login(username, password):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM admins WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()
    if row and check_password_hash(row["password_hash"], password):
        return True
    return False


def change_password(username, current_password, new_password):
    """Returns (success: bool, message: str). Verifies the current password
    before allowing the change."""
    if not verify_login(username, current_password):
        return False, "Current password is incorrect."
    if len(new_password) < 6:
        return False, "New password must be at least 6 characters."

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE admins SET password_hash = ? WHERE username = ?",
        (generate_password_hash(new_password), username),
    )
    conn.commit()
    conn.close()
    return True, "Password updated successfully."


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper
