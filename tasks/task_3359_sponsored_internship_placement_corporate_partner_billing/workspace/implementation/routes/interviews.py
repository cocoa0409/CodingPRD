"""Interview scheduling and outcome recording (PRD 3.4)."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware
import response
import validators
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INTERVIEW_ROUNDS_EXHAUSTED,
    ERR_INTERVIEW_SLOT_CONFLICT,
    ERR_INVALID_STATE,
    ERR_PARENT_STATE_CONFLICT,
    ApiError,
)
from routes.common import must_get, require_owner
from services import billing_svc, placement_svc

DEFAULT_DURATION_MINUTES = 45
MIN_DURATION_MINUTES = 30

bp = Blueprint("interviews", __name__)


def _slot_conflicts(scheduled_for, duration_minutes, supervisor_name):
    start = scheduled_for
    end = scheduled_for + timedelta(minutes=duration_minutes)
    for round_row in db.all_rows("interview_rounds"):
        if round_row["supervisor_name"] != supervisor_name:
            continue
        other_start = round_row["scheduled_for"]
        other_end = other_start + timedelta(minutes=int(round_row["duration_minutes"]))
        if start < other_end and other_start < end:
            return True
    return False


def _scheduling_admissible(placement):
    """MATCHED, or INTERVIEWED after a FAILED round with rounds remaining."""
    state = placement["state"]
    if state == "MATCHED":
        return True
    if state == "INTERVIEWED":
        return (
            placement_svc.latest_round_failed(placement)
            and int(placement["interview_attempt"]) < int(placement["max_interview_rounds"])
        )
    return False


@bp.post("/placements/<placement_id>/interviews")
def schedule_interview(placement_id):
    middleware.require(("ProgramStaff",))
    placement = must_get("placements", placement_id, "placement")
    data = validators.body()

    scheduled_for = validators.as_dt(data, "scheduled_for")
    supervisor_name = validators.as_str(data, "supervisor_name")
    duration_minutes = validators.as_int(
        data, "duration_minutes", required=False, default=DEFAULT_DURATION_MINUTES
    )
    if int(duration_minutes) < MIN_DURATION_MINUTES:
        validators.fail("duration_minutes must be at least %d" % MIN_DURATION_MINUTES)

    if placement["state"] == "TERMINATED":
        raise ApiError(ERR_ALREADY_TERMINAL, "placement %s is TERMINATED" % placement_id, 409)
    if not _scheduling_admissible(placement):
        raise ApiError(
            ERR_INVALID_STATE,
            "placement %s is %s and cannot be scheduled for an interview"
            % (placement_id, placement["state"]),
            409,
        )

    agreement = db.get("agreements", placement["agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise ApiError(
            ERR_PARENT_STATE_CONFLICT,
            "the sponsoring agreement is not ACTIVE",
            409,
        )
    if not (
        agreement["start_date"].date() <= scheduled_for.date() <= agreement["end_date"].date()
    ):
        raise ApiError(
            ERR_PARENT_STATE_CONFLICT,
            "scheduled_for does not fall inside the sponsoring agreement's window",
            409,
        )

    if _slot_conflicts(scheduled_for, int(duration_minutes), supervisor_name):
        raise ApiError(
            ERR_INTERVIEW_SLOT_CONFLICT,
            "supervisor %s already has an interview booked in that slot" % supervisor_name,
            409,
        )

    if int(placement["interview_attempt"]) >= int(placement["max_interview_rounds"]):
        raise ApiError(
            ERR_INTERVIEW_ROUNDS_EXHAUSTED,
            "placement %s has used all of its allowed interview rounds" % placement_id,
            409,
        )

    round_row = db.make_row(
        placement_id=placement["id"],
        scheduled_for=scheduled_for,
        duration_minutes=int(duration_minutes),
        supervisor_name=supervisor_name,
        round_number=int(placement["interview_attempt"]) + 1,
        outcome="PENDING",
        feedback="",
    )
    db.insert("interview_rounds", round_row)

    placement["state"] = "INTERVIEW_SCHEDULED"
    db.touch(placement)
    return response.success(round_row, status=201)


@bp.post("/interviews/<interview_id>/outcomes")
def record_interview_outcome(interview_id):
    actor = middleware.require(("Partner",))
    round_row = must_get("interview_rounds", interview_id, "interview round")
    data = validators.body()
    outcome = validators.as_enum(data, "outcome", ("PASSED", "FAILED"))
    feedback = validators.as_str(data, "feedback", required=False, default=None)

    if round_row["outcome"] != "PENDING":
        raise ApiError(
            ERR_INVALID_STATE,
            "interview round %s already carries an outcome" % interview_id,
            409,
        )

    placement = must_get("placements", round_row["placement_id"], "placement")
    if placement["state"] == "TERMINATED":
        raise ApiError(
            ERR_ALREADY_TERMINAL, "placement %s is TERMINATED" % placement["id"], 409
        )

    if int(placement["interview_attempt"]) + 1 > int(placement["max_interview_rounds"]):
        raise ApiError(
            ERR_INTERVIEW_ROUNDS_EXHAUSTED,
            "placement %s has used all of its allowed interview rounds" % placement["id"],
            409,
        )

    agreement = db.get("agreements", placement["agreement_id"])
    partner = billing_svc.partner_of_agreement(agreement)
    require_owner(actor, partner["id"] if partner else None, "placement %s" % placement["id"])

    round_row["outcome"] = outcome
    if feedback is not None:
        round_row["feedback"] = feedback
    db.touch(round_row)

    placement["interview_attempt"] = int(placement["interview_attempt"]) + 1
    attempt = int(placement["interview_attempt"])
    max_rounds = int(placement["max_interview_rounds"])

    if outcome == "PASSED":
        placement["state"] = "INTERVIEWED"
    elif attempt >= max_rounds:
        placement["state"] = "MATCHED"
    else:
        placement["state"] = "INTERVIEWED"
    db.touch(placement)

    return response.success(round_row)
