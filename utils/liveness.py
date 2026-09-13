"""
liveness.py — Adaptive high-speed blink-based liveness verification.

Uses both an absolute Eye Aspect Ratio (EAR) threshold and an adaptive
baseline drop metric (e.g. ~24% dip from the person's resting eye-openness).
This enables instant detection of natural 150-250ms blinks, even for users
with glasses or narrower resting eye structures.
"""

import threading
import numpy as np

EAR_BLINK_THRESHOLD = 0.23   # slightly more forgiving base threshold
_lock = threading.Lock()
# token -> {"emp_id": int|None, "eyes_closed": bool, "blinked": bool, "baseline_ear": float}
_state = {}


def _eye_aspect_ratio(eye_points):
    """Standard EAR formula (Soukupová & Čech). eye_points is a list of
    6 (x, y) tuples in dlib's standard eye-contour order."""
    eye = np.array(eye_points)
    a = np.linalg.norm(eye[1] - eye[5])
    b = np.linalg.norm(eye[2] - eye[4])
    c = np.linalg.norm(eye[0] - eye[3])
    if c == 0:
        return 0.3  # fallback degenerate case
    return (a + b) / (2.0 * c)


def compute_ear(landmarks):
    """Computes average EAR across left and right eyes."""
    if not landmarks or "left_eye" not in landmarks or "right_eye" not in landmarks:
        return None
    left_ear = _eye_aspect_ratio(landmarks["left_eye"])
    right_ear = _eye_aspect_ratio(landmarks["right_eye"])
    return (left_ear + right_ear) / 2.0


def reset(token):
    with _lock:
        _state[token] = {
            "emp_id": None,
            "eyes_closed": False,
            "blinked": False,
            "baseline_ear": 0.28
        }


def update_blink(token, emp_id, ear, mode="fast"):
    """Feed one frame's EAR reading in.
    Uses adaptive baseline comparison for instant blink recognition.
    """
    if mode == "off":
        return True

    with _lock:
        state = _state.setdefault(token, {
            "emp_id": None,
            "eyes_closed": False,
            "blinked": False,
            "baseline_ear": 0.28
        })

        if state["emp_id"] != emp_id:
            state["emp_id"] = emp_id
            state["eyes_closed"] = False
            state["blinked"] = False
            state["baseline_ear"] = ear if (ear and ear > 0.22) else 0.28

        if ear is not None:
            # Dynamically adapt baseline to highest open eye ratio observed
            if ear > state["baseline_ear"]:
                state["baseline_ear"] = (state["baseline_ear"] * 0.4) + (ear * 0.6)

            baseline = state["baseline_ear"]
            
            # Closure criteria: either below absolute threshold OR relative drop of 24%
            is_closed = (ear < EAR_BLINK_THRESHOLD) or (ear < baseline * 0.76)

            if is_closed:
                state["eyes_closed"] = True
            elif state["eyes_closed"]:
                # Re-opening criteria: eyes reopened back towards baseline
                is_reopened = (ear >= EAR_BLINK_THRESHOLD) or (ear >= baseline * 0.86)
                if is_reopened:
                    state["blinked"] = True
                    state["eyes_closed"] = False

        return state["blinked"]


def mark_confirmed_and_reset(token):
    reset(token)
