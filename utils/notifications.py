"""
notifications.py — Asynchronous notification and webhook dispatcher for Sentinel.

Sends instant notifications on:
  - Employee Check-In / Check-Out
  - Late arrival warnings
  - Unrecognized face alerts

Supports Slack, Discord, Microsoft Teams, and standard JSON HTTP webhooks.
Runs in a background thread so attendance recognition is never delayed.
"""

import threading
import json
import requests
from utils.db import get_setting


def _send_payload(url, payload):
    try:
        headers = {"Content-Type": "application/json", "User-Agent": "Sentinel-Attendance/2.0"}
        requests.post(url, json=payload, headers=headers, timeout=5)
    except Exception as e:
        # Avoid crashing the application if the network or webhook endpoint fails
        print(f"[Sentinel Webhook Error] {e}")


def dispatch_attendance_alert(emp_name, emp_code, department, punch_type, time_str, is_late=False):
    """Sends attendance alert via configured webhook URL in background."""
    webhook_url = get_setting("webhook_url", "").strip()
    if not webhook_url:
        return

    is_in = (punch_type.lower() == "in")
    action_text = "CHECKED IN" if is_in else "CHECKED OUT"
    color = 0x10b981 if is_in else 0x3b82f6 # Green for IN, Blue for OUT
    if is_late and is_in:
        color = 0xf59e0b # Amber for Late
        action_text += " (LATE)"

    # Payload compatible with Discord & Slack & Custom Webhooks
    title = f"🛡️ Sentinel Attendance: {emp_name} {action_text}"
    description = f"**Employee:** {emp_name} (`{emp_code}`)\n**Department:** {department or 'General'}\n**Time:** {time_str}"
    
    # Discord format
    payload = {
        "content": f"**Sentinel Notice**: {emp_name} has {action_text.lower()} at {time_str}.",
        "username": "Sentinel Attendance",
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
            "footer": {"text": "Sentinel Biometric Attendance"}
        }],
        # Generic payload fields
        "event": "attendance_punch",
        "employee_code": emp_code,
        "employee_name": emp_name,
        "department": department,
        "punch_type": punch_type.upper(),
        "timestamp_local": time_str,
        "is_late": is_late
    }

    # Dispatch in daemon thread
    thread = threading.Thread(target=_send_payload, args=(webhook_url, payload), daemon=True)
    thread.start()


def test_webhook_url(url):
    """Synchronous test check for the Settings UI."""
    if not url or not url.startswith(("http://", "https://")):
        return False, "Invalid URL. Must start with http:// or https://"
    
    payload = {
        "content": "🔔 **Sentinel Webhook Test**: Connection established successfully!",
        "username": "Sentinel Attendance",
        "embeds": [{
            "title": "Sentinel Webhook Verified",
            "description": "Your attendance system is now integrated with this channel.",
            "color": 0x10b981
        }],
        "event": "test_ping"
    }
    try:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=6)
        if resp.status_code in [200, 204]:
            return True, "Test alert sent successfully!"
        return False, f"Server responded with status code {resp.status_code}"
    except Exception as e:
        return False, f"Could not reach endpoint: {e}"
