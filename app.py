"""
app.py — Full web app for Sentinel, a face recognition attendance system:
a public landing page that doubles as an in-browser recognition kiosk (no
login needed — this is the "door" anyone walks up to), and a login-gated
admin dashboard for enrollment and attendance history.

Usage:
    python app.py
Then open http://localhost:5000 in a browser.

Default admin login: admin / changeme123  (set ADMIN_USERNAME / ADMIN_PASSWORD
env vars to override — see README).

kiosk.py (the desktop OpenCV version) still works standalone and shares the
same database, if you'd rather run recognition outside the browser.
"""

import os
import io
import time
import base64
import uuid
from datetime import datetime, date, timezone
from utils.timezone import now_utc, parse_stored, to_local_time_only, today_utc_range

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import face_recognition
import numpy as np
from PIL import Image

from utils.db import (
    init_db, get_all_employees, get_attendance_log, get_connection,
    add_employee, log_attendance, get_last_seen, get_employee_by_code,
    delete_employee, clear_attendance_log,
)
from utils.auth import init_auth, verify_login, login_required, change_password
from utils import liveness

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-this-in-production")

PHOTOS_DIR = os.path.join(os.path.dirname(__file__), "data", "photos")
MATCH_THRESHOLD = 0.5           # same as kiosk.py — lower = stricter match
RE_LOG_COOLDOWN_SECONDS = 120   # don't re-log the same person within this window


def get_stats():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM employees")
    total_employees = cur.fetchone()["c"]

    start_utc, end_utc = today_utc_range()
    cur.execute(
        "SELECT COUNT(DISTINCT employee_id) as c FROM attendance WHERE timestamp >= ? AND timestamp <= ?",
        (start_utc, end_utc),
    )
    checked_in_today = cur.fetchone()["c"]
    conn.close()
    return {"total_employees": total_employees, "checked_in_today": checked_in_today}


# ---------------------------------------------------------------- auth ----

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify_login(username, password):
            session["logged_in"] = True
            session["username"] = username
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ------------------------------------------------------------- public ----

@app.route("/")
def index():
    """Public landing page — this IS the live scanner. No login needed.
    Camera starts immediately; admin access is a small link in the corner."""
    employee_count = get_stats()["total_employees"]
    return render_template("kiosk.html", employee_count=employee_count)


@app.route("/kiosk")
def kiosk_scan():
    """Kept as an alias so old links/bookmarks still work."""
    return redirect(url_for("index"))


@app.route("/api/recognize", methods=["POST"])
def api_recognize():
    """Called repeatedly by the kiosk page with a webcam frame. Returns
    match status and, on a confident match AND a confirmed blink (real
    person, not a held-up photo), logs attendance server-side."""
    if "liveness_token" not in session:
        session["liveness_token"] = str(uuid.uuid4())
    token = session["liveness_token"]

    data = request.get_json(silent=True) or {}
    image_data = data.get("image", "")
    if not image_data:
        return jsonify({"status": "error", "message": "No image received"}), 400

    employees = get_all_employees()
    if not employees:
        return jsonify({"status": "no_employees"})

    try:
        header, encoded = image_data.split(",", 1)
        img_bytes = base64.b64decode(encoded)
        image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        rgb_array = np.array(image)
    except Exception:
        return jsonify({"status": "error", "message": "Could not decode image"}), 400

    face_locations = face_recognition.face_locations(rgb_array)
    if not face_locations:
        liveness.reset(token)
        return jsonify({"status": "scanning"})

    encodings = face_recognition.face_encodings(rgb_array, face_locations)
    face_enc = encodings[0]

    known_encodings = [e["encoding"] for e in employees]
    distances = face_recognition.face_distance(known_encodings, face_enc)
    best_idx = int(np.argmin(distances))

    if distances[best_idx] > MATCH_THRESHOLD:
        liveness.reset(token)
        return jsonify({"status": "unknown"})

    emp = employees[best_idx]
    confidence = max(0.0, (1 - distances[best_idx])) * 100

    # Liveness: track eye-openness for this person across frames, and
    # only proceed once a real blink has been observed.
    landmarks_list = face_recognition.face_landmarks(rgb_array, face_locations)
    ear = liveness.compute_ear(landmarks_list[0]) if landmarks_list else None
    blinked = liveness.update_blink(token, emp["id"], ear)

    if not blinked:
        return jsonify({
            "status": "verifying",
            "name": emp["name"],
            "department": emp["department"],
            "emp_code": emp["emp_code"],
            "confidence": round(confidence, 1),
        })

    logged_now = False
    last_seen = get_last_seen(emp["id"])
    if last_seen is None or (now_utc() - parse_stored(last_seen)).total_seconds() > RE_LOG_COOLDOWN_SECONDS:
        log_attendance(emp["id"])
        logged_now = True

    liveness.mark_confirmed_and_reset(token)

    return jsonify({
        "status": "matched",
        "name": emp["name"],
        "department": emp["department"],
        "emp_code": emp["emp_code"],
        "confidence": round(confidence, 1),
        "logged_now": logged_now,
    })


