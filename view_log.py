"""
view_log.py — Print recent attendance entries to the terminal.

Usage:
    python view_log.py
    python view_log.py 100    # show last 100 entries
"""

import sys
import os

sys.path.append(os.path.dirname(__file__))
from utils.db import init_db, get_attendance_log
from utils.timezone import to_local_display


def main():
    init_db()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    rows = get_attendance_log(limit=limit)

    if not rows:
        print("No attendance records yet.")
        return

    print(f"{'Time (IST)':<24} {'Name':<20} {'Dept':<15} {'ID':<10} {'Type'}")
    print("-" * 84)
    for r in rows:
        ts = to_local_display(r["timestamp"])
        print(f"{ts:<24} {r['name']:<20} {(r['department'] or '-'):<15} "
              f"{r['emp_code']:<10} {r['entry_type']}")


if __name__ == "__main__":
    main()

