"""
enroll.py — Register a new employee: capture their face via webcam,
compute a face encoding, and store it (with name/ID/department) in the DB.

Usage:
    python enroll.py
"""

import cv2
import face_recognition
import sys
import os

sys.path.append(os.path.dirname(__file__))
from utils.db import init_db, add_employee, get_all_employees
from utils import ui

PHOTOS_DIR = os.path.join(os.path.dirname(__file__), "data", "photos")


def main():
    init_db()
    os.makedirs(PHOTOS_DIR, exist_ok=True)

    print("=" * 50)
    print(" FACE ATTENDANCE — EMPLOYEE ENROLLMENT")
    print("=" * 50)
    emp_code = input("Employee ID (e.g. EMP001): ").strip()
    name = input("Full name: ").strip()
    department = input("Department: ").strip()

    existing = {e["emp_code"] for e in get_all_employees()}
    if emp_code in existing:
        print(f"\n[!] Employee ID '{emp_code}' already exists. Aborting.")
        return

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[!] Could not access webcam. Check your camera connection/permissions.")
        return

    print("\nLook at the camera. Press SPACE to capture, ESC to cancel.")
    captured_encoding = None
    saved_photo_path = None

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        display = frame.copy()
        rgb_small = cv2.cvtColor(cv2.resize(frame, (0, 0), fx=0.5, fy=0.5), cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb_small)

        status = "matched" if locations else "scanning"
        boxes_full = [(t * 2, r * 2, b * 2, l * 2) for (t, r, b, l) in locations]
        for box in boxes_full:
            ui.draw_face_box(display, box, color=ui.SUCCESS if locations else ui.WARNING,
                              label="FACE DETECTED" if locations else None)

        display = ui.render_overlay(
            display,
            status="matched" if locations else "scanning",
            name=name if locations else None,
            department=department if locations else None,
            emp_code=emp_code if locations else None,
            confidence=100.0 if locations else None,
        )

        hint = "Press SPACE to capture  |  ESC to cancel"
        cv2.putText(display, hint, (20, display.shape[0] - 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 245), 1, cv2.LINE_AA)

        cv2.imshow("Enroll Employee - Face Attendance", display)
        key = cv2.waitKey(1) & 0xFF

        if key == 27:  # ESC
            print("Cancelled.")
            cap.release()
            cv2.destroyAllWindows()
            return

        if key == 32 and locations:  # SPACE, only if a face is present
            rgb_full = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            encodings = face_recognition.face_encodings(rgb_full)
            if encodings:
                captured_encoding = encodings[0]
                saved_photo_path = os.path.join(PHOTOS_DIR, f"{emp_code}.jpg")
                cv2.imwrite(saved_photo_path, frame)
                print("[+] Face captured successfully.")
                break
            else:
                print("[!] Could not extract encoding, try again with better lighting.")

    cap.release()
    cv2.destroyAllWindows()

    if captured_encoding is not None:
        add_employee(emp_code, name, department, captured_encoding, saved_photo_path)
        print(f"\n✅ Enrolled '{name}' ({emp_code}, {department}) successfully.")
    else:
        print("\n[!] No face captured. Enrollment aborted.")


if __name__ == "__main__":
    main()
