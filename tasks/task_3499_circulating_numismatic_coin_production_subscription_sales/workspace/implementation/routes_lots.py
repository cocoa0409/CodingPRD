"""Metal procurement lots and vault receipt (PRD §3.2)."""
from flask import Blueprint

import serialize
import store
from helpers import (auth, body, envelope, err, need_date_str, need_enum,
                     need_int, need_str, no_undeclared, not_found, opt_int)

bp = Blueprint("lots", __name__)

COMMODITIES = {"COPPER", "NICKEL", "ZINC", "GOLD", "SILVER", "PLATINUM"}
VAULTS = {"WEST_POINT", "FORT_KNOX", "DENVER_VAULT"}
VAULT_DAILY_CAP_TONNES = 50


@bp.route("/mint/metal-procurement-lots", methods=["POST"])
def create_lot():
    auth("ProcurementOfficer")
    b = body()
    # Rung 6: denomination reference, then spot-price availability.
    denom = None
    if isinstance(b.get("denomination_code"), str):
        denom = store.db["denominations"].get(b["denomination_code"])
        if denom is None:
            err("ERR_UNKNOWN_DENOMINATION", 422, "Unknown denomination_code")
    commodity = b.get("commodity")
    if isinstance(commodity, str) and commodity in COMMODITIES:
        if commodity not in store.db["spot_prices"]:
            err("ERR_SPOT_PRICE_MISSING", 422,
                "No current spot price established for %s" % commodity)
    # Rung 9: shape.
    no_undeclared(b, {"commodity", "denomination_code", "quantity_tonnes",
                      "budget_price_cents_per_tonne",
                      "locked_unit_price_cents_per_tonne", "vault",
                      "planned_delivery_date"})
    commodity = need_enum(b, "commodity", COMMODITIES)
    code = need_str(b, "denomination_code")
    if denom is None:
        denom = store.db["denominations"].get(code)
        if denom is None:
            err("ERR_UNKNOWN_DENOMINATION", 422, "Unknown denomination_code")
    if commodity not in store.db["spot_prices"]:
        err("ERR_SPOT_PRICE_MISSING", 422,
            "No current spot price established for %s" % commodity)
    qty = need_int(b, "quantity_tonnes")
    if qty <= 0:
        err("ERR_QUANTITY_INVALID", 400, "quantity_tonnes must be greater than zero")
    budget_price = need_int(b, "budget_price_cents_per_tonne")
    locked = opt_int(b, "locked_unit_price_cents_per_tonne")
    vault = need_enum(b, "vault", VAULTS)
    planned = need_date_str(b, "planned_delivery_date")
    lot = store.mint_entity({
        "commodity": commodity,
        "denomination_code": code,
        "quantity_tonnes": qty,
        "budget_price_cents_per_tonne": budget_price,
        "locked_unit_price_cents_per_tonne": locked,
        "order_spot_cents_per_tonne": store.db["spot_prices"][commodity],
        "vault": vault,
        "planned_delivery_date": planned,
        "status": "ORDERED",
        "blanks_produced": qty * denom["blanks_per_tonne"],
        "realized_cost_cents": None,
        "_delivered_date": None,
    })
    store.db["lots"][lot["id"]] = lot
    return envelope(serialize.lot(lot), status=201)


def _get_lot_or_404(lid):
    l = store.db["lots"].get(lid)
    if l is None:
        not_found("Metal procurement lot not found")
    return l


@bp.route("/mint/metal-procurement-lots/<lid>", methods=["GET"])
def get_lot(lid):
    auth("ProcurementOfficer", "ProductionPlanner", "FinanceOfficer",
         "MintDirector", "PlatformAdmin")
    return envelope(serialize.lot(_get_lot_or_404(lid)))


@bp.route("/mint/metal-procurement-lots/<lid>/receive", methods=["POST"])
def receive_lot(lid):
    auth("ProcurementOfficer")
    lot = _get_lot_or_404(lid)
    if lot["status"] != "ORDERED":
        err("ERR_LOT_NOT_RECEIVABLE", 422, "Only an ORDERED lot may be received")
    no_undeclared(body(), set())
    # Vault daily capacity: same-day delivered tonnage at the vault plus the
    # arriving lot must stay at or below 50 tonnes (logical-clock date).
    today = store.now_dt().date()
    same_day = sum(l["quantity_tonnes"] for l in store.db["lots"].values()
                   if l["status"] == "DELIVERED" and l["vault"] == lot["vault"]
                   and l["_delivered_date"] == today)
    if same_day + lot["quantity_tonnes"] > VAULT_DAILY_CAP_TONNES:
        err("ERR_VAULT_CAPACITY_EXCEEDED", 422,
            "Vault daily receiving capacity of 50 tonnes would be exceeded")
    # Realized cost: locked unit price when hedged, else the commodity's
    # current spot per tonne at delivery time.
    if lot["locked_unit_price_cents_per_tonne"] is not None:
        unit = lot["locked_unit_price_cents_per_tonne"]
    else:
        unit = store.db["spot_prices"][lot["commodity"]]
    lot["realized_cost_cents"] = lot["quantity_tonnes"] * unit
    lot["status"] = "DELIVERED"
    lot["_delivered_date"] = today
    store.bump(lot)
    denom = store.db["denominations"][lot["denomination_code"]]
    denom["blank_stock_pieces"] += lot["blanks_produced"]
    store.bump(denom)
    return envelope(serialize.lot(lot))
