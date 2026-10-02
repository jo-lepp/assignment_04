"""
compute.py — Step 3 of the pipeline: pay, labels, and the file the provider wants.

Two element functions that need **two** values from a row, two DataFrame
functions that run them across every row with `DataFrame.apply(..., axis=1)`,
the function that chains all three steps into one call, and the export that
reshapes the result for the online payroll provider.

No walkthrough this time. You have `clean.py` and `join.py` beside you, the
docstrings say what each function must return, and `tests/test_unit.py` and
`tests/test_pipeline.py` say exactly how they will be checked.
"""

import pandas as pd

from .clean import add_hourly_rate, add_hours_worked
from .join import merge_employees

OVERTIME_THRESHOLD = 40.0   # weekly hours above this are paid at time-and-a-half
OVERTIME_MULTIPLIER = 1.5


def calc_gross_pay(hours: float, rate: float) -> float:
    """Gross pay for one employee-week, rounded to cents.

    Up to 40 hours at `rate`; every hour above 40 at `rate * 1.5`. A missing rate
    (`NaN`, because the employee was not on the roster) pays `0.0` — the row is
    flagged elsewhere, it is not this function's job to crash.

    Examples:

        calc_gross_pay(38.5, 18.5)   ->  712.25
        calc_gross_pay(42.0, 19.0)   ->  817.0      # 40*19 + 2*19*1.5
        calc_gross_pay(0.75, 17.0)   ->  12.75
        calc_gross_pay(20.0, float("nan"))  ->  0.0
    """
    if pd.isna(rate):
        return 0.0
    if hours > OVERTIME_THRESHOLD:
        reg_hours = OVERTIME_THRESHOLD
        overtime = hours - OVERTIME_THRESHOLD
        overtime_pay = overtime * (rate * OVERTIME_MULTIPLIER)
        reg_pay = reg_hours * rate
        return round(overtime_pay + reg_pay, 2)
    else:
        return round(hours * rate, 2)


def classify_pay(hours: float, rate: float) -> str:
    """One word the office manager can filter on: what kind of pay row is this?

        "unmatched"   the rate is missing -> employee_id was not on the roster
        "overtime"    more than 40 hours
        "regular"     everything else

    Check for unmatched *first*: an unknown employee with 45 hours is still
    unmatched, not overtime.
    """
    if pd.isna(rate):
        return "unmatched"
    elif hours > OVERTIME_THRESHOLD:
        return "overtime"
    else:
        return "regular"


def add_gross_pay(payroll: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with one new column, `gross_pay`: `calc_gross_pay` for every row.

    The function needs two values from the same row, so this is `DataFrame.apply`
    with `axis=1`, and a lambda that unpacks the row:

        lambda row: calc_gross_pay(row["hours_worked"], row["hourly_rate_usd"])
    """
    copy = payroll.copy()
    copy["gross_pay"] = copy.apply(lambda row: calc_gross_pay(row["hours_worked"],
                                                              row["hourly_rate_usd"]), axis=1)
    return copy



def add_pay_type(payroll: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with one new column, `pay_type`: `classify_pay` for every row."""
    copy = payroll.copy()
    copy["pay_type"] = copy.apply(lambda row: classify_pay(row["hours_worked"],
                                                                  row["hourly_rate_usd"]), axis=1)
    return copy


def build_payroll(timesheet: pd.DataFrame, employees: pd.DataFrame) -> pd.DataFrame:
    """The whole pipeline in one call: raw timesheet + raw roster -> payroll table.

    Clean both frames (Step 1), merge them (Step 2), then add `gross_pay` and
    `pay_type` (Step 3). Every column that went in comes out, plus the four the
    pipeline computes (`hours_worked`, `hourly_rate_usd`, `gross_pay`, `pay_type`)
    and the roster's columns — one row per timesheet row.
    """
    # CLEANING TIMESHEET
    add_hours_timesheet = add_hours_worked(timesheet)
    add_rate_timesheet = add_hourly_rate(add_hours_timesheet)

    # CLEANING ROSTER
    add_hours_roster = add_hours_worked(employees)
    add_rate_roster = add_hourly_rate(add_hours_roster)

    # MERGING
    merged_df = merge_employees(add_rate_timesheet, add_rate_roster)

    # ADDING COLUMNS
    df_gross_pay = add_gross_pay(merged_df)
    df_pay_type = add_pay_type(df_gross_pay)

    return df_pay_type


def payroll_export(payroll: pd.DataFrame) -> pd.DataFrame:
    """The file the online payroll provider imports — a NEW frame, not a renamed one.

    Exactly these columns, in this order, with these names:

        payrolldate, employeeid, hours, rate, total

    taken from `payroll_date`, `employee_id`, `hours_worked`, `hourly_rate_usd`
    and `gross_pay`. Only rows the provider can pay: `pay_type != "unmatched"`
    (the provider rejects an ID it does not know, and the manager fixes those
    rows in the app before re-exporting).

    Build it as a new DataFrame from the columns you want — do not rename the
    pipeline's columns. The pipeline table keeps its lineage; the export is a
    view of it shaped for someone else's system.
    """
    payable = payroll[payroll["pay_type"] != "unmatched"]

    export = pd.DataFrame({
        "payrolldate": payable['payroll_date'],
        "employeeid": payable['employee_id'],
        "hours": payable['hours_worked'],
        "rate": payable['hourly_rate_usd'],
        "total": payable['gross_pay']
    })

    return export
