"""ServiceContract endpoints (PRD 3.1)."""

from flask import Blueprint

import calc
import store
from envelope import created, ok, paginate, pagination
from errors import ApiError
from guards import (ALL_ROLES, authorize, body, equality_filter, id_field,
                    must_exist, parse_date, validate_body)
from store import touch

bp = Blueprint("contracts", __name__)

CREATE_SPEC = [
    {"name": "client_name", "kind": "string", "min_len": 1, "max_len": 120},
    {"name": "site_type", "kind": "enum", "values": ("HOTEL", "CAMPUS", "CORPORATE")},
    {"name": "base_rate_cents_per_service_hour", "kind": "int", "min": 1},
    {"name": "term_start_date", "kind": "date"},
    {"name": "term_end_date", "kind": "date"},
    {"name": "escalation_index_pct", "kind": "number", "min": 0, "max": 10},
    {"name": "sla_on_time_threshold_pct", "kind": "number", "min": 0, "max": 100},
    {"name": "penalty_rate_cents_per_missed_trip", "kind": "int", "min": 0},
    {"name": "ada_min_accessible_pct", "kind": "number", "min": 0, "max": 100},
    id_field("predecessor_contract_id", required=False, nullable=True),
]


def new_contract_row(data):
    row = store.base_row()
    row.update({
        "client_name": data["client_name"],
        "site_type": data["site_type"],
        "base_rate_cents_per_service_hour": data["base_rate_cents_per_service_hour"],
        "term_start_date": data["term_start_date"],
        "term_end_date": data["term_end_date"],
        "escalation_index_pct": data["escalation_index_pct"],
        "sla_on_time_threshold_pct": data["sla_on_time_threshold_pct"],
        "penalty_rate_cents_per_missed_trip": data["penalty_rate_cents_per_missed_trip"],
        "ada_min_accessible_pct": data["ada_min_accessible_pct"],
        "predecessor_contract_id": data.get("predecessor_contract_id"),
        "status": "DRAFT",
        "credit_balance_cents": 0,
        "branded_vehicle_count": 0,
        "branded_ada_vehicle_count": 0,
    })
    store.register_new(row)
    store.contracts[row["id"]] = row
    return row


@bp.post("/service-contracts")
def create_contract():
    authorize(["ContractAdmin"])
    data = validate_body(body(), CREATE_SPEC)
    if parse_date(data["term_end_date"]) < parse_date(data["term_start_date"]):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'term_end_date' may not precede 'term_start_date'.")
    if data.get("predecessor_contract_id") is not None:
        must_exist(store.contracts, data["predecessor_contract_id"], "ERR_CONTRACT_NOT_FOUND")
    return created(store.public(new_contract_row(data)))


@bp.get("/service-contracts/<cid>")
def get_contract(cid):
    authorize(ALL_ROLES)
    contract = must_exist(store.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    return ok(store.public(contract))


@bp.get("/service-contracts")
def list_contracts():
    authorize(ALL_ROLES)
    limit, offset = pagination()
    rows = list(store.contracts.values())
    rows = equality_filter(rows, "status", "status")
    rows = equality_filter(rows, "predecessor_contract_id", "predecessor_contract_id")
    rows = equality_filter(rows, "site_type", "site_type")
    rows.sort(key=store.sort_key_created)
    return paginate(rows, limit, offset, store.public)


@bp.post("/service-contracts/<cid>/activate")
def activate_contract(cid):
    authorize(["ContractAdmin"])
    contract = must_exist(store.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT")
    contract["status"] = "ACTIVE"
    touch(contract)
    return ok(store.public(contract))


@bp.post("/service-contracts/<cid>/terminate")
def terminate_contract(cid):
    authorize(["ContractAdmin"])
    validate_body(body(), [{"name": "termination_reason", "kind": "string", "min_len": 1}])
    contract = must_exist(store.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    if contract["status"] not in ("ACTIVE", "RENEWAL_PENDING"):
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    was_renewal_pending = contract["status"] == "RENEWAL_PENDING"

    # link 1 + 2: routes retire, their SCHEDULED/ASSIGNED trips cancel
    for route in list(store.routes.values()):
        if route["contract_id"] == contract["id"] and route["status"] in (
                "DRAFT", "PUBLISHED", "DEGRADED"):
            calc.retire_route(route)

    # link 3: PENDING / MATCHED on-demand requests expire
    for req in list(store.on_demand_requests.values()):
        if req["contract_id"] != contract["id"]:
            continue
        if req["status"] not in ("PENDING", "MATCHED"):
            continue
        matched_trip_id = req["matched_trip_id"] if req["status"] == "MATCHED" else None
        req["status"] = "EXPIRED"
        req["matched_trip_id"] = None
        touch(req)
        if matched_trip_id:
            trip = store.trips.get(matched_trip_id)
            if trip is not None:
                calc.recompute_trip_matched_party_seats(trip)

    # link 4: the standing renewal offer is superseded
    if was_renewal_pending:
        for offer in list(store.renewal_offers.values()):
            if offer["contract_id"] == contract["id"] and offer["status"] in (
                    "OPEN", "COUNTERED"):
                offer["status"] = "SUPERSEDED"
                touch(offer)

    contract["status"] = "TERMINATED"
    touch(contract)
    return ok(store.public(contract))
