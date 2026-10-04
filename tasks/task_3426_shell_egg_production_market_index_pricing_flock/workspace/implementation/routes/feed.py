"""Feed procurement, hedging, receipts and milling (PRD §3.8): contracts with
mill receiving capacity checks, single-hedge pricing on earliest receipts,
FIFO consumption, and dual ACTUAL vs STANDARD batch costing."""

from datetime import timedelta
from fractions import Fraction

from flask import Blueprint, request

from auth import authenticate, check_complex_manager_ownership, require_role
from calc import (
    STANDARD_BLEND_CENTS_PER_TON,
    blended_cost,
    consume_feed,
    receipt_cost,
)
from db import STORE, set_dt, stamp_new, touch
from errors import (
    ApiError,
    ERR_COMPLEX_NOT_FOUND,
    ERR_HEDGE_EXCEEDS_CONTRACT,
    ERR_INSUFFICIENT_FEED_INVENTORY,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MILL_RECEIVING_CAPACITY_EXCEEDED,
    ERR_ORGANIC_INPUTS_REQUIRED,
    ERR_OUTSIDE_DELIVERY_WINDOW,
    ERR_RECEIVE_EXCEEDS_CONTRACT,
)
from helpers import get_complex, get_feed_contract, list_response
from serialize import serialize_feed_batch, serialize_feed_contract
from util import (
    COMMODITIES,
    PROGRAMS,
    ceil_frac,
    round2_half_up,
    round_half_up,
    success_object,
)
from validate import apply_values, get_body, validate_payload

bp = Blueprint("feed", __name__)


def _window_days_fraction(contract_or_start, end=None):
    """Window length in days as an exact Fraction."""
    if end is None:
        start = contract_or_start["_dt_delivery_start"]
        end = contract_or_start["_dt_delivery_end"]
    else:
        start = contract_or_start
    delta = end - start
    return Fraction(
        delta.days * 86400 + delta.seconds, 86400
    ) + Fraction(delta.microseconds, 86400 * 1000000)


def _daily_load(contract):
    """ceil(total_tons / window_days) — the contract's even daily spread."""
    window_days = _window_days_fraction(contract)
    return ceil_frac(Fraction(contract["total_tons"]) / window_days)


def _check_mill_capacity(cx, new_values):
    """Every calendar day of the new contract's window must keep the summed
    daily loads of the complex's OPEN / PARTIALLY_RECEIVED contracts (the new
    one included) within mill_receiving_tons_per_day."""
    window_days = _window_days_fraction(
        new_values["delivery_start"], new_values["delivery_end"]
    )
    new_daily = ceil_frac(Fraction(new_values["total_tons"]) / window_days)
    start = new_values["delivery_start"]
    end = new_values["delivery_end"]
    others = [
        c
        for c in STORE.feed_contracts.values()
        if c["complex_id"] == cx["id"] and c["status"] in ("OPEN", "PARTIALLY_RECEIVED")
    ]
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        day_end = day + timedelta(days=1)
        load = new_daily
        for c in others:
            if c["_dt_delivery_start"] < day_end and c["_dt_delivery_end"] > day:
                load += _daily_load(c)
        if load > cx["mill_receiving_tons_per_day"]:
            raise ApiError(
                ERR_MILL_RECEIVING_CAPACITY_EXCEEDED,
                422,
                "aggregate daily receiving exceeds the mill capacity",
            )
        day = day_end


