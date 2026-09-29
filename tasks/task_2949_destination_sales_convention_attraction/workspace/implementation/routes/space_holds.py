"""Date-and-space holds, challenges, releases and the expiry checkpoint
(PRD 3.3, 3.4)."""

import datetime

from flask import Blueprint, request

import aggregates
import calc
import domain
import queries
import resolve
import serialize
from auth import BUREAU_ADMIN, CENTER_SCHEDULER, SALES_MANAGER, endpoint
from errors import ApiError
from response import created, list_response, object_response, pagination
from store import db, ordered, touch
from validation import (body_json, query_enum, query_str, req_instant, req_ref,
                        strictly_before)

bp = Blueprint("space_holds", __name__)

BLOCKING_STATUSES = ("HELD", "CHALLENGED", "CONFIRMED")


@bp.route("/space-holds", methods=["POST"])
@endpoint(CENTER_SCHEDULER)
def create_hold():
    body = body_json()
    opportunity_id = req_ref(body, "opportunity_id")
    center_hall_id = req_ref(body, "center_hall_id")
    move_in_start = req_instant(body, "move_in_start")
    move_out_end = req_instant(body, "move_out_end")
    strictly_before(move_in_start, move_out_end, "move_in_start", "move_out_end")

    opportunity = resolve.opportunity(opportunity_id)
    hall = resolve.hall(center_hall_id)

    if opportunity["sales_stage"] not in ("QUALIFIED", "BIDDING"):
        raise ApiError("ERR_INVALID_OPPORTUNITY_STAGE",
                       "Holds may only be placed for a lead in QUALIFIED or BIDDING.")
    if hall["hall_status"] != "AVAILABLE":
        raise ApiError("ERR_HALL_UNAVAILABLE",
                       "A hall under renovation accepts no new hold.")

    # the blocking set: every hold on the same hall in HELD, CHALLENGED or
    # CONFIRMED whose buffered window conflicts with the candidate's
    blocking = []
    for other in queries.holds_of_hall(hall["id"]):
        if other["status"] not in BLOCKING_STATUSES:
            continue
        if calc.windows_conflict(move_in_start, move_out_end,
                                 other["move_in_start"], other["move_out_end"],
                                 hall["turnaround_hours"]):
            blocking.append(other)

    if any(h["status"] == "CONFIRMED" for h in blocking):
        raise ApiError("ERR_HALL_WINDOW_CONFLICT",
                       "A confirmed hold already occupies the buffered window.")
    if len(blocking) >= domain.HALL_HOLD_LIMIT:
        raise ApiError("ERR_HALL_HOLD_LIMIT_REACHED",
                       "The hall sells a FIRST and a SECOND option and nothing beyond.")
    if (opportunity["attendance_estimate"] > hall["capacity_persons"]
            or opportunity["exhibit_sqft_requested"] > hall["exhibit_sqft"]):
        raise ApiError("ERR_HALL_CAPACITY_INSUFFICIENT",
                       "The hall is not large enough for the event.")

    if not blocking:
        hold_rank = "FIRST"
        expires_at = db.clock + datetime.timedelta(days=domain.FIRST_HOLD_DAYS)
    else:
        # a SECOND-rank hold copies the expires_at of the single FIRST hold that
        # blocked it, so the second option never outlives the first
        hold_rank = "SECOND"
        expires_at = blocking[0]["expires_at"]

    row = db.new_row()
    row.update({
        "opportunity_id": opportunity["id"],
        "center_hall_id": hall["id"],
        "challenged_by_space_hold_id": None,
        "move_in_start": move_in_start,
        "move_out_end": move_out_end,
        "hold_rank": hold_rank,
        "status": "HELD",
        "expires_at": expires_at,
        "challenge_deadline": None,
        "release_reason": None,
    })
    db.space_holds[row["id"]] = row

    # creating a FIRST-rank hold moves hold_posture to TENTATIVE; a SECOND-rank
    # hold leaves it exactly as it was.  Either way the lead's version rises by
    # one -- and both dimensions live on the one row, so it rises by exactly one.
    before_version = opportunity["version"]
    if hold_rank == "FIRST":
        opportunity["hold_posture"] = "TENTATIVE"
    opportunity["version"] = before_version + 1
    opportunity["updated_at"] = db.clock
    return created(serialize.space_hold(row))


