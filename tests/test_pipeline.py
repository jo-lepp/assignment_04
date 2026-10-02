"""Pipeline and app tests — the DataFrame functions, the whole pipeline, and the page.

The unit tests prove each element function is right on its own. These prove the
*pipeline* is right: that each step adds its columns without touching what it
was given (the lineage rule), that the merge keeps every timesheet row, that the
whole thing chains, and that the Streamlit page shows a manager the right totals.

Two kinds of data, on purpose:

- **Hand-built frames** for the scoped tests. `test_add_gross_pay` hands the
  function a tiny frame that already has `hours_worked` and `hourly_rate_usd`,
  so it passes when *that* function works — even if Step 1 is still a stub.
- **Generated timesheets** (`generate_timesheet(seed)`) for the wired tests. The
  same seed always gives the same rows, so the totals below are stable — but
  they are not rows you can read off and hardcode.

Run one part at a time:

    pytest tests/test_pipeline.py -k clean
    pytest tests/test_pipeline.py -k merge
    pytest tests/test_pipeline.py -k app
"""

import pandas as pd
import pytest

from helpers import (
    assert_lineage, assert_unmodified, data_file, load_app, metrics, no_exception,
    page_text, snapshot, upload_csv, widget,
)
from payroll.clean import add_hourly_rate, add_hours_worked
from payroll.compute import add_gross_pay, add_pay_type, build_payroll, payroll_export
from payroll.extract import generate_timesheet, load_employees, load_timesheet
from payroll.join import merge_employees

APP = "code/payroll_app.py"

# --- Hand-built inputs ---------------------------------------------------------------

RAW_TIMESHEET = pd.DataFrame({
    "payroll_date": ["2026-11-06", "2026-11-06", "2026-11-06"],
    "employee_id": ["X2", "X1", "X9"],
    "hours": ["10h 30m", "41h", "3.5"],
})

RAW_ROSTER = pd.DataFrame({
    "employee_id": ["X1", "X2", "X3"],
    "first_name": ["Ann", "Bo", "Cy"],
    "last_name": ["Ash", "Birch", "Cedar"],
    "department": ["Kitchen", "Register", "Barista"],
    "hourly_rate": ["$20.00", "15.50", "$18.00"],
})

# Already through Step 1 and Step 2 — what Step 3's functions receive.
JOINED = pd.DataFrame({
    "payroll_date": ["2026-11-06"] * 3,
    "employee_id": ["X2", "X1", "X9"],
    "hours": ["10h 30m", "41h", "3.5"],
    "hours_worked": [10.5, 41.0, 3.5],
    "first_name": ["Bo", "Ann", None],
    "last_name": ["Birch", "Ash", None],
    "department": ["Register", "Kitchen", None],
    "hourly_rate": ["15.50", "$20.00", None],
    "hourly_rate_usd": [15.5, 20.0, float("nan")],
})

ROSTER_COLUMNS = ["first_name", "last_name", "department", "hourly_rate", "hourly_rate_usd"]

# --- Expected totals for the generated weeks -----------------------------------------
# (rows, total hours, total gross pay, overtime rows, unmatched rows)
SEEDED = {
    3: (9, 206.0, 3755.93, 2, 0),
    7: (10, 267.5, 4885.69, 3, 0),
    9: (11, 221.5, 4050.56, 1, 0),
    42: (9, 158.25, 2763.81, 1, 1),
}

# The sample files in data/, checked the same way.
FILES = {
    "timesheet_test.csv": (9, 241.75, 4133.72, 2, 1),
    "timesheet_2026-10-02.csv": (10, 331.75, 6139.61, 2, 0),
    "timesheet_2026-10-09.csv": (9, 263.25, 4759.18, 1, 1),
    "timesheet_2026-10-16.csv": (11, 367.75, 6835.31, 2, 0),
}


# --- Step 1: clean ----------------------------------------------------------------


def test_add_hours_worked_keeps_lineage():
    """One new float column; `hours` still says '10h 30m'; the input is untouched."""
    before = snapshot(RAW_TIMESHEET)
    out = add_hours_worked(RAW_TIMESHEET)

    assert_lineage(before, out, ["hours_worked"], "add_hours_worked")
    assert_unmodified(RAW_TIMESHEET, before, "add_hours_worked")
    assert list(out["hours_worked"]) == pytest.approx([10.5, 41.0, 3.5])


