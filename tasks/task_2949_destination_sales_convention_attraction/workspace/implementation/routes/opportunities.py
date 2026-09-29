"""Citywide convention leads (PRD 3.2) plus their impact and servicing lists."""

import datetime
from decimal import Decimal

from flask import Blueprint, request

import aggregates
import calc
import domain
import queries
import resolve
import serialize
from auth import (BOARD_ANALYST, BUREAU_ADMIN, CENTER_SCHEDULER, HOTEL_PARTNER,
                  INCENTIVE_APPROVER, MEETING_PLANNER, SALES_MANAGER,
                  SERVICES_MANAGER, endpoint)
from errors import ApiError
from response import created, list_response, object_response, pagination
from store import db, ordered, touch
from util import date_at_midnight
from validation import (body_json, opt_ref, query_enum, query_str, req_date,
                        req_enum, req_int, req_money, req_ref, req_str,
                        strictly_before)

bp = Blueprint("opportunities", __name__)

READ_ROLES = (BUREAU_ADMIN, SALES_MANAGER, CENTER_SCHEDULER, INCENTIVE_APPROVER,
              SERVICES_MANAGER, BOARD_ANALYST, MEETING_PLANNER, HOTEL_PARTNER)


@bp.route("/opportunities", methods=["POST"])
@endpoint(SALES_MANAGER)
def create_opportunity():
    body = body_json()
    planner_id = req_ref(body, "planner_id")
    event_name = req_str(body, "event_name", min_len=1, max_len=160)
    arrival_date = req_date(body, "arrival_date")
    departure_date = req_date(body, "departure_date")
    strictly_before(arrival_date, departure_date, "arrival_date", "departure_date")
    peak_rooms_requested = req_int(body, "peak_rooms_requested", minimum=1)
    total_room_nights = req_int(body, "total_room_nights_requested", minimum=1)
    attendance_estimate = req_int(body, "attendance_estimate", minimum=1)
    exhibit_sqft_requested = req_int(body, "exhibit_sqft_requested", minimum=0)
    rate_ceiling_amount = req_money(body, "rate_ceiling_amount", positive=True)
    supersedes_id = opt_ref(body, "supersedes_opportunity_id")

    planner = resolve.planner(planner_id)
    if supersedes_id is not None:
        resolve.opportunity(supersedes_id)

    row = db.new_row()
    row.update({
        "planner_id": planner["id"],
        "supersedes_opportunity_id": supersedes_id,
        "event_name": event_name,
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "event_nights": calc.event_nights(arrival_date, departure_date),
        "peak_rooms_requested": peak_rooms_requested,
        "total_room_nights_requested": total_room_nights,
        "attendance_estimate": attendance_estimate,
        "exhibit_sqft_requested": exhibit_sqft_requested,
        "rate_ceiling_amount": rate_ceiling_amount,
        "sales_stage": "LEAD",
        "hold_posture": "NONE",
        "committed_peak_rooms": 0,
        "block_coverage_pct": Decimal("0.00"),
        "citywide_cutoff_days_before_arrival": 0,
        "cutoff_alignment_spread_days": 0,
        "definite_room_nights": 0,
        "definite_at": None,
        "lost_reason": None,
        "attrition_settlement_amount": Decimal("0.00"),
    })
    db.opportunities[row["id"]] = row
    # creating the lead also refreshes the owning planner's last_touch_at
    aggregates.set_last_touch(planner)
    touch(planner)
    return created(serialize.opportunity(row))


