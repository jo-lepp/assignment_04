"""
payroll — the ETL pipeline behind the weekly payroll app.  *(Provided for you.)*

    from payroll import load_employees, load_timesheet, build_payroll, payroll_export

The pipeline is three steps in three modules, each adding columns and never
removing or overwriting any:

    extract.py   load the roster and a week's timesheet          (given)
    clean.py     Step 1 — text to numbers with Series.apply      (you)
    join.py      Step 2 — timesheet + roster with pd.merge       (you)
    compute.py   Step 3 — pay and labels with row apply; export  (you)

This file just declares the public API — the same job `__init__.py` did in
Assignment 02. Every name below must exist in its module, even before you have
written its body, or `import payroll` fails and every test in the suite goes red
at once. That is why the stubs keep every function signature.
"""

from .clean import add_hourly_rate, add_hours_worked, clean_currency, parse_hours
from .compute import (
    add_gross_pay,
    add_pay_type,
    build_payroll,
    calc_gross_pay,
    classify_pay,
    payroll_export,
)
from .extract import generate_timesheet, load_employees, load_timesheet
from .join import merge_employees

__all__ = [
    "load_employees",
    "load_timesheet",
    "generate_timesheet",
    "parse_hours",
    "clean_currency",
    "add_hours_worked",
    "add_hourly_rate",
    "merge_employees",
    "calc_gross_pay",
    "classify_pay",
    "add_gross_pay",
    "add_pay_type",
    "build_payroll",
    "payroll_export",
]
