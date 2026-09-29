"""Grade passback to the registrar -- PRD 3.8."""

from decimal import Decimal

from flask import Blueprint

import lookup
from db import db, mark, new_record, set_field
from errors import require
from middleware import (INSTRUCTOR, LMS_ADMIN, REGISTRAR, actor, as_enum,
                        as_str, body)
from routes.common import apply_filters, created, guard, listing, ok
from services import access, compute
from util import q2

bp = Blueprint("passbacks", __name__)

ACTIONS = ("SUBMIT", "RESTAGE")
DECISIONS = ("ACCEPT", "RETURN")
ZERO = Decimal("0.00")


def staged(passback):
    return compute.staged_rows(passback["shell_id"])


def stage_provisional(passback):
    rows = staged(passback)
    for row in rows:
        set_field(row, "provisional_grade_pct", compute.provisional_pct(row))
        mark(row)
    set_field(passback, "staged_enrollment_count", len(rows))
    return rows


@bp.post("/grade-passbacks")
def create_passback():
    guard(INSTRUCTOR)
    payload = body()
    access.own_shell(lookup.peek("shells", payload.get("shell_id")))
    shell = lookup.fk(payload, "shell_id", "shells")
    if shell is None:
        as_str(payload, "shell_id", required=True)
    term = db.terms[shell["term_id"]]

    require(not [p for p in db.passbacks.values() if p["shell_id"] == shell["id"]],
            "ERR_DUPLICATE_PASSBACK",
            "This shell already carries a passback.")
    require(term["lifecycle_state"] in ("FINALS", "GRADING"),
            "ERR_INVALID_STATE_TRANSITION",
            "A term in %s does not accept a passback." % term["lifecycle_state"])
    require(shell["provisioning_state"] in ("PUBLISHED", "CONCLUDED"),
            "ERR_SHELL_STATE_BLOCKS_ENROLLMENT",
            "A shell in %s does not accept passback staging."
            % shell["provisioning_state"])

    passback = new_record(
        _kind="passback",
        shell_id=shell["id"],
        term_id=shell["term_id"],
        passback_state="STAGED",
        variant_applied="PROVISIONAL",
        staged_enrollment_count=0,
        submitted_points_total=ZERO,
        accepted_points_total=ZERO,
        disputed_points_held=ZERO,
        open_dispute_count=0,
        amendment_round=0,
        registrar_note=None,
        _submitted_by_user_id=None,
    )
    db.passbacks[passback["id"]] = passback
    stage_provisional(passback)
    return created(passback)


@bp.get("/grade-passbacks")
def list_passbacks():
    guard(INSTRUCTOR, REGISTRAR, LMS_ADMIN)
    records = apply_filters(db.passbacks.values(), {
        "shell_id": "shell_id",
        "term_id": "term_id",
        "passback_state": "passback_state",
    })
    return listing(records)


@bp.get("/grade-passbacks/<passback_id>")
def read_passback(passback_id):
    guard(INSTRUCTOR, REGISTRAR, LMS_ADMIN)
    return ok(lookup.passback(passback_id))


def apply_final(passback, shell):
    rows = staged(passback)
    for row in rows:
        set_field(row, "final_grade_pct", compute.final_pct(row, shell))
        mark(row)
    set_field(passback, "staged_enrollment_count", len(rows))
    return rows


@bp.post("/grade-passbacks/<passback_id>/transitions")
def drive_passback(passback_id):
    guard(INSTRUCTOR)
    existing = lookup.peek("passbacks", passback_id)
    if existing is not None:
        access.own_shell(db.shells.get(existing["shell_id"]))
    passback = lookup.passback(passback_id)
    payload = body()
    action = as_str(payload, "action", required=True)
    require(action in ACTIONS, "ERR_INVALID_STATE_TRANSITION",
            "'%s' is not a declared passback action." % action)
    shell = db.shells[passback["shell_id"]]
    term = db.terms[passback["term_id"]]
    state = passback["passback_state"]

    if action == "SUBMIT":
        require(state in ("STAGED", "AMENDED"), "ERR_INVALID_STATE_TRANSITION",
                "SUBMIT runs from STAGED or AMENDED, not from %s." % state)
        if state == "STAGED":
            rows = staged(passback)
            for row in rows:
                person = db.people.get(row["person_id"])
                if person is not None and person["ferpa_block"]:
                    require(False, "ERR_FERPA_BLOCK_ACTIVE",
                            "A staged enrollment belongs to a person carrying a "
                            "FERPA directory block.")
            require(term["continuity_posture"] != "CONTINUITY_MODE",
                    "ERR_TERM_POSTURE_FROZEN",
                    "The term is in CONTINUITY_MODE; authoring is frozen.")
            require(any(row["graded_points_possible"] > 0 for row in rows),
                    "ERR_NO_GRADES_STAGED",
                    "No staged enrollment carries graded points.")
            set_field(passback, "variant_applied", "FINAL")
            apply_final(passback, shell)
            total = ZERO
            for row in staged(passback):
                total = total + row["earned_points_total"]
            set_field(passback, "submitted_points_total", q2(total))
            set_field(passback, "accepted_points_total", ZERO)
            set_field(passback, "disputed_points_held", ZERO)
        else:
            require(term["continuity_posture"] != "CONTINUITY_MODE",
                    "ERR_TERM_POSTURE_FROZEN",
                    "The term is in CONTINUITY_MODE; authoring is frozen.")
            require(passback["open_dispute_count"] == 0,
                    "ERR_INVALID_STATE_TRANSITION",
                    "Every dispute must be resolved before resubmitting.")
            set_field(passback, "variant_applied", "FINAL")
            apply_final(passback, shell)
        set_field(passback, "passback_state", "SUBMITTED")
        passback["_submitted_by_user_id"] = actor()
        mark(passback)
        compute.recompute_term(term)
        mark(term)
        return ok(passback)

    require(state == "RETURNED", "ERR_INVALID_STATE_TRANSITION",
            "RESTAGE runs from RETURNED, not from %s." % state)
    set_field(passback, "variant_applied", "PROVISIONAL")
    for row in stage_provisional(passback):
        set_field(row, "final_grade_pct", None)
        mark(row)
    set_field(passback, "submitted_points_total", ZERO)
    set_field(passback, "passback_state", "STAGED")
    mark(passback)
    return ok(passback)


@bp.post("/grade-passbacks/<passback_id>/registrar-decisions")
def decide_passback(passback_id):
    guard(REGISTRAR)
    passback = lookup.passback(passback_id)
    payload = body()
    decision = as_enum(payload, "decision", DECISIONS, required=True)
    note = as_str(payload, "note")
    state = passback["passback_state"]
    require(state == "SUBMITTED", "ERR_INVALID_STATE_TRANSITION",
            "A registrar decision runs from SUBMITTED, not from %s." % state)
    require(actor() != passback.get("_submitted_by_user_id"),
            "ERR_SEGREGATION_OF_DUTIES",
            "The instructor who submitted this passback may not decide it.")

    if note is not None:
        set_field(passback, "registrar_note", note)
    if decision == "ACCEPT":
        set_field(passback, "passback_state", "ACCEPTED")
        set_field(passback, "accepted_points_total",
                  passback["submitted_points_total"])
        set_field(passback, "disputed_points_held", ZERO)
    else:
        set_field(passback, "passback_state", "RETURNED")
        set_field(passback, "submitted_points_total", ZERO)
        set_field(passback, "accepted_points_total", ZERO)
        set_field(passback, "disputed_points_held", ZERO)
    mark(passback)
    return ok(passback)
