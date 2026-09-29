"""Hold records, the case cascade they drive and the case counter partition."""

import db

NON_TERMINAL_HOLD_STATES = ("HELD", "UNDER_TEST", "RETEST_REQUIRED")


def cases_of(run_id):
    cases = [c for c in db.rows("finished_cases") if c["process_run_id"] == run_id]
    cases.sort(key=lambda c: c["case_sequence"])
    return cases


def holds_of(run_id):
    return [h for h in db.rows("hold_records") if h["process_run_id"] == run_id]


def open_holds(run_id):
    return [h for h in holds_of(run_id) if h["status"] in NON_TERMINAL_HOLD_STATES]


def recount(run):
    """Recompute the four counters that partition the run's cases."""
    counts = {"IN_INVENTORY": 0, "ON_HOLD": 0, "SHIPPED": 0, "DESTROYED": 0}
    for case in cases_of(run["id"]):
        counts[case["status"]] = counts[case["status"]] + 1
    mapping = (
        ("cases_available", "IN_INVENTORY"),
        ("cases_on_hold", "ON_HOLD"),
        ("cases_shipped", "SHIPPED"),
        ("cases_destroyed", "DESTROYED"),
    )
    changed = False
    for field, status in mapping:
        if run.get(field) != counts[status]:
            run[field] = counts[status]
            changed = True
    return changed


def open_hold(run, reason, now):
    """Open a hold on the run and move its IN_INVENTORY cases to ON_HOLD."""
    cases = cases_of(run["id"])
    shipped_count = len([c for c in cases if c["status"] == "SHIPPED"])
    hold = db.new_row(
        "hold_records",
        {
            "process_run_id": run["id"],
            "reason": reason,
            "status": "HELD",
            "test_round": 0,
            "latest_test_type": None,
            "latest_test_result": None,
            "latest_apc_cfu_g": None,
            "resulted_by_user_id": None,
            "released_by_user_id": None,
            "cases_held_count": 0,
            "shipped_case_count": shipped_count,
            "closed_at": None,
            "_dt_closed_at": None,
        },
    )
    db.stamp(hold, "opened_at", now)
    moved = 0
    for case in cases:
        if case["status"] == "IN_INVENTORY":
            case["status"] = "ON_HOLD"
            db.touch(case)
            moved += 1
    hold["cases_held_count"] = moved
    changed = recount(run)
    if run["disposition_status"] != "REJECTED" and run["disposition_status"] != "HELD":
        run["disposition_status"] = "HELD"
        changed = True
    if changed:
        db.touch(run)
    return hold


def restore_cases(run, code_date, code_date_label):
    """Hold release: ON_HOLD cases return to IN_INVENTORY with the FINAL code date."""
    for case in cases_of(run["id"]):
        if case["status"] in ("SHIPPED", "DESTROYED"):
            continue
        touched = False
        if case["status"] == "ON_HOLD":
            case["status"] = "IN_INVENTORY"
            touched = True
        if code_date is not None and case["code_date"] != code_date:
            case["code_date"] = code_date
            case["code_date_label"] = code_date_label
            touched = True
        elif code_date is not None and case["code_date_label"] != code_date_label:
            case["code_date_label"] = code_date_label
            touched = True
        if touched:
            db.touch(case)


def destroy_cases(run):
    for case in cases_of(run["id"]):
        if case["status"] == "ON_HOLD":
            case["status"] = "DESTROYED"
            db.touch(case)
