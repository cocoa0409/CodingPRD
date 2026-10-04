"""Origination contracts: create, read, list, pricing elections, settle."""
from decimal import Decimal

from flask import Blueprint, request

from auth import require_roles
from calc import (d3, final_settlement, pricing_event_accrual,
                  provisional_estimate, round_int)
from envelope import success_list, success_obj
from errors import fail
from quotes import asof
from store import db, get_clock, new_id, stamp_new, to_jsonable, touch
from validate import (body_dict, forbid_fields, get_int, paginate, req_decimal,
                      req_int, req_month, sort_created, to_int)
from dates import parse_iso

bp = Blueprint("contracts", __name__)

CONTRACT_TYPES = ("CASH", "BASIS", "DEFERRED")


@bp.post("/api/origination-contracts")
def create_contract():
    require_roles("OriginationMerchandiser")
    body = body_dict()
    ctype = body.get("contract_type")
    if ctype not in CONTRACT_TYPES:
        fail("ERR_INVALID_REQUEST", "contract_type must be CASH, BASIS or DEFERRED")

    # Body FK resolution (priority 4) for supplied FK fields.
    farmer = elevator = program = None
    if body.get("farmer_id") is not None:
        farmer = db["farmers"].get(body["farmer_id"])
        if farmer is None:
            fail("ERR_FARMER_NOT_FOUND", "farmer_id does not resolve")
    if body.get("elevator_id") is not None:
        elevator = db["elevators"].get(body["elevator_id"])
        if elevator is None:
            fail("ERR_ELEVATOR_NOT_FOUND", "elevator_id does not resolve")
    if body.get("program_id") is not None:
        program = db["programs"].get(body["program_id"])
        if program is None:
            fail("ERR_PROGRAM_NOT_FOUND", "program_id does not resolve")

    # Temporal rule (priority 7): DEFERRED deadline must be in the future.
    clock = get_clock()
    deadline = None
    if ctype == "DEFERRED" and body.get("pricing_deadline") is not None:
        deadline = parse_iso(body["pricing_deadline"])
        if deadline is None:
            fail("ERR_INVALID_REQUEST", "pricing_deadline must be an ISO 8601 datetime")
        if deadline <= clock:
            fail("ERR_DELIVERY_WINDOW_INVALID",
                 "pricing_deadline must be in the future at creation")

    # Shape rules (priority 9): presence, type-matched fields, quantities.
    if farmer is None:
        fail("ERR_INVALID_REQUEST", "farmer_id is required")
    if elevator is None:
        fail("ERR_INVALID_REQUEST", "elevator_id is required")
    qty = d3(req_decimal(body, "quantity_bushels"))
    if qty <= 0:
        fail("ERR_INVALID_REQUEST", "quantity_bushels must be > 0")

    cash_price = basis = storage_rate = None
    futures_month = None
    if ctype == "CASH":
        cash_price = req_int(body, "cash_price_cents_per_bushel")
        forbid_fields(body, ("basis_cents_per_bushel", "futures_month",
                             "pricing_deadline", "storage_rate_cents_per_bushel_day"))
    elif ctype == "BASIS":
        basis = req_int(body, "basis_cents_per_bushel")
        futures_month = req_month(body, "futures_month")
        forbid_fields(body, ("cash_price_cents_per_bushel", "pricing_deadline",
                             "storage_rate_cents_per_bushel_day"))
    else:  # DEFERRED
        futures_month = req_month(body, "futures_month")
        if deadline is None:
            fail("ERR_INVALID_REQUEST", "pricing_deadline is required for DEFERRED")
        storage_rate = req_int(body, "storage_rate_cents_per_bushel_day")
        if storage_rate < 0:
            fail("ERR_INVALID_REQUEST",
                 "storage_rate_cents_per_bushel_day must be >= 0")
        forbid_fields(body, ("cash_price_cents_per_bushel", "basis_cents_per_bushel"))

    # Referenced-entity state (priority 11): program must be ACTIVE.
    if program is not None and program["status"] != "ACTIVE":
        fail("ERR_PROGRAM_CLOSED", "program is CLOSED")

    rec = {
        "id": new_id(),
        "farmer_id": farmer["id"],
        "elevator_id": elevator["id"],
        "program_id": program["id"] if program else None,
        "contract_type": ctype,
        "quantity_bushels": qty,
        "cash_price_cents_per_bushel": cash_price,
        "basis_cents_per_bushel": basis,
        "futures_month": futures_month,
        "pricing_deadline": deadline,
        "storage_rate_cents_per_bushel_day": storage_rate,
        "delivered_bushels": Decimal(0),
        "priced_bushels": Decimal(0),
        "priced_value_cents": 0,
        "elections": [],
        "accrued_storage_cents": 0,
        "unpriced_pool_bushels": Decimal(0),
        "last_accrual_date": None,
        "estimated_settlement_cents": None,
        "settlement_line_total_cents": None,
        "settlement_accrual_deduction_cents": None,
        "settlement_net_payable_cents": None,
        "pricing_status": "UNPRICED",
        "fulfillment_status": "OPEN",
    }
    if ctype == "CASH":
        rec["elections"].append({
            "bushels": qty,
            "unit_price_cents": cash_price,
            "elected_at": clock,
            "origin": "CLIENT",
        })
        rec["priced_bushels"] = qty
        rec["priced_value_cents"] = round_int(qty * cash_price)
        rec["pricing_status"] = "PRICED"
    stamp_new(rec)
    db["contracts"][rec["id"]] = rec
    rec["estimated_settlement_cents"] = provisional_estimate(rec)
    return success_obj(to_jsonable(rec), 201)


