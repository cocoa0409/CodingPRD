"""Enrollments, seats and the waitlist -- PRD 3.4."""

from decimal import Decimal

from flask import Blueprint

import lookup
from db import db, mark, new_record, now, set_field
from errors import require
from middleware import (INSTRUCTOR, LMS_ADMIN, REGISTRAR, STUDENT, as_enum,
                        as_str, bad, body)
from routes.common import apply_filters, arg, created, guard, listing, ok
from services import access, compute

bp = Blueprint("enrollments", __name__)

LMS_ROLES = ("STUDENT", "TEACHER", "TA", "DESIGNER", "OBSERVER")
REQUESTED_STATES = ("ACTIVE", "WAITLISTED")
ACTIONS = ("DROP", "REINSTATE", "PROMOTE", "COMPLETE")
LIVE_SHELL = ("PROVISIONED", "PUBLISHED")
BLOCKING_PAIR_STATES = ("ACTIVE", "WAITLISTED", "DROPPED")
ZERO = Decimal("0.00")


def shell_allows(shell, states=LIVE_SHELL):
    require(shell["provisioning_state"] in states,
            "ERR_SHELL_STATE_BLOCKS_ENROLLMENT",
            "A shell in %s does not accept this operation."
            % shell["provisioning_state"])


def pair_rows(shell_id, person_id):
    return [e for e in db.enrollments.values()
            if e["shell_id"] == shell_id and e["person_id"] == person_id]


def new_enrollment(shell, person, lms_role, state, batch_id=None):
    """Creates the row and applies the per-event seat deltas of PRD 2.8."""
    position = None
    if state == "WAITLISTED":
        position = shell["waitlisted_enrollment_count"] + 1
    row = new_record(
        _kind="enrollment",
        shell_id=shell["id"],
        person_id=person["id"],
        batch_id=batch_id,
        merged_from_shell_id=None,
        role=lms_role,
        enrollment_state=state,
        waitlist_position=position,
        earned_points_total=ZERO,
        graded_points_possible=ZERO,
        provisional_grade_pct=ZERO,
        final_grade_pct=None,
        dropped_at=None,
        reinstatement_count=0,
        disputed_points_held=ZERO,
    )
    db.enrollments[row["id"]] = row
    return row


@bp.post("/enrollments")
def create_enrollment():
    guard(REGISTRAR)
    payload = body()
    shell = lookup.fk(payload, "shell_id", "shells")
    person = lookup.fk(payload, "person_id", "people")
    if shell is None:
        as_str(payload, "shell_id", required=True)
    if person is None:
        as_str(payload, "person_id", required=True)
    lms_role = as_enum(payload, "role", LMS_ROLES, required=True)
    requested = as_enum(payload, "requested_state", REQUESTED_STATES,
                        default="ACTIVE")
    if requested == "WAITLISTED" and lms_role != "STUDENT":
        bad("requested_state", "may only be WAITLISTED for a STUDENT role")

    term = db.terms[shell["term_id"]]
    shell_allows(shell)
    if shell["shell_type"] in ("SANDBOX", "DEV") and lms_role == "STUDENT":
        require(False, "ERR_SANDBOX_NOT_PUBLISHABLE",
                "A sandbox or dev shell can never carry a STUDENT enrollment.")
    existing = [e for e in pair_rows(shell["id"], person["id"])
                if e["enrollment_state"] in BLOCKING_PAIR_STATES]
    require(not existing, "ERR_ROLE_CONFLICT",
            "This person already holds a live enrollment in this shell.")
    if lms_role == "STUDENT":
        require(shell["owner_person_id"] != person["id"], "ERR_ROLE_CONFLICT",
                "A shell owner may not hold a STUDENT enrollment in their own shell.")
        if requested == "ACTIVE":
            cap = compute.frozen_seat_cap(shell, term)
            require(len(compute.active_rows(shell["id"])) < cap,
                    "ERR_SEAT_CAP_EXCEEDED",
                    "No seat is open under the shell's effective capacity.")

    row = new_enrollment(shell, person, lms_role, requested)
    compute.run_capacity(shell, term, promote=False)
    return created(row)


