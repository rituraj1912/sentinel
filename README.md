# Sentinel — Face Attendance

A single-person, motion-triggered face recognition attendance system.
Enroll employees once → walk up to the camera → it recognizes them,
shows a "Welcome, Name" card, and logs the entry time to a local database.

Runs entirely on your own machine — no cloud service, no data leaves your computer.

## Features

- **Motion-triggered** — face recognition only runs when something moves in frame, saving CPU.
- **Sci-fi style lock-on UI** — corner-bracket face tracking, glass-panel status banner, live clock.
- **Blink-based liveness check** — a match isn't enough on its own; the system watches for a natural eye blink before granting access, so a printed photo or a phone screen held up to the camera won't check someone in. See the "Liveness detection" section below for exactly what this does and doesn't protect against.
- **SQLite storage** — employee profiles (name, ID, department) + attendance timestamps.
- **Cooldown logic** — the same person won't log 10 entries for standing near the camera; a 2-minute window prevents duplicate logs.
- **Manage employees** — remove an enrolled employee (and their attendance history) any time from the Employees page.
- **Change admin password** — from Settings, no need to edit files or restart anything.

## 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

> **Note:** `face_recognition` depends on `dlib`, which needs a C++ compiler and
> CMake to build. On Windows, installing via `pip install cmake dlib` first
> (or using conda: `conda install -c conda-forge dlib`) is usually smoothest.
> On macOS: `brew install cmake` first. On Ubuntu/Debian:
> `sudo apt install build-essential cmake libopenblas-dev liblapack-dev`.

## 2. Enroll employees

```bash
python enroll.py
```

You'll be asked for an Employee ID, name, and department, then the webcam
opens — press **SPACE** when your face is detected (green brackets) to
capture, or **ESC** to cancel. Repeat once per employee.

## 3. Run the kiosk

```bash
python kiosk.py
```

The camera feed opens with the live overlay. Walk into frame — motion
triggers detection, a match shows a green "ACCESS GRANTED" welcome card,
and an unmatched face shows a red "FACE NOT RECOGNIZED" card. Press **ESC**
to quit.

## 4. View attendance history

```bash
python view_log.py          # last 50 entries
python view_log.py 200      # last 200 entries
```

## Web app: public scanner + admin dashboard, all in one

Running `app.py` gives you a single website with two very different areas:

- **Homepage** (`/`) — this **is** the live scanner. The camera starts
  automatically the moment the page loads — no extra click needed. It
  behaves just like `kiosk.py`'s desktop window: amber lock-on brackets,
  a status banner, and a green "ACCESS GRANTED" welcome card with
  name/department/confidence when it recognizes someone. Every match is
  logged to the same database, with the same 2-minute cooldown so one
  visit doesn't spam the log. A small **Admin** link sits in the top-right
  corner — that's the only way in to enrollment, tucked out of the way.
- **Admin dashboard** (`/dashboard`, `/employees`, `/employees/new`) —
  behind that Admin link: login-gated enrollment (webcam capture in the
  browser), employee directory, and recent check-ins.

`kiosk.py` (the separate desktop OpenCV window) still works standalone
too, and shares the exact same `data/attendance.db` — use whichever fits:
the browser kiosk is easier to put on a shared tablet/laptop at an
entrance without installing anything extra; `kiosk.py` doesn't depend on
a browser or webcam permissions prompt.

### Run it

```bash
python app.py
```

Then open **http://localhost:5000** — the camera opens immediately. Default
admin login (via the small "Admin" link, top-right):

```
username: admin
password: changeme123
```

**Change this before letting anyone else near it** — see the environment
variable instructions below.

> Browsers only allow webcam access (`getUserMedia`) on `localhost` /
> `127.0.0.1` or real HTTPS — if you open the site using your machine's
> network IP (e.g. `http://10.x.x.x:5000`) the camera will fail to load
> with a vague error. Always use `localhost` or `127.0.0.1` locally.

### Change the admin credentials

```bash
# Windows (cmd)
set ADMIN_USERNAME=youradminname
set ADMIN_PASSWORD=your-strong-password
python app.py
```

This sets the credentials used the **first time** the app creates an admin
account. Once you're logged in, you can also change the password any time
from **Settings** — no need to touch environment variables or restart
anything.

