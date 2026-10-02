"""
extract.py — the **E** in ETL.  *(This module is provided for you.)*

Extract gets the data *out* of the source systems and into pandas, and does
nothing else. Whatever the files contain, that is what you get — every value is
read as **text** (`dtype=str`), because "38h 30m" and "$18.50" are text, and a
DataFrame that has already guessed types for you has already hidden something.

Two sources, two grains:

- **The employee roster** — one row per *person*. HR owns it. It changes rarely.
- **A weekly timesheet** — one row per *person who worked that week*. The
  point-of-sale system exports it every Friday. Someone who took the week off is
  simply not in it, and an ID that HR hasn't added yet can turn up in it anyway.

You do not modify this file, but you *do* need to read it: you cannot clean data
you have not looked at. Pay attention to the ways `hours` and `hourly_rate` are
written, because your Transform functions have to read all of them.
"""

import os
import random

import pandas as pd

# data/ sits beside code/ at the repository root, whatever folder the app or the
# tests were started from.
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
EMPLOYEES_FILE = os.path.join(DATA_DIR, "employees.csv")


def load_employees() -> pd.DataFrame:
    """The roster: one row per employee.

    Columns: `employee_id`, `first_name`, `last_name`, `department`, `hourly_rate`.

    `hourly_rate` is text exactly as HR typed it — `"$18.50"`, `"17.75"` — so it
    cannot be multiplied by anything until you clean it.
    """
    return pd.read_csv(EMPLOYEES_FILE, dtype=str)


def load_timesheet(source) -> pd.DataFrame:
    """One week of timesheets: one row per employee who worked.

    `source` is a path (`"data/timesheet_test.csv"`) or an uploaded file from
    `st.file_uploader` — `pd.read_csv` accepts either.

    Columns: `payroll_date` (the Friday the week ends), `employee_id`, `hours`.

    `hours` is text exactly as the shift leads typed it. Every one of these
    appears in the sample files, and your parser has to read them all:

        "38h 30m"     hours and minutes
        "42h"         whole hours
        "45m"         minutes only
        "24.5"        a decimal — some leads type it that way
    """
    return pd.read_csv(source, dtype=str)


# --- Generated timesheets: the reason you cannot hardcode ---------------------------

_HOUR_STYLES = ("h_m", "h_m", "h", "decimal", "m")


def _format_hours(rng: random.Random, style: str) -> str:
    """Write a random weekly total the way a shift lead might type it."""
    if style == "m":
        return f"{rng.choice([30, 45, 90])}m"
    whole = rng.randint(6, 46)
    if style == "h":
        return f"{whole}h"
    if style == "decimal":
        return f"{whole + rng.choice([0.0, 0.25, 0.5, 0.75])}"
    minutes = rng.choice([0, 15, 30, 45])
    return f"{whole}h {minutes}m" if minutes else f"{whole}h"


def generate_timesheet(seed: int, payroll_date: str = "2026-10-23") -> pd.DataFrame:
    """A made-up week of timesheets, the same one every time for the same seed.

    Between 8 and 12 rostered employees work; the rest are off that week. About
    half the time an ID that is not on the roster sneaks in too, the way a new
    hire's does before HR catches up. Hours use every format the real files use.

    The tests run your pipeline against several seeds. Seed 42 always produces
    the same rows — but not rows you can read off and type into your function.
    """
    rng = random.Random(seed)
    roster_ids = [f"E{n:03d}" for n in range(1, 13)]
    worked = sorted(rng.sample(roster_ids, rng.randint(8, 12)))
    rows = [
        {"payroll_date": payroll_date, "employee_id": eid,
         "hours": _format_hours(rng, rng.choice(_HOUR_STYLES))}
        for eid in worked
    ]
    if rng.random() < 0.5:
        rows.append({"payroll_date": payroll_date,
                     "employee_id": f"E{rng.randint(90, 99)}",
                     "hours": _format_hours(rng, "h_m")})
    return pd.DataFrame(rows, dtype=str)


if __name__ == "__main__":
    print(load_employees())
    print(load_timesheet(os.path.join(DATA_DIR, "timesheet_test.csv")))
    print(generate_timesheet(42))