# ------------------------------------------------------------ dashboard ----

@app.route("/dashboard")
@login_required
def dashboard():
    stats = get_stats()
    recent = get_attendance_log(limit=15)
    for r in recent:
        r["time_local"] = to_local_time_only(r["timestamp"])
    return render_template("dashboard.html", stats=stats, recent=recent,
                            username=session.get("username"))


@app.route("/employees")
@login_required
def employees():
    emp_list = get_all_employees()
    # Attach photo existence so the template can show a thumbnail
    for e in emp_list:
        photo_path = os.path.join(PHOTOS_DIR, f"{e['emp_code']}.jpg")
        e["has_photo"] = os.path.exists(photo_path)
    return render_template("employees.html", employees=emp_list,
                            username=session.get("username"))


@app.route("/employees/photo/<emp_code>")
@login_required
def employee_photo(emp_code):
    from flask import send_file
    photo_path = os.path.join(PHOTOS_DIR, f"{emp_code}.jpg")
    if os.path.exists(photo_path):
        return send_file(photo_path, mimetype="image/jpeg")
    return "", 404


@app.route("/employees/new", methods=["GET", "POST"])
@login_required
def enroll_employee():
    if request.method == "POST":
        emp_code = request.form.get("emp_code", "").strip()
        name = request.form.get("name", "").strip()
        department = request.form.get("department", "").strip()
        image_data = request.form.get("image_data", "")

        if not (emp_code and name and image_data):
            flash("Employee ID, name, and a captured photo are required.", "error")
            return render_template("enroll.html")

        existing = {e["emp_code"] for e in get_all_employees()}
        if emp_code in existing:
            flash(f"Employee ID '{emp_code}' already exists.", "error")
            return render_template("enroll.html")

        try:
            header, encoded = image_data.split(",", 1)
            img_bytes = base64.b64decode(encoded)
            image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            rgb_array = np.array(image)

            face_locations = face_recognition.face_locations(rgb_array)
            if not face_locations:
                flash("No face detected in the captured photo. Try again with "
                      "better lighting, facing the camera directly.", "error")
                return render_template("enroll.html")

            encodings = face_recognition.face_encodings(rgb_array, face_locations)
            encoding = encodings[0]

            os.makedirs(PHOTOS_DIR, exist_ok=True)
            photo_path = os.path.join(PHOTOS_DIR, f"{emp_code}.jpg")
            image.save(photo_path, "JPEG")

            add_employee(emp_code, name, department, encoding, photo_path)
            flash(f"Enrolled '{name}' ({emp_code}) successfully.", "success")
            return redirect(url_for("employees"))

        except Exception as exc:
            flash(f"Could not process the photo: {exc}", "error")
            return render_template("enroll.html")

    return render_template("enroll.html")


@app.route("/employees/delete/<emp_code>", methods=["POST"])
@login_required
def delete_employee_route(emp_code):
    emp = get_employee_by_code(emp_code)
    if not emp:
        flash(f"No employee found with ID '{emp_code}'.", "error")
        return redirect(url_for("employees"))

    photo_path = delete_employee(emp["id"])
    if photo_path and os.path.exists(photo_path):
        try:
            os.remove(photo_path)
        except OSError:
            pass

    flash(f"Removed '{emp['name']}' ({emp_code}) and their attendance history.", "success")
    return redirect(url_for("employees"))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if new_password != confirm_password:
                flash("New password and confirmation don't match.", "error")
            else:
                success, message = change_password(session.get("username"), current_password, new_password)
                flash(message, "success" if success else "error")

        elif action == "clear_attendance":
            clear_attendance_log()
            flash("Attendance history cleared. Enrolled employees were not affected.", "success")

        return redirect(url_for("settings"))

    return render_template("settings.html", username=session.get("username"))


# --------------------------------------------------------------- api ----

@app.route("/api/attendance/today")
@login_required
def api_attendance_today():
    start_utc, end_utc = today_utc_range()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.timestamp, e.name, e.department, e.emp_code
        FROM attendance a JOIN employees e ON a.employee_id = e.id
        WHERE a.timestamp >= ? AND a.timestamp <= ?
        ORDER BY a.timestamp DESC
    """, (start_utc, end_utc))
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["time_local"] = to_local_time_only(r["timestamp"])
    conn.close()
    return jsonify(rows)


if __name__ == "__main__":
    init_db()
    init_auth()
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, host="0.0.0.0", port=port)
else:
    # Also run init when imported by a WSGI server (gunicorn) in production
    init_db()
    init_auth()