Only someone who knows the admin login can reach the "Enroll employee" page.
Anyone else can only use the public scanner (`/kiosk`) — they can check in
if already enrolled, but can't add themselves or anyone else.

> The admin password is stored as a salted hash in `data/attendance.db`
> (via `werkzeug.security`), not in plain text. Still, `app.run(debug=True)`
> in `app.py` is a **development server** — fine for testing/personal use,
> not for exposing this beyond your own machine over the internet.

### Managing employees and data

- **Remove an employee** — go to **Employees**, click the trash icon on
  their row. This deletes their profile, face data, photo, and their
  entire attendance history. There's a confirmation prompt first, and
  it can't be undone.
- **Clear all attendance history** — go to **Settings → Danger zone →
  Clear attendance history**. This wipes check-in records but keeps
  everyone enrolled, so nobody needs to be re-added.
- **Change the admin password** — go to **Settings**, enter your current
  password once, then set a new one.

## Project structure

```
face_attendance/
├── enroll.py           # CLI: register a new employee (capture face + details)
├── kiosk.py            # main recognition + attendance loop (webcam kiosk)
├── view_log.py         # CLI: print attendance history
├── app.py              # web dashboard (Flask) — admin login + enrollment page
├── requirements.txt
├── utils/
│   ├── db.py           # SQLite schema + helper functions
│   ├── auth.py         # admin login (session-based, hashed passwords)
│   └── ui.py           # overlay rendering (cards, banners, lock-on brackets)
├── templates/          # HTML pages (login, dashboard, employees, enroll, settings, kiosk)
├── static/
│   └── style.css       # dashboard design system
└── data/
    ├── attendance.db   # created on first run
    └── photos/         # enrollment photos, one per employee
```

## Liveness detection

Matching a face isn't the same as confirming a real person is standing
there — a printed photo or a phone screen showing someone's photo can
match the encoding just as well as their real face. To catch this, both
`kiosk.py` and the web scanner now require a **blink** before granting
access:

1. Face detected → matched to an enrolled employee → status shows
   **"PLEASE BLINK"** (light blue) instead of granting access immediately.
2. The system tracks eye-openness (a measurement called "eye aspect
   ratio") across frames, watching for a genuine open → closed → open
   sequence.
3. Once a real blink is seen, it switches to **"ACCESS GRANTED"** (green)
   and logs the entry.

A static image never produces that open → closed → open pattern, so it
gets stuck at "please blink" indefinitely. A real person blinks
involuntarily every few seconds without even trying, so legitimate
employees aren't slowed down in practice.

**What this does and doesn't protect against:**
- ✅ Stops a printed photo held up to the camera
- ✅ Stops a static image shown on a phone/tablet screen
- ❌ Does **not** stop a *video* of someone blinking played on a screen —
  that's a more advanced spoofing case this project doesn't attempt to
  solve (real commercial systems use depth cameras or infrared for that,
  which a standard webcam can't do)

This is a genuine, working anti-spoofing layer appropriate for a
personal/portfolio project, not a claim that this is unbeatable. Worth
being upfront about that if you show this to anyone technical.

## Tuning

- `MATCH_THRESHOLD` in `kiosk.py` (default `0.5`) — lower = stricter matching,
  fewer false positives but more missed matches in bad lighting. Raise slightly
  if real employees aren't being recognized; lower it if strangers are matching.
- `RE_LOG_COOLDOWN_SECONDS` (default `120`) — how long before the same person
  can be logged again.
- `MOTION_MIN_AREA` — raise this if the camera is triggering on tiny background
  movement (e.g. flickering lights, moving curtains).

## Before deploying this in a real workplace

This handles biometric data, which is legally sensitive in most places
(GDPR in the EU, India's DPDP Act, Illinois BIPA, etc.). Before rolling
this out beyond a personal prototype:

- Get **explicit written consent** from every enrolled employee.
- Define a **data retention & deletion policy** (e.g., delete face data
  when someone leaves the company).
- Store the database securely — encrypt `data/attendance.db` at rest if
  it will hold real employee data long-term.
- Add a **manual check-in fallback** for days recognition fails (masks,
  new haircuts, camera issues).
- Consider **liveness detection** (blink detection, etc.) if this will be
  used unsupervised, to prevent someone holding up a photo to spoof it.
