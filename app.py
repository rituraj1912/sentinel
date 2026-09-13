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
