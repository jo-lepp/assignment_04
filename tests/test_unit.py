"""Unit tests — the four element functions, one value at a time.

These functions take one or two plain Python values and return one. They know
nothing about DataFrames, which is exactly why they are easy to test: no data
file, no pipeline, just inputs and the answer you should get back.

They import from the module that owns each function rather than from the
package, so they run even while other modules are still stubs. Run them alone:

    pytest tests/test_unit.py -v
"""

import math

import pytest

from payroll.clean import clean_currency, parse_hours
from payroll.compute import calc_gross_pay, classify_pay

NAN = float("nan")


# --- Step 1: reading text ----------------------------------------------------------


@pytest.mark.parametrize("text, hours", [
    ("38h 30m", 38.5),
    ("42h", 42.0),
    ("45m", 0.75),
    ("24.5", 24.5),
    ("40h 15m", 40.25),
    ("90m", 1.5),
    ("  36h  ", 36.0),        # shift leads leave spaces
    ("0h", 0.0),
])
def test_parse_hours(text, hours):
    """Every format the shift leads use, including the one where 'm' means minutes."""
    assert parse_hours(text) == pytest.approx(hours), f"parse_hours({text!r})"


@pytest.mark.parametrize("bad", ["", "   ", "forty", "8 hours", None, NAN])
def test_parse_hours_never_crashes(bad):
    """Unreadable is zero, not a traceback. One bad cell must not take down payroll."""
    assert parse_hours(bad) == 0.0


def test_parse_hours_accepts_a_number():
    """A file where every value is a plain decimal may arrive already numeric."""
    assert parse_hours(37.5) == 37.5


@pytest.mark.parametrize("text, amount", [
    ("$18.50", 18.5),
    ("17.75", 17.75),
    ("$1,020.00", 1020.0),
    (" $20.25 ", 20.25),
    ("$16", 16.0),
])
def test_clean_currency(text, amount):
    assert clean_currency(text) == pytest.approx(amount), f"clean_currency({text!r})"


@pytest.mark.parametrize("bad", ["", "N/A", "twenty", None, NAN])
def test_clean_currency_never_crashes(bad):
    assert clean_currency(bad) == 0.0


# --- Step 3: two values in, one out ------------------------------------------------


@pytest.mark.parametrize("hours, rate, pay", [
    (38.5, 18.5, 712.25),         # under 40: hours * rate
    (40.0, 20.0, 800.0),          # exactly 40 is not overtime
    (42.0, 19.0, 817.0),          # 40*19 + 2*19*1.5
    (40.25, 20.25, 817.59),       # rounded to cents: 810 + 7.59375
    (0.75, 17.0, 12.75),
    (0.0, 18.0, 0.0),
])
def test_calc_gross_pay(hours, rate, pay):
    assert calc_gross_pay(hours, rate) == pytest.approx(pay, abs=0.005)


def test_calc_gross_pay_with_no_rate_is_zero():
    """An employee the roster does not know cannot be paid — but must not crash."""
    assert calc_gross_pay(20.0, NAN) == 0.0
    assert not math.isnan(calc_gross_pay(20.0, NAN))


@pytest.mark.parametrize("hours, rate, label", [
    (38.5, 18.5, "regular"),
    (40.0, 18.5, "regular"),      # 40 on the nose is a full week, not overtime
    (40.25, 18.5, "overtime"),
    (45.0, NAN, "unmatched"),     # unmatched wins, even with overtime hours
    (0.0, NAN, "unmatched"),
])
def test_classify_pay(hours, rate, label):
    assert classify_pay(hours, rate) == label