@bp.route("/api/feed-contracts", methods=["POST"])
def create_feed_contract():
    _uid, role = authenticate()
    require_role(role, {"ProcurementLead"})
    body = get_body()
    # Priority 5: the body complex_id resolves before payload shape is judged.
    raw_complex = body.get("complex_id") if isinstance(body, dict) else None
    if isinstance(raw_complex, str) and raw_complex not in STORE.complexes:
        raise ApiError(
            ERR_COMPLEX_NOT_FOUND, 404, "complex not found: %s" % raw_complex
        )
    values, raws = validate_payload(
        body,
        {
            "complex_id": {"kind": "string", "required": True},
            "commodity": {"kind": "enum", "required": True, "enum": COMMODITIES},
            "total_tons": {"kind": "int", "required": True, "gt": 0},
            "basis_cents_per_ton": {"kind": "int", "required": True},
            "spot_reference_cents_per_ton": {
                "kind": "int", "required": True, "gt": 0,
            },
            "delivery_start": {"kind": "datetime", "required": True},
            "delivery_end": {"kind": "datetime", "required": True},
            "is_organic_certified": {"kind": "bool", "default": False},
        },
    )
    cx = STORE.complexes.get(values["complex_id"])
    if cx is None:
        raise ApiError(
            ERR_COMPLEX_NOT_FOUND,
            404,
            "complex not found: %s" % values["complex_id"],
        )
    if not values["delivery_start"] < values["delivery_end"]:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "delivery_start must precede delivery_end"
        )
    _check_mill_capacity(cx, values)
    contract = {
        "complex_id": cx["id"],
        "commodity": values["commodity"],
        "is_organic_certified": values["is_organic_certified"],
        "total_tons": values["total_tons"],
        "received_tons": 0,
        "basis_cents_per_ton": values["basis_cents_per_ton"],
        "spot_reference_cents_per_ton": values["spot_reference_cents_per_ton"],
        "hedged_tons": 0,
        "hedge_futures_cents_per_ton": None,
        "hedged_applied_tons": 0,
        "total_cost_cents": 0,
        "average_received_cost_cents_per_ton": None,
        "status": "OPEN",
        "_consumed_tons": 0,
        "_dt_first_receipt_at": None,
    }
    apply_values(
        contract,
        {"delivery_start": values["delivery_start"],
         "delivery_end": values["delivery_end"]},
        {"delivery_start": raws["delivery_start"],
         "delivery_end": raws["delivery_end"]},
    )
    stamp_new(contract)
    STORE.feed_contracts[contract["id"]] = contract
    return success_object(serialize_feed_contract(contract), 201)


@bp.route("/api/complexes/<cid>/feed-contracts", methods=["GET"])
def list_feed_contracts(cid):
    authenticate()
    cx = get_complex(cid)
    items = [
        c for c in STORE.feed_contracts.values() if c["complex_id"] == cx["id"]
    ]
    commodity = request.args.get("commodity")
    if commodity is not None:
        items = [c for c in items if c["commodity"] == commodity]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, serialize_feed_contract)


@bp.route("/api/feed-contracts/<fid>/hedge", methods=["POST"])
def hedge_feed_contract(fid):
    _uid, role = authenticate()
    require_role(role, {"ProcurementLead"})
    contract = get_feed_contract(fid)
    values, _raws = validate_payload(
        get_body(),
        {
            "hedged_tons": {"kind": "int", "required": True, "ge": 1},
            "hedge_futures_cents_per_ton": {"kind": "int", "required": True, "gt": 0},
        },
    )
    if contract["status"] != "OPEN":
        raise ApiError(
            ERR_INVALID_STATE, 409, "hedging is allowed only while OPEN"
        )
    if values["hedged_tons"] > contract["total_tons"]:
        raise ApiError(
            ERR_HEDGE_EXCEEDS_CONTRACT,
            422,
            "hedged_tons exceeds total_tons",
        )
    contract["hedged_tons"] = values["hedged_tons"]
    contract["hedge_futures_cents_per_ton"] = values["hedge_futures_cents_per_ton"]
    touch(contract)
    return success_object(serialize_feed_contract(contract))


@bp.route("/api/feed-contracts/<fid>/receive", methods=["POST"])
def receive_feed_contract(fid):
    _uid, role = authenticate()
    require_role(role, {"ProcurementLead"})
    contract = get_feed_contract(fid)
    values, _raws = validate_payload(
        get_body(),
        {
            "tons": {"kind": "int", "required": True, "ge": 1},
            "spot_cents_per_ton": {"kind": "int", "required": True, "gt": 0},
        },
    )
    if contract["status"] not in ("OPEN", "PARTIALLY_RECEIVED"):
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "contract is not open for receipts",
        )
    clock = STORE.clock
    if not (contract["_dt_delivery_start"] <= clock < contract["_dt_delivery_end"]):
        raise ApiError(
            ERR_OUTSIDE_DELIVERY_WINDOW,
            422,
            "the clock is outside the delivery window",
        )
    tons = values["tons"]
    remaining = contract["total_tons"] - contract["received_tons"]
    if tons > remaining:
        raise ApiError(
            ERR_RECEIVE_EXCEEDS_CONTRACT,
            422,
            "receipt tons exceed the remaining undelivered balance",
        )
    cost, hedged_share = receipt_cost(contract, tons, values["spot_cents_per_ton"])
    contract["total_cost_cents"] += cost
    contract["hedged_applied_tons"] += hedged_share
    contract["received_tons"] += tons
    if contract.get("_dt_first_receipt_at") is None:
        contract["_dt_first_receipt_at"] = clock
    contract["average_received_cost_cents_per_ton"] = round_half_up(
        Fraction(contract["total_cost_cents"], contract["received_tons"])
    )
    contract["status"] = (
        "FILLED"
        if contract["received_tons"] == contract["total_tons"]
        else "PARTIALLY_RECEIVED"
    )
    # Credit the matching complex inventory pool (commodity x organic flag).
    cx = STORE.complexes.get(contract["complex_id"])
    if cx is not None:
        pool = _pool_field(contract["commodity"], contract["is_organic_certified"])
        cx[pool] += tons
        touch(cx)
    touch(contract)
    return success_object(serialize_feed_contract(contract))