@bp.get("/enrollments")
def list_enrollments():
    guard(REGISTRAR, LMS_ADMIN, INSTRUCTOR, STUDENT)
    from middleware import actor, role
    if role() == STUDENT:
        require(arg("person_id") == actor(), "ERR_NOT_RESOURCE_OWNER",
                "A student may only filter to their own person_id.")
    records = apply_filters(db.enrollments.values(), {
        "shell_id": "shell_id",
        "person_id": "person_id",
        "batch_id": "batch_id",
        "merged_from_shell_id": "merged_from_shell_id",
        "role": "role",
        "enrollment_state": "enrollment_state",
    })
    if role() == STUDENT:
        seen = set()
        for row in records:
            shell = db.shells.get(row["shell_id"])
            if shell is not None and shell["term_id"] not in seen:
                seen.add(shell["term_id"])
                access.student_gate(db.terms.get(shell["term_id"]))
        access.student_gate(None)
    return listing(records)


@bp.get("/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    guard(REGISTRAR, LMS_ADMIN, INSTRUCTOR, STUDENT)
    return ok(lookup.enrollment(enrollment_id))


@bp.post("/enrollments/<enrollment_id>/transitions")
def drive_enrollment(enrollment_id):
    guard(REGISTRAR)
    row = lookup.enrollment(enrollment_id)
    payload = body()
    action = as_str(payload, "action", required=True)
    require(action in ACTIONS, "ERR_INVALID_STATE_TRANSITION",
            "'%s' is not a declared enrollment action." % action)
    reason = as_str(payload, "reason")
    shell = db.shells[row["shell_id"]]
    term = db.terms[shell["term_id"]]
    state = row["enrollment_state"]

    if action == "DROP":
        require(state == "ACTIVE", "ERR_INVALID_STATE_TRANSITION",
                "DROP runs from ACTIVE, not from %s." % state)
        shell_allows(shell)
        set_field(row, "enrollment_state", "DROPPED")
        set_field(row, "dropped_at", now())
        mark(row)
        compute.run_capacity(shell, term, promote=True)
        return ok(row)

    if action == "PROMOTE":
        require(state == "WAITLISTED", "ERR_INVALID_STATE_TRANSITION",
                "PROMOTE runs from WAITLISTED, not from %s." % state)
        shell_allows(shell)
        cap, open_seats, promotable = compute.capacity_probe(shell, term)
        require(promotable >= 1, "ERR_SEAT_CAP_EXCEEDED",
                "The capacity rule reports no promotable slot.")
        set_field(row, "enrollment_state", "ACTIVE")
        set_field(row, "waitlist_position", None)
        mark(row)
        compute.renumber_waitlist(shell["id"])
        compute.recompute_shell(shell)
        compute.recompute_term(term)
        return ok(row)

    if action == "REINSTATE":
        require(state == "DROPPED", "ERR_INVALID_STATE_TRANSITION",
                "REINSTATE runs from DROPPED, not from %s." % state)
        if term["add_drop_deadline_at"] is not None:
            require(now() <= term["add_drop_deadline_at"],
                    "ERR_ADD_DROP_WINDOW_CLOSED",
                    "The term's add/drop window closed at %s."
                    % term["add_drop_deadline_at"])
        shell_allows(shell)
        if row["role"] == "STUDENT":
            cap = compute.frozen_seat_cap(shell, term)
            require(len(compute.active_rows(shell["id"])) < cap,
                    "ERR_SEAT_CAP_EXCEEDED",
                    "No seat is open under the shell's effective capacity.")
        set_field(row, "enrollment_state", "ACTIVE")
        set_field(row, "reinstatement_count", row["reinstatement_count"] + 1)
        set_field(row, "dropped_at", None)
        mark(row)
        compute.run_capacity(shell, term, promote=False)
        return ok(row)

    require(state == "ACTIVE", "ERR_INVALID_STATE_TRANSITION",
            "COMPLETE runs from ACTIVE, not from %s." % state)
    shell_allows(shell, ("PUBLISHED", "CONCLUDED"))
    set_field(row, "enrollment_state", "COMPLETED")
    mark(row)
    compute.recompute_shell(shell)
    compute.recompute_term(term)
    return ok(row)
