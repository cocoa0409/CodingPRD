"""Solicitation round endpoints (PRD section 3.4)."""
from flask import Blueprint

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
from money import q2
from services import rollups

bp = Blueprint("rfps", __name__)

RFP_EVENT_STATUSES = ("REQUIREMENTS_LOCKED", "BID_REVIEW")


@bp.route("/sourcing/events/<event_id>/rfps", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def draft_rfp(event_id):
    event = lookup.event(event_id)
    data = validate.body()

    previous = None
    raw_previous = data.get("previous_rfp_id")
    if raw_previous is not None:
        if not isinstance(raw_previous, str):
            validate.bad("Field previous_rfp_id must be a string")
        previous = lookup.rfp(raw_previous)

    round_number = validate.req_int(data, "round_number", minimum=1)
    response_due_at = validate.req_instant(data, "response_due_at")
    standard_response_version = validate.req_enum(
        data, "standard_response_version", enums.RESPONSE_VERSIONS
    )
    instructions = validate.opt_str(data, "instructions")

    for existing in lookup.rfps_of_event(event["id"]):
        if existing["round_number"] == round_number:
            raise ApiError("ERR_RFP_ROUND_DUPLICATE",
                           "This round number is already used on the event")

    if event["status"] not in RFP_EVENT_STATUSES:
        raise ApiError("ERR_EVENT_STATE_INVALID",
                       "The event does not admit a new solicitation round")

    if round_number > 1:
        if (previous is None
                or previous["event_id"] != event["id"]
                or previous["status"] != "CLOSED"):
            raise ApiError("ERR_PREVIOUS_ROUND_NOT_CLOSED",
                           "A later round must chain to a CLOSED round of this event")
    elif previous is not None:
        raise ApiError("ERR_PREVIOUS_ROUND_NOT_CLOSED",
                       "Round 1 must not chain to a previous round")

    if (response_due_at <= clock.now()
            or response_due_at >= clock.day_start(event["start_date"])):
        raise ApiError("ERR_RESPONSE_DUE_OUT_OF_RANGE",
                       "response_due_at is outside the permitted window")

    row = store.base_row()
    row.update({
        "event_id": event["id"],
        "round_number": round_number,
        "previous_rfp_id": previous["id"] if previous else None,
        "response_due_at": response_due_at,
        "standard_response_version": standard_response_version,
        "instructions": instructions,
        "status": "DRAFT",
        "invited_count": 0,
        "submitted_count": 0,
        "issued_at": None,
        "closed_at": None,
    })
    db.rfps[row["id"]] = row
    return response.obj(serializers.rfp(row), 201)


def _blank_proposal(rfp, venue_id):
    row = store.base_row()
    row.update({
        "rfp_id": rfp["id"],
        "venue_id": venue_id,
        "status": "INVITED",
        "room_rate_usd": None,
        "rate_type": None,
        "commission_pct": None,
        "room_nights_offered": None,
        "comp_room_ratio": None,
        "resort_fee_usd_per_night": None,
        "service_charge_pct": None,
        "tax_pct": None,
        "av_estimate_usd": None,
        "fnb_minimum_usd": None,
        "concession_credit_usd": None,
        "attrition_allowance_pct": None,
        "cancellation_schedule": None,
        "force_majeure_scope": None,
        "rebooking_credit_pct": None,
        "net_adr_usd": None,
        "comp_room_nights": None,
        "paid_room_nights": None,
        "total_cost_contracted_usd": None,
        "total_cost_modeled_usd": None,
        "last_evaluation_basis": None,
        "benchmark_variance_pct": None,
        "compliance_status": "NOT_EVALUATED",
        "negotiation_round_count": 0,
        "submitted_at": None,
    })
    db.proposals[row["id"]] = row
    return row


@bp.route("/sourcing/rfps/<rfp_id>/issue", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def issue_rfp(rfp_id):
    rfp = lookup.rfp(rfp_id)
    event = db.events[rfp["event_id"]]

    if rfp["status"] != "DRAFT":
        raise ApiError("ERR_RFP_STATE_INVALID", "Only a DRAFT round may be issued")
    if event["status"] not in RFP_EVENT_STATUSES:
        raise ApiError("ERR_EVENT_STATE_INVALID",
                       "The event does not admit issuing a round")

    eligible = [
        e for e in lookup.entries_of_event(event["id"])
        if e["status"] in enums.RFP_ELIGIBLE_ENTRY_STATUSES
    ]
    if not eligible:
        raise ApiError("ERR_NO_SHORTLISTED_VENUES",
                       "The event has no eligible shortlist entries")
    for entry in eligible:
        if entry["inspection_required"] and entry["status"] != "INSPECTED":
            raise ApiError("ERR_INSPECTION_INCOMPLETE",
                           "An entry requiring inspection has not been inspected")

    if (clock.now() >= rfp["response_due_at"]
            or rfp["response_due_at"] >= clock.day_start(event["start_date"])):
        raise ApiError("ERR_RESPONSE_DUE_OUT_OF_RANGE",
                       "response_due_at is no longer in the permitted window")

    rfp["issued_at"] = clock.now()
    rfp["status"] = "ISSUED"

    created = 0
    for entry in sorted(eligible, key=lambda e: e["rank_seq"]):
        _blank_proposal(rfp, entry["venue_id"])
        created += 1
        entry["status"] = "RFP_ISSUED"
        touch(entry)
    rfp["invited_count"] = created
    rollups.refresh_submitted_count(rfp)
    touch(rfp)

    event["status"] = "SOURCING"
    rollups.refresh_event_rollup(event)
    touch(event)
    return response.obj(serializers.rfp(rfp))


@bp.route("/sourcing/rfps/<rfp_id>/close", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def close_rfp(rfp_id):
    rfp = lookup.rfp(rfp_id)
    event = db.events[rfp["event_id"]]

    if rfp["status"] != "ISSUED":
        raise ApiError("ERR_RFP_STATE_INVALID", "Only an ISSUED round may be closed")

    rfp["closed_at"] = clock.now()
    rfp["status"] = "CLOSED"
    for proposal in lookup.proposals_of_rfp(rfp["id"]):
        if proposal["status"] == "INVITED":
            proposal["status"] = "EXPIRED"
            touch(proposal)
    rollups.refresh_submitted_count(rfp)
    touch(rfp)

    if event["status"] == "SOURCING":
        event["status"] = "BID_REVIEW"
    rollups.refresh_event_rollup(event)
    touch(event)
    return response.obj(serializers.rfp(rfp))


@bp.route("/sourcing/rfps/<rfp_id>", methods=["GET"])
@middleware.roles(*middleware.ALL_ROLES)
def get_rfp(rfp_id):
    return response.obj(serializers.rfp(lookup.rfp(rfp_id)))


@bp.route("/sourcing/rfps", methods=["GET"])
@middleware.roles(*middleware.ALL_ROLES)
def list_rfps():
    status = validate.enum_filter("status", enums.RFP_STATUSES)
    event_id = validate.str_filter("event_id")
    previous_rfp_id = validate.str_filter("previous_rfp_id")
    limit, offset = validate.pagination()
    rows = store.ordered(db.rfps.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    if event_id:
        rows = [r for r in rows if r["event_id"] == event_id]
    if previous_rfp_id:
        rows = [r for r in rows if r["previous_rfp_id"] == previous_rfp_id]
    return validate.page(rows, limit, offset, serializers.rfp)
