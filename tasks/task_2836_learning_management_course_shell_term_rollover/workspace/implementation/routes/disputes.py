"""Grade disputes and their compensating resolutions -- PRD 3.8."""

from decimal import Decimal

from flask import Blueprint

import lookup
from db import db, mark, new_record, now, set_field
from errors import require
from middleware import (INSTRUCTOR, REGISTRAR, STUDENT, actor, as_decimal,
                        as_enum, as_str, bad, body)
from routes.common import apply_filters, created, guard, listing, ok
from services import access, compute
from util import q2

bp = Blueprint("disputes", __name__)

OUTCOMES = ("UPHELD", "CHANGED")
ZERO = Decimal("0.00")


@bp.post("/grade-disputes")
def file_dispute():
    guard(STUDENT)
    payload = body()
    access.own_enrollment(lookup.peek("enrollments", payload.get("enrollment_id")))
    passback = lookup.fk(payload, "passback_id", "passbacks")
    enrollment = lookup.fk(payload, "enrollment_id", "enrollments")
    item = lookup.fk(payload, "content_item_id", "items")
    if passback is None:
        as_str(payload, "passback_id", required=True)
    if enrollment is None:
        as_str(payload, "enrollment_id", required=True)
    if item is None:
        as_str(payload, "content_item_id", required=True)
    claimed = as_decimal(payload, "claimed_earned_points", required=True)
    if item["shell_id"] != enrollment["shell_id"]:
        bad("content_item_id", "must belong to the same shell as the enrollment")

    require(passback["passback_state"] in ("ACCEPTED", "DISPUTED"),
            "ERR_INVALID_STATE_TRANSITION",
            "A passback in %s does not accept a dispute."
            % passback["passback_state"])
    term = db.terms[passback["term_id"]]
    access.student_gate(term)
    require(not [d for d in db.disputes.values()
                 if d["enrollment_id"] == enrollment["id"]
                 and d["dispute_state"] == "OPEN"],
            "ERR_ROLE_CONFLICT",
            "This enrollment already carries an open dispute.")

    held = q2(enrollment["earned_points_total"])
    dispute = new_record(
        _kind="dispute",
        passback_id=passback["id"],
        enrollment_id=enrollment["id"],
        content_item_id=item["id"],
        claimed_earned_points=q2(claimed),
        dispute_state="OPEN",
        held_points=held,
        adjusted_earned_points=None,
        filed_by_user_id=actor(),
        resolved_at=None,
        _round=passback["amendment_round"],
    )
    db.disputes[dispute["id"]] = dispute
    set_field(enrollment, "disputed_points_held", held)
    mark(enrollment)

    set_field(passback, "passback_state", "DISPUTED")
    set_field(passback, "open_dispute_count", passback["open_dispute_count"] + 1)
    set_field(passback, "accepted_points_total",
              q2(passback["accepted_points_total"] - held))
    set_field(passback, "disputed_points_held",
              q2(passback["disputed_points_held"] + held))
    mark(passback)
    compute.recompute_term(term)
    mark(term)
    return created(dispute)


@bp.get("/grade-disputes")
def list_disputes():
    guard(STUDENT, INSTRUCTOR, REGISTRAR)
    records = apply_filters(db.disputes.values(), {
        "passback_id": "passback_id",
        "enrollment_id": "enrollment_id",
        "content_item_id": "content_item_id",
        "dispute_state": "dispute_state",
    })
    return listing(records)


@bp.get("/grade-disputes/<dispute_id>")
def read_dispute(dispute_id):
    guard(STUDENT, INSTRUCTOR, REGISTRAR)
    return ok(lookup.dispute(dispute_id))


def close_round(passback, term):
    """When the last open dispute of a round resolves the passback returns to
    ACCEPTED if every resolution was upheld, and moves to AMENDED if at least
    one changed a grade (PRD 3.8)."""
    if passback["open_dispute_count"] != 0:
        return
    round_no = passback["amendment_round"]
    rows = [d for d in db.disputes.values()
            if d["passback_id"] == passback["id"] and d.get("_round") == round_no]
    if not rows:
        return
    if any(d["dispute_state"] == "RESOLVED_CHANGED" for d in rows):
        set_field(passback, "passback_state", "AMENDED")
        set_field(passback, "amendment_round", round_no + 1)
    else:
        set_field(passback, "passback_state", "ACCEPTED")
    mark(passback)
    compute.recompute_term(term)
    mark(term)


@bp.post("/grade-disputes/<dispute_id>/resolve")
def resolve_dispute(dispute_id):
    guard(INSTRUCTOR)
    existing = lookup.peek("disputes", dispute_id)
    if existing is not None:
        enrollment = db.enrollments.get(existing["enrollment_id"])
        if enrollment is not None:
            access.own_shell(db.shells.get(enrollment["shell_id"]))
    dispute = lookup.dispute(dispute_id)
    payload = body()
    outcome = as_enum(payload, "outcome", OUTCOMES, required=True)
    adjusted = as_decimal(payload, "adjusted_earned_points")
    as_str(payload, "note")
    if outcome == "CHANGED" and (adjusted is None or adjusted < 0):
        bad("adjusted_earned_points",
            "must be present and at least 0 when the outcome is CHANGED")
    require(dispute["dispute_state"] == "OPEN", "ERR_INVALID_STATE_TRANSITION",
            "A dispute in %s is already resolved." % dispute["dispute_state"])

    enrollment = db.enrollments[dispute["enrollment_id"]]
    shell = db.shells[enrollment["shell_id"]]
    passback = db.passbacks[dispute["passback_id"]]
    term = db.terms[passback["term_id"]]
    held = dispute["held_points"]

    set_field(dispute, "resolved_at", now())
    set_field(enrollment, "disputed_points_held", ZERO)
    if outcome == "UPHELD":
        set_field(dispute, "dispute_state", "RESOLVED_UPHELD")
        set_field(dispute, "adjusted_earned_points", None)
        set_field(passback, "disputed_points_held",
                  q2(passback["disputed_points_held"] - held))
        set_field(passback, "accepted_points_total",
                  q2(passback["accepted_points_total"] + held))
    else:
        figure = q2(adjusted)
        set_field(dispute, "dispute_state", "RESOLVED_CHANGED")
        set_field(dispute, "adjusted_earned_points", figure)
        set_field(enrollment, "earned_points_total", figure)
        set_field(enrollment, "final_grade_pct",
                  compute.final_pct(enrollment, shell))
        set_field(passback, "disputed_points_held",
                  q2(passback["disputed_points_held"] - held))
        set_field(passback, "accepted_points_total",
                  q2(passback["accepted_points_total"] + figure))
        set_field(passback, "submitted_points_total",
                  q2(passback["submitted_points_total"] + (figure - held)))
    mark(dispute)
    mark(enrollment)
    set_field(passback, "open_dispute_count",
              passback["open_dispute_count"] - 1)
    mark(passback)
    close_round(passback, term)
    return ok(dispute)
