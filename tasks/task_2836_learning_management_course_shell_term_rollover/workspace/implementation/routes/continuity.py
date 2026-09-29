"""Continuity windows -- PRD 3.9."""

from flask import Blueprint

import lookup
from db import db, mark, new_record, now, set_field
from errors import require
from middleware import (INSTRUCTOR, LMS_ADMIN, REGISTRAR, as_dt, as_enum,
                        as_int, as_str, bad, body)
from routes.common import apply_filters, created, guard, listing, ok
from services import compute

bp = Blueprint("continuity", __name__)

KINDS = ("OUTAGE", "EXTENSION", "MAINTENANCE")
ACTIONS = ("CLOSE", "CANCEL")
OPEN_TERM_STATES = ("IN_SESSION", "FINALS", "GRADING")
MAX_CONCURRENT_OUTAGES = 2


def open_windows_of(term_id):
    return [w for w in db.windows.values()
            if w["term_id"] == term_id and w["window_state"] == "OPEN"]


def half_open_overlap(a_start, a_end, b_start, b_end):
    """Includes the start, excludes the end: two windows that merely touch do
    not collide (PRD 3.9)."""
    return a_start < b_end and b_start < a_end


def closed_overlap(a_start, a_end, b_start, b_end):
    """Includes both endpoints, so windows that touch do share that instant."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/continuity-windows")
def open_window():
    guard(LMS_ADMIN)
    payload = body()
    term = lookup.fk(payload, "term_id", "terms")
    shell = lookup.fk(payload, "shell_id", "shells")
    if term is None:
        as_str(payload, "term_id", required=True)
    kind = as_enum(payload, "kind", KINDS, required=True)
    window_start = as_dt(payload, "window_start", required=True)
    window_end = as_dt(payload, "window_end", required=True)
    expected = as_int(payload, "expected_term_version", required=True)
    if window_end <= window_start:
        bad("window_end", "must be strictly after window_start")

    require(term["lifecycle_state"] in OPEN_TERM_STATES,
            "ERR_INVALID_STATE_TRANSITION",
            "A term in %s does not accept a continuity window."
            % term["lifecycle_state"])
    require(expected == term["version"], "ERR_STALE_VERSION",
            "The term has moved on to version %d." % term["version"])

    if shell is not None:
        clash = [w for w in open_windows_of(term["id"])
                 if w["shell_id"] == shell["id"] and w["kind"] == kind
                 and half_open_overlap(window_start, window_end,
                                       w["window_start"], w["window_end"])]
        require(not clash, "ERR_WINDOW_OVERLAP",
                "Another open window of this shell and kind covers that interval.")
    if kind == "OUTAGE":
        sharing = [w for w in open_windows_of(term["id"])
                   if w["kind"] == "OUTAGE"
                   and closed_overlap(window_start, window_end,
                                      w["window_start"], w["window_end"])]
        require(len(sharing) < MAX_CONCURRENT_OUTAGES,
                "ERR_CONTINUITY_CAP_EXCEEDED",
                "At most two open outage windows of a term may cover one instant.")

    if shell is not None:
        affected = shell["active_enrollment_count"]
    else:
        affected = term["total_active_enrollments"]
    granted = 0
    if kind == "EXTENSION":
        granted = int(compute.extension_days(window_start, window_end))

    window = new_record(
        _kind="window",
        term_id=term["id"],
        shell_id=shell["id"] if shell is not None else None,
        kind=kind,
        window_start=window_start,
        window_end=window_end,
        window_state="OPEN",
        affected_enrollment_count=affected,
        extension_days_granted=granted,
        closed_at=None,
    )
    db.windows[window["id"]] = window
    # Opening a window increments the term's version (PRD 3.9).
    mark(term)
    return created(window)


@bp.get("/continuity-windows")
def list_windows():
    guard(LMS_ADMIN, REGISTRAR, INSTRUCTOR)
    records = apply_filters(db.windows.values(), {
        "term_id": "term_id",
        "shell_id": "shell_id",
        "kind": "kind",
        "window_state": "window_state",
    })
    return listing(records)


@bp.get("/continuity-windows/<window_id>")
def read_window(window_id):
    guard(LMS_ADMIN, REGISTRAR, INSTRUCTOR)
    return ok(lookup.window(window_id))


@bp.post("/continuity-windows/<window_id>/transitions")
def drive_window(window_id):
    guard(LMS_ADMIN)
    window = lookup.window(window_id)
    payload = body()
    action = as_str(payload, "action", required=True)
    require(action in ACTIONS, "ERR_INVALID_STATE_TRANSITION",
            "'%s' is not a declared window action." % action)
    state = window["window_state"]
    require(state == "OPEN", "ERR_INVALID_STATE_TRANSITION",
            "%s runs from OPEN, not from %s." % (action, state))

    if action == "CLOSE":
        set_field(window, "window_state", "CLOSED")
        set_field(window, "closed_at", now())
        mark(window)
        return ok(window)

    require(now() < window["window_start"], "ERR_WINDOW_ALREADY_STARTED",
            "This window has already begun affecting students.")
    set_field(window, "window_state", "CANCELLED")
    set_field(window, "affected_enrollment_count", 0)
    set_field(window, "extension_days_granted", 0)
    mark(window)
    return ok(window)
