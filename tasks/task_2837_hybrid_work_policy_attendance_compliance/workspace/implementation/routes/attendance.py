"""AttendanceWeek and ComplianceSignal routes."""
from flask import Blueprint

import calc
import clock
import db
import guards
import middleware
import recompute
from errors import fail
from middleware import (ALL_ROLES, EMPLOYEE, HR_BUSINESS_PARTNER, PEOPLE_MANAGER,
                        SYSTEM_INTEGRATION)

bp = Blueprint("attendance", __name__)

READ_ROLES = tuple(r for r in ALL_ROLES if r != EMPLOYEE)
WEEK_STATUSES = ("OPEN", "FINALIZED", "AMENDED", "LOCKED")
SIGNAL_SOURCES = ("BADGE", "NETWORK", "MANUAL_ATTEST")
EDITABLE = ("OPEN", "AMENDED")


@bp.route("/attendance-weeks", methods=["POST"])
def create_week():
    middleware.authorize((SYSTEM_INTEGRATION, HR_BUSINESS_PARTNER, PEOPLE_MANAGER))
    payload = middleware.body()
    employee_id = middleware.req_present(payload, "employee_id")
    employee = middleware.must_exist("employee", employee_id)
    cycle = recompute.cycle_of_employee(employee)

    iso_week = middleware.req_string(payload, "iso_week", 1, None, r"^\d{4}-W\d{2}$")
    week_start_date = middleware.req_date(payload, "week_start_date")
    monday = clock.week_monday(iso_week)
    if monday is None:
        fail("ERR_INVALID_REQUEST", "iso_week is not a real ISO week")
    if week_start_date != monday:
        fail("ERR_INVALID_REQUEST", "week_start_date must be the Monday of iso_week")

    guards.gate_cycle_not_locked(cycle)
    guards.gate_employee_active(employee)

    for existing in db.find("attendance_week", employee_id=employee["id"]):
        if existing["iso_week"] == iso_week:
            fail("ERR_DUPLICATE_ATTENDANCE_WEEK",
                 "an attendance week already exists for this employee and iso_week")

    row = db.insert("attendance_week", {
        "employee_id": employee["id"],
        "iso_week": iso_week,
        "week_start_date": week_start_date.isoformat(),
        "status": "OPEN",
        "required_days": 0,
        "variant_applied": None,
        "credited_days": 0,
        "relief_days_credited": 0,
        "shortfall_days": 0,
        "amendment_reason": None,
        "finalized_at": None,
    })
    return guards.single("attendance_week", row, 201)


@bp.route("/attendance-weeks/<week_id>", methods=["GET"])
def get_week(week_id):
    actor = middleware.authorize(ALL_ROLES)
    row = middleware.must_exist("attendance_week", week_id)
    guards.require_owner(actor, row["employee_id"])
    return guards.single("attendance_week", row)


@bp.route("/attendance-weeks", methods=["GET"])
def list_weeks():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("attendance_week")
    for arg in ("employee_id", "iso_week", "status"):
        value = middleware.filter_arg(arg)
        if value is not None:
            rows = [r for r in rows if r[arg] == value]
    return guards.paged("attendance_week", rows,
                        sort_key=lambda w: (w["week_start_date"], db.seq_key(w)))


@bp.route("/attendance-weeks/<week_id>/signals", methods=["POST"])
def append_signal(week_id):
    middleware.authorize((SYSTEM_INTEGRATION, PEOPLE_MANAGER))
    week = middleware.must_exist("attendance_week", week_id)
    employee = db.get("employee", week["employee_id"])
    cycle = recompute.cycle_of_employee(employee)

    payload = middleware.body()
    source = middleware.req_enum(payload, "signal_source", SIGNAL_SOURCES)
    site_code = middleware.req_string(payload, "site_code", 1, 16)
    observed_date = middleware.req_date(payload, "observed_date")
    minutes_present = middleware.req_int(payload, "minutes_present", 0, 1440)
    dedupe_key = middleware.req_string(payload, "dedupe_key", 1, 64)

    guards.gate_cycle_not_locked(cycle)
    if week["status"] not in EDITABLE:
        fail("ERR_WEEK_NOT_OPEN", "attendance week is not editable")

    for existing in db.find("compliance_signal", attendance_week_id=week["id"]):
        if existing["dedupe_key"] == dedupe_key:
            fail("ERR_DUPLICATE_SIGNAL", "dedupe_key already present on this week")

    if observed_date not in clock.week_dates(week["iso_week"]):
        fail("ERR_SIGNAL_OUTSIDE_WEEK", "observed_date falls outside the week's seven dates")

    row = db.insert("compliance_signal", {
        "attendance_week_id": week["id"],
        "signal_source": source,
        "site_code": site_code,
        "observed_date": observed_date.isoformat(),
        "minutes_present": minutes_present,
        "dedupe_key": dedupe_key,
    }, versioned=False)
    return guards.single("compliance_signal", row, 201)


@bp.route("/attendance-weeks/<week_id>/finalize", methods=["POST"])
def finalize_week(week_id):
    middleware.authorize((SYSTEM_INTEGRATION, HR_BUSINESS_PARTNER, PEOPLE_MANAGER))
    week = middleware.must_exist("attendance_week", week_id)
    employee = db.get("employee", week["employee_id"])
    team = recompute.team_of_employee(employee)
    cycle = recompute.cycle_of_team(team) if team else None

    guards.gate_cycle_not_locked(cycle)
    if week["status"] not in EDITABLE:
        fail("ERR_WEEK_NOT_OPEN", "attendance week is not editable")
    guards.gate_employee_not_separated(employee)

    # LINK 1 - the week's own accounting
    changes = recompute.week_accounting(week, employee, team)
    changes["status"] = "FINALIZED"
    changes["finalized_at"] = clock.now_iso()
    db.apply_changes(week, changes)
    # LINK 2..LINK 6
    recompute.settle_employee(employee)
    return guards.single("attendance_week", week)


@bp.route("/attendance-weeks/<week_id>/amend", methods=["POST"])
def amend_week(week_id):
    middleware.authorize((HR_BUSINESS_PARTNER,))
    week = middleware.must_exist("attendance_week", week_id)
    employee = db.get("employee", week["employee_id"])
    cycle = recompute.cycle_of_employee(employee)

    payload = middleware.body()
    reason = middleware.req_string(payload, "amendment_reason", 1, None)

    guards.gate_cycle_not_locked(cycle)
    if week["status"] != "FINALIZED":
        fail("ERR_WEEK_NOT_FINALIZED", "attendance week is not FINALIZED")

    db.apply_changes(week, {
        "status": "AMENDED",
        "amendment_reason": reason,
        "credited_days": 0,
        "relief_days_credited": 0,
        "shortfall_days": 0,
    })
    recompute.settle_employee(employee, allow_case_open=False)
    return guards.single("attendance_week", week)


@bp.route("/compliance-signals/<signal_id>", methods=["GET"])
def get_signal(signal_id):
    middleware.authorize(READ_ROLES)
    row = middleware.must_exist("compliance_signal", signal_id)
    return guards.single("compliance_signal", row)


@bp.route("/compliance-signals", methods=["GET"])
def list_signals():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("compliance_signal")
    for arg in ("attendance_week_id", "signal_source"):
        value = middleware.filter_arg(arg)
        if value is not None:
            rows = [r for r in rows if r[arg] == value]
    return guards.paged("compliance_signal", rows,
                        sort_key=lambda s: (s["observed_date"], db.seq_key(s)))
