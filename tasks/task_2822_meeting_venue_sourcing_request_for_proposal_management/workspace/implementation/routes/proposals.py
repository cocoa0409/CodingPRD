"""Bid endpoints (PRD sections 3.5 and 3.6)."""
from decimal import Decimal

from flask import Blueprint, g

import clock
import db as store
import enums
import lookup
import middleware
import response
import serializers
import validate
from db import db, touch
from errors import ApiError
from services import calc, flows, rollups

bp = Blueprint("proposals", __name__)


def _read_quoted_terms(data):
    return {
        "room_rate_usd": validate.req_money(data, "room_rate_usd"),
        "rate_type": validate.req_enum(data, "rate_type", enums.RATE_TYPES),
        "commission_pct": validate.req_pct(data, "commission_pct",
                                           high=Decimal("0.20")),
        "room_nights_offered": validate.req_int(data, "room_nights_offered",
                                                minimum=0),
        "comp_room_ratio": validate.req_int(data, "comp_room_ratio", minimum=0),
        "resort_fee_usd_per_night": validate.req_money(
            data, "resort_fee_usd_per_night"),
        "service_charge_pct": validate.req_pct(data, "service_charge_pct"),
        "tax_pct": validate.req_pct(data, "tax_pct"),
        "av_estimate_usd": validate.req_money(data, "av_estimate_usd"),
        "fnb_minimum_usd": validate.req_money(data, "fnb_minimum_usd"),
        "concession_credit_usd": validate.req_money(data, "concession_credit_usd"),
        "attrition_allowance_pct": validate.req_pct(
            data, "attrition_allowance_pct", high=Decimal("0.50")),
        "cancellation_schedule": validate.req_schedule(data,
                                                       "cancellation_schedule"),
        "force_majeure_scope": validate.req_enum(data, "force_majeure_scope",
                                                 enums.FORCE_MAJEURE_SCOPES),
        "rebooking_credit_pct": validate.req_pct(data, "rebooking_credit_pct",
                                                 high=Decimal("1")),
    }


@bp.route("/sourcing/proposals/<proposal_id>/submit", methods=["POST"])
@middleware.roles(middleware.ROLE_VENUE_REP)
def submit(proposal_id):
    proposal = lookup.proposal(proposal_id)
    middleware.own_venue(proposal["venue_id"])
    data = validate.body()
    terms = _read_quoted_terms(data)

    if proposal["status"] != "INVITED":
        raise ApiError("ERR_PROPOSAL_STATE_INVALID",
                       "Only an INVITED bid may be submitted")

    rfp = db.rfps[proposal["rfp_id"]]
    if rfp["status"] != "ISSUED":
        raise ApiError("ERR_RFP_NOT_OPEN", "The solicitation round is not ISSUED")

    event = db.events[rfp["event_id"]]
    venue = db.venues[proposal["venue_id"]]
    benchmark = flows.require_benchmark(venue, event)

    if clock.now() > rfp["response_due_at"]:
        raise ApiError("ERR_RESPONSE_DEADLINE_PASSED",
                       "The response deadline has passed")

    proposal.update(terms)
    proposal["status"] = "SUBMITTED"
    proposal["submitted_at"] = clock.now()
    flows.apply_contracted_pricing(proposal, venue, benchmark)
    touch(proposal)

    rollups.refresh_submitted_count(rfp)
    touch(rfp)
    rollups.refresh_event_rollup(event)
    touch(event)
    return response.obj(serializers.proposal(proposal))


@bp.route("/sourcing/proposals/<proposal_id>/decline", methods=["POST"])
@middleware.roles(middleware.ROLE_VENUE_REP)
def decline(proposal_id):
    proposal = lookup.proposal(proposal_id)
    middleware.own_venue(proposal["venue_id"])
    if proposal["status"] != "INVITED":
        raise ApiError("ERR_PROPOSAL_STATE_INVALID",
                       "Only an INVITED bid may be declined")
    proposal["status"] = "DECLINED"
    touch(proposal)
    return response.obj(serializers.proposal(proposal))


@bp.route("/sourcing/proposals/<proposal_id>/withdraw", methods=["POST"])
@middleware.roles(middleware.ROLE_VENUE_REP)
def withdraw(proposal_id):
    proposal = lookup.proposal(proposal_id)
    middleware.own_venue(proposal["venue_id"])
    if proposal["status"] not in enums.LIVE_PROPOSAL_STATUSES:
        raise ApiError("ERR_PROPOSAL_STATE_INVALID", "This bid cannot be withdrawn")

    proposal["status"] = "WITHDRAWN"
    touch(proposal)

    rfp = db.rfps[proposal["rfp_id"]]
    rollups.refresh_submitted_count(rfp)
    touch(rfp)
    event = db.events[rfp["event_id"]]
    rollups.refresh_event_rollup(event)
    touch(event)
    return response.obj(serializers.proposal(proposal))