def _pool_field(commodity, organic):
    if commodity == "CORN":
        return "corn_organic_inventory_tons" if organic else "corn_inventory_tons"
    return "soy_organic_inventory_tons" if organic else "soy_inventory_tons"


# ---------------------------------------------------------------------------
# Feed batches (milling)
# ---------------------------------------------------------------------------
@bp.route("/api/complexes/<cid>/feed-batches", methods=["POST"])
def create_feed_batch(cid):
    uid, role = authenticate()
    require_role(role, {"ComplexManager", "PlatformAdmin"})
    cx = get_complex(cid)
    # Priority 3: entity-backed ownership for the ComplexManager role.
    check_complex_manager_ownership(uid, role, cx["id"])
    values, _raws = validate_payload(
        get_body(),
        {
            "program": {"kind": "enum", "required": True, "enum": PROGRAMS},
            "corn_tons": {"kind": "int", "required": True, "ge": 0},
            "soybean_tons": {"kind": "int", "required": True, "ge": 0},
        },
    )
    corn_tons = values["corn_tons"]
    soybean_tons = values["soybean_tons"]
    if corn_tons + soybean_tons <= 0:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "corn_tons + soybean_tons must be > 0"
        )
    organic = values["program"] == "ORGANIC"
    corn_pool = _pool_field("CORN", organic)
    soy_pool = _pool_field("SOYBEAN_MEAL", organic)
    if organic:
        # Organic integrity is evaluated before the generic inventory check:
        # an organic shortfall is this error even when non-organic stock is full.
        if cx[corn_pool] < corn_tons or cx[soy_pool] < soybean_tons:
            raise ApiError(
                ERR_ORGANIC_INPUTS_REQUIRED,
                422,
                "insufficient organic-certified inventory",
            )
    elif cx[corn_pool] < corn_tons or cx[soy_pool] < soybean_tons:
        raise ApiError(
            ERR_INSUFFICIENT_FEED_INVENTORY,
            422,
            "insufficient feed inventory",
        )
    corn_draws = consume_feed(cx["id"], "CORN", organic, corn_tons) if corn_tons else []
    soy_draws = (
        consume_feed(cx["id"], "SOYBEAN_MEAL", organic, soybean_tons)
        if soybean_tons
        else []
    )
    for contract, drawn in corn_draws + soy_draws:
        contract["_consumed_tons"] = contract.get("_consumed_tons", 0) + drawn
    total_tons = corn_tons + soybean_tons
    blended = blended_cost(corn_draws, soy_draws, total_tons)
    batch = {
        "complex_id": cx["id"],
        "program": values["program"],
        "corn_tons": corn_tons,
        "soybean_tons": soybean_tons,
        "tons_produced": total_tons,
        "blended_cost_cents_per_ton": blended,
        "actual_cost_per_dozen_cents": round2_half_up(Fraction(blended, 500)),
        "standard_cost_per_dozen_cents": round2_half_up(
            Fraction(STANDARD_BLEND_CENTS_PER_TON, 500)
        ),
    }
    stamp_new(batch)
    STORE.feed_batches[batch["id"]] = batch
    cx[corn_pool] -= corn_tons
    cx[soy_pool] -= soybean_tons
    touch(cx)
    return success_object(serialize_feed_batch(batch), 201)


@bp.route("/api/complexes/<cid>/feed-batches", methods=["GET"])
def list_feed_batches(cid):
    authenticate()
    cx = get_complex(cid)
    items = [b for b in STORE.feed_batches.values() if b["complex_id"] == cx["id"]]
    program = request.args.get("program")
    if program is not None:
        items = [b for b in items if b["program"] == program]
    return list_response(items, serialize_feed_batch)
