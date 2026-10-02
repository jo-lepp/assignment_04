"""Code structure tests — read the source and check the pipeline is built the right way.

The pipeline tests check what your functions *return*. These check *how*: that
each step uses the pandas technique it is teaching, that nothing overwrites,
drops or renames a column (the lineage rule, enforced), and that nothing from a
later lesson has crept in to do a job a Series `.sum()` can do.

Everything here reads the **parsed** source (`ast`), not the text, so a
technique mentioned in a comment does not count, and a forbidden call cannot
hide behind one. When a test fails, the message names the file and the exact
thing it was looking for.
"""

import ast

from helpers import repo_path

CLEAN = "code/payroll/clean.py"
JOIN = "code/payroll/join.py"
COMPUTE = "code/payroll/compute.py"
APP = "code/payroll_app.py"
PIPELINE_MODULES = (CLEAN, JOIN, COMPUTE)

# The columns the source files give you. A pipeline step may READ these; it may
# never assign to them.
INPUT_COLUMNS = {
    "payroll_date", "employee_id", "hours",
    "first_name", "last_name", "department", "hourly_rate",
}

# Ways to destroy lineage. None of them belong in this pipeline.
# (`.replace` is not here: `"$18.50".replace("$", "")` is string cleaning, and a
# DataFrame.replace that alters an input column is caught by the pipeline tests.)
LINEAGE_BREAKERS = {"drop", "rename", "pop", "insert", "drop_duplicates"}

# Later lessons. A single week's payroll needs none of them — totals are
# `series.sum()`, filtering is a boolean index, dates stay as text.
OUT_OF_SCOPE = {
    "groupby", "pivot", "pivot_table", "melt", "agg", "aggregate", "transform",
    "to_datetime", "resample", "crosstab", "Grouper",
}


# --- Reading the source ---------------------------------------------------------------


def parse(script: str) -> ast.Module:
    with open(repo_path(script), encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=script)


def calls(tree: ast.Module) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def call_name(node: ast.Call) -> str:
    """`pd.merge(...)` -> "merge"; `out["x"].apply(f)` -> "apply"; `float(x)` -> "float"."""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def called_names(tree: ast.Module) -> set[str]:
    return {call_name(node) for node in calls(tree)}


def keyword_value(node: ast.Call, name: str):
    for keyword in node.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def imported_modules(tree: ast.Module) -> set[str]:
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def assigned_columns(tree: ast.Module) -> list[str]:
    """Every column name assigned with `frame["name"] = ...` or `frame.name = ...`."""
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
                names.append(str(target.slice.value))
            elif isinstance(target, ast.Attribute):
                names.append(target.attr)
    return names


def lineage_violations(script: str) -> list[str]:
    """Human-readable descriptions of every lineage-breaking construct in a file."""
    tree = parse(script)
    problems = []

    for name in sorted(set(assigned_columns(tree)) & INPUT_COLUMNS):
        problems.append(f"assigns to input column {name!r} — clean into a NEW column instead")

    for node in calls(tree):
        name = call_name(node)
        if name in LINEAGE_BREAKERS:
            problems.append(f"calls .{name}() — a pipeline step never removes, renames or replaces a column")
        if keyword_value(node, "inplace") is True:
            problems.append("uses inplace=True — pipeline steps return a new frame, they do not mutate")

    for node in ast.walk(tree):
        if isinstance(node, ast.Delete):
            problems.append("uses `del` — columns are never removed")

    return problems


def out_of_scope_uses(script: str) -> list[str]:
    tree = parse(script)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in OUT_OF_SCOPE | {"dt"}:
            found.append(node.attr)
        elif isinstance(node, ast.Name) and node.id in OUT_OF_SCOPE:
            found.append(node.id)
    return sorted(set(found))


# --- Step 1 -----------------------------------------------------------------------------


def test_clean_uses_series_apply_on_a_copy():
    """Step 1 runs the element functions with Series.apply, on a copy of the input."""
    called = called_names(parse(CLEAN))

    assert "apply" in called, f"{CLEAN} should run parse_hours / clean_currency with .apply(...)"
    assert "copy" in called, f"{CLEAN} should start each step with .copy() so the caller's frame is untouched"
    assert "parse_hours" in called and "clean_currency" in called, (
        f"{CLEAN} should pass parse_hours and clean_currency to .apply — not re-do their work inline"
    )
    assert not lineage_violations(CLEAN), f"{CLEAN}: " + "; ".join(lineage_violations(CLEAN))


