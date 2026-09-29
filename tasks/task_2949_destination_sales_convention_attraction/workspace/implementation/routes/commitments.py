"""Room block commitments: invitation, offer, commit, withdrawal and the
nightly pickup records (PRD 3.5, 3.9)."""

import datetime

from flask import Blueprint, request

import aggregates
import domain
import queries
import resolve
import serialize
from auth import (BOARD_ANALYST, BUREAU_ADMIN, HOTEL_PARTNER, SALES_MANAGER,
                  endpoint, require_owner)
from errors import ApiError, bad_request
from response import created, list_response, object_response, pagination
from store import db, ordered, touch
from util import money
from validation import (body_json, query_enum, query_str, req_date, req_enum,
                        req_int, req_money, req_ref)

bp = Blueprint("commitments", __name__)

READ_ROLES = (BUREAU_ADMIN, SALES_MANAGER, HOTEL_PARTNER, BOARD_ANALYST)

CLIENT_WITHDRAW_REASONS = ("PROPERTY_SOLD_OUT", "RATE_DISPUTE", "INVITE_DECLINED")
OFFERED_WITHDRAW_REASONS = ("PROPERTY_SOLD_OUT", "RATE_DISPUTE")


def _check_ceilings(commitment, opportunity, hotel, rooms, rate):
    """Both ceilings of PRD 3.5, re-applied at commit time."""
    if rate > opportunity["rate_ceiling_amount"]:
        raise ApiError("ERR_RATE_CEILING_EXCEEDED",
                       "The offered rate exceeds the lead's rate ceiling.")
    if rooms > hotel["committable_rooms"]:
        raise ApiError("ERR_RATE_CEILING_EXCEEDED",
                       "The offered rooms exceed the property's committable rooms.")


@bp.route("/room-block-commitments", methods=["POST"])
@endpoint(SALES_MANAGER)
def create_commitment():
    body = body_json()
    opportunity_id = req_ref(body, "opportunity_id")
    hotel_id = req_ref(body, "hotel_id")
    rooms_peak_invited = req_int(body, "rooms_peak_invited", minimum=1)
    expected_version = req_int(body, "expected_opportunity_version", minimum=0)

    opportunity = resolve.opportunity(opportunity_id)
    hotel = resolve.hotel(hotel_id)

    if expected_version != opportunity["version"]:
        raise ApiError("ERR_STALE_OPPORTUNITY_VERSION",
                       "Assembling a block from a stale coverage view is refused.")
    if opportunity["sales_stage"] not in ("QUALIFIED", "BIDDING"):
        raise ApiError("ERR_INVALID_OPPORTUNITY_STAGE",
                       "A block is assembled only for a lead in QUALIFIED or BIDDING.")
    if hotel["participation_status"] != "PARTICIPATING":
        raise ApiError("ERR_HOTEL_NOT_PARTICIPATING",
                       "A SUSPENDED property may not be invited into a block.")
    for other in queries.commitments_of_opportunity(opportunity["id"]):
        if (other["hotel_id"] == hotel["id"]
                and other["status"] in domain.LIVE_COMMITMENT_STATUSES):
            raise ApiError("ERR_DUPLICATE_COMMITMENT",
                           "That property is already in this lead's block.")

    row = db.new_row()
    row.update({
        "opportunity_id": opportunity["id"],
        "hotel_id": hotel["id"],
        "rooms_peak_invited": rooms_peak_invited,
        "rooms_peak_offered": None,
        "rate_offered_amount": None,
        "cutoff_days_before_arrival": None,
        "cutoff_date": None,
        "offer_round": 0,
        "status": "INVITED",
        "withdraw_reason": None,
        "rooms_peak_committed": 0,
        "committed_room_nights": 0,
        "picked_up_room_nights": 0,
        "attrition_shortfall_nights": 0,
        "attrition_damages_amount": money(0),
    })
    db.commitments[row["id"]] = row
    touch(opportunity)
    return created(serialize.commitment(row))


