"""DeferredTest (seasonal testing) endpoints."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, ROLE_CX_AUTHORITY, authenticate, body_json, bump_project, clock, db,
    fail, fmt_dt, new_row, ok, ok_list, paginate, parse_dt, public, q, sorted_rows,
    touch, v_datetime, v_enum, v_number, v_string,
)
from finders import get_deferred_test, get_equipment, get_issue, get_requirement

bp = Blueprint("deferred_tests", __name__)


@bp.post("/deferred-tests")
def create_deferred_test():
    authenticate([ROLE_CX_AUTHORITY])
    body = body_json()
    equipment_id = v_string(body, "equipment_id")
    requirement_id = v_string(body, "requirement_id")
    season = v_enum(body, "season", calc.SEASONS)
    window_start = v_datetime(body, "window_start")
    window_end = v_datetime(body, "window_end")
    issue_id = v_string(body, "issue_id", required=False, default=None)

    equipment_row = get_equipment(equipment_id)
    requirement = get_requirement(requirement_id)
    issue = get_issue(issue_id) if issue_id is not None else None

    project_id = equipment_row["project_id"]
    if requirement["project_id"] != project_id:
        fail("ERR_PROJECT_SCOPE_MISMATCH",
             "The owner requirement belongs to a different engagement.")
    if issue is not None and issue["project_id"] != project_id:
        fail("ERR_PROJECT_SCOPE_MISMATCH", "The issue belongs to a different engagement.")

    project = db.projects.get(project_id)
    if project["readiness_posture"] == "FROZEN":
        fail("ERR_PROJECT_FROZEN", "The engagement is FROZEN.")

    if window_end <= window_start:
        fail("ERR_INVALID_WINDOW", "window_end must be strictly after window_start.")

    if calc.seasonal_conflict(equipment_id, window_start, window_end):
        fail("ERR_SEASONAL_WINDOW_CONFLICT",
             "The seasonal window overlaps another live window on this equipment unit.")

    plan = calc.newest_approved_plan(project_id)
    if plan is None or requirement_id not in plan["pinned_requirement_ids"]:
        fail("ERR_REQUIREMENT_NOT_PINNED",
             "The requirement is not pinned by the newest approved commissioning plan.")

    row = new_row(db.deferred_tests, {
        "equipment_id": equipment_id,
        "requirement_id": requirement_id,
        "issue_id": issue_id,
        "season": season,
        "window_start": fmt_dt(window_start),
        "window_end": fmt_dt(window_end),
        "status": "PLANNED",
        "executed_at": None,
        "measured_value": None,
    })
    services.reconcile()
    return ok(public(row), 201)


@bp.get("/deferred-tests")
def list_deferred_tests():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.deferred_tests.values()))
    for param in ("equipment_id", "requirement_id", "issue_id", "status", "season"):
        value = q(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.get("/deferred-tests/<deferred_test_id>")
def read_deferred_test(deferred_test_id):
    authenticate(ALL_ROLES)
    return ok(public(get_deferred_test(deferred_test_id)))


@bp.post("/deferred-tests/<deferred_test_id>/execute")
def execute_deferred_test(deferred_test_id):
    authenticate([ROLE_CX_AUTHORITY])
    row = get_deferred_test(deferred_test_id)
    body = body_json()
    measured_value = v_number(body, "measured_value")

    if row["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "Only a PLANNED seasonal test may be executed.")

    now = clock.now()
    window_start = parse_dt(row["window_start"])
    window_end = parse_dt(row["window_end"])
    if not (window_start <= now < window_end):
        fail("ERR_OUTSIDE_SEASONAL_WINDOW",
             "The logical clock is outside the seasonal window.")

    equipment_row = db.equipment.get(row["equipment_id"])
    project = db.projects.get(equipment_row["project_id"])
    requirement = db.requirements.get(row["requirement_id"])

    deviation = calc.compute_deviation_pct(measured_value, requirement)
    passed = deviation <= calc.D(requirement["tolerance_pct"])

    row["status"] = "EXECUTED_PASS" if passed else "EXECUTED_FAIL"
    row["executed_at"] = clock.now_iso()
    row["measured_value"] = measured_value
    touch(row)

    linked = db.issues.get(row.get("issue_id")) if row.get("issue_id") else None
    if linked is not None and linked["status"] == "DEFERRED":
        if passed:
            services.apply_issue_status_change(linked, "VERIFIED_CLOSED")
            touch(linked)
        else:
            services.apply_issue_status_change(linked, "OPEN")
            linked["reopen_count"] = linked["reopen_count"] + 1
            touch(linked)

    bump_project(project)
    services.reconcile()
    return ok(public(row))
