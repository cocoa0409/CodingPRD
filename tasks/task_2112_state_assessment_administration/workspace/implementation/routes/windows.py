"""Test windows: creation, lifecycle transitions and the family report
distribution pass (PRD 3.2, 3.8, 3.9)."""

from flask import Blueprint, request

import serialize
from cascades import cancel_session
from db import create, db, now, ordered, touch
from derive import (
    MAKEUP_EXTENSION_DAYS,
    lots_of_window,
    participation_final,
    participation_provisional,
    registrations_of_window,
    sessions_of_window,
)
from errors import api_error
from middleware import ALL_ROLES, STATE_OFFICER, endpoint, json_body, resolve
from response import object_response, paginate
from timeutil import plus_days
from validators import (
    datetime_field,
    enum_field,
    integer_field,
    number_field,
    optional_text,
    string_field,
)

bp = Blueprint("windows", __name__)

SUBJECTS = {"ELA", "MATH", "SCIENCE", "SOCIAL_STUDIES"}
GRADE_BANDS = {"G3_5", "G6_8", "G9_12"}
WINDOW_STATUSES = {"PLANNED", "OPEN", "MAKEUP", "SCORING", "RELEASED", "FINALIZED", "CANCELLED"}

DECLARED_EDGES = {
    ("PLANNED", "OPEN"),
    ("OPEN", "PLANNED"),
    ("OPEN", "MAKEUP"),
    ("MAKEUP", "SCORING"),
    ("SCORING", "MAKEUP"),
    ("SCORING", "RELEASED"),
    ("RELEASED", "FINALIZED"),
    ("PLANNED", "CANCELLED"),
}

DEFAULT_APPEAL_WINDOW_DAYS = 10
DEFAULT_MIN_PARTICIPATION_PCT = 95.0


@bp.post("/test-windows")
@endpoint(STATE_OFFICER)
def create_window(actor):
    body = json_body()
    name = string_field(body, "name", min_length=1, max_length=120)
    subject = enum_field(body, "subject", SUBJECTS)
    grade_band = enum_field(body, "grade_band", GRADE_BANDS)
    window_start = datetime_field(body, "window_start")
    window_end = datetime_field(body, "window_end")
    makeup_start = datetime_field(body, "makeup_start")
    makeup_end = datetime_field(body, "makeup_end")
    appeal_window_days = integer_field(
        body, "appeal_window_days", required=False, minimum=1, maximum=45,
        default=DEFAULT_APPEAL_WINDOW_DAYS,
    )
    min_participation_pct = number_field(
        body, "min_participation_pct", required=False, minimum=0.0, maximum=100.0,
        default=DEFAULT_MIN_PARTICIPATION_PCT,
    )

    if not window_end > window_start:
        raise api_error("ERR_INVALID_REQUEST", "window_end must fall strictly after window_start.")
    if not makeup_start >= window_end:
        raise api_error("ERR_INVALID_REQUEST", "makeup_start must fall at or after window_end.")
    if not makeup_end > makeup_start:
        raise api_error("ERR_INVALID_REQUEST", "makeup_end must fall strictly after makeup_start.")

    window = create(
        db.windows,
        {
            "name": name,
            "subject": subject,
            "grade_band": grade_band,
            "window_start": window_start,
            "window_end": window_end,
            "makeup_start": makeup_start,
            "makeup_end": makeup_end,
            "appeal_window_days": appeal_window_days,
            "min_participation_pct": min_participation_pct,
            "status": "PLANNED",
            "released_at": None,
            "appeal_window_closes_at": None,
            "participation_rate_provisional_pct": None,
            "participation_rate_final_pct": None,
            "registered_distinct_count": 0,
            "present_distinct_count": 0,
            "open_breach_count": 0,
            "security_hold": False,
        },
    )
    return object_response(serialize.window(window), 201)


@bp.get("/test-windows/<window_id>")
@endpoint(*ALL_ROLES)
def read_window(actor, window_id):
    window = resolve(db.windows, window_id, "ERR_TEST_WINDOW_NOT_FOUND")
    return object_response(serialize.window(window))


@bp.get("/test-windows")
@endpoint(*ALL_ROLES)
def list_windows(actor):
    subject = request.args.get("subject")
    grade_band = request.args.get("grade_band")
    status = request.args.get("status")
    items = [
        window
        for window in db.windows.values()
        if (subject is None or window["subject"] == subject)
        and (grade_band is None or window["grade_band"] == grade_band)
        and (status is None or window["status"] == status)
    ]
    return paginate(ordered(items), serialize.window)


