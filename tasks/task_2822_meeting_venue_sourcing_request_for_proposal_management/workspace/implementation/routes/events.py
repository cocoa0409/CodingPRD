"""Meeting event endpoints (PRD section 3.2)."""
from flask import Blueprint, g

import db as store
import enums
import lookup
import middleware
import response
import serializers
import validate
from db import db, touch
from errors import ApiError
from money import q2
from services import calc, rollups

bp = Blueprint("events", __name__)


@bp.route("/sourcing/events", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def create_event():
    data = validate.body()
    event_code = validate.req_str(data, "event_code", min_len=3, max_len=32)
    name = validate.req_str(data, "name")
    program_type = validate.req_enum(data, "program_type", enums.PROGRAM_TYPES)
    start_date = validate.req_date(data, "start_date")
    end_date = validate.req_date(data, "end_date")
    peak_attendees = validate.req_int(data, "peak_attendees", minimum=1)
    requested_room_nights = validate.req_int(data, "requested_room_nights",
                                             minimum=1)
    largest_meeting_space_sqft = validate.req_int(
        data, "largest_meeting_space_sqft", minimum=0
    )
    budget_ceiling_usd = validate.req_money(data, "budget_ceiling_usd",
                                            exclusive_min=True)
    preferred_program_only = validate.opt_bool(data, "preferred_program_only",
                                               False)

    if end_date <= start_date:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "end_date must be strictly after start_date")

    for existing in db.events.values():
        if existing["event_code"] == event_code:
            raise ApiError("ERR_EVENT_CODE_DUPLICATE",
                           "event_code is already in use")

    row = store.base_row()
    row.update({
        "event_code": event_code,
        "name": name,
        "program_type": program_type,
        "start_date": start_date,
        "end_date": end_date,
        "nights_span": (end_date - start_date).days,
        "peak_attendees": peak_attendees,
        "requested_room_nights": requested_room_nights,
        "largest_meeting_space_sqft": largest_meeting_space_sqft,
        "budget_ceiling_usd": q2(budget_ceiling_usd),
        "preferred_program_only": preferred_program_only,
        "status": "DRAFT",
        "sourcing_owner_user_id": g.user_id,
        "shortlisted_venue_count": 0,
        "best_total_cost_usd": None,
        "awarded_proposal_id": None,
        "committed_spend_usd": q2(0),
        "cancellation_liability_usd": q2(0),
        "budget_remaining_usd": q2(budget_ceiling_usd),
        "savings_recognized_usd": None,
    })
    db.events[row["id"]] = row
    return response.obj(serializers.event(row), 201)


@bp.route("/sourcing/events/<event_id>/lock-requirements", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def lock_requirements(event_id):
    event = lookup.event(event_id)
    if event["status"] != "DRAFT":
        raise ApiError("ERR_EVENT_STATE_INVALID",
                       "Only a DRAFT event may lock its requirements")
    event["status"] = "REQUIREMENTS_LOCKED"
    touch(event)
    return response.obj(serializers.event(event))


@bp.route("/sourcing/events/<event_id>", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def get_event(event_id):
    return response.obj(serializers.event(lookup.event(event_id)))


@bp.route("/sourcing/events", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def list_events():
    status = validate.enum_filter("status", enums.EVENT_STATUSES)
    program_type = validate.enum_filter("program_type", enums.PROGRAM_TYPES)
    awarded_proposal_id = validate.str_filter("awarded_proposal_id")
    limit, offset = validate.pagination()
    rows = store.ordered(db.events.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    if program_type:
        rows = [r for r in rows if r["program_type"] == program_type]
    if awarded_proposal_id:
        rows = [r for r in rows
                if r["awarded_proposal_id"] == awarded_proposal_id]
    return validate.page(rows, limit, offset, serializers.event)


@bp.route("/sourcing/events/<event_id>/cost-comparison", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def cost_comparison(event_id):
    event = lookup.event(event_id)
    limit, offset = validate.pagination()

    rows = []
    for proposal in rollups.live_proposals_of_event(event["id"]):
        contracted = calc.cost_model(proposal, "CONTRACTED_BASIS")["total_cost_usd"]
        actualized = calc.cost_model(proposal, "ACTUALIZED_BASIS")["total_cost_usd"]
        venue = db.venues.get(proposal["venue_id"])
        rows.append({
            "sort_key": (contracted, proposal["created_at"], proposal["_seq"]),
            "row": {
                "proposal_id": proposal["id"],
                "venue_id": proposal["venue_id"],
                "venue_name": venue["name"] if venue else None,
                "status": proposal["status"],
                "total_cost_contracted_usd": float(contracted),
                "total_cost_actualized_usd": float(actualized),
                "variant_delta_usd": float(q2(contracted - actualized)),
                "benchmark_variance_pct": (
                    float(proposal["benchmark_variance_pct"])
                    if proposal["benchmark_variance_pct"] is not None else None
                ),
                "compliance_status": proposal["compliance_status"],
                "within_budget": contracted <= event["budget_ceiling_usd"],
            },
        })
    rows.sort(key=lambda item: item["sort_key"])
    ordered_rows = [item["row"] for item in rows]
    total = len(ordered_rows)
    window = ordered_rows[offset:offset + limit]
    return response.collection(window, limit, offset, total)
