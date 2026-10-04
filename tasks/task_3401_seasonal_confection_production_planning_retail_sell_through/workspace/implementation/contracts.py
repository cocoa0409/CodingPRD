"""CommodityContract routes: book (provisional landed cost), read, list,
settle (final landed cost)."""

from flask import Blueprint, request

from db import db, touch
from domain import COMMODITIES, get_contract, ser_contract
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_PROGRAM_NOT_FOUND, ERR_INVALID_STATE,
    ERR_HEDGE_EXCEEDS_QUANTITY,
)
from middleware import authorize, ROLE_PLATFORM_ADMIN, ALL_ROLES
from programs import _create_entity
from respond import ok, created, ok_list, paginate, parse_pagination
from validate import json_body, v_str, v_int, v_enum

bp = Blueprint("contracts", __name__)


def _landed_cost(quantity, hedged, reference_price, hedge_price):
    """landed_material_cost: quantity x reference - hedged x max(0, reference -
    strike). The hedge pays off only when the reference price exceeds the
    strike. All operands are integers, so the result is exact in cents."""
    strike = hedge_price if hedge_price is not None else 0
    payoff = max(0, reference_price - strike)
    return quantity * reference_price - hedged * payoff


@bp.post("/confection/commodity-contracts")
def create_contract():
    data = json_body()
    program_id = v_str(data, "program_id")
    commodity = v_enum(data, "commodity", COMMODITIES)
    quantity_units = v_int(data, "quantity_units", min_v=1)
    contract_price = v_int(data, "contract_price_cents_per_unit", min_v=1)
    hedged = v_int(data, "hedged_quantity_units", required=False)
    if hedged is None:
        hedged = 0
    if hedged < 0:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "hedged_quantity_units must be >= 0")
    hedge_price = v_int(data, "hedge_price_cents_per_unit", required=False)
    if hedge_price is not None and hedge_price <= 0:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "hedge_price_cents_per_unit must be > 0 when supplied")

    authorize(ROLE_PLATFORM_ADMIN)

    if program_id not in db.programs:
        raise ApiError(404, ERR_PROGRAM_NOT_FOUND,
                       "SeasonalProgram %s does not exist" % program_id)

    # Structural (priority 10): hedge bounds.
    if hedged > quantity_units:
        raise ApiError(422, ERR_HEDGE_EXCEEDS_QUANTITY,
                       "hedged_quantity_units may not exceed quantity_units")
    if hedged > 0 and hedge_price is None:
        raise ApiError(422, ERR_HEDGE_EXCEEDS_QUANTITY,
                       "hedge_price_cents_per_unit is required when hedged_quantity_units > 0")

    contract = _create_entity(db.contracts, {
        "program_id": program_id,
        "commodity": commodity,
        "quantity_units": quantity_units,
        "contract_price_cents_per_unit": contract_price,
        "hedged_quantity_units": hedged,
        "hedge_price_cents_per_unit": hedge_price,
        "spot_price_cents_per_unit": None,
        "provisional_spend_cents": _landed_cost(
            quantity_units, hedged, contract_price, hedge_price),
        "effective_spend_cents": None,
        "status": "OPEN",
    })
    return created(ser_contract(contract))


@bp.get("/confection/commodity-contracts/<contract_id>")
def read_contract(contract_id):
    authorize(*ALL_ROLES)
    return ok(ser_contract(get_contract(contract_id)))


@bp.get("/confection/commodity-contracts")
def list_contracts():
    limit, offset = parse_pagination()
    authorize(*ALL_ROLES)
    items = list(db.contracts.values())
    for param in ("program_id", "commodity", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if c[param] == val]
    page, total, limit, offset = paginate(items, limit, offset)
    return ok_list([ser_contract(c) for c in page], total, limit, offset)


@bp.post("/confection/commodity-contracts/<contract_id>/settle")
def settle_contract(contract_id):
    data = json_body()
    spot_price = v_int(data, "spot_price_cents_per_unit", min_v=1)

    authorize(ROLE_PLATFORM_ADMIN)
    contract = get_contract(contract_id)

    if contract["status"] != "OPEN":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only an OPEN contract can be settled")

    contract["spot_price_cents_per_unit"] = spot_price
    contract["effective_spend_cents"] = _landed_cost(
        contract["quantity_units"], contract["hedged_quantity_units"],
        spot_price, contract["hedge_price_cents_per_unit"])
    contract["status"] = "SETTLED"
    touch(contract)
    return ok(ser_contract(contract))
