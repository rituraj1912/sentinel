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