@bp.route("/space-holds/<row_id>", methods=["GET"])
@endpoint(BUREAU_ADMIN, CENTER_SCHEDULER, SALES_MANAGER)
def get_hold(row_id):
    return object_response(serialize.space_hold(resolve.space_hold(row_id)))


@bp.route("/space-holds", methods=["GET"])
@endpoint(BUREAU_ADMIN, CENTER_SCHEDULER, SALES_MANAGER)
def list_holds():
    opportunity_id = query_str(request.args, "opportunity_id")
    center_hall_id = query_str(request.args, "center_hall_id")
    challenger_id = query_str(request.args, "challenged_by_space_hold_id")
    status = query_enum(request.args, "status", domain.HOLD_STATUSES)
    hold_rank = query_enum(request.args, "hold_rank", domain.HOLD_RANKS)
    limit, offset = pagination(request.args)
    rows = ordered(list(db.space_holds.values()))
    if opportunity_id is not None:
        rows = [r for r in rows if r["opportunity_id"] == opportunity_id]
    if center_hall_id is not None:
        rows = [r for r in rows if r["center_hall_id"] == center_hall_id]
    if challenger_id is not None:
        rows = [r for r in rows if r["challenged_by_space_hold_id"] == challenger_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if hold_rank is not None:
        rows = [r for r in rows if r["hold_rank"] == hold_rank]
    return list_response(rows, serialize.space_hold, limit, offset)


@bp.route("/space-holds/<row_id>/challenge", methods=["POST"])
@endpoint(CENTER_SCHEDULER)
def challenge(row_id):
    target = resolve.space_hold(row_id)
    body = body_json()
    challenger_id = req_ref(body, "challenging_space_hold_id")
    challenger = resolve.space_hold(challenger_id)

    if target["status"] != "HELD":
        raise ApiError("ERR_INVALID_HOLD_STATE",
                       "Only a hold in status HELD may be challenged.")
    if target["expires_at"] is not None and db.clock >= target["expires_at"]:
        raise ApiError("ERR_HOLD_EXPIRED", "The challenged hold has already lapsed.")

    hall = db.halls.get(target["center_hall_id"])
    well_formed = (
        challenger["status"] == "HELD"
        and challenger["hold_rank"] == "SECOND"
        and target["hold_rank"] == "FIRST"
        and challenger["center_hall_id"] == target["center_hall_id"]
        and challenger["opportunity_id"] != target["opportunity_id"]
        and target["challenge_deadline"] is None
        and hall is not None
        and calc.holds_conflict(challenger, target, hall)
    )
    if not well_formed:
        raise ApiError("ERR_CHALLENGE_TARGET_INVALID",
                       "The challenge is not well-formed.")

    target["status"] = "CHALLENGED"
    target["challenge_deadline"] = db.clock + datetime.timedelta(
        days=domain.CHALLENGE_RESPONSE_DAYS)
    target["challenged_by_space_hold_id"] = challenger["id"]
    touch(target)
    # the acting SECOND-rank hold itself does not change state
    opportunity = db.opportunities.get(target["opportunity_id"])
    if opportunity is not None and opportunity["hold_posture"] == "TENTATIVE":
        opportunity["hold_posture"] = "CHALLENGED"
        touch(opportunity)
    touch(hall)
    return object_response(serialize.space_hold(target))


@bp.route("/space-holds/<row_id>/release", methods=["POST"])
@endpoint(CENTER_SCHEDULER)
def release(row_id):
    hold = resolve.space_hold(row_id)
    if hold["status"] not in domain.ACTIVE_HOLD_STATUSES:
        raise ApiError("ERR_INVALID_HOLD_STATE",
                       "Only a hold in status HELD or CHALLENGED may be released.")
    if hold["expires_at"] is not None and db.clock >= hold["expires_at"]:
        raise ApiError("ERR_HOLD_EXPIRED", "The hold has already lapsed.")

    aggregates.deactivate_hold(hold, "RELEASED", "SCHEDULER_RELEASE")
    aggregates.after_hold_left_active_set(
        db.opportunities.get(hold["opportunity_id"]))
    return object_response(serialize.space_hold(hold))


@bp.route("/space-hold-expiry-runs", methods=["POST"])
@endpoint(BUREAU_ADMIN, CENTER_SCHEDULER)
def expiry_run():
    return object_response(aggregates.run_expiry_checkpoint())
