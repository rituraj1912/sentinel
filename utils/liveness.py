"""
liveness.py — Simple blink-based liveness check.

A printed photo or a phone screen held up to the camera can match a face
encoding just fine, but it can't blink. This module tracks eye-openness
(the "eye aspect ratio", EAR) across the frames a browser session sends,
and only confirms "liveness" once it sees a genuine open -> closed -> open
sequence — a real blink.

This is a lightweight anti-spoofing measure, not a bulletproof one — a
video replay of a blinking face would still pass. It's meant to stop the
easy case (a photo held up to the camera), which is the most common
attack against basic face-recognition attendance systems.
"""

import threading
import numpy as np

EAR_BLINK_THRESHOLD = 0.22   # below this, eyes are considered "closed"
EAR_HISTORY_LEN = 12         # how many recent frames we remember per session

_lock = threading.Lock()
_state = {}   # token -> {"emp_id": int|None, "eyes_closed": bool, "blinked": bool}


def _eye_aspect_ratio(eye_points):
    """Standard EAR formula (Soukupová & Čech). eye_points is a list of
    6 (x, y) tuples in dlib's standard eye-contour order, as returned by
    face_recognition.face_landmarks()."""
    eye = np.array(eye_points)
    a = np.linalg.norm(eye[1] - eye[5])
    b = np.linalg.norm(eye[2] - eye[4])
    c = np.linalg.norm(eye[0] - eye[3])
    if c == 0:
        return 0.3  # degenerate case, treat as "open" rather than crash
    return (a + b) / (2.0 * c)


def compute_ear(landmarks):
    """landmarks is one entry from face_recognition.face_landmarks() —
    a dict with 'left_eye' and 'right_eye' keys. Returns the average EAR
    of both eyes, or None if landmarks are missing either eye."""
    if "left_eye" not in landmarks or "right_eye" not in landmarks:
        return None
    left_ear = _eye_aspect_ratio(landmarks["left_eye"])
    right_ear = _eye_aspect_ratio(landmarks["right_eye"])
    return (left_ear + right_ear) / 2.0


def get_state(token):
    with _lock:
        if token not in _state:
            _state[token] = {"emp_id": None, "eyes_closed": False, "blinked": False}
        return _state[token]


def reset(token):
    with _lock:
        _state[token] = {"emp_id": None, "eyes_closed": False, "blinked": False}


def update_blink(token, emp_id, ear):
    """Feed one frame's EAR reading in. Resets the blink flag if a
    different person (or no one) was being tracked. Returns True once a
    full open->closed->open blink cycle has been observed for this
    person since the last reset."""
    with _lock:
        state = _state.setdefault(token, {"emp_id": None, "eyes_closed": False, "blinked": False})

        if state["emp_id"] != emp_id:
            state["emp_id"] = emp_id
            state["eyes_closed"] = False
            state["blinked"] = False

        if ear is not None:
            if ear < EAR_BLINK_THRESHOLD:
                state["eyes_closed"] = True
            elif state["eyes_closed"] and ear >= EAR_BLINK_THRESHOLD:
                state["blinked"] = True
                state["eyes_closed"] = False

        return state["blinked"]


def mark_confirmed_and_reset(token):
    """Call after a successful, liveness-confirmed check-in so the next
    person (or the same person checking in again later) needs a fresh
    blink rather than riding on an old one."""
    reset(token)