# --------------------------------------------------------------------------
# Lifecycle transitions
# --------------------------------------------------------------------------
@bp.post("/test-windows/<window_id>/transitions")
@endpoint(STATE_OFFICER)
def transition_window(actor, window_id):
    window = resolve(db.windows, window_id, "ERR_TEST_WINDOW_NOT_FOUND")
    body = json_body()
    to_status = enum_field(body, "to_status", WINDOW_STATUSES)
    optional_text(body, "reason")

    current = window["status"]
    if (current, to_status) not in DECLARED_EDGES:
        raise api_error("ERR_INVALID_STATE_TRANSITION")

    handler = _HANDLERS[(current, to_status)]
    handler(window)
    return object_response(serialize.window(window))


def _open_window(window):
    # Check 19 — the initial period must not already have elapsed.
    if not now() < window["window_end"]:
        raise api_error("ERR_TIMING_PRECONDITION_NOT_MET")
    # No numbered check owns this one; its fallback error is the generic
    # ERR_INVALID_STATE_TRANSITION, screened after the numbered checks.
    if not lots_of_window(window["id"]):
        raise api_error(
            "ERR_INVALID_STATE_TRANSITION",
            "no material lot has been shipped for this window.",
        )
    window["status"] = "OPEN"
    touch(window)


def _revert_window(window):
    sessions = sessions_of_window(window["id"])
    if any(session["status"] in ("ACTIVE", "CLOSED", "INVALIDATED") for session in sessions):
        raise api_error(
            "ERR_INVALID_STATE_TRANSITION",
            "a session in this window has already opened.",
        )
    window["status"] = "PLANNED"
    touch(window)
    for session in sessions:
        if session["status"] in ("DRAFT", "SCHEDULED"):
            cancel_session(session)


def _to_makeup(window):
    if not now() >= window["window_end"]:
        raise api_error("ERR_TIMING_PRECONDITION_NOT_MET")
    if any(session["status"] == "ACTIVE" for session in sessions_of_window(window["id"])):
        raise api_error("ERR_INVALID_STATE_TRANSITION", "a session in this window is still active.")
    window["status"] = "MAKEUP"
    touch(window)


def _to_scoring(window):
    if not now() >= window["makeup_end"]:
        raise api_error("ERR_TIMING_PRECONDITION_NOT_MET")
    sessions = sessions_of_window(window["id"])
    if any(session["status"] not in ("CLOSED", "CANCELLED", "INVALIDATED") for session in sessions):
        raise api_error(
            "ERR_INVALID_STATE_TRANSITION",
            "every session must be closed, cancelled or invalidated.",
        )
    if any(lot["status"] not in ("RECONCILED", "DISCREPANT") for lot in lots_of_window(window["id"])):
        raise api_error(
            "ERR_INVALID_STATE_TRANSITION",
            "every material lot must be reconciled or discrepant.",
        )
    rate, denominator, numerator = participation_provisional(window)
    window["status"] = "SCORING"
    window["participation_rate_provisional_pct"] = rate
    window["registered_distinct_count"] = denominator
    window["present_distinct_count"] = numerator
    touch(window)


def _reopen_makeup(window):
    provisional = window["participation_rate_provisional_pct"]
    if provisional is None or not provisional < window["min_participation_pct"]:
        raise api_error(
            "ERR_INVALID_STATE_TRANSITION",
            "provisional participation is not below the window minimum.",
        )
    window["status"] = "MAKEUP"
    window["makeup_end"] = plus_days(window["makeup_end"], MAKEUP_EXTENSION_DAYS)
    window["participation_rate_provisional_pct"] = None
    touch(window)


def _release_window(window):
    registrations = registrations_of_window(window["id"])
    # Check 26 is screened before check 27: a window that is simultaneously
    # short on participation and under a security hold reports participation.
    provisional = window["participation_rate_provisional_pct"]
    if provisional is None or provisional < window["min_participation_pct"]:
        raise api_error("ERR_PARTICIPATION_BELOW_MINIMUM")
    if window["security_hold"]:
        raise api_error("ERR_SECURITY_HOLD_ACTIVE")
    for registration in registrations:
        if registration["attendance_status"] == "PRESENT" and registration["score_status"] not in (
            "SCORED",
            "INVALIDATED",
        ):
            raise api_error(
                "ERR_INVALID_STATE_TRANSITION",
                "a present student has no recorded outcome.",
            )

    released_at = now()
    window["status"] = "RELEASED"
    window["released_at"] = released_at
    window["appeal_window_closes_at"] = plus_days(released_at, window["appeal_window_days"])
    touch(window)
    for registration in registrations:
        if registration["score_status"] == "SCORED":
            registration["score_status"] = "RELEASED"
            touch(registration)