@bp.route("/opportunities/<row_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_opportunity(row_id):
    return object_response(serialize.opportunity(resolve.opportunity(row_id)))


@bp.route("/opportunities", methods=["GET"])
@endpoint(BUREAU_ADMIN, SALES_MANAGER, CENTER_SCHEDULER, BOARD_ANALYST)
def list_opportunities():
    planner_id = query_str(request.args, "planner_id")
    supersedes_id = query_str(request.args, "supersedes_opportunity_id")
    stage = query_enum(request.args, "sales_stage", domain.SALES_STAGES)
    posture = query_enum(request.args, "hold_posture", domain.HOLD_POSTURES)
    limit, offset = pagination(request.args)
    rows = ordered(list(db.opportunities.values()))
    if planner_id is not None:
        rows = [r for r in rows if r["planner_id"] == planner_id]
    if supersedes_id is not None:
        rows = [r for r in rows if r["supersedes_opportunity_id"] == supersedes_id]
    if stage is not None:
        rows = [r for r in rows if r["sales_stage"] == stage]
    if posture is not None:
        rows = [r for r in rows if r["hold_posture"] == posture]
    return list_response(rows, serialize.opportunity, limit, offset)


@bp.route("/opportunities/<row_id>/qualify", methods=["POST"])
@endpoint(SALES_MANAGER)
def qualify(row_id):
    opportunity = resolve.opportunity(row_id)
    if opportunity["sales_stage"] != "LEAD":
        raise ApiError("ERR_INVALID_OPPORTUNITY_STAGE",
                       "Qualification requires the lead to be in sales_stage LEAD.")
    lead_time = date_at_midnight(opportunity["arrival_date"]) - db.clock
    if lead_time < datetime.timedelta(days=domain.QUALIFY_LEAD_TIME_DAYS):
        raise ApiError("ERR_LEAD_TIME_TOO_SHORT",
                       "Arrival must be at least %d days after the current clock."
                       % domain.QUALIFY_LEAD_TIME_DAYS)

    opportunity["sales_stage"] = "QUALIFIED"
    touch(opportunity)
    planner = db.planners.get(opportunity["planner_id"])
    if planner is not None:
        aggregates.set_engaged(planner)
        aggregates.set_last_touch(planner)
        touch(planner)
    return object_response(serialize.opportunity(opportunity))


@bp.route("/opportunities/<row_id>/lose", methods=["POST"])
@endpoint(SALES_MANAGER)
def lose(row_id):
    opportunity = resolve.opportunity(row_id)
    body = body_json()
    lost_reason = req_enum(body, "lost_reason", domain.LOST_REASONS)
    if opportunity["sales_stage"] not in ("QUALIFIED", "BIDDING"):
        raise ApiError("ERR_INVALID_OPPORTUNITY_STAGE",
                       "Losing a lead requires sales_stage QUALIFIED or BIDDING.")
    # when the lead was in BIDDING the live package is declined with a reason
    # mapped from the lead's lost_reason
    was_bidding = opportunity["sales_stage"] == "BIDDING"
    aggregates.lose_opportunity(opportunity, lost_reason,
                                decline_live_package=was_bidding)
    return object_response(serialize.opportunity(opportunity))


@bp.route("/opportunities/<row_id>/economic-impact-estimates", methods=["GET"])
@endpoint(BUREAU_ADMIN, SALES_MANAGER, INCENTIVE_APPROVER, BOARD_ANALYST)
def list_estimates(row_id):
    opportunity = resolve.opportunity(row_id)
    variant = query_enum(request.args, "variant", domain.ESTIMATE_VARIANTS)
    limit, offset = pagination(request.args)
    rows = queries.estimates_of_opportunity(opportunity["id"])
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]
    return list_response(rows, serialize.estimate, limit, offset)


@bp.route("/opportunities/<row_id>/servicing-orders", methods=["GET"])
@endpoint(BUREAU_ADMIN, SERVICES_MANAGER, SALES_MANAGER, BOARD_ANALYST)
def list_servicing_orders(row_id):
    opportunity = resolve.opportunity(row_id)
    category = query_enum(request.args, "category", domain.SERVICING_CATEGORIES)
    status = query_enum(request.args, "status", domain.SERVICING_STATUSES)
    limit, offset = pagination(request.args)
    rows = queries.servicing_orders_of_opportunity(opportunity["id"])
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serialize.servicing_order, limit, offset)
