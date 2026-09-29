"""ExceptionRequest routes: the interactive process, adjudication and revocation."""
from flask import Blueprint

import clock
import db
import guards
import middleware
import recompute
from errors import fail
from middleware import (ACCOMMODATION_SPECIALIST, ALL_ROLES, EMPLOYEE,
                        HR_BUSINESS_PARTNER, PEOPLE_MANAGER)

bp = Blueprint("exceptions", __name__)

READ_ROLES = tuple(r for r in ALL_ROLES if r != EMPLOYEE)
CATEGORIES = ("MEDICAL", "CAREGIVING", "DISABILITY_ACCOMMODATION")
LIVE_STATUSES = ("SUBMITTED", "INFO_REQUESTED", "APPROVED")
INTERACTIVE_CATEGORIES = ("MEDICAL", "DISABILITY_ACCOMMODATION")


def _overlaps(start_a, end_a, start_b, end_b):
    return start_a <= end_b and start_b <= end_a


def _window(request):
    return clock.parse_date(request["start_date"]), clock.parse_date(request["end_date"])


@bp.route("/exception-requests", methods=["POST"])
def create_request():
    actor = middleware.authorize((EMPLOYEE, PEOPLE_MANAGER, HR_BUSINESS_PARTNER))
    payload = middleware.body()
    employee_id = middleware.req_present(payload, "employee_id")
    employee = middleware.must_exist("employee", employee_id)
    guards.require_owner(actor, employee["id"])
    cycle = recompute.cycle_of_employee(employee)

    category = middleware.req_enum(payload, "category", CATEGORIES)
    requested_days = middleware.req_int(payload, "requested_relief_days", 1, 5)
    start_date = middleware.req_date(payload, "start_date")
    end_date = middleware.req_date(payload, "end_date")
    rationale = middleware.req_string(payload, "rationale", 1, 1000)
    if end_date < start_date:
        fail("ERR_INVALID_INTERVAL", "end_date must not fall before start_date")

    guards.gate_cycle_not_locked(cycle)
    guards.gate_employee_active(employee)

    for existing in db.find("exception_request", employee_id=employee["id"]):
        if existing["category"] != category or existing["status"] not in LIVE_STATUSES:
            continue
        other_start, other_end = _window(existing)
        if _overlaps(start_date, end_date, other_start, other_end):
            fail("ERR_EXCEPTION_WINDOW_OVERLAP",
                 "a live request of this category already covers an overlapping window")

    interactive = (category in INTERACTIVE_CATEGORIES
                   or bool(employee["disability_accommodation_on_file"]))
    row = db.insert("exception_request", {
        "employee_id": employee["id"],
        "category": category,
        "requested_relief_days": requested_days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "rationale": rationale,
        "status": "SUBMITTED",
        "interactive_process_required": interactive,
        "granted_relief_days": 0,
        "info_needed": None,
        "response_note": None,
        "info_round_count": 0,
        "adjudicated_by_user_id": None,
        "closure_reason": None,
    })
    return guards.single("exception_request", row, 201)


@bp.route("/exception-requests/<request_id>/request-info", methods=["POST"])
def request_info(request_id):
    actor = middleware.authorize((ACCOMMODATION_SPECIALIST, HR_BUSINESS_PARTNER))
    row = middleware.must_exist("exception_request", request_id)
    payload = middleware.body()
    info_needed = middleware.req_string(payload, "info_needed", 1, None)

    if row["status"] != "SUBMITTED":
        fail("ERR_REQUEST_NOT_SUBMITTED", "exception request is not SUBMITTED")
    if row["interactive_process_required"] and actor.role != ACCOMMODATION_SPECIALIST:
        fail("ERR_ACCOMMODATION_SPECIALIST_REQUIRED",
             "only an AccommodationSpecialist may open an information round on this request")

    db.apply_changes(row, {"status": "INFO_REQUESTED", "info_needed": info_needed})
    return guards.single("exception_request", row)


@bp.route("/exception-requests/<request_id>/respond", methods=["POST"])
def respond(request_id):
    actor = middleware.authorize((EMPLOYEE, PEOPLE_MANAGER, HR_BUSINESS_PARTNER))
    row = middleware.must_exist("exception_request", request_id)
    guards.require_owner(actor, row["employee_id"])
    payload = middleware.body()
    note = middleware.req_string(payload, "response_note", 1, None)

    if row["status"] != "INFO_REQUESTED":
        fail("ERR_REQUEST_NOT_INFO_REQUESTED", "exception request is not INFO_REQUESTED")

    db.apply_changes(row, {
        "status": "SUBMITTED",
        "response_note": note,
        "info_round_count": row["info_round_count"] + 1,
    })
    return guards.single("exception_request", row)