@bp.route("/sourcing/proposals/<proposal_id>/evaluate", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def evaluate(proposal_id):
    proposal = lookup.proposal(proposal_id)
    data = validate.body()
    basis = validate.req_enum(data, "basis", enums.EVALUATION_BASES)

    if proposal["status"] not in ("SUBMITTED", "UNDER_REVIEW", "REVISED"):
        raise ApiError("ERR_PROPOSAL_STATE_INVALID",
                       "This bid cannot be evaluated in its current status")

    event = lookup.event_of_proposal(proposal)
    venue = db.venues[proposal["venue_id"]]
    benchmark = lookup.find_benchmark(venue["destination_tier"],
                                      event["program_type"])
    model = calc.cost_model(proposal, basis)

    row = store.base_row(versioned=False)
    row.update({
        "proposal_id": proposal["id"],
        "basis": basis,
        "evaluated_by_user_id": g.user_id,
        "paid_room_nights_used": model["paid_room_nights_used"],
        "room_revenue_usd": model["room_revenue_usd"],
        "resort_fee_total_usd": model["resort_fee_total_usd"],
        "av_adjusted_usd": model["av_adjusted_usd"],
        "fnb_usd": model["fnb_usd"],
        "service_charge_usd": model["service_charge_usd"],
        "tax_usd": model["tax_usd"],
        "concession_applied_usd": model["concession_applied_usd"],
        "attrition_damages_usd": model["attrition_damages_usd"],
        "total_cost_usd": model["total_cost_usd"],
        "benchmark_adr_usd": (
            benchmark["benchmark_adr_usd"] if benchmark else None
        ),
        "evaluated_at": clock.now(),
    })
    db.evaluations[row["id"]] = row

    proposal["total_cost_modeled_usd"] = model["total_cost_usd"]
    proposal["last_evaluation_basis"] = basis
    proposal["status"] = "UNDER_REVIEW"
    touch(proposal)
    return response.obj(serializers.evaluation(row), 201)


@bp.route("/sourcing/proposals/<proposal_id>/counters", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def create_counter(proposal_id):
    proposal = lookup.proposal(proposal_id)
    data = validate.body()
    expected_version = validate.req_int(data, "expected_proposal_version")
    term_category = validate.req_enum(data, "term_category",
                                      enums.TERM_CATEGORIES)
    proposed_numeric_value = validate.opt_money(data, "proposed_numeric_value",
                                                minimum=None)
    proposed_text_value = validate.opt_str(data, "proposed_text_value")
    planner_note = validate.opt_str(data, "planner_note")

    if proposal["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_PROPOSAL_STATE_INVALID",
                       "Only a bid UNDER_REVIEW may be countered")

    if expected_version != proposal["version"]:
        raise ApiError("ERR_STALE_PROPOSAL_VERSION",
                       "expected_proposal_version does not match the bid")

    rfp = db.rfps[proposal["rfp_id"]]
    if rfp["status"] != "ISSUED":
        raise ApiError("ERR_RFP_NOT_OPEN", "The solicitation round is not ISSUED")

    row = store.base_row()
    row.update({
        "proposal_id": proposal["id"],
        "round_seq": proposal["negotiation_round_count"] + 1,
        "term_category": term_category,
        "proposed_numeric_value": proposed_numeric_value,
        "proposed_text_value": proposed_text_value,
        "planner_note": planner_note,
        "initiated_by_user_id": g.user_id,
        "resolution": "OPEN",
        "resolved_at": None,
    })
    db.counters[row["id"]] = row

    proposal["status"] = "COUNTERED"
    proposal["negotiation_round_count"] = proposal["negotiation_round_count"] + 1
    touch(proposal)
    return response.obj(serializers.counter(row), 201)


REVISED_FIELDS = (
    ("revised_room_rate_usd", "room_rate_usd", "money", None),
    ("revised_concession_credit_usd", "concession_credit_usd", "money", None),
    ("revised_attrition_allowance_pct", "attrition_allowance_pct", "pct",
     Decimal("0.50")),
    ("revised_cancellation_schedule", "cancellation_schedule", "schedule", None),
    ("revised_force_majeure_scope", "force_majeure_scope", "enum", None),
    ("revised_rebooking_credit_pct", "rebooking_credit_pct", "pct", Decimal("1")),
    ("revised_av_estimate_usd", "av_estimate_usd", "money", None),
    ("revised_fnb_minimum_usd", "fnb_minimum_usd", "money", None),
)


def _read_revised_terms(data):
    updates = {}
    for source, target, kind, high in REVISED_FIELDS:
        if data.get(source) is None:
            continue
        if kind == "money":
            updates[target] = validate.req_money(data, source)
        elif kind == "pct":
            updates[target] = validate.req_pct(data, source, high=high)
        elif kind == "schedule":
            updates[target] = validate.req_schedule(data, source)
        else:
            updates[target] = validate.req_enum(data, source,
                                                enums.FORCE_MAJEURE_SCOPES)
    return updates


@bp.route("/sourcing/proposals/<proposal_id>/revise", methods=["POST"])
@middleware.roles(middleware.ROLE_VENUE_REP)
def revise(proposal_id):
    proposal = lookup.proposal(proposal_id)
    middleware.own_venue(proposal["venue_id"])
    data = validate.body()

    counter = None
    raw_counter_id = data.get("counter_id")
    if raw_counter_id is not None:
        if not isinstance(raw_counter_id, str):
            validate.bad("Field counter_id must be a string")
        counter = lookup.counter(raw_counter_id)

    validate.req_str(data, "counter_id")
    accepted = validate.req_bool(data, "accepted")
    updates = _read_revised_terms(data)

    if proposal["status"] != "COUNTERED":
        raise ApiError("ERR_PROPOSAL_STATE_INVALID",
                       "Only a COUNTERED bid may be revised")

    if counter["proposal_id"] != proposal["id"] or counter["resolution"] != "OPEN":
        raise ApiError("ERR_COUNTER_NOT_OPEN",
                       "The counter does not belong to this bid or is resolved")

    event = lookup.event_of_proposal(proposal)
    venue = db.venues[proposal["venue_id"]]
    benchmark = flows.require_benchmark(venue, event)

    counter["resolution"] = "ACCEPTED" if accepted else "DECLINED_BY_VENUE"
    counter["resolved_at"] = clock.now()
    touch(counter)

    proposal.update(updates)
    flows.apply_contracted_pricing(proposal, venue, benchmark)
    proposal["status"] = "REVISED"
    touch(proposal)

    rollups.refresh_event_rollup(event)
    touch(event)
    return response.obj(serializers.proposal(proposal))


@bp.route("/sourcing/proposals/<proposal_id>", methods=["GET"])
@middleware.roles(*middleware.ALL_ROLES)
def get_proposal(proposal_id):
    return response.obj(serializers.proposal(lookup.proposal(proposal_id)))


@bp.route("/sourcing/proposals", methods=["GET"])
@middleware.roles(*middleware.ALL_ROLES)
def list_proposals():
    status = validate.enum_filter("status", enums.PROPOSAL_STATUSES)
    rfp_id = validate.str_filter("rfp_id")
    venue_id = validate.str_filter("venue_id")
    limit, offset = validate.pagination()
    rows = store.ordered(db.proposals.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    if rfp_id:
        rows = [r for r in rows if r["rfp_id"] == rfp_id]
    if venue_id:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    return validate.page(rows, limit, offset, serializers.proposal)


@bp.route("/sourcing/proposals/<proposal_id>/bid-evaluations", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def list_evaluations(proposal_id):
    proposal = lookup.proposal(proposal_id)
    limit, offset = validate.pagination()
    basis = validate.enum_filter("basis", enums.EVALUATION_BASES)
    rows = lookup.evaluations_of_proposal(proposal["id"])
    if basis is not None:
        rows = [r for r in rows if r["basis"] == basis]
    return validate.page(rows, limit, offset, serializers.evaluation)


@bp.route("/sourcing/proposals/<proposal_id>/negotiation-counters", methods=["GET"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER, middleware.ROLE_VENUE_REP,
                  middleware.ROLE_CONTRACT_APPROVER, middleware.ROLE_PROGRAM_ADMIN)
def list_counters(proposal_id):
    proposal = lookup.proposal(proposal_id)
    limit, offset = validate.pagination()
    resolution = validate.enum_filter("resolution", enums.COUNTER_RESOLUTIONS)
    rows = lookup.counters_of_proposal(proposal["id"])
    if resolution is not None:
        rows = [r for r in rows if r["resolution"] == resolution]
    return validate.page(rows, limit, offset, serializers.counter)
