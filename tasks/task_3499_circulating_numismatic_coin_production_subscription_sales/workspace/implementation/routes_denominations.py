"""Denominations and Federal Reserve orders (PRD §3.1)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import serialize
import store
from helpers import (auth, bad_request, body, envelope, err, need_date_str,
                     need_int, need_num, need_str, no_undeclared, not_found)

bp = Blueprint("denominations", __name__)

ORDER_TERMINAL = {"FULFILLED", "SHORTFALL_RECORDED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Shared order lifecycle helpers (used by the production-run routes too)
# ---------------------------------------------------------------------------
def finalize_realized_seigniorage(order):
    """Realized variant: delivered-cost average over the denomination's
    DELIVERED lots, unit margin rounded half-up to 2dp BEFORE multiplying
    by the ordered quantity (pinned order of operations)."""
    d = store.db["denominations"][order["denomination_code"]]
    lots = [l for l in store.db["lots"].values()
            if l["denomination_code"] == d["code"] and l["status"] == "DELIVERED"]
    total_cost = sum(l["realized_cost_cents"] for l in lots)
    total_blanks = sum(l["blanks_produced"] for l in lots)
    unit_cost = (Decimal(total_cost) / Decimal(total_blanks)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    margin = (Decimal(d["face_value_cents"]) - unit_cost
              - d["striking_cost_cents"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    order["realized_seigniorage_cents"] = margin * order["quantity_ordered_pieces"]


def advance_order_after_run_change(order):
    """Auto-transitions after a run completes or is cancelled."""
    if order["status"] not in ("SCHEDULED", "FULFILLING"):
        return
    if order["quantity_fulfilled_pieces"] >= order["quantity_ordered_pieces"]:
        if order["status"] == "FULFILLING":
            order["status"] = "FULFILLED"
            finalize_realized_seigniorage(order)
            store.bump(order)
        return
    runs = [r for r in store.db["runs"].values() if r["fed_order_id"] == order["id"]]
    if runs and all(r["status"] in ("COMPLETED", "CANCELLED") for r in runs):
        order["status"] = "SHORTFALL_RECORDED"
        store.bump(order)


# ---------------------------------------------------------------------------
# Denominations
# ---------------------------------------------------------------------------
@bp.route("/mint/denominations", methods=["POST"])
def create_denomination():
    auth("PlatformAdmin")
    b = body()
    no_undeclared(b, {"code", "face_value_cents", "blank_budget_cost_cents",
                      "striking_cost_cents", "blanks_per_tonne"})
    code = need_str(b, "code")
    face = need_int(b, "face_value_cents")
    if face < 1:
        bad_request("face_value_cents must be at least 1")
    budget = need_num(b, "blank_budget_cost_cents")
    striking = need_num(b, "striking_cost_cents")
    blanks_per_tonne = need_int(b, "blanks_per_tonne")
    if code in store.db["denominations"]:
        err("ERR_DENOMINATION_EXISTS", 409, "Denomination code already exists")
    unit_seig = serialize.round2(Decimal(face) - budget - striking)
    d = store.mint_entity({
        "code": code,
        "face_value_cents": face,
        "blank_budget_cost_cents": budget,
        "striking_cost_cents": striking,
        "blanks_per_tonne": blanks_per_tonne,
        "blank_stock_pieces": 0,
        "budgeted_unit_seigniorage_cents": unit_seig,
    })
    store.db["denominations"][code] = d
    return envelope(serialize.denomination(d), status=201)


# ---------------------------------------------------------------------------
# Federal Reserve orders
# ---------------------------------------------------------------------------
@bp.route("/mint/federal-reserve-orders", methods=["POST"])
def create_fed_order():
    auth("FedLiaison")
    b = body()
    # Rung 6 (referential) precedes rung 9 (shape) for a resolvable reference.
    denom = None
    if isinstance(b.get("denomination_code"), str):
        denom = store.db["denominations"].get(b["denomination_code"])
        if denom is None:
            err("ERR_UNKNOWN_DENOMINATION", 422, "Unknown denomination_code")
    no_undeclared(b, {"fiscal_year", "denomination_code", "quantity_ordered_pieces",
                      "due_date"})
    fiscal_year = need_int(b, "fiscal_year")
    code = need_str(b, "denomination_code")
    if denom is None:
        denom = store.db["denominations"].get(code)
        if denom is None:
            err("ERR_UNKNOWN_DENOMINATION", 422, "Unknown denomination_code")
    qty = need_int(b, "quantity_ordered_pieces")
    if qty <= 0:
        err("ERR_QUANTITY_INVALID", 400, "quantity_ordered_pieces must be greater than zero")
    due_date = need_date_str(b, "due_date")
    o = store.mint_entity({
        "fiscal_year": fiscal_year,
        "denomination_code": code,
        "quantity_ordered_pieces": qty,
        "due_date": due_date,
        "status": "SUBMITTED",
        "quantity_fulfilled_pieces": 0,
        # Creation-time snapshot of the budgeted variant.
        "budgeted_seigniorage_cents": denom["budgeted_unit_seigniorage_cents"] * qty,
        "realized_seigniorage_cents": None,
    })
    store.db["fed_orders"][o["id"]] = o
    return envelope(serialize.fed_order(o), status=201)


def _get_order_or_404(oid):
    o = store.db["fed_orders"].get(oid)
    if o is None:
        not_found("Federal Reserve order not found")
    return o


@bp.route("/mint/federal-reserve-orders/<oid>", methods=["GET"])
def get_fed_order(oid):
    auth("FedLiaison", "ProductionPlanner", "MintDirector", "FinanceOfficer",
         "PlatformAdmin")
    return envelope(serialize.fed_order(_get_order_or_404(oid)))


@bp.route("/mint/federal-reserve-orders/<oid>/cancel", methods=["POST"])
def cancel_fed_order(oid):
    auth("FedLiaison")
    o = _get_order_or_404(oid)
    if o["status"] not in ("SUBMITTED", "SCHEDULED"):
        err("ERR_FEDORDER_NOT_CANCELLABLE", 422,
            "Only SUBMITTED or SCHEDULED orders may be cancelled")
    no_undeclared(body(), set())
    # Cascade: linked runs still in PLANNED or REWORK become CANCELLED.
    # They hold no reserved blanks (reservation happens only at start), so
    # no pieces return to stock.
    for r in store.db["runs"].values():
        if r["fed_order_id"] == o["id"] and r["status"] in ("PLANNED", "REWORK"):
            r["status"] = "CANCELLED"
            store.bump(r)
    o["status"] = "CANCELLED"
    store.bump(o)
    return envelope(serialize.fed_order(o))
