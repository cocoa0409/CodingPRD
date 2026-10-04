"""Placement lifecycle actions: offers, acceptance, completion, termination
(PRD 3.4, 3.6)."""

from flask import Blueprint

import db
import middleware
import response
import timeutil
import validators
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_PARENT_STATE_CONFLICT,
    ERR_PARTNER_PAST_DUE,
    ERR_PARTNER_SUSPENDED,
    ERR_PLACEMENT_WINDOW_INVALID,
    ERR_STUDENT_ALREADY_PLACED,
    ApiError,
)
from routes.common import must_get, require_owner
from services import billing_svc, credit_svc, placement_svc, student_svc

MIN_ACCEPTED_WINDOW_DAYS = 28
MIN_HOURS_PER_WEEK = 20
DEFAULT_HOURS_PER_WEEK = 20
PAST_DUE_GRACE_DAYS = 14
AGREEMENT_STATES_ADMITTING_ACCEPTANCE = ("ACTIVE", "FULFILLED")

bp = Blueprint("placement_actions", __name__)


def _guard_terminal(placement):
    if placement["state"] == "TERMINATED":
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "placement %s is TERMINATED" % placement["id"],
            409,
        )


def _guard_state(placement, allowed, action):
    if placement["state"] not in allowed:
        raise ApiError(
            ERR_INVALID_STATE,
            "placement %s is %s; %s is not admissible" % (placement["id"], placement["state"], action),
            409,
        )


@bp.post("/placements/<placement_id>/offers")
def extend_offer(placement_id):
    middleware.require(("ProgramStaff",))
    placement = must_get("placements", placement_id, "placement")
    _guard_terminal(placement)

    if placement["state"] != "INTERVIEWED" or not placement_svc.latest_round_passed(placement):
        raise ApiError(
            ERR_INVALID_STATE,
            "an offer requires an INTERVIEWED placement whose latest round PASSED",
            409,
        )

    agreement = db.get("agreements", placement["agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise ApiError(
            ERR_PARENT_STATE_CONFLICT,
            "the sponsoring agreement is not ACTIVE",
            409,
        )

    partner = billing_svc.partner_of_agreement(agreement)
    if partner is None or partner["status"] != "ACTIVE":
        raise ApiError(ERR_PARTNER_SUSPENDED, "the sponsoring partner is not ACTIVE", 402)

    from services import partner_svc

    if partner_svc.has_overdue_beyond_days(partner["id"], PAST_DUE_GRACE_DAYS):
        raise ApiError(
            ERR_PARTNER_PAST_DUE,
            "partner %s carries an invoice overdue by more than %d days"
            % (partner["id"], PAST_DUE_GRACE_DAYS),
            402,
        )

    placement["placement_fee_cents"] = billing_svc.fee_for_agreement_window(agreement)
    placement["state"] = "OFFERED"
    db.touch(placement)
    return response.success(placement)


@bp.post("/placements/<placement_id>/acceptance")
def accept_offer(placement_id):
    actor = middleware.require(("Student",))
    placement = must_get("placements", placement_id, "placement")
    data = validators.body()

    start_date = validators.as_dt(data, "start_date")
    end_date = validators.as_dt(data, "end_date")
    hours_per_week = validators.as_int(
        data, "hours_per_week", required=False, default=DEFAULT_HOURS_PER_WEEK
    )
    if (end_date.date() - start_date.date()).days < MIN_ACCEPTED_WINDOW_DAYS:
        validators.fail(
            "end_date must be at least %d days after start_date" % MIN_ACCEPTED_WINDOW_DAYS
        )

    _guard_terminal(placement)
    _guard_state(placement, ("OFFERED",), "acceptance")
    require_owner(actor, placement["student_id"], "placement %s" % placement["id"])

    agreement = db.get("agreements", placement["agreement_id"])
    if agreement is None or agreement["status"] not in AGREEMENT_STATES_ADMITTING_ACCEPTANCE:
        raise ApiError(
            ERR_PARENT_STATE_CONFLICT,
            "the sponsoring agreement is not ACTIVE or FULFILLED",
            409,
        )

    if not placement_svc.agreement_window_contains(agreement, start_date, end_date):
        raise ApiError(
            ERR_PLACEMENT_WINDOW_INVALID,
            "the accepted window is not inside the agreement's window",
            409,
        )
    if int(hours_per_week) < MIN_HOURS_PER_WEEK:
        raise ApiError(
            ERR_PLACEMENT_WINDOW_INVALID,
            "hours_per_week must be at least %d" % MIN_HOURS_PER_WEEK,
            409,
        )

    if student_svc.has_active_placement(placement["student_id"], exclude_placement_id=placement["id"]):
        raise ApiError(
            ERR_STUDENT_ALREADY_PLACED,
            "the student already holds a placement at ACCEPTED or ACTIVE",
            409,
        )

    placement["start_date"] = start_date
    placement["end_date"] = end_date
    placement["hours_per_week"] = int(hours_per_week)
    placement["placement_fee_cents"] = billing_svc.placement_fee_cents(
        agreement, start_date, end_date
    )
    placement["state"] = "ACCEPTED"
    db.touch(placement)

    placement_svc.refresh_agreement_status(agreement)

    if timeutil.today() >= start_date.date() and agreement["status"] in AGREEMENT_STATES_ADMITTING_ACCEPTANCE:
        placement["state"] = "ACTIVE"
        db.touch(placement)

    return response.success(placement)


@bp.post("/placements/<placement_id>/completions")
def complete_placement(placement_id):
    middleware.require(("ProgramStaff",))
    placement = must_get("placements", placement_id, "placement")
    data = validators.body()
    outcome = validators.as_enum(data, "outcome", ("CONVERTED", "NOT_CONVERTED"))

    _guard_terminal(placement)
    _guard_state(placement, ("ACTIVE",), "completion")

    if placement["end_date"] is None or timeutil.today() < placement["end_date"].date():
        raise ApiError(
            ERR_INVALID_STATE,
            "the placement cannot complete before its end_date on the logical clock",
            409,
        )
    latest = placement_svc.latest_satisfaction(placement["id"])
    if latest is None:
        raise ApiError(
            ERR_INVALID_STATE,
            "the placement cannot complete without at least one satisfaction record",
            409,
        )

    converted = outcome == "CONVERTED"
    student = db.get("students", placement["student_id"])

    placement["outcome"] = outcome
    placement["satisfaction_score"] = latest["composite_score"]
    placement["state"] = "COMPLETED"
    db.touch(placement)

    if converted:
        credit_svc.mark_converted_to_hire(placement)

    if student is not None:
        if converted:
            student["conversion_streak"] = int(student.get("conversion_streak") or 0) + 1
        else:
            student["conversion_streak"] = 0
        graduated = student_svc.maybe_graduate(student)
        if not graduated:
            db.touch(student)

    placement_svc.refresh_agreement_for_placement(placement)
    return response.success(placement)


@bp.post("/placements/<placement_id>/terminations")
def terminate_placement(placement_id):
    middleware.require(("ProgramStaff",))
    placement = must_get("placements", placement_id, "placement")
    _guard_terminal(placement)

    if placement["state"] == "COMPLETED":
        raise ApiError(
            ERR_INVALID_STATE,
            "a COMPLETED placement has no transition to TERMINATED",
            409,
        )

    placement["state"] = "TERMINATED"
    db.touch(placement)
    placement_svc.refresh_agreement_for_placement(placement)
    return response.success(placement)