def _get_contract_or_404(cid):
    c = db["contracts"].get(cid)
    if c is None:
        fail("ERR_CONTRACT_NOT_FOUND", "origination contract not found")
    return c


def _check_farmer_ownership(uid, role, contract):
    if role == "Farmer" and contract["farmer_id"] != uid:
        fail("ERR_FORBIDDEN", "Farmer callers may only access their own contracts")


@bp.get("/api/origination-contracts/<cid>")
def get_contract(cid):
    uid, role = require_roles("PlatformAdmin", "OriginationMerchandiser", "Farmer")
    c = _get_contract_or_404(cid)
    _check_farmer_ownership(uid, role, c)
    return success_obj(to_jsonable(c))


@bp.get("/api/origination-contracts")
def list_contracts():
    uid, role = require_roles("PlatformAdmin", "OriginationMerchandiser", "Farmer")
    items = sort_created(list(db["contracts"].values()))
    if role == "Farmer":
        items = [c for c in items if c["farmer_id"] == uid]
    farmer_id = request.args.get("farmer_id")
    elevator_id = request.args.get("elevator_id")
    program_id = request.args.get("program_id")
    pricing_status = request.args.get("pricing_status")
    fulfillment_status = request.args.get("fulfillment_status")
    if farmer_id is not None:
        items = [c for c in items if c["farmer_id"] == farmer_id]
    if elevator_id is not None:
        items = [c for c in items if c["elevator_id"] == elevator_id]
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    if pricing_status is not None:
        items = [c for c in items if c["pricing_status"] == pricing_status]
    if fulfillment_status is not None:
        items = [c for c in items if c["fulfillment_status"] == fulfillment_status]
    page, limit, offset, total = paginate(items)
    return success_list([to_jsonable(c) for c in page], limit, offset, total)


@bp.post("/api/origination-contracts/<cid>/pricing-elections")
def pricing_election(cid):
    uid, role = require_roles("OriginationMerchandiser", "Farmer")
    c = _get_contract_or_404(cid)
    _check_farmer_ownership(uid, role, c)
    body = body_dict()
    # OCC (priority 5): stale writes are rejected before any state inspection.
    expected = to_int(body.get("expected_contract_version"))
    if expected is None:
        fail("ERR_INVALID_REQUEST", "expected_contract_version is required")
    if expected != c["version"]:
        fail("ERR_STALE_CONTRACT_VERSION",
             "expected_contract_version does not match the contract's current version")
    # State (priority 6): must be a pricable contract.
    if c["contract_type"] == "CASH" or c["pricing_status"] == "PRICED":
        fail("ERR_CONTRACT_NOT_PRICABLE",
             "contract is not in a pricable state")
    # Temporal (priority 7): DEFERRED elections must arrive on or before the deadline.
    clock = get_clock()
    if c["contract_type"] == "DEFERRED" and clock > c["pricing_deadline"]:
        fail("ERR_CONTRACT_NOT_PRICABLE",
             "pricing_deadline has passed; the sweep prices the contract")
    # Shape / quantity (priority 9).
    bushels = req_decimal(body, "bushels")
    if bushels <= 0 or c["priced_bushels"] + bushels > c["quantity_bushels"]:
        fail("ERR_PRICING_EXCEEDS_QUANTITY",
             "election bushels must be positive and must not exceed the unpriced remainder")
    bushels = d3(bushels)
    # Referenced market data (priority 11).
    fut = asof("BEAN", c["futures_month"])
    if fut is None:
        fail("ERR_NO_MARKET_QUOTE",
             "no as-of BEAN futures quote for the contract's futures_month")
    unit = fut + (c["basis_cents_per_bushel"] if c["contract_type"] == "BASIS" else 0)
    # Side effects: accrual leg finalized first, then pool shrinks; election appended.
    pricing_event_accrual(c, bushels, clock)
    c["elections"].append({
        "bushels": bushels,
        "unit_price_cents": unit,
        "elected_at": clock,
        "origin": "CLIENT",
    })
    c["priced_bushels"] = Decimal(c["priced_bushels"]) + bushels
    c["priced_value_cents"] += round_int(bushels * unit)
    c["pricing_status"] = ("PRICED" if c["priced_bushels"] == c["quantity_bushels"]
                           else "PARTIALLY_PRICED")
    c["estimated_settlement_cents"] = provisional_estimate(c)
    touch(c)
    return success_obj(to_jsonable(c))


@bp.post("/api/origination-contracts/<cid>/settle")
def settle_contract(cid):
    require_roles("OriginationMerchandiser")
    c = _get_contract_or_404(cid)
    if c["fulfillment_status"] != "DELIVERED" or c["pricing_status"] != "PRICED":
        fail("ERR_CONTRACT_NOT_SETTLEABLE",
             "settlement requires fulfillment DELIVERED and pricing PRICED")
    final_settlement(c)
    c["fulfillment_status"] = "SETTLED"
    touch(c)
    return success_obj(to_jsonable(c))