def test_add_hourly_rate_keeps_lineage():
    before = snapshot(RAW_ROSTER)
    out = add_hourly_rate(RAW_ROSTER)

    assert_lineage(before, out, ["hourly_rate_usd"], "add_hourly_rate")
    assert_unmodified(RAW_ROSTER, before, "add_hourly_rate")
    assert list(out["hourly_rate_usd"]) == pytest.approx([20.0, 15.5, 18.0])


def test_clean_runs_on_the_real_roster():
    """Every rate on the real roster is readable, and none of them is zero."""
    out = add_hourly_rate(load_employees())
    assert len(out) == 12
    assert (out["hourly_rate_usd"] > 0).all(), "a roster rate came back as 0.0 — check clean_currency"


# --- Step 2: join -----------------------------------------------------------------


def test_merge_keeps_every_timesheet_row():
    """Three timesheet rows in, three out — including X9, who is not on the roster.

    An inner merge silently drops X9, and the week's totals look perfectly
    plausible without them. That is the bug this test exists to catch.
    """
    timesheet = add_hours_worked(RAW_TIMESHEET)
    roster = add_hourly_rate(RAW_ROSTER)
    before = snapshot(timesheet)

    out = merge_employees(timesheet, roster)

    assert_lineage(before, out, ROSTER_COLUMNS, "merge_employees")
    assert_unmodified(timesheet, before, "merge_employees")
    assert list(out["employee_id"]) == ["X2", "X1", "X9"], "rows should keep the timesheet's order"


def test_merge_fills_roster_columns_and_leaves_gaps():
    """Matched rows get the person's roster values; the unknown ID gets NaN, not an error."""
    out = merge_employees(add_hours_worked(RAW_TIMESHEET), add_hourly_rate(RAW_ROSTER))
    by_id = out.set_index("employee_id")

    assert by_id.loc["X2", "first_name"] == "Bo"
    assert by_id.loc["X1", "hourly_rate_usd"] == 20.0
    assert by_id.loc["X1", "hourly_rate"] == "$20.00", "the raw rate text should come along too"
    assert pd.isna(by_id.loc["X9", "hourly_rate_usd"]), "an unknown employee has no rate — NaN"


def test_merge_does_not_invent_rows_for_people_who_did_not_work():
    """X3 is on the roster but has no timesheet row, so X3 is not paid this week."""
    out = merge_employees(add_hours_worked(RAW_TIMESHEET), add_hourly_rate(RAW_ROSTER))
    assert "X3" not in set(out["employee_id"]), "a right or outer merge adds rows the timesheet never had"


# --- Step 3: compute --------------------------------------------------------------


def test_add_gross_pay_keeps_lineage():
    """Scoped: given a frame that already has hours and rates, add gross_pay and nothing else."""
    before = snapshot(JOINED)
    out = add_gross_pay(JOINED)

    assert_lineage(before, out, ["gross_pay"], "add_gross_pay")
    assert_unmodified(JOINED, before, "add_gross_pay")
    # 10.5*15.5 ; 40*20 + 1*20*1.5 ; no rate -> 0
    assert list(out["gross_pay"]) == pytest.approx([162.75, 830.0, 0.0])


def test_add_pay_type_keeps_lineage():
    before = snapshot(JOINED)
    out = add_pay_type(JOINED)

    assert_lineage(before, out, ["pay_type"], "add_pay_type")
    assert list(out["pay_type"]) == ["regular", "overtime", "unmatched"]


def test_build_payroll_chains_the_steps():
    """Raw in, payroll out: every raw column still there, all new columns present, one row per timesheet row."""
    before = snapshot(RAW_TIMESHEET)
    out = build_payroll(RAW_TIMESHEET, RAW_ROSTER)

    assert_lineage(
        before, out,
        ["hours_worked", "gross_pay", "pay_type"] + ROSTER_COLUMNS,
        "build_payroll",
    )
    assert_unmodified(RAW_TIMESHEET, before, "build_payroll")
    assert list(out["pay_type"]) == ["regular", "overtime", "unmatched"]
    assert out["gross_pay"].sum() == pytest.approx(992.75)


@pytest.mark.parametrize("seed", sorted(SEEDED))
def test_build_payroll_on_generated_weeks(seed):
    """The whole pipeline on a week you have never seen. Same seed, same answer, every time."""
    rows, hours, gross, overtime, unmatched = SEEDED[seed]
    timesheet = generate_timesheet(seed)
    out = build_payroll(timesheet, load_employees())

    assert len(out) == rows, f"seed {seed}: expected {rows} rows (one per timesheet row)"
    assert out["hours_worked"].sum() == pytest.approx(hours), f"seed {seed}: total hours"
    assert out["gross_pay"].sum() == pytest.approx(gross, abs=0.01), f"seed {seed}: total gross pay"
    assert (out["pay_type"] == "overtime").sum() == overtime, f"seed {seed}: overtime rows"
    assert (out["pay_type"] == "unmatched").sum() == unmatched, f"seed {seed}: unmatched rows"