# --- Step 2 -----------------------------------------------------------------------------


def test_join_keeps_one_side_with_merge():
    """Step 2 is one pd.merge, on employee_id, keeping every timesheet row.

    `how="left"` with the timesheet on the left is the natural spelling, but
    `how="right"` with the frames swapped says the same thing, and either is
    accepted. What is not accepted is the default (`inner`) or `outer`.
    """
    merges = [node for node in calls(parse(JOIN)) if call_name(node) == "merge"]

    assert merges, f"{JOIN} should combine the frames with pd.merge(...)"
    hows = [keyword_value(node, "how") for node in merges]
    assert "left" in hows or "right" in hows, (
        f"{JOIN} merges with how={hows} (None means the default, inner) — a timesheet row "
        "whose employee_id is not on the roster must survive with NaN, and rostered people "
        "who did not work must not appear. That is a one-sided join: how='left' with the "
        "timesheet as the left frame (or how='right' with the frames swapped). Re-read the "
        "four join types in lesson 3-3."
    )
    assert not lineage_violations(JOIN), f"{JOIN}: " + "; ".join(lineage_violations(JOIN))


# --- Step 3 -----------------------------------------------------------------------------


def test_compute_uses_row_apply_and_reuses_the_earlier_steps():
    """Step 3 applies two-argument functions across rows (axis=1) and chains the real steps."""
    tree = parse(COMPUTE)
    applies = [node for node in calls(tree) if call_name(node) == "apply"]
    called = called_names(tree)

    assert applies, f"{COMPUTE} should compute gross_pay and pay_type with .apply(...)"
    assert any(keyword_value(node, "axis") == 1 for node in applies), (
        f"{COMPUTE}: calc_gross_pay needs two values from the same row, so the apply is "
        "DataFrame.apply(lambda row: ..., axis=1)"
    )
    assert "calc_gross_pay" in called and "classify_pay" in called, (
        f"{COMPUTE} should call calc_gross_pay and classify_pay from inside the apply"
    )
    for step in ("add_hours_worked", "add_hourly_rate", "merge_employees", "add_gross_pay", "add_pay_type"):
        assert step in called, f"{COMPUTE}: build_payroll should call {step}() rather than re-implementing it"
    assert not lineage_violations(COMPUTE), f"{COMPUTE}: " + "; ".join(lineage_violations(COMPUTE))


# --- The lineage rule, across the whole pipeline ----------------------------------------


def test_pipeline_only_ever_adds_columns():
    """Every column assignment in the pipeline is to a NEW name; nothing is dropped or renamed."""
    all_assigned = []
    problems = []
    for script in PIPELINE_MODULES:
        all_assigned.extend(assigned_columns(parse(script)))
        problems.extend(f"{script}: {p}" for p in lineage_violations(script))

    assert all_assigned, "the pipeline never assigns a column — the steps are not written yet"
    assert not problems, "\n".join(problems)
    for expected in ("hours_worked", "hourly_rate_usd", "gross_pay", "pay_type"):
        assert expected in all_assigned, f"no step assigns the {expected!r} column"


def test_pipeline_stays_in_this_weeks_toolbox():
    """No group-by, pivot, melt or datetime anywhere — and the app totals with .sum()."""
    for script in PIPELINE_MODULES + (APP,):
        used = out_of_scope_uses(script)
        assert not used, (
            f"{script} uses {used}. A single week's payroll needs none of these: a total is "
            "`series.sum()`, a count is `len(frame[condition])`, and dates stay as text."
        )
    assert "sum" in called_names(parse(APP)), f"{APP} should total hours and pay with .sum() on a Series"


# --- The app ------------------------------------------------------------------------------


def test_app_assembles_the_pipeline():
    """The page loads the roster, takes an upload, calls build_payroll once, and shows the results."""
    tree = parse(APP)
    called = called_names(tree)

    assert "payroll" in imported_modules(tree), f"{APP} should import from the payroll package"
    for name in ("load_employees", "load_timesheet", "build_payroll", "payroll_export"):
        assert name in called, f"{APP} should call {name}() — the app assembles the pipeline, it does not re-do it"
    for widget in ("file_uploader", "metric", "warning", "dataframe", "download_button"):
        assert widget in called, f"{APP} should use st.{widget}(...)"
    assert "print" not in called and "input" not in called, f"{APP}: use widgets, not the console"
    assert not lineage_violations(APP), f"{APP}: " + "; ".join(lineage_violations(APP))