def _finalize_window(window):
    registrations = registrations_of_window(window["id"])
    registration_ids = {registration["id"] for registration in registrations}
    # Check 19 first, then the un-numbered cross-aggregate preconditions.
    if not now() >= window["appeal_window_closes_at"]:
        raise api_error("ERR_TIMING_PRECONDITION_NOT_MET")
    for appeal in db.appeals.values():
        if appeal["status"] == "FILED" and appeal["registration_id"] in registration_ids:
            raise api_error("ERR_INVALID_STATE_TRANSITION", "a score appeal is still open.")
    from derive import OPEN_BREACH_STATUSES, window_of_report

    for report in db.reports.values():
        if report["status"] not in OPEN_BREACH_STATUSES:
            continue
        scoped = window_of_report(report)
        if scoped is not None and scoped["id"] == window["id"]:
            raise api_error("ERR_INVALID_STATE_TRANSITION", "an irregularity report is still open.")

    # Order is pinned: flip the scores first, then count participation.
    for registration in registrations:
        if registration["score_status"] in ("RELEASED", "CORRECTED"):
            registration["score_status"] = "FINAL"
            touch(registration)
    rate, denominator, numerator = participation_final(window)
    window["participation_rate_final_pct"] = rate
    window["registered_distinct_count"] = denominator
    window["present_distinct_count"] = numerator
    window["status"] = "FINALIZED"
    touch(window)


def _cancel_window(window):
    if sessions_of_window(window["id"]):
        raise api_error("ERR_INVALID_STATE_TRANSITION", "the window already holds sessions.")
    window["status"] = "CANCELLED"
    touch(window)


_HANDLERS = {
    ("PLANNED", "OPEN"): _open_window,
    ("OPEN", "PLANNED"): _revert_window,
    ("OPEN", "MAKEUP"): _to_makeup,
    ("MAKEUP", "SCORING"): _to_scoring,
    ("SCORING", "MAKEUP"): _reopen_makeup,
    ("SCORING", "RELEASED"): _release_window,
    ("RELEASED", "FINALIZED"): _finalize_window,
    ("PLANNED", "CANCELLED"): _cancel_window,
}


# --------------------------------------------------------------------------
# Family score report distribution (PRD 3.9)
# --------------------------------------------------------------------------
@bp.post("/test-windows/<window_id>/report-distribution-runs")
@endpoint(STATE_OFFICER)
def run_report_distribution(actor, window_id):
    window = resolve(db.windows, window_id, "ERR_TEST_WINDOW_NOT_FOUND")
    if window["status"] != "RELEASED":
        raise api_error("ERR_WINDOW_PHASE_INVALID")

    distributed = 0
    suppressed = 0
    skipped = 0
    for registration in ordered(registrations_of_window(window["id"])):
        if registration["report_delivery_status"] != "NOT_QUEUED":
            skipped += 1
            continue
        score_status = registration["score_status"]
        if score_status == "INVALIDATED":
            registration["report_delivery_status"] = "SUPPRESSED"
            registration["report_suppressed_reason"] = "INVALIDATED"
            suppressed += 1
            touch(registration)
        elif score_status == "UNDER_APPEAL":
            registration["report_delivery_status"] = "SUPPRESSED"
            registration["report_suppressed_reason"] = "UNDER_APPEAL"
            suppressed += 1
            touch(registration)
        elif score_status in ("RELEASED", "CORRECTED"):
            guardian_email = registration.get("guardian_email")
            if guardian_email is None or guardian_email == "":
                registration["report_delivery_status"] = "SUPPRESSED"
                registration["report_suppressed_reason"] = "MISSING_GUARDIAN_EMAIL"
                suppressed += 1
            else:
                registration["report_delivery_status"] = "DELIVERED"
                registration["report_delivered_at"] = now()
                distributed += 1
            touch(registration)
        else:
            skipped += 1

    payload = {
        "window_id": window["id"],
        "distributed_count": distributed,
        "suppressed_count": suppressed,
        "skipped_count": skipped,
    }
    return object_response(payload)
