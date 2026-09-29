"""Winery delivery windows, harvest loads and the logical-clock capability."""

from decimal import Decimal

from flask import Blueprint

import calc
import derive
import service
import store
from common import ApiError, invalid, r2, respond_list, respond_object
from validate import ALL_ROLES, F, auth, parse_payload

bp = Blueprint("harvest", __name__)

LOAD_STATUSES = ("PLANNED", "IN_TRANSIT", "RECEIVED", "REJECTED")
REJECTION_REASONS = ("MOG_EXCESS", "LOW_BRIX", "ROT_DAMAGE", "LATE_ARRIVAL")
WINDOW_ROLES = ["VineyardManager", "Controller", "CrewSupervisor"]
LOAD_ROLES = ["VineyardManager", "Controller", "CrewSupervisor"]


# --------------------------------------------------------------------------
# WineryDeliveryWindow
# --------------------------------------------------------------------------

WINDOW_SCHEMA = [
    F("winery_name", "string", min_len=1, max_len=120),
    F("window_start", "datetime"),
    F("window_end", "datetime"),
    F("capacity_tons", "number", gt=0),
]


@bp.route("/delivery-windows", methods=["POST"])
def create_window():
    auth(["VineyardManager"])
    body = parse_payload(WINDOW_SCHEMA)
    start = body["_dt_window_start"]
    end = body["_dt_window_end"]
    if not end > start:
        raise invalid("window_end must be strictly later than window_start.")

    row = store.new_row()
    row.update({
        "winery_name": body["winery_name"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "_start": start,
        "_end": end,
        "capacity_tons": body["capacity_tons"],
    })
    store.delivery_windows[row["id"]] = row
    return respond_object(derive.serialize_window(row), 201)


@bp.route("/delivery-windows/<window_id>", methods=["GET"])
def read_window(window_id):
    auth(WINDOW_ROLES)
    window = service.get_window(window_id)
    return respond_object(derive.serialize_window(window))


# --------------------------------------------------------------------------
# HarvestLoad
# --------------------------------------------------------------------------

LOAD_SCHEMA = [
    F("block_id", "id", min_len=1),
    F("crew_id", "id", min_len=1),
    F("delivery_window_id", "id", min_len=1),
    F("estimated_tons", "number", gt=0),
    F("delivery_eta", "datetime"),
    F("expected_delivery_window_version", "integer", ge=1),
]


@bp.route("/harvest-loads", methods=["POST"])
def create_load():
    auth(["VineyardManager"])
    body = parse_payload(LOAD_SCHEMA)
    eta = body["_dt_delivery_eta"]

    block = service.get_block(body["block_id"])
    crew = service.get_crew(body["crew_id"])
    window = service.get_window(body["delivery_window_id"])

    # rung 14 — optimistic concurrency on the window
    if body["expected_delivery_window_version"] != window["version"]:
        raise ApiError("ERR_STALE_DELIVERY_WINDOW_VERSION", 412)

    # rung 15
    contract = None
    if block["contract_id"] is not None:
        contract = store.contracts[block["contract_id"]]
        if contract["contract_status"] != "ACTIVE":
            raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409)
    service.require_block_live(block)
    service.require_crew_active(crew)

    # rung 17 — pre-harvest clearance measured against the planned arrival
    phi_clear_at = derive.block_clearances(block)[1]
    if phi_clear_at is not None and eta < phi_clear_at:
        raise ApiError("ERR_PREHARVEST_INTERVAL_ACTIVE", 409)

    # rung 18 — closed-interval containment
    if eta < window["_start"] or eta > window["_end"]:
        raise ApiError("ERR_DELIVERY_ETA_OUTSIDE_WINDOW", 409)

    # rung 19
    if block["contract_id"] is None:
        raise ApiError("ERR_BLOCK_NOT_ENROLLED", 409)
    ledger = derive.block_harvest_ledger(block)
    if ledger["harvest_posture"] == "NOT_ESTIMATED":
        raise ApiError("ERR_NO_YIELD_ESTIMATE", 409)
    if "HARVEST" not in crew["task_capabilities"]:
        raise ApiError("ERR_CREW_TASK_MISMATCH", 409)

    # rung 20
    committed = derive.window_committed_tons(window["id"])
    if r2(committed + body["estimated_tons"]) > window["capacity_tons"]:
        raise ApiError("ERR_WINDOW_CAPACITY_EXCEEDED", 409)
    booked = r2(ledger["committed_harvest_tons"] + ledger["received_tons"]
                + body["estimated_tons"])
    ceiling = r2(ledger["governing_estimate_tons"] * calc.HARVEST_TOLERANCE)
    if booked > ceiling:
        raise ApiError("ERR_HARVEST_EXCEEDS_ESTIMATE", 409)

    row = store.new_row()
    row.update({
        "block_id": block["id"],
        "crew_id": crew["id"],
        "delivery_window_id": window["id"],
        "estimated_tons": body["estimated_tons"],
        "delivery_eta": body["delivery_eta"],
        "_eta": eta,
        "load_status": "PLANNED",
        "gross_tons_at_dispatch": None,
        "dispatched_at": None,
        "gross_tons": None,
        "tare_tons": None,
        "mog_deduct_pct": None,
        "brix_at_receipt": None,
        "net_tons": None,
        "quality_incentive_amount": None,
        "received_at": None,
        "rejected_at": None,
        "rejection_reason": None,
    })
    store.harvest_loads[row["id"]] = row
    store.touch(window)
    store.touch(block)
    return respond_object(derive.serialize_load(row), 201)


