"""Supervision case endpoints — PRD section 3.3."""

from flask import Blueprint

from cascades import conflict_future_shifts, restore_conflicted_shifts
from common import list_result, match_filters, READ_ROLES, resolve
from domain import SUPERVISION_TYPES, WORK_AUTH_DECISIONS, rows, sync_participant
from envelope import created, ok
from errors import fail
from store import db, new_row, public, touch
from validation import (
    body, caller_id, opt_date, opt_int, opt_str, present, req_enum, req_str,
    require_roles,
)

bp = Blueprint("supervision", __name__)

OFFICER = ["SupervisionOfficer"]
CASE_STATUS_TARGETS = ["ACTIVE", "DISCHARGED", "REVOKED"]
CASE_EDGES = {
    ("PENDING_CONTACT", "ACTIVE"),
    ("ACTIVE", "DISCHARGED"),
    ("ACTIVE", "REVOKED"),
}
AUTH_EDGES = {
    ("NOT_REQUESTED", "APPROVED"),
    ("NOT_REQUESTED", "DENIED"),
    ("APPROVED", "SUSPENDED"),
    ("SUSPENDED", "APPROVED"),
}


def _require_officer(case):
    if caller_id() != case["officer_user_id"]:
        fail("ERR_NOT_CASE_OFFICER",
             "Only the case's own supervision officer may drive this case")


@bp.post("/supervision-cases")
def create_case():
    require_roles(OFFICER)
    payload = body()
    participant_id = req_str(payload, "participant_id")
    officer_user_id = req_str(payload, "officer_user_id")
    officer_name = req_str(payload, "officer_name")
    supervision_type = req_enum(payload, "supervision_type", SUPERVISION_TYPES)
    opt_date(payload, "expected_discharge_date")

    if participant_id not in db.participants:
        fail("ERR_PARTICIPANT_NOT_FOUND", "participant_id matches no participant")

    row = new_row(
        participant_id=participant_id,
        officer_user_id=officer_user_id,
        officer_name=officer_name,
        supervision_type=supervision_type,
        expected_discharge_date=payload.get("expected_discharge_date"),
        status="PENDING_CONTACT",
        work_authorization_status="NOT_REQUESTED",
        authorization_change_count=0,
        approved_window_start_minute=None,
        approved_window_end_minute=None,
    )
    db.supervision_cases[row["id"]] = row
    return created(public(row))


@bp.get("/supervision-cases/<case_id>")
def read_case(case_id):
    require_roles(READ_ROLES)
    case = resolve("supervision_cases", db.supervision_cases, case_id)
    return ok(public(case))


@bp.get("/supervision-cases")
def list_cases():
    require_roles(READ_ROLES)
    result = match_filters(
        rows(db.supervision_cases),
        string_filters=["participant_id", "status", "work_authorization_status",
                        "officer_user_id"],
    )
    return list_result(result)


@bp.post("/supervision-cases/<case_id>/status")
def drive_case_status(case_id):
    require_roles(OFFICER)
    payload = body()
    to_status = req_enum(payload, "to_status", CASE_STATUS_TARGETS)

    case = resolve("supervision_cases", db.supervision_cases, case_id)
    _require_officer(case)
    if (case["status"], to_status) not in CASE_EDGES:
        fail("ERR_SUPERVISION_CASE_INVALID_STATE",
             "That supervision-case transition is not declared")

    case["status"] = to_status
    if to_status == "REVOKED":
        if case["work_authorization_status"] == "APPROVED":
            case["work_authorization_status"] = "SUSPENDED"
        touch(case)
        conflict_future_shifts(case["participant_id"], "SUPERVISION_REVOKED")
    else:
        touch(case)
    return ok(public(case))


@bp.post("/supervision-cases/<case_id>/work-authorization")
def drive_work_authorization(case_id):
    require_roles(OFFICER)
    payload = body()
    decision = req_enum(payload, "decision", WORK_AUTH_DECISIONS)
    if present(payload, "approved_window_start_minute"):
        opt_int(payload, "approved_window_start_minute")
    if present(payload, "approved_window_end_minute"):
        opt_int(payload, "approved_window_end_minute")

    case = resolve("supervision_cases", db.supervision_cases, case_id)
    _require_officer(case)
    if case["status"] != "ACTIVE":
        fail("ERR_SUPERVISION_CASE_INVALID_STATE",
             "Work authorisation may only be driven on an ACTIVE case")
    current = case["work_authorization_status"]
    if (current, decision) not in AUTH_EDGES:
        fail("ERR_SUPERVISION_CASE_INVALID_STATE",
             "That work-authorisation decision is not declared")

    if decision == "APPROVED":
        start = payload.get("approved_window_start_minute")
        end = payload.get("approved_window_end_minute")
        if start is None or end is None:
            fail("ERR_VALIDATION",
                 "An approval must carry both approved window minutes")
        if start < 0 or start > 1440 or end < 0 or end > 1440:
            fail("ERR_VALIDATION",
                 "Window minutes must fall between 0 and 1440 inclusive")
        if end <= start:
            fail("ERR_VALIDATION",
                 "approved_window_end_minute must exceed the start minute")
        case["approved_window_start_minute"] = start
        case["approved_window_end_minute"] = end

    case["work_authorization_status"] = decision
    case["authorization_change_count"] = int(
        case["authorization_change_count"]) + 1
    touch(case)

    if decision == "SUSPENDED":
        conflict_future_shifts(case["participant_id"],
                               "WORK_AUTHORIZATION_SUSPENDED")
    elif decision == "APPROVED" and current == "SUSPENDED":
        restore_conflicted_shifts(case["participant_id"], case)
    else:
        participant = db.participants.get(case["participant_id"])
        if participant is not None:
            sync_participant(participant)
    return ok(public(case))
