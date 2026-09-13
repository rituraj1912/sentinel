"""
app.py — Full web application for Sentinel Face Attendance System:
  - Public in-browser kiosk scanner with blink liveness, audio greetings, and auto IN/OUT shift detection.
  - Admin dashboard with real-time statistics, punch feed, employee directory, and CSV export.
  - Webhook dispatcher for Slack, Discord, and custom endpoints.
"""

import os
import io
import csv
import time
import base64
import uuid
from datetime import datetime, date, timezone
from utils.timezone import (
    now_utc, parse_stored, to_local_time_only, to_local_display,
    today_utc_range, DISPLAY_TZ, today_local_date_str
)

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    jsonify, flash, Response, make_response
)
import face_recognition
import numpy as np
from PIL import Image

from utils.db import (
    init_db, get_all_employees, get_attendance_log, get_connection,
    add_employee, log_attendance, get_last_seen, get_employee_by_code,
    delete_employee, clear_attendance_log, get_setting, set_setting,
    get_all_settings, get_last_punch_today, get_daily_attendance_summary,
    get_employee_status_list, get_export_rows
)
from utils.auth import init_auth, verify_login, login_required, change_password
from utils.notifications import dispatch_attendance_alert, test_webhook_url
from utils import liveness

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "sentinel-super-secret-key-2026")

PHOTOS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "photos"))
MATCH_THRESHOLD = 0.5           # Lower = stricter match


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


# ------------------------------------------------------------- public kiosk ----

@app.route("/")
def index():
    """Public landing page — this IS the live camera kiosk."""
    stats = get_daily_attendance_summary()
    settings = get_all_settings()
    return render_template("kiosk.html", stats=stats, settings=settings)


@app.route("/kiosk")
def kiosk_scan():
    """Alias for backwards compatibility."""
    return redirect(url_for("index"))