@bp.route("/harvest-loads/<load_id>", methods=["GET"])
def read_load(load_id):
    auth(LOAD_ROLES)
    load = service.get_load(load_id)
    return respond_object(derive.serialize_load(load))


@bp.route("/harvest-loads", methods=["GET"])
def list_loads():
    auth(LOAD_ROLES)
    rows = service.filtered(store.harvest_loads, (
        ("block_id", "block_id"),
        ("crew_id", "crew_id"),
        ("delivery_window_id", "delivery_window_id"),
        ("load_status", "load_status"),
    ))
    items, limit, offset, total = service.page(rows, derive.serialize_load)
    return respond_list(items, limit, offset, total)


DISPATCH_SCHEMA = [F("gross_tons_at_dispatch", "number", ge=0)]


@bp.route("/harvest-loads/<load_id>/dispatch", methods=["POST"])
def dispatch_load(load_id):
    user_id, role = auth(["CrewSupervisor"])
    body = parse_payload(DISPATCH_SCHEMA)
    load = service.get_load(load_id)
    service.require_crew_owner(role, user_id, load["crew_id"])

    if load["load_status"] != "PLANNED":
        raise ApiError("ERR_LOAD_NOT_PLANNED", 409)
    crew = store.crews[load["crew_id"]]
    service.require_crew_active(crew)

    block = store.blocks[load["block_id"]]
    phi_clear_at = derive.block_clearances(block)[1]
    if phi_clear_at is not None and store.now_utc() < phi_clear_at:
        raise ApiError("ERR_PREHARVEST_INTERVAL_ACTIVE", 409)

    load["load_status"] = "IN_TRANSIT"
    load["gross_tons_at_dispatch"] = body["gross_tons_at_dispatch"]
    load["dispatched_at"] = store.now_utc()
    store.touch(load)
    return respond_object(derive.serialize_load(load))


RECEIVE_SCHEMA = [
    F("gross_tons", "number", ge=0),
    F("tare_tons", "number", ge=0),
    F("mog_deduct_pct", "number"),
    F("brix_at_receipt", "number", ge=0),
]


@bp.route("/harvest-loads/<load_id>/receive", methods=["POST"])
def receive_load(load_id):
    auth(["VineyardManager"])
    body = parse_payload(RECEIVE_SCHEMA)

    # rung 7 — weigh-tag sanity
    if not body["tare_tons"] < body["gross_tons"]:
        raise invalid("tare_tons must be strictly less than gross_tons.")
    if body["mog_deduct_pct"] < 0 or body["mog_deduct_pct"] > 1:
        raise invalid("mog_deduct_pct must be between 0 and 1 inclusive.")

    load = service.get_load(load_id)
    if load["load_status"] != "IN_TRANSIT":
        raise ApiError("ERR_LOAD_NOT_IN_TRANSIT", 409)

    block = store.blocks[load["block_id"]]
    contract = store.contracts.get(block["contract_id"])

    net = calc.net_tons(body["gross_tons"], body["tare_tons"], body["mog_deduct_pct"])
    incentive = Decimal("0.00")
    if contract is not None and body["brix_at_receipt"] >= contract["quality_brix_threshold"]:
        incentive = r2(net * contract["quality_incentive_per_ton"])

    load["gross_tons"] = body["gross_tons"]
    load["tare_tons"] = body["tare_tons"]
    load["mog_deduct_pct"] = body["mog_deduct_pct"]
    load["brix_at_receipt"] = body["brix_at_receipt"]
    load["net_tons"] = net
    load["quality_incentive_amount"] = incentive
    load["load_status"] = "RECEIVED"
    load["received_at"] = store.now_utc()
    store.touch(load)

    store.touch(block)
    if contract is not None:
        store.touch(contract)
    window = store.delivery_windows[load["delivery_window_id"]]
    store.touch(window)
    return respond_object(derive.serialize_load(load))


REJECT_SCHEMA = [F("rejection_reason", "enum", values=REJECTION_REASONS)]


@bp.route("/harvest-loads/<load_id>/reject", methods=["POST"])
def reject_load(load_id):
    auth(["VineyardManager"])
    body = parse_payload(REJECT_SCHEMA)
    load = service.get_load(load_id)
    if load["load_status"] != "IN_TRANSIT":
        raise ApiError("ERR_LOAD_NOT_IN_TRANSIT", 409)

    load["load_status"] = "REJECTED"
    load["rejection_reason"] = body["rejection_reason"]
    load["rejected_at"] = store.now_utc()
    load["net_tons"] = Decimal("0.00")
    load["quality_incentive_amount"] = Decimal("0.00")
    store.touch(load)

    store.touch(store.blocks[load["block_id"]])
    store.touch(store.delivery_windows[load["delivery_window_id"]])
    return respond_object(derive.serialize_load(load))


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

CLOCK_SCHEMA = [F("current_utc", "datetime")]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(ALL_ROLES)
    body = parse_payload(CLOCK_SCHEMA)
    store.set_clock(body["_dt_current_utc"])
    return respond_object({"current_utc": body["current_utc"]})
