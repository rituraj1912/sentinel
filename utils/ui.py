"""
ui.py — Draws a polished, animated-feeling overlay on top of the OpenCV camera
feed: a welcome card with name/department, a status banner, a live clock,
and a face-tracking box with corner brackets (like a sci-fi lock-on reticle).

Uses PIL for anti-aliased text/rounded rectangles (OpenCV's own text/shape
drawing looks jagged and dated), then converts back to an OpenCV frame.
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# ---- Palette ---------------------------------------------------------
BG_DARK = (18, 18, 24)          # near-black panel background
ACCENT = (0, 200, 255)          # cyan accent (BGR-friendly warm cyan)
ACCENT_SOFT = (0, 140, 190)
SUCCESS = (80, 220, 140)        # matched / recognized
WARNING = (60, 180, 255)        # scanning / searching
DANGER = (70, 70, 235)          # unrecognized
VERIFYING = (242, 184, 109)     # BGR light-blue equivalent — liveness check in progress
WHITE = (240, 240, 245)
GRAY = (150, 150, 160)

FONT_PATH_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_PATH_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except IOError:
        return ImageFont.load_default()


FONT_TITLE = _font(FONT_PATH_BOLD, 30)
FONT_NAME = _font(FONT_PATH_BOLD, 26)
FONT_SUB = _font(FONT_PATH_REG, 18)
FONT_SMALL = _font(FONT_PATH_REG, 14)
FONT_CLOCK = _font(FONT_PATH_BOLD, 20)


def _rounded_rect(draw, xy, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_face_box(frame, box, color=ACCENT, label=None, thickness=2, corner_len=18):
    """Sci-fi style lock-on brackets instead of a plain rectangle.
    box = (top, right, bottom, left) as returned by face_recognition."""
    top, right, bottom, left = box
    corners = [
        ((left, top), (left + corner_len, top), (left, top + corner_len)),
        ((right, top), (right - corner_len, top), (right, top + corner_len)),
        ((left, bottom), (left + corner_len, bottom), (left, bottom - corner_len)),
        ((right, bottom), (right - corner_len, bottom), (right, bottom - corner_len)),
    ]
    for corner, h_end, v_end in corners:
        cv2.line(frame, corner, h_end, color, thickness, cv2.LINE_AA)
        cv2.line(frame, corner, v_end, color, thickness, cv2.LINE_AA)

    if label:
        cv2.putText(frame, label, (left, top - 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, color, 2, cv2.LINE_AA)
    return frame


def render_overlay(frame, status="scanning", name=None, department=None,
                    emp_code=None, confidence=None, message=None):
    """
    status: "scanning" | "matched" | "unknown"
    Draws a top status banner + bottom-left welcome card directly on `frame`
    (a BGR OpenCV image) and returns the modified frame.
    """
    h, w = frame.shape[:2]
    pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img, "RGBA")

    status_color = {"scanning": WARNING, "matched": SUCCESS, "unknown": DANGER, "verifying": VERIFYING}[status]
    status_text = {
        "scanning": "SCANNING FOR FACE...",
        "matched": "ACCESS GRANTED",
        "unknown": "FACE NOT RECOGNIZED",
        "verifying": "PLEASE BLINK",
    }[status]

    # ---- Top banner ----
    banner_h = 56
    draw.rectangle([(0, 0), (w, banner_h)], fill=(*BG_DARK, 235))
    draw.rectangle([(0, banner_h - 3), (w, banner_h)], fill=(*status_color, 255))

    draw.text((20, 14), "FACE ATTENDANCE", font=FONT_TITLE, fill=(*WHITE, 255))

    # status pill (right side of banner)
    pill_text = status_text
    tb = draw.textbbox((0, 0), pill_text, font=FONT_SUB)
    pill_w = (tb[2] - tb[0]) + 36
    pill_x2 = w - 20
    pill_x1 = pill_x2 - pill_w
    _rounded_rect(draw, [(pill_x1, 12), (pill_x2, 44)], radius=16,
                  fill=(*status_color, 60), outline=(*status_color, 255), width=2)
    draw.text((pill_x1 + 18, 18), pill_text, font=FONT_SUB, fill=(*status_color, 255))

    # ---- Clock, bottom right ----
    now_str = datetime.now().strftime("%I:%M:%S %p  •  %d %b %Y")
    tb = draw.textbbox((0, 0), now_str, font=FONT_CLOCK)
    clock_w = tb[2] - tb[0]
    draw.rectangle([(0, h - 40), (w, h)], fill=(*BG_DARK, 200))
    draw.text((w - clock_w - 20, h - 32), now_str, font=FONT_CLOCK, fill=(*GRAY, 255))

    # ---- Welcome / info card, bottom-left ----
    if status == "matched" and name:
        card_w, card_h = 360, 130
        cx, cy = 20, h - 40 - card_h - 16
        _rounded_rect(draw, [(cx, cy), (cx + card_w, cy + card_h)], radius=18,
                      fill=(*BG_DARK, 235), outline=(*SUCCESS, 255), width=2)

        draw.text((cx + 20, cy + 16), f"Welcome, {name}", font=FONT_NAME, fill=(*WHITE, 255))
        sub = department or "—"
        if emp_code:
            sub += f"   •   ID: {emp_code}"
        draw.text((cx + 20, cy + 54), sub, font=FONT_SUB, fill=(*GRAY, 255))

        conf_text = f"Match confidence: {confidence:.0f}%" if confidence is not None else ""
        draw.text((cx + 20, cy + 84), conf_text, font=FONT_SMALL, fill=(*SUCCESS, 255))

    elif status == "verifying" and name:
        card_w, card_h = 360, 110
        cx, cy = 20, h - 40 - card_h - 16
        _rounded_rect(draw, [(cx, cy), (cx + card_w, cy + card_h)], radius=18,
                      fill=(*BG_DARK, 235), outline=(*VERIFYING, 255), width=2)

        draw.text((cx + 20, cy + 16), f"{name} — please blink", font=FONT_NAME, fill=(*WHITE, 255))
        sub = department or "—"
        if emp_code:
            sub += f"   •   ID: {emp_code}"
        draw.text((cx + 20, cy + 54), sub, font=FONT_SUB, fill=(*GRAY, 255))
        draw.text((cx + 20, cy + 82), "Confirming you're really here...",
                  font=FONT_SMALL, fill=(*VERIFYING, 255))

    elif status == "unknown":
        card_w, card_h = 320, 70
        cx, cy = 20, h - 40 - card_h - 16
        _rounded_rect(draw, [(cx, cy), (cx + card_w, cy + card_h)], radius=18,
                      fill=(*BG_DARK, 235), outline=(*DANGER, 255), width=2)
        draw.text((cx + 20, cy + 22), message or "No matching employee found",
                  font=FONT_SUB, fill=(*WHITE, 255))

    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
