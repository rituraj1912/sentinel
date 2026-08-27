"""
kiosk.py — Main attendance kiosk.

Flow:
  1. Watch the webcam feed; only run face recognition when motion is detected
     (saves CPU, avoids processing empty frames).
  2. When a face appears, compute its encoding and compare against all
     enrolled employees.
  3. On a confident match, show a "Welcome, <Name>" card and log the
     entry to the attendance table (with a cooldown so one visit doesn't
     spam multiple log rows).
  4. If a face is detected but doesn't match anyone, show "Not recognized".

Usage:
    python kiosk.py
"""

import cv2
import time
import face_recognition
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(__file__))
from utils.db import init_db, get_all_employees, log_attendance, get_last_seen
from utils import ui
from utils import liveness

MATCH_THRESHOLD = 0.5          # lower = stricter match (face_recognition distance)
MOTION_MIN_AREA = 2500         # ignore tiny motion (noise)
RE_LOG_COOLDOWN_SECONDS = 120  # don't re-log the same person within this window
FRAME_RESIZE_SCALE = 0.5       # downscale for faster face detection


def compute_motion_score(prev_gray, gray):
    if prev_gray is None:
        return 0
    diff = cv2.absdiff(prev_gray, gray)
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return sum(cv2.contourArea(c) for c in contours)


def main():
    init_db()
    employees = get_all_employees()
    if not employees:
        print("[!] No employees enrolled yet. Run `python enroll.py` first.")
        return

    known_encodings = [e["encoding"] for e in employees]
    print(f"[i] Loaded {len(employees)} enrolled employee(s).")

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[!] Could not access webcam. Check your camera connection/permissions.")
        return

    prev_gray = None
    last_logged_at = {}   # employee_id -> timestamp, in-memory debounce
    current_status = "scanning"
    current_info = {}
    hold_until = 0         # keep last result on screen briefly even without motion
    LIVENESS_TOKEN = "desktop-kiosk"  # single camera/session, one shared liveness state

    print("[i] Kiosk running. Press ESC to quit.")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        motion_score = compute_motion_score(prev_gray, gray)
        prev_gray = gray

        motion_detected = motion_score > MOTION_MIN_AREA
        display = frame.copy()

        if motion_detected or time.time() < hold_until:
            small = cv2.resize(frame, (0, 0), fx=FRAME_RESIZE_SCALE, fy=FRAME_RESIZE_SCALE)
            rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            locations = face_recognition.face_locations(rgb_small)

            if locations:
                encodings = face_recognition.face_encodings(rgb_small, locations)
                landmarks_list = face_recognition.face_landmarks(rgb_small, locations)
                scale = int(1 / FRAME_RESIZE_SCALE)
                boxes_full = [(t * scale, r * scale, b * scale, l * scale)
                              for (t, r, b, l) in locations]

                for box, face_enc, landmarks in zip(boxes_full, encodings, landmarks_list):
                    distances = face_recognition.face_distance(known_encodings, face_enc)
                    best_idx = int(np.argmin(distances)) if len(distances) else None

                    if best_idx is not None and distances[best_idx] <= MATCH_THRESHOLD:
                        emp = employees[best_idx]
                        confidence = max(0.0, (1 - distances[best_idx])) * 100

                        ear = liveness.compute_ear(landmarks)
                        blinked = liveness.update_blink(LIVENESS_TOKEN, emp["id"], ear)

                        if not blinked:
                            current_status = "verifying"
                            current_info = {
                                "name": emp["name"],
                                "department": emp["department"],
                                "emp_code": emp["emp_code"],
                            }
                            ui.draw_face_box(display, box, color=ui.VERIFYING, label="verifying...")
                        else:
                            now = time.time()
                            last = last_logged_at.get(emp["id"], 0)
                            if now - last > RE_LOG_COOLDOWN_SECONDS:
                                log_attendance(emp["id"])
                                last_logged_at[emp["id"]] = now
                                print(f"[✓] Logged entry: {emp['name']} ({emp['emp_code']}) "
                                      f"at {time.strftime('%H:%M:%S')}")
                            liveness.mark_confirmed_and_reset(LIVENESS_TOKEN)

                            current_status = "matched"
                            current_info = {
                                "name": emp["name"],
                                "department": emp["department"],
                                "emp_code": emp["emp_code"],
                                "confidence": confidence,
                            }
                            ui.draw_face_box(display, box, color=ui.SUCCESS, label=emp["name"])
                    else:
                        liveness.reset(LIVENESS_TOKEN)
                        current_status = "unknown"
                        current_info = {"message": "No matching employee found"}
                        ui.draw_face_box(display, box, color=ui.DANGER, label="UNKNOWN")

                hold_until = time.time() + 2.5  # keep result visible briefly
            else:
                liveness.reset(LIVENESS_TOKEN)
                if time.time() >= hold_until:
                    current_status = "scanning"
                    current_info = {}
        else:
            current_status = "scanning"
            current_info = {}

        display = ui.render_overlay(display, status=current_status, **current_info)
        cv2.imshow("Face Attendance Kiosk", display)

        if cv2.waitKey(1) & 0xFF == 27:  # ESC to quit
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
