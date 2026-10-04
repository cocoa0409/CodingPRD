"""Load, LoadOffer and Trip routes — the board, the award and the haul."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from cascades import (
    decline_accepted_offer, open_offers_of, return_load_to_board,
    withdraw_open_offers,
)
from common import (
    STATE, ApiError, bad_request, body, client_fields, clock_dt, err, fetch,
    mint, ok, ok_list, paginate, parse_ts, query_str, require_auth, require_enum,
    require_int, require_role, require_state_code, require_text, require_ts,
    touch,
)
from domain import (
    EQUIPMENT_TURNAROUND_BUFFER_HOURS, ESCROW_MIN_CENTS, POWER_UNITS, compute_split,
    derive_offer_ranks, equipment_inspection_status, maintenance_reserve_for,
    non_solicitation_breached, present, present_all, sync_bco, sync_equipment,
    sync_load, sync_offer, sync_trip, territory_owner, customer_owned_by_other,
    board_required_of,
)
from entities import (
    active_trip_on, commitment_load_of, find_customer_account, last_delivered_at,
    new_offer_payload,
)

bp = Blueprint("loads", __name__)


# ─── Load ────────────────────────────────────────────────────────────────────
@bp.post("/network/loads")
def create_load():
    require_role("FreightAgent")
    payload = body()
    fields = client_fields(payload, [
        "agent_id", "customer_ref", "origin_state", "destination_state",
        "linehaul_revenue_cents", "fuel_surcharge_cents",
        "accessorial_revenue_cents", "dispatched_miles",
    ])
    agent = fetch("agent", require_text(fields, "agent_id"))
    customer_ref = require_text(fields, "customer_ref")
    origin = require_state_code(fields, "origin_state")
    destination = require_state_code(fields, "destination_state")
    linehaul = require_int(fields, "linehaul_revenue_cents", minimum=1)
    fuel = require_int(fields, "fuel_surcharge_cents", 0, minimum=0)
    accessorial = require_int(fields, "accessorial_revenue_cents", 0, minimum=0)
    miles = require_int(fields, "dispatched_miles", minimum=1)

    # Priority 7: the compliance gate runs before the load is written.
    if origin not in agent["territory_codes"]:
        raise ApiError("ERR_TERRITORY_VIOLATION", 422,
                       f"{origin} is not inside the promoting agent's territory.")
    if customer_owned_by_other(agent["id"], customer_ref, clock_dt()):
        raise ApiError("ERR_CUSTOMER_NON_SOLICITATION_ACTIVE", 422,
                       "The customer is inside another arrangement's live window.")
    if agent["settlement_hold"]:
        raise ApiError("ERR_AGENT_SETTLEMENT_HELD", 422,
                       "The agent is on settlement hold and may not promote loads.")

    if agent["status"] != "ACTIVE":
        raise ApiError("ERR_AGENT_SETTLEMENT_HELD", 422,
                       "The agent holds no live board position.")
    row = mint("loads", {
        "agent_id": agent["id"],
        "awarded_capacity_owner_id": None,
        "customer_ref": customer_ref,
        "origin_state": origin,
        "destination_state": destination,
        "linehaul_revenue_cents": linehaul,
        "fuel_surcharge_cents": fuel,
        "accessorial_revenue_cents": accessorial,
        "dispatched_miles": miles,
        "board_required": True,
        "status": "POSTED",
    })
    sync_load(row, bump=False)
    return ok(present("load", row), 201)


@bp.get("/network/loads")
def list_loads():
    require_role("FreightAgent", "CapacityOwnerOperator", "SettlementOperator",
                 "NetworkAdministrator")
    rows = list(STATE.loads.values())
    agent_id = query_str("agent_id")
    awarded = query_str("awarded_capacity_owner_id")
    status = query_str("status")
    origin = query_str("origin_state")
    if agent_id:
        rows = [r for r in rows if r["agent_id"] == agent_id]
    if awarded:
        rows = [r for r in rows if r["awarded_capacity_owner_id"] == awarded]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if origin:
        rows = [r for r in rows if r["origin_state"] == origin]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("load", page), total, limit, offset)


def _load_row(row_id):
    return fetch("load", row_id)


@bp.get("/network/loads/<row_id>")
def get_load(row_id):
    require_role("FreightAgent", "CapacityOwnerOperator", "SettlementOperator",
                 "NetworkAdministrator")
    return ok(present("load", _load_row(row_id)))


@bp.post("/network/loads/<row_id>/cancel")
def cancel_load(row_id):
    require_role("FreightAgent")
    load = _load_row(row_id)
    fields = client_fields(body(), ["reason_code"])
    require_text(fields, "reason_code")
    if load["status"] != "POSTED":
        raise ApiError("ERR_LOAD_NOT_CANCELLABLE", 409,
                       "Only a POSTED load may be cancelled.")
    if require_auth() == "FreightAgent" and load["agent_id"] != _user_id():
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "The caller does not own this load.")
    load["status"] = "CANCELLED"
    withdraw_open_offers(row_id)
    sync_load(load)
    return ok(present("load", load))


@bp.post("/network/loads/<row_id>/settlement")
def evaluate_load_settlement(row_id):
    require_role("SettlementOperator", "NetworkAdministrator")
    load = _load_row(row_id)
    fields = client_fields(body(), ["settlement_method"])
    method = require_text(fields, "settlement_method")
    if load["status"] not in ("DELIVERED", "SETTLED"):
        raise ApiError("ERR_LOAD_NOT_SETTLEABLE", 409,
                       "Only a DELIVERED or SETTLED load may be settled.")
    trips = [t for t in STATE.trips.values()
             if t["load_id"] == row_id and t["status"] in ("DELIVERED", "COMPLETED")]
    if not trips:
        raise ApiError("ERR_LOAD_NOT_SETTLEABLE", 409,
                       "The load carries no completed trip to settle.")
    trip = sorted(trips, key=lambda t: t["created_at"])[-1]
    agent = STATE.agents[load["agent_id"]]
    bco = STATE.capacity_owners[trip["capacity_owner_id"]]
    figures = compute_split(load, agent, bco, trip, method)
    if figures is None:
        raise bad_request("settlement_method must be PROVISIONAL or FINAL.")
    from entities import record_split_flags
    record_split_flags(trip["id"], method)
    variants = STATE.split_variants[trip["id"]]
    if "PROVISIONAL" in variants and "FINAL" in variants:
        provisional = compute_split(load, agent, bco, trip, "PROVISIONAL")
        final = compute_split(load, agent, bco, trip, "FINAL")
        figures["variant_delta_cents"] = (
            final["net_owner_operator_pay_cents"]
            - provisional["net_owner_operator_pay_cents"])
    else:
        figures["variant_delta_cents"] = 0
    payload = {
        "agent_share_cents": figures["agent_share_cents"],
        "owner_operator_share_cents": figures["owner_operator_share_cents"],
        "company_share_cents": figures["company_share_cents"],
        "linehaul_revenue_allocated_cents": figures["linehaul_revenue_allocated_cents"],
        "fuel_surcharge_allocated_cents": figures["fuel_surcharge_allocated_cents"],
        "accessorial_allocated_cents": figures["accessorial_allocated_cents"],
        "oa_premium_cents": figures["oa_premium_cents"],
        "insurance_premium_cents": figures["insurance_premium_cents"],
        "escrow_withholding_cents": figures["escrow_withholding_cents"],
        "maintenance_withholding_cents": figures["maintenance_withholding_cents"],
        "advance_repayment_cents": figures["advance_repayment_cents"],
        "net_owner_operator_pay_cents": figures["net_owner_operator_pay_cents"],
        "net_agent_pay_cents": figures["net_agent_pay_cents"],
        "settled_total_cents": figures["settled_total_cents"],
        "variant_delta_cents": figures["variant_delta_cents"],
    }
    return ok(payload)


# ─── LoadOffer ───────────────────────────────────────────────────────────────
@bp.get("/network/load-offers/board")
def load_offer_board():
    require_role("FreightAgent", "CapacityOwnerOperator", "SettlementOperator",
                 "NetworkAdministrator")
    load_id = query_str("load_id")
    if not load_id:
        raise bad_request("load_id is required.")
    fetch("load", load_id)
    from domain import board_view
    rows = board_view(load_id)
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("load_offer", page), total, limit, offset)


@bp.post("/network/load-offers")
def create_load_offer():
    require_role("FreightAgent")
    payload = body()
    fields = client_fields(payload, [
        "load_id", "capacity_owner_id", "offered_pay_cents", "offered_at",
        "expected_network_load_version",
    ])
    load = fetch("load", require_text(fields, "load_id"))
    bco = fetch("capacity_owner", require_text(fields, "capacity_owner_id"))
    offered_pay = require_int(fields, "offered_pay_cents", minimum=1)
    offered_at = fields.get("offered_at")
    offered_dt = parse_ts(offered_at, "offered_at")
    expected = require_int(fields, "expected_network_load_version")
    if expected != load["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       f"expected load version {expected} does not match the "
                       f"current version {load['version']}.")
    if load["status"] != "POSTED" or not board_required_of(load):
        raise ApiError("ERR_LOAD_NOT_OPEN_FOR_AWARD", 409,
                       "The load is not open for award on the board.")
    from common import round_half_up_cents, dec
    ceiling = round_half_up_cents(
        dec(load["linehaul_revenue_cents"] + load["fuel_surcharge_cents"])
        * bco["revenue_split_pct"])
    if offered_pay > ceiling:
        raise ApiError("ERR_OFFER_EXCEEDS_PAY_CEILING", 400,
                       f"offered_pay_cents {offered_pay} exceeds the ceiling {ceiling}.")
    row = mint("load_offers", new_offer_payload(load, bco, offered_pay, offered_at))
    row["owner_pay_ceiling_cents"] = ceiling
    derive_offer_ranks(load["id"], bump=False)
    sync_load(load)
    return ok(present("load_offer", row), 201)


@bp.get("/network/load-offers")
def list_load_offers():
    require_role("FreightAgent", "CapacityOwnerOperator", "SettlementOperator",
                 "NetworkAdministrator")
    rows = list(STATE.load_offers.values())
    load_id = query_str("load_id")
    owner_id = query_str("capacity_owner_id")
    status = query_str("status")
    if load_id:
        rows = [r for r in rows if r["load_id"] == load_id]
    if owner_id:
        rows = [r for r in rows if r["capacity_owner_id"] == owner_id]
    for row in rows:
        sync_offer(row, bump=False)
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("load_offer", page), total, limit, offset)


@bp.get("/network/loads/<row_id>/load-offers")
def list_load_board_offers(row_id):
    require_role("FreightAgent", "CapacityOwnerOperator", "SettlementOperator",
                 "NetworkAdministrator")
    fetch("load", row_id)
    from domain import board_view
    rows = board_view(row_id)
    status = query_str("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("load_offer", page), total, limit, offset)


def _offer_row(row_id):
    return fetch("offer", row_id)


@bp.get("/network/load-offers/<row_id>")
def get_load_offer(row_id):
    require_role("FreightAgent", "CapacityOwnerOperator", "SettlementOperator",
                 "NetworkAdministrator")
    row = _offer_row(row_id)
    sync_offer(row, bump=False)
    return ok(present("load_offer", row))


@bp.post("/network/load-offers/<row_id>/accept")
def accept_load_offer(row_id):
    require_role("CapacityOwnerOperator")
    offer = _offer_row(row_id)
    fields = client_fields(body(), ["accepted_at"])
    accepted_at = fields.get("accepted_at")
    if accepted_at is not None:
        parse_ts(accepted_at, "accepted_at")
    sync_offer(offer, bump=False)
    load = STATE.loads[offer["load_id"]]
    bco = STATE.capacity_owners[offer["capacity_owner_id"]]

    # Priority 4: the offer's own state, then its live window.
    if offer["status"] != "OPEN":
        raise ApiError("ERR_OFFER_NOT_OPEN", 409, "The offer is not OPEN.")
    if clock_dt() >= parse_ts(offer["_expires_at"], "expires_at"):
        raise ApiError("ERR_OFFER_EXPIRED", 409, "The offer has reached its expiry.")
    # The board selector policy is evaluated before the acting party is named.
    if offer["selected_rank"] != 1:
        raise ApiError("ERR_OFFER_NOT_TOP_RANKED", 409,
                       "The offer is not the top-ranked open offer on its load.")
    # Priority 5: ownership.
    if require_auth() == "CapacityOwnerOperator" and _user_id() != offer["capacity_owner_id"]:
        raise ApiError("ERR_OFFER_NOT_DIRECTED_TO_CAPACITY_OWNER", 403,
                       "The offer was directed to a different capacity owner.")
    # Priority 4 (continued): the load's award state.
    if load["status"] != "POSTED" or not board_required_of(load):
        raise ApiError("ERR_LOAD_NOT_OPEN_FOR_AWARD", 409,
                       "The load is not open for award.")
    # Priority 6: business safety.
    if bco["status"] != "QUALIFIED":
        raise ApiError("ERR_CAPACITY_OWNER_NOT_QUALIFIED_CLEAR", 422,
                       "The capacity owner is not qualified to haul.")
    units = [e for e in STATE.equipment.values()
             if e["capacity_owner_id"] == bco["id"]]
    if not units:
        raise ApiError("ERR_EQUIPMENT_FLEET_EMPTY", 400,
                       "The capacity owner owns no fleet unit, so the award "
                       "cannot be covered.")
    if commitment_load_of(bco["id"]) is not None:
        raise ApiError("ERR_CAPACITY_OWNER_BUSY", 409,
                       "The capacity owner already holds a non-terminal load.")
    # Priority 7: compliance gate.
    agent = STATE.agents[load["agent_id"]]
    if load["origin_state"] not in agent["territory_codes"]:
        raise ApiError("ERR_TERRITORY_VIOLATION", 422,
                       "The load's origin state is outside the agent's territory.")
    if non_solicitation_breached(load, clock_dt()):
        raise ApiError("ERR_NON_SOLICITATION_BREACH", 422,
                       "The load matches a customer inside the non-solicitation radius.")
    offer["status"] = "ACCEPTED"
    touch(offer)
    load["awarded_capacity_owner_id"] = bco["id"]
    load["status"] = "AWARDED"
    for other in STATE.load_offers.values():
        if other["id"] == offer["id"] or other["load_id"] != load["id"]:
            continue
        if other["status"] == "OPEN":
            other["status"] = "DECLINED"
            other["selected_rank"] = None
            touch(other)
    derive_offer_ranks(load["id"])
    sync_load(load)
    from domain import sync_agent
    sync_agent(agent)
    return ok(present("load_offer", offer))


@bp.post("/network/load-offers/<row_id>/decline")
def decline_load_offer(row_id):
    require_role("CapacityOwnerOperator")
    offer = _offer_row(row_id)
    fields = client_fields(body(), ["declined_at"])
    if "declined_at" in fields:
        parse_ts(fields["declined_at"], "declined_at")
    sync_offer(offer, bump=False)
    if offer["status"] != "OPEN":
        raise ApiError("ERR_OFFER_NOT_OPEN", 409, "The offer is not OPEN.")
    if require_auth() == "CapacityOwnerOperator" and _user_id() != offer["capacity_owner_id"]:
        raise ApiError("ERR_OFFER_NOT_DIRECTED_TO_CAPACITY_OWNER", 403,
                       "The offer was directed to a different capacity owner.")
    offer["status"] = "DECLINED"
    offer["selected_rank"] = None
    touch(offer)
    load = STATE.loads[offer["load_id"]]
    derive_offer_ranks(load["id"])
    sync_load(load)
    return ok(present("load_offer", offer))


@bp.post("/network/load-offers/<row_id>/withdraw")
def withdraw_load_offer(row_id):
    require_role("FreightAgent")
    offer = _offer_row(row_id)
    fields = client_fields(body(), ["reason_code"])
    require_text(fields, "reason_code")
    sync_offer(offer, bump=False)
    if offer["status"] != "OPEN":
        raise ApiError("ERR_OFFER_NOT_OPEN", 409, "The offer is not OPEN.")
    load = STATE.loads[offer["load_id"]]
    if require_auth() == "FreightAgent" and load["agent_id"] != _user_id():
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "The caller does not own the parent load.")
    offer["status"] = "WITHDRAWN"
    offer["selected_rank"] = None
    touch(offer)
    derive_offer_ranks(load["id"])
    sync_load(load)
    return ok(present("load_offer", offer))


# ─── Trip ────────────────────────────────────────────────────────────────────
@bp.post("/network/trips")
def create_trip():
    require_role("CapacityOwnerOperator")
    payload = body()
    fields = client_fields(payload, [
        "load_id", "capacity_owner_id", "equipment_id", "departed_at",
        "deadline_at",
    ])
    load = fetch("load", require_text(fields, "load_id"))
    bco = fetch("capacity_owner", require_text(fields, "capacity_owner_id"))
    unit = fetch("equipment", require_text(fields, "equipment_id"))
    departed_at = fields.get("departed_at")
    deadline_at = fields.get("deadline_at")
    departed_dt = parse_ts(departed_at, "departed_at")
    deadline_dt = parse_ts(deadline_at, "deadline_at")
    # The unit the trip names must exist in the fleet.
    if unit["capacity_owner_id"] != bco["id"]:
        raise ApiError("ERR_EQUIPMENT_NOT_FOUND", 404,
                       "The named unit does not belong to this capacity owner.")

    # Priority 4: resource state.
    if load["status"] != "AWARDED":
        raise ApiError("ERR_LOAD_NOT_AWARDED", 409, "The load is not AWARDED.")
    # Priority 9: the named owner must be the load's awarded owner.
    if load["awarded_capacity_owner_id"] != bco["id"]:
        raise ApiError("ERR_TRIP_OWNER_MISMATCH", 400,
                       "The trip's capacity owner is not the load's awarded owner.")
    # Priority 6: business safety.
    if bco["status"] != "QUALIFIED":
        raise ApiError("ERR_CAPACITY_OWNER_NOT_QUALIFIED_CLEAR", 422,
                       "The capacity owner is not qualified to haul.")
    if equipment_inspection_status(unit, clock_dt()) != "CURRENT":
        raise ApiError("ERR_EQUIPMENT_INSPECTION_NOT_CURRENT", 409,
                       "The unit's inspection is not CURRENT.")
    if unit["status"] != "IN_SERVICE":
        raise ApiError("ERR_EQUIPMENT_NOT_IN_SERVICE", 409,
                       "The unit is not IN_SERVICE.")
    if unit["equipment_type"] not in POWER_UNITS:
        raise ApiError("ERR_EQUIPMENT_TYPE_MISMATCH", 400,
                       "Only TRACTOR and STRAIGHT_TRUCK units may haul.")
    # Priority 8: single-assignment conflict.
    if active_trip_on(unit["id"]) is not None:
        raise ApiError("ERR_EQUIPMENT_ALREADY_ASSIGNED", 409,
                       "The unit is already on a non-terminal trip.")
    previous = last_delivered_at(unit["id"])
    if previous is not None:
        buffer_end = parse_ts(previous, "delivered_at") + timedelta(
            hours=EQUIPMENT_TURNAROUND_BUFFER_HOURS)
        if departed_dt < buffer_end:
            raise ApiError("ERR_EQUIPMENT_TURNAROUND_OVERLAP", 409,
                           "The departure falls inside the unit's turnaround buffer.")
    # Priority 4 (window): a deadline at or before the departure is malformed.
    if deadline_dt <= departed_dt:
        raise ApiError("ERR_INVALID_TRIP_WINDOW", 400,
                       "deadline_at must be strictly after departed_at.")

    trip = mint("trips", {
        "load_id": load["id"],
        "capacity_owner_id": bco["id"],
        "equipment_id": unit["id"],
        "departed_at": departed_at,
        "deadline_at": deadline_at,
        "delivered_at": None,
        "actual_miles": 0,
        "proof_of_delivery_code": None,
        "on_time": None,
        "maintenance_reserve_cents": 0,
        "status": "DISPATCH_PENDING",
    })
    load["status"] = "COVERED"
    sync_load(load)
    sync_trip(trip, bump=False)
    return ok(present("trip", trip), 201)


@bp.get("/network/trips")
def list_trips():
    require_role("CapacityOwnerOperator", "SettlementOperator", "SafetyReviewer",
                 "NetworkAdministrator")
    rows = list(STATE.trips.values())
    load_id = query_str("load_id")
    owner_id = query_str("capacity_owner_id")
    equipment_id = query_str("equipment_id")
    status = query_str("status")
    if load_id:
        rows = [r for r in rows if r["load_id"] == load_id]
    if owner_id:
        rows = [r for r in rows if r["capacity_owner_id"] == owner_id]
    if equipment_id:
        rows = [r for r in rows if r["equipment_id"] == equipment_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("trip", page), total, limit, offset)


@bp.get("/network/loads/<row_id>/trips")
def list_load_trips(row_id):
    require_role("FreightAgent", "CapacityOwnerOperator", "SettlementOperator",
                 "NetworkAdministrator")
    fetch("load", row_id)
    rows = [t for t in STATE.trips.values() if t["load_id"] == row_id]
    status = query_str("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("trip", page), total, limit, offset)


def _trip_row(row_id):
    return fetch("trip", row_id)


@bp.get("/network/trips/<row_id>")
def get_trip(row_id):
    require_role("FreightAgent", "CapacityOwnerOperator", "SettlementOperator",
                 "NetworkAdministrator")
    return ok(present("trip", _trip_row(row_id)))


@bp.post("/network/trips/<row_id>/dispatch")
def dispatch_trip(row_id):
    require_role("CapacityOwnerOperator")
    trip = _trip_row(row_id)
    fields = client_fields(body(), ["dispatched_at"])
    if "dispatched_at" in fields:
        parse_ts(fields["dispatched_at"], "dispatched_at")
    load = STATE.loads[trip["load_id"]]
    bco = STATE.capacity_owners[trip["capacity_owner_id"]]
    if trip["status"] != "DISPATCH_PENDING":
        raise ApiError("ERR_TRIP_NOT_DISPATCH_PENDING", 409,
                       "The trip is not DISPATCH_PENDING.")
    if load["status"] != "COVERED":
        raise ApiError("ERR_LOAD_NOT_COVERED", 409, "The load is not COVERED.")
    if bco["status"] != "QUALIFIED":
        raise ApiError("ERR_CAPACITY_OWNER_NOT_QUALIFIED_CLEAR", 422,
                       "The capacity owner is not qualified to haul.")
    unit = STATE.equipment.get(trip["equipment_id"])
    if unit is not None and equipment_inspection_status(unit, clock_dt()) != "CURRENT":
        raise ApiError("ERR_EQUIPMENT_INSPECTION_NOT_CURRENT", 409,
                       "The unit's inspection is no longer CURRENT.")
    # One bump per machine per call: both the trip and its parent load advance.
    load["status"] = "IN_TRANSIT"
    load["board_required"] = board_required_of(load)
    touch(load)
    trip["status"] = "EN_ROUTE"
    touch(trip)
    return ok(present("trip", trip))


@bp.post("/network/trips/<row_id>/complete")
def complete_trip(row_id):
    require_role("CapacityOwnerOperator")
    trip = _trip_row(row_id)
    payload = body()
    fields = client_fields(payload, ["actual_miles", "proof_of_delivery_code"])
    miles = require_int(fields, "actual_miles", minimum=1)
    pod = require_text(fields, "proof_of_delivery_code")
    load = STATE.loads[trip["load_id"]]
    if load["status"] != "IN_TRANSIT":
        raise ApiError("ERR_LOAD_NOT_IN_TRANSIT", 409, "The load is not IN_TRANSIT.")
    if trip["status"] != "EN_ROUTE":
        raise ApiError("ERR_TRIP_NOT_EN_ROUTE", 409, "The trip is not EN_ROUTE.")
    trip["actual_miles"] = miles
    trip["proof_of_delivery_code"] = pod
    trip["delivered_at"] = clock_dt().strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{clock_dt().microsecond // 1000:03d}Z"
    trip["maintenance_reserve_cents"] = maintenance_reserve_for(miles)
    trip["status"] = "DELIVERED"
    sync_trip(trip)
    load["status"] = "DELIVERED"
    sync_load(load)
    return ok(present("trip", trip))


@bp.post("/network/trips/<row_id>/verify-pod")
def verify_pod(row_id):
    require_role("SettlementOperator")
    trip = _trip_row(row_id)
    fields = client_fields(body(), ["pod_verified"])
    if trip["status"] != "DELIVERED":
        raise ApiError("ERR_TRIP_NOT_DELIVERED", 409, "The trip is not DELIVERED.")
    verified = fields.get("pod_verified")
    if not trip["proof_of_delivery_code"]:
        raise ApiError("ERR_POD_MISSING", 409, "The trip carries no proof of delivery.")
    if verified is not True:
        raise ApiError("ERR_POD_MISSING", 409, "pod_verified must be true.")
    trip["status"] = "COMPLETED"
    trip["maintenance_reserve_cents"] = maintenance_reserve_for(trip["actual_miles"])
    sync_trip(trip)
    return ok(present("trip", trip))


@bp.post("/network/trips/<row_id>/abort")
def abort_trip_route(row_id):
    require_role("CapacityOwnerOperator")
    trip = _trip_row(row_id)
    fields = client_fields(body(), ["reason_code"])
    require_text(fields, "reason_code")
    if trip["status"] not in ("DISPATCH_PENDING", "EN_ROUTE"):
        raise ApiError("ERR_TRIP_NOT_ABORTABLE", 409,
                       "Only a non-terminal trip may be aborted.")
    from cascades import abort_trip as _abort
    _abort(trip)
    return ok(present("trip", trip))


def _user_id():
    from flask import g
    return g.get("user_id")