@pytest.mark.parametrize("filename", sorted(FILES))
def test_build_payroll_on_the_sample_files(filename):
    rows, hours, gross, overtime, unmatched = FILES[filename]
    out = build_payroll(load_timesheet(f"data/{filename}"), load_employees())

    assert len(out) == rows
    assert out["hours_worked"].sum() == pytest.approx(hours)
    assert out["gross_pay"].sum() == pytest.approx(gross, abs=0.01)
    assert (out["pay_type"] == "overtime").sum() == overtime
    assert (out["pay_type"] == "unmatched").sum() == unmatched


def test_payroll_export_has_the_providers_columns():
    """Exactly the five columns the provider imports, in order, and only payable rows."""
    payroll = build_payroll(RAW_TIMESHEET, RAW_ROSTER)
    before = snapshot(payroll)
    export = payroll_export(payroll)

    assert list(export.columns) == ["payrolldate", "employeeid", "hours", "rate", "total"]
    assert list(export["employeeid"]) == ["X2", "X1"], "the unmatched row X9 must not be exported"
    assert list(export["hours"]) == pytest.approx([10.5, 41.0])
    assert list(export["rate"]) == pytest.approx([15.5, 20.0])
    assert list(export["total"]) == pytest.approx([162.75, 830.0])
    assert_unmodified(payroll, before, "payroll_export")
    assert "payroll_date" in payroll.columns, "the pipeline table keeps its own column names"


# --- The app --------------------------------------------------------------------------


def test_app_starts_quiet():
    """Title and uploader on the first run; no totals until a timesheet is uploaded."""
    app = load_app(APP)
    no_exception(app, APP)

    assert "Payroll" in page_text(app)
    widget(app.file_uploader, "timesheet", "file_uploader")
    assert not app.metric, "no totals should be shown before a file is uploaded"
    assert not app.download_button, "nothing to download before a file is uploaded"


def test_app_shows_the_weeks_totals():
    """Uploading the test week: the four metric cards, the pay period, the warning, the table."""
    app = load_app(APP)
    upload_csv(app, "timesheet_test.csv", data_file("timesheet_test.csv"))
    app.run()
    no_exception(app, APP)

    shown = metrics(app)
    assert shown.get("Employees paid") == "8", shown
    assert shown.get("Total hours") == "241.75", shown
    assert shown.get("Total gross pay") == "$4,133.72", shown
    assert shown.get("Overtime weeks") == "2", shown

    text = page_text(app)
    assert "2026-09-25" in text, "the pay period date should be on the page"
    assert app.warning, "an unmatched employee_id should raise an st.warning"
    assert "E099" in app.warning[0].value, "the warning should name the unmatched employee_id"

    assert app.dataframe, "the payroll table should be shown with st.dataframe"
    table = app.dataframe[0].value
    for column in ("hours", "hours_worked", "hourly_rate", "hourly_rate_usd", "gross_pay", "pay_type"):
        assert column in table.columns, f"the table should show lineage column {column!r}"


def test_app_offers_the_export_download():
    app = load_app(APP)
    upload_csv(app, "timesheet_2026-10-02.csv", data_file("timesheet_2026-10-02.csv"))
    app.run()
    no_exception(app, APP)

    assert not app.warning, "a week with every ID on the roster should not warn"
    button = widget(app.download_button, "download", "download_button")
    assert button.proto.url.endswith(".csv"), "the download should be a CSV file"
    assert metrics(app).get("Employees paid") == "10"


def test_app_recomputes_for_a_generated_week():
    """A week the app has never seen — the numbers on the page come from the pipeline."""
    week = generate_timesheet(42)
    app = load_app(APP)
    upload_csv(app, "timesheet_2026-10-23.csv", week.to_csv(index=False))
    app.run()
    no_exception(app, APP)

    shown = metrics(app)
    assert shown.get("Employees paid") == "8", shown          # 9 rows, 1 unmatched
    assert shown.get("Total hours") == "158.25", shown
    assert shown.get("Total gross pay") == "$2,763.81", shown
    assert app.warning and "E9" in app.warning[0].value