@bp.route("/exception-requests/<request_id>/adjudicate", methods=["POST"])
def adjudicate(request_id):
    actor = middleware.authorize((ACCOMMODATION_SPECIALIST, HR_BUSINESS_PARTNER))
    row = middleware.must_exist("exception_request", request_id)
    employee = db.get("employee", row["employee_id"])

    payload = middleware.body()
    decision = middleware.req_enum(payload, "decision", ("APPROVE", "DENY", "WITHDRAW"))
    granted = None
    if decision == "APPROVE":
        granted = middleware.req_int(payload, "granted_relief_days", 0)
    closure_reason = middleware.opt_string(payload, "closure_reason", 1, None)

    if row["status"] not in ("SUBMITTED", "INFO_REQUESTED"):
        fail("ERR_REQUEST_NOT_SUBMITTED", "exception request is not live")
    if decision in ("APPROVE", "DENY") and row["status"] != "SUBMITTED":
        fail("ERR_REQUEST_NOT_SUBMITTED", "exception request is not SUBMITTED")

    if row["interactive_process_required"] and actor.role != ACCOMMODATION_SPECIALIST:
        fail("ERR_ACCOMMODATION_SPECIALIST_REQUIRED",
             "only an AccommodationSpecialist may adjudicate this request")
    if (decision == "APPROVE" and row["interactive_process_required"]
            and row["info_round_count"] == 0):
        fail("ERR_INTERACTIVE_PROCESS_PENDING",
             "at least one information round must complete before approval")

    start_date, end_date = _window(row)
    if decision == "APPROVE":
        for existing in db.find("exception_request", employee_id=row["employee_id"],
                                status="APPROVED"):
            if existing["id"] == row["id"] or existing["category"] != row["category"]:
                continue
            other_start, other_end = _window(existing)
            if _overlaps(start_date, end_date, other_start, other_end):
                fail("ERR_EXCEPTION_WINDOW_OVERLAP",
                     "an approved request of this category already covers an overlapping window")
        if granted > row["requested_relief_days"]:
            fail("ERR_RELIEF_EXCEEDS_REQUEST",
                 "granted_relief_days may not exceed requested_relief_days")

    if decision == "DENY":
        changes = {"status": "DENIED", "adjudicated_by_user_id": actor.user_id}
        if closure_reason is not None:
            changes["closure_reason"] = closure_reason
        db.apply_changes(row, changes)
    elif decision == "WITHDRAW":
        changes = {"status": "WITHDRAWN"}
        if closure_reason is not None:
            changes["closure_reason"] = closure_reason
        db.apply_changes(row, changes)
    else:
        changes = {
            "status": "APPROVED",
            "granted_relief_days": granted,
            "adjudicated_by_user_id": actor.user_id,
        }
        if closure_reason is not None:
            changes["closure_reason"] = closure_reason
        db.apply_changes(row, changes)
        recompute.recompute_relief_for_settled_weeks(employee, start_date, end_date)
        recompute.settle_employee(employee)
    return guards.single("exception_request", row)


@bp.route("/exception-requests/<request_id>/revoke", methods=["POST"])
def revoke(request_id):
    actor = middleware.authorize((ACCOMMODATION_SPECIALIST, HR_BUSINESS_PARTNER))
    row = middleware.must_exist("exception_request", request_id)
    employee = db.get("employee", row["employee_id"])
    payload = middleware.body()
    closure_reason = middleware.req_string(payload, "closure_reason", 1, None)

    if row["status"] != "APPROVED":
        fail("ERR_EXCEPTION_NOT_APPROVED", "exception request is not APPROVED")

    start_date, end_date = _window(row)
    db.apply_changes(row, {
        "status": "REVOKED",
        "granted_relief_days": 0,
        "closure_reason": closure_reason,
    })
    recompute.recompute_relief_for_settled_weeks(employee, start_date, end_date)
    recompute.settle_employee(employee)
    return guards.single("exception_request", row)


@bp.route("/exception-requests/<request_id>", methods=["GET"])
def get_request(request_id):
    actor = middleware.authorize(ALL_ROLES)
    row = middleware.must_exist("exception_request", request_id)
    guards.require_owner(actor, row["employee_id"])
    return guards.single("exception_request", row)


@bp.route("/exception-requests", methods=["GET"])
def list_requests():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("exception_request")
    for arg in ("employee_id", "status", "category"):
        value = middleware.filter_arg(arg)
        if value is not None:
            rows = [r for r in rows if r[arg] == value]
    return guards.paged("exception_request", rows)