@app.route("/api/recognize", methods=["POST"])
def api_recognize():
    """Processes frame from webcam, checks blink liveness, and logs IN/OUT attendance."""
    if "liveness_token" not in session:
        session["liveness_token"] = str(uuid.uuid4())
    token = session["liveness_token"]

    data = request.get_json(silent=True) or {}
    image_data = data.get("image", "")
    mode = data.get("mode", "auto").lower() # 'auto', 'in', 'out'

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

    import cv2
    # Downscale image by 50% for 3x-4x faster HOG face detection and landmark extraction
    small_frame = cv2.resize(rgb_array, (0, 0), fx=0.5, fy=0.5)
    small_face_locations = face_recognition.face_locations(small_frame)
    if not small_face_locations:
        liveness.reset(token)
        return jsonify({"status": "scanning"})

    # Scale back coordinates to full resolution for accurate 128-d face embedding
    face_locations = [(top * 2, right * 2, bottom * 2, left * 2) for (top, right, bottom, left) in small_face_locations]
    encodings = face_recognition.face_encodings(rgb_array, face_locations)
    if not encodings:
        return jsonify({"status": "scanning"})
        
    face_enc = encodings[0]
    known_encodings = [e["encoding"] for e in employees if e["encoding"] is not None]
    valid_employees = [e for e in employees if e["encoding"] is not None]
    
    if not known_encodings:
        return jsonify({"status": "no_employees"})

    distances = face_recognition.face_distance(known_encodings, face_enc)
    best_idx = int(np.argmin(distances))

    if distances[best_idx] > MATCH_THRESHOLD:
        liveness.reset(token)
        return jsonify({"status": "unknown"})

    emp = valid_employees[best_idx]
    confidence = max(0.0, (1 - distances[best_idx])) * 100

    # Liveness check via adaptive eye blink detection
    liveness_mode = get_setting("liveness_mode", "fast")
    if liveness_mode == "off":
        blinked = True
    else:
        # Landmarks extracted from small frame (~12ms latency, scale-invariant EAR)
        landmarks_list = face_recognition.face_landmarks(small_frame, small_face_locations)
        ear = liveness.compute_ear(landmarks_list[0]) if landmarks_list else None
        blinked = liveness.update_blink(token, emp["id"], ear, mode=liveness_mode)

    if not blinked:
        return jsonify({
            "status": "verifying",
            "name": emp["name"],
            "department": emp["department"],
            "emp_code": emp["emp_code"],
            "confidence": round(confidence, 1),
        })

    # Cooldown check
    cooldown_seconds = int(get_setting("cooldown_seconds", "120"))
    last_seen = get_last_seen(emp["id"])
    now_dt = now_utc()
    can_log = True
    if last_seen is not None:
        secs_since = (now_dt - parse_stored(last_seen)).total_seconds()
        if secs_since < cooldown_seconds:
            can_log = False

    punch_type = "in"
    duration_str = ""
    is_late = False
    now_local = datetime.now(DISPLAY_TZ)
    time_str = now_local.strftime("%I:%M:%S %p")
    logged_now = False

    last_punch = get_last_punch_today(emp["id"])

    # Determine punch type
    if mode == "in":
        punch_type = "in"
    elif mode == "out":
        punch_type = "out"
    else: # auto mode
        if not last_punch or last_punch["entry_type"] == "out":
            punch_type = "in"
        else:
            punch_type = "out"

    cutoff = get_setting("late_cutoff_time", "09:30")
    if punch_type == "in" and (not last_punch):
        if now_local.strftime("%H:%M") > cutoff:
            is_late = True

    if can_log:
        log_attendance(emp["id"], entry_type=punch_type)
        logged_now = True
        
        # Calculate duration if check out
        if punch_type == "out" and last_punch:
            start_dt = parse_stored(last_punch["timestamp"])
            total_secs = max(0, (now_dt - start_dt).total_seconds())
            hours = int(total_secs // 3600)
            mins = int((total_secs % 3600) // 60)
            duration_str = f"{hours}h {mins}m logged"

        # Dispatch async webhook alert
        dispatch_attendance_alert(
            emp["name"], emp["emp_code"], emp["department"],
            punch_type, time_str, is_late=is_late
        )

    liveness.mark_confirmed_and_reset(token)

    return jsonify({
        "status": "matched",
        "name": emp["name"],
        "department": emp["department"] or "General",
        "emp_code": emp["emp_code"],
        "confidence": round(confidence, 1),
        "logged_now": logged_now,
        "cooldown": not can_log,
        "punch_type": punch_type.upper(),
        "time_local": time_str,
        "is_late": is_late,
        "duration": duration_str
    })


# ------------------------------------------------------------ dashboard ----

@app.route("/dashboard")
@login_required
def dashboard():
    stats = get_daily_attendance_summary()
    recent = get_attendance_log(limit=30)
    for r in recent:
        r["time_local"] = to_local_time_only(r["timestamp"])
        r["date_local"] = to_local_display(r["timestamp"], fmt="%b %d")
    
    employees = get_employee_status_list()
    return render_template("dashboard.html", stats=stats, recent=recent,
                           employees=employees, username=session.get("username"))


@app.route("/api/attendance/live")
@login_required
def api_attendance_live():
    """Live polling endpoint for dashboard stream."""
    stats = get_daily_attendance_summary()
    recent = get_attendance_log(limit=15)
    for r in recent:
        r["time_local"] = to_local_time_only(r["timestamp"])
        r["date_local"] = to_local_display(r["timestamp"], fmt="%b %d")
    return jsonify({
        "stats": stats,
        "recent": recent
    })


# ------------------------------------------------------------ employees ----

@app.route("/employees")
@login_required
def employees():
    emp_list = get_employee_status_list()
    for e in emp_list:
        photo_path = os.path.join(PHOTOS_DIR, f"{e['emp_code']}.jpg")
        e["has_photo"] = os.path.exists(photo_path)
    
    # Collect unique departments
    depts = sorted(list(set(e["department"] for e in emp_list if e["department"])))
    return render_template("employees.html", employees=emp_list,
                           departments=depts, username=session.get("username"))


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
                flash("No face detected in the captured photo. Center your face and ensure good lighting.", "error")
                return render_template("enroll.html")

            encodings = face_recognition.face_encodings(rgb_array, face_locations)
            encoding = encodings[0]

            os.makedirs(PHOTOS_DIR, exist_ok=True)
            photo_path = os.path.join(PHOTOS_DIR, f"{emp_code}.jpg")
            image.save(photo_path, "JPEG")

            add_employee(emp_code, name, department, encoding, photo_path)
            flash(f"Successfully enrolled {name} ({emp_code}).", "success")
            return redirect(url_for("employees"))

        except Exception as exc:
            flash(f"Could not process enrollment photo: {exc}", "error")
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

    flash(f"Removed '{emp['name']}' ({emp_code}) and cleared attendance logs.", "success")
    return redirect(url_for("employees"))


# ----------------------------------------------------------------- export ----

@app.route("/api/export/csv")
@login_required
def export_csv():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    department = request.args.get("department")

    rows = get_export_rows(start_date=start_date, end_date=end_date, department=department)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "Date", "Time", "Employee ID", "Name", "Department", "Punch Type", "Timestamp UTC"
    ])
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    csv_data = output.getvalue()
    filename = f"sentinel_attendance_{today_local_date_str()}.csv"
    
    response = Response(csv_data, mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


# --------------------------------------------------------------- settings ----

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

        elif action == "update_settings":
            late_cutoff = request.form.get("late_cutoff_time", "09:30").strip()
            webhook_url = request.form.get("webhook_url", "").strip()
            cooldown = request.form.get("cooldown_seconds", "120").strip()
            liveness_mode = request.form.get("liveness_mode", "fast").strip()
            voice_greeting = "true" if request.form.get("voice_greeting") else "false"
            sound_chime = "true" if request.form.get("sound_chime") else "false"

            set_setting("late_cutoff_time", late_cutoff)
            set_setting("webhook_url", webhook_url)
            set_setting("cooldown_seconds", cooldown)
            set_setting("liveness_mode", liveness_mode)
            set_setting("voice_greeting", voice_greeting)
            set_setting("sound_chime", sound_chime)
            flash("System configuration updated successfully.", "success")

        elif action == "clear_attendance":
            clear_attendance_log()
            flash("All attendance records wiped. Enrolled employees remain safe.", "success")

        return redirect(url_for("settings"))

    all_settings = get_all_settings()
    return render_template("settings.html", settings=all_settings, username=session.get("username"))


@app.route("/api/test-webhook", methods=["POST"])
@login_required
def api_test_webhook():
    data = request.get_json(silent=True) or {}
    url = data.get("webhook_url", "").strip()
    success, msg = test_webhook_url(url)
    return jsonify({"success": success, "message": msg})


# ------------------------------------------------------------- app boot ----

init_db()
init_auth()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    print(f"[*] Sentinel running at http://localhost:{port}")
    app.run(debug=debug_mode, host="0.0.0.0", port=port)
