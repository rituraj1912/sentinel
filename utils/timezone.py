"""
timezone.py — All attendance timestamps are stored in UTC (a standard best
practice, avoids ambiguity regardless of what timezone the server runs in —
e.g. Render's servers run in UTC, but a laptop running kiosk.py locally
might be in any timezone). Display functions convert to IST (Asia/Kolkata)
since that's where this system is used.

If you deploy this somewhere else, change DISPLAY_TZ below to your timezone
(any name from the IANA tz database, e.g. "America/New_York", "Europe/London").
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("Asia/Kolkata")


def now_utc_iso():
    """Current time in UTC, as an ISO string with timezone info — use this
    for anything written to the database."""
    return datetime.now(timezone.utc).isoformat()


def now_utc():
    """Current time as a timezone-aware UTC datetime object."""
    return datetime.now(timezone.utc)


def parse_stored(iso_string):
    """Parses a timestamp string from the database back into a timezone-aware
    datetime. Handles both new-style (UTC-aware) and old-style (naive,
    pre-fix) stored strings so existing data doesn't break."""
    dt = datetime.fromisoformat(iso_string)
    if dt.tzinfo is None:
        # Old data stored before this fix — assume it was already UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_local_display(iso_string, fmt="%Y-%m-%d %I:%M:%S %p"):
    """Converts a stored UTC timestamp string into a formatted IST string
    for display in templates, the CLI, etc."""
    dt_utc = parse_stored(iso_string)
    dt_local = dt_utc.astimezone(DISPLAY_TZ)
    return dt_local.strftime(fmt)


def to_local_time_only(iso_string):
    """Just the time portion (e.g. '09:41:03 AM'), IST."""
    return to_local_display(iso_string, fmt="%I:%M:%S %p")


def today_local_date_str():
    """Today's date string in IST — use this instead of raw date.today()
    when filtering 'today's attendance', since 'today' in India may differ
    from 'today' on a UTC server for several hours around midnight."""
    return datetime.now(DISPLAY_TZ).strftime("%Y-%m-%d")


def today_utc_range():
    """Returns (start_utc_iso, end_utc_iso) — the UTC instants corresponding
    to the start and end of 'today' in IST. Use this to correctly filter
    'today's attendance' from UTC-stored timestamps: a naive string-prefix
    match on the date would misclassify anything within ~5.5 hours of
    midnight IST, since that falls on a different UTC calendar date."""
    now_local = datetime.now(DISPLAY_TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start_local.astimezone(timezone.utc).isoformat(), end_local.astimezone(timezone.utc).isoformat()