@bp.route("/room-block-commitments/<row_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_commitment(row_id):
    return object_response(serialize.commitment(resolve.commitment(row_id)))


@bp.route("/room-block-commitments", methods=["GET"])
@endpoint(*READ_ROLES)
def list_commitments():
    opportunity_id = query_str(request.args, "opportunity_id")
    hotel_id = query_str(request.args, "hotel_id")
    status = query_enum(request.args, "status", domain.COMMITMENT_STATUSES)
    limit, offset = pagination(request.args)
    rows = ordered(list(db.commitments.values()))
    if opportunity_id is not None:
        rows = [r for r in rows if r["opportunity_id"] == opportunity_id]
    if hotel_id is not None:
        rows = [r for r in rows if r["hotel_id"] == hotel_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serialize.commitment, limit, offset)


@bp.route("/room-block-commitments/<row_id>/offer", methods=["POST"])
@endpoint(HOTEL_PARTNER)
def offer(row_id):
    commitment = resolve.commitment(row_id)
    require_owner(commitment["hotel_id"],
                  "A property may only answer its own invitation.")
    body = body_json()
    rooms = req_int(body, "rooms_peak_offered", minimum=0)
    rate = req_money(body, "rate_offered_amount")
    cutoff_days = req_int(body, "cutoff_days_before_arrival", minimum=0)

    if commitment["status"] not in ("INVITED", "OFFERED"):
        raise ApiError("ERR_INVALID_COMMITMENT_STATE",
                       "Only an INVITED or OFFERED commitment may be offered on.")
    hotel = db.hotels.get(commitment["hotel_id"])
    if hotel["participation_status"] != "PARTICIPATING":
        raise ApiError("ERR_HOTEL_NOT_PARTICIPATING",
                       "A SUSPENDED property may not answer an invitation.")
    opportunity = db.opportunities.get(commitment["opportunity_id"])
    _check_ceilings(commitment, opportunity, hotel, rooms, rate)

    commitment["rooms_peak_offered"] = rooms
    commitment["rate_offered_amount"] = rate
    commitment["cutoff_days_before_arrival"] = cutoff_days
    commitment["cutoff_date"] = (opportunity["arrival_date"]
                                 - datetime.timedelta(days=cutoff_days))
    commitment["offer_round"] += 1
    commitment["status"] = "OFFERED"
    touch(commitment)
    return object_response(serialize.commitment(commitment))


@bp.route("/room-block-commitments/<row_id>/commit", methods=["POST"])
@endpoint(SALES_MANAGER)
def commit(row_id):
    commitment = resolve.commitment(row_id)
    opportunity = db.opportunities.get(commitment["opportunity_id"])
    if opportunity["sales_stage"] not in ("QUALIFIED", "BIDDING"):
        raise ApiError("ERR_INVALID_OPPORTUNITY_STAGE",
                       "A block is committed only for a lead in QUALIFIED or BIDDING.")
    if commitment["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_COMMITMENT_STATE",
                       "Only an OFFERED commitment may be committed.")
    hotel = db.hotels.get(commitment["hotel_id"])
    if hotel["participation_status"] != "PARTICIPATING":
        raise ApiError("ERR_HOTEL_NOT_PARTICIPATING",
                       "A SUSPENDED property may not have an offer committed.")
    _check_ceilings(commitment, opportunity, hotel,
                    commitment["rooms_peak_offered"],
                    commitment["rate_offered_amount"])

    # the per-night inventory check: one property sits in several citywide
    # blocks at once, and landing exactly on committable_rooms is allowed
    loads = aggregates.hotel_night_loads(hotel["id"])
    for night in aggregates.opportunity_nights(opportunity):
        if (loads.get(night, 0) + commitment["rooms_peak_offered"]
                > hotel["committable_rooms"]):
            raise ApiError("ERR_HOTEL_CAPACITY_EXCEEDED",
                           "The property has no room left on at least one night.")

    commitment["status"] = "COMMITTED"
    commitment["rooms_peak_committed"] = commitment["rooms_peak_offered"]
    commitment["committed_room_nights"] = (commitment["rooms_peak_committed"]
                                           * opportunity["event_nights"])
    touch(commitment)
    aggregates.recompute_hotel(hotel)
    aggregates.recompute_block(opportunity)
    touch(opportunity)
    return object_response(serialize.commitment(commitment))


@bp.route("/room-block-commitments/<row_id>/withdraw", methods=["POST"])
@endpoint(HOTEL_PARTNER)
def withdraw(row_id):
    commitment = resolve.commitment(row_id)
    require_owner(commitment["hotel_id"],
                  "A property may only withdraw from its own commitment.")
    body = body_json()
    reason = req_enum(body, "withdraw_reason", CLIENT_WITHDRAW_REASONS)

    was = commitment["status"]
    if was not in domain.LIVE_COMMITMENT_STATUSES:
        raise ApiError("ERR_INVALID_COMMITMENT_STATE",
                       "Only an INVITED, OFFERED or COMMITTED commitment may be "
                       "withdrawn.")
    opportunity = db.opportunities.get(commitment["opportunity_id"])
    if opportunity["sales_stage"] == "SERVICED":
        raise ApiError("ERR_INVALID_OPPORTUNITY_STAGE",
                       "Withdrawal is permitted only while the lead has not reached "
                       "SERVICED.")
    # the three arms are deliberately asymmetric in the reason each accepts
    if was == "INVITED":
        if reason != "INVITE_DECLINED":
            raise bad_request(
                "An INVITED commitment may only be withdrawn as INVITE_DECLINED.")
    elif reason not in OFFERED_WITHDRAW_REASONS:
        raise bad_request(
            "Field 'withdraw_reason' must be one of %s."
            % ", ".join(OFFERED_WITHDRAW_REASONS))

    commitment["status"] = "WITHDRAWN"
    commitment["withdraw_reason"] = reason
    touch(commitment)

    if was == "COMMITTED":
        # hop 2: rooms have left the block
        commitment["rooms_peak_committed"] = 0
        commitment["committed_room_nights"] = 0
        aggregates.recompute_hotel(db.hotels.get(commitment["hotel_id"]))
        aggregates.recompute_block(opportunity)
        # hops 3 and 4: a SUBMITTED bid falls back to DRAFT and its charge
        # is decommitted once coverage drops under the floor
        aggregates.apply_coverage_drop(opportunity)
    # every arm increments the opportunity's version by exactly one
    touch(opportunity)
    return object_response(serialize.commitment(commitment))


@bp.route("/room-block-commitments/<row_id>/pickup-records", methods=["POST"])
@endpoint(HOTEL_PARTNER)
def create_pickup(row_id):
    commitment = resolve.commitment(row_id)
    require_owner(commitment["hotel_id"],
                  "A property may only report pickup on its own commitment.")
    body = body_json()
    night_date = req_date(body, "night_date")
    rooms = req_int(body, "rooms_picked_up", minimum=0)
    rate = req_money(body, "rate_charged_amount")

    if commitment["status"] not in ("COMMITTED", "RELEASED"):
        raise ApiError("ERR_INVALID_COMMITMENT_STATE",
                       "Pickup is reported only against a COMMITTED or RELEASED "
                       "commitment.")
    opportunity = db.opportunities.get(commitment["opportunity_id"])
    if not (opportunity["arrival_date"] <= night_date
            < opportunity["departure_date"]):
        raise ApiError("ERR_PICKUP_NIGHT_OUT_OF_RANGE",
                       "The night lies outside the block's occupied nights.")
    for other in queries.pickups_of_commitment(commitment["id"]):
        if other["night_date"] == night_date:
            raise ApiError("ERR_DUPLICATE_PICKUP_NIGHT",
                           "That night is already reported on this commitment.")

    row = db.new_row(versioned=False)
    row.update({
        "room_block_commitment_id": commitment["id"],
        "night_date": night_date,
        "rooms_picked_up": rooms,
        "rate_charged_amount": rate,
        "room_night_revenue_amount": money(rate * rooms),
    })
    db.pickup_records[row["id"]] = row

    commitment["picked_up_room_nights"] += rooms
    aggregates.recompute_commitment_attrition(commitment)
    touch(commitment)
    aggregates.add_hotel_pickup(db.hotels.get(commitment["hotel_id"]), rooms)
    if aggregates.recompute_settlement(opportunity):
        touch(opportunity)
    return created(serialize.pickup_record(row))


@bp.route("/room-block-commitments/<row_id>/pickup-records", methods=["GET"])
@endpoint(*READ_ROLES)
def list_pickups(row_id):
    commitment = resolve.commitment(row_id)
    limit, offset = pagination(request.args)
    rows = queries.pickups_of_commitment(commitment["id"])
    return list_response(rows, serialize.pickup_record, limit, offset)
