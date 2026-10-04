"""Dealers, price books, and shipment orders."""
from datetime import date, timedelta
from flask import Blueprint, request, g

import db as dbmod
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_LINE_SUPPORT_ONLY, ERR_LINE_SUNSET, ERR_DEALER_SUSPENDED,
                    ERR_CREDIT_LIMIT, ERR_FG_SHORTFALL, ERR_OUTSIDE_SHIP_WEEK,
                    ERR_UNAUTHORIZED)
from middleware import require_roles
from services import calcs
from services.lookup import get_path, get_body_ref, single_plant, plant_for_line
from util import (body, ok_object, ok_list, req_str, req_int, parse_date,
                  new_resource, touch)

bp = Blueprint("dealers", __name__)


# ---------- Dealers ----------

@bp.post("/decking/dealers")
@require_roles("ChannelManager")
def create_dealer():
    data = body()
    name = req_str(data, "name")
    terr = req_str(data, "territory_code")
    credit = req_int(data, "credit_limit_cents", minimum=0)
    d = new_resource({
        "name": name,
        "territory_code": terr,
        "credit_limit_cents": credit,
        "outstanding_cents": 0,
        "status": "ACTIVE",
    })
    dbmod.db.dealers[d["id"]] = d
    return ok_object(dict(d), status=201)


@bp.get("/decking/dealers/<did>")
@require_roles("ChannelManager", "DealerSalesRep", "Dealer", "ClaimsAdjuster")
def get_dealer(did):
    return ok_object(dict(get_path("dealers", did)))


@bp.get("/decking/dealers/<did>/shipment-orders")
@require_roles("DealerSalesRep", "Dealer", "ChannelManager")
def dealer_orders(did):
    get_path("dealers", did)
    items = [o for o in dbmod.db.shipment_orders.values() if o["dealer_id"] == did]
    v = request.args.get("status")
    if v:
        items = [o for o in items if o["status"] == v]
    return ok_list([dict(o) for o in items])


@bp.get("/decking/dealers/<did>/stocking-commitments")
@require_roles("DealerSalesRep", "Dealer", "ChannelManager")
def dealer_commitments(did):
    get_path("dealers", did)
    items = [s for s in dbmod.db.stocking_commitments.values() if s["dealer_id"] == did]
    v = request.args.get("status")
    if v:
        items = [s for s in items if s["status"] == v]
    return ok_list([dict(s) for s in items])


# ---------- Price books ----------

@bp.post("/decking/price-books")
@require_roles("ChannelManager")
def create_price_book():
    data = body()
    name = req_str(data, "name")
    eff = req_str(data, "effective_from")
    parse_date(eff, "effective_from")
    base_prices = data.get("base_prices")
    if not isinstance(base_prices, dict):
        raise_err(ERR_INVALID_REQUEST, "base_prices must be an object keyed by product_line_id")
    for k, v in base_prices.items():
        if isinstance(v, bool) or not isinstance(v, int):
            raise_err(ERR_INVALID_REQUEST, "base_prices values must be integer cents")
    tier_disc = data.get("tier_discounts_bp")
    if not isinstance(tier_disc, dict) or "STANDARD" not in tier_disc or "PREFERRED" not in tier_disc:
        raise_err(ERR_INVALID_REQUEST, "tier_discounts_bp must have STANDARD and PREFERRED keys")
    for k, v in tier_disc.items():
        if isinstance(v, bool) or not isinstance(v, int):
            raise_err(ERR_INVALID_REQUEST, "tier_discounts_bp values must be integer bp")
    pb = new_resource({
        "name": name,
        "effective_from": eff,
        "base_prices": dict(base_prices),
        "tier_discounts_bp": dict(tier_disc),
        "status": "ACTIVE",
    })
    dbmod.db.price_books[pb["id"]] = pb
    # supersede earlier books whose effective_from <= this one's effective_from
    # and which this book now replaces (the active book per date is the latest
    # effective_from <= that date)
    for other in dbmod.db.price_books.values():
        if other["id"] == pb["id"]:
            continue
        if other["status"] == "ACTIVE" and other["effective_from"] <= eff:
            other["status"] = "SUPERSEDED"
            touch(other)
    return ok_object(dict(pb), status=201)


@bp.get("/decking/price-books/<pid>")
@require_roles("ChannelManager", "DealerSalesRep", "Dealer")
def get_price_book(pid):
    return ok_object(dict(get_path("price_books", pid)))


def active_price_book(on_date):
    """The book with the latest effective_from <= on_date (any status ACTIVE)."""
    cands = [b for b in dbmod.db.price_books.values()
             if b["status"] == "ACTIVE" and b["effective_from"] <= on_date]
    if not cands:
        return None
    cands.sort(key=lambda b: (b["effective_from"], b["created_at"], b["id"]))
    return cands[-1]


# ---------- Shipment orders ----------

@bp.post("/decking/shipment-orders")
@require_roles("Dealer", "DealerSalesRep")
def create_order():
    data = body()
    dealer = get_body_ref("dealers", data.get("dealer_id"), "dealer_id")
    line = get_body_ref("product_lines", data.get("product_line_id"), "product_line_id")
    if g.role == "Dealer" and g.user_id != dealer["id"]:
        raise_err(ERR_UNAUTHORIZED, "dealer may only place own orders")
    lf = req_int(data, "lf", minimum=1)
    sws = req_str(data, "ship_week_start")
    parse_date(sws, "ship_week_start")
    if line["status"] == "SUNSET":
        raise_err(ERR_LINE_SUNSET, "SUNSET line forbids orders")
    if line["status"] != "ACTIVE":
        raise_err(ERR_LINE_SUPPORT_ONLY, "orders require line status ACTIVE")
    o = new_resource({
        "dealer_id": dealer["id"],
        "product_line_id": line["id"],
        "lf": lf,
        "ship_week_start": sws,
        "status": "REQUESTED",
        "invoiced_cents": None,
        "actual_ship_date": None,
        "price_book_id": None,
        "shipped_lot_ids": [],
    })
    dbmod.db.shipment_orders[o["id"]] = o
    return ok_object(dict(o), status=201)


@bp.get("/decking/shipment-orders/<oid>")
@require_roles("DealerSalesRep", "Dealer", "ChannelManager", "ClaimsAdjuster")
def get_order(oid):
    return ok_object(dict(get_path("shipment_orders", oid)))


@bp.get("/decking/shipment-orders")
@require_roles("DealerSalesRep", "Dealer", "ChannelManager")
def list_orders():
    items = list(dbmod.db.shipment_orders.values())
    for f in ("product_line_id", "price_book_id", "dealer_id", "status"):
        v = request.args.get(f)
        if v:
            items = [o for o in items if str(o.get(f)) == v]
    return ok_list([dict(o) for o in items])


@bp.post("/decking/shipment-orders/<oid>/confirm")
@require_roles("DealerSalesRep")
def confirm_order(oid):
    o = get_path("shipment_orders", oid)
    if o["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, f"order is {o['status']}")
    dealer = dbmod.db.dealers[o["dealer_id"]]
    if dealer["status"] != "ACTIVE":
        raise_err(ERR_DEALER_SUSPENDED, "dealer not ACTIVE")
    # pin price book: open allocation commitment for (dealer, line) wins
    pinned = None
    for ac in dbmod.db.allocation_commitments.values():
        if ac["dealer_id"] == o["dealer_id"] and ac["product_line_id"] == o["product_line_id"] \
                and ac["status"] == "OPEN":
            pinned = dbmod.db.price_books[ac["price_book_id"]]
            break
    if pinned is None:
        today = dbmod.clock_date().isoformat()
        pinned = active_price_book(today)
    if pinned is None:
        raise_err(ERR_INVALID_REQUEST, "no active price book")
    if o["product_line_id"] not in pinned["base_prices"]:
        raise_err(ERR_INVALID_REQUEST, "price book lacks base price for product line")
    # credit headroom with provisional invoicing
    ship_date_guess = date.fromisoformat(o["ship_week_start"])
    projected = calcs.invoice_cents(o, pinned, ship_date_guess)
    if dealer["outstanding_cents"] + projected >= dealer["credit_limit_cents"]:
        raise_err(ERR_CREDIT_LIMIT, "projected invoice exceeds credit headroom")
    # finished-goods availability net of confirmed-unshipped demand
    plant = plant_for_line(o["product_line_id"])
    fg = plant["fg_store"].get(o["product_line_id"], 0) if plant else 0
    committed = sum(x["lf"] for x in dbmod.db.shipment_orders.values()
                    if x["product_line_id"] == o["product_line_id"] and x["status"] == "CONFIRMED")
    if fg - committed < o["lf"]:
        raise_err(ERR_FG_SHORTFALL, "finished goods net of confirmed demand below order size")
    o["price_book_id"] = pinned["id"]
    o["status"] = "CONFIRMED"
    touch(o)
    return ok_object(dict(o))


@bp.post("/decking/shipment-orders/<oid>/ship")
@require_roles("DealerSalesRep")
def ship_order(oid):
    o = get_path("shipment_orders", oid)
    if o["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, f"order is {o['status']}")
    today = dbmod.clock_date()
    start = date.fromisoformat(o["ship_week_start"])
    if not (start <= today <= start + timedelta(days=6)):
        raise_err(ERR_OUTSIDE_SHIP_WEEK, "ship date outside the confirmed week window")
    plant = plant_for_line(o["product_line_id"])
    plant["fg_store"][o["product_line_id"]] = plant["fg_store"].get(o["product_line_id"], 0) - o["lf"]
    # FIFO lot consumption
    lots = [l for l in dbmod.db.board_lots.values()
            if l["product_line_id"] == o["product_line_id"] and l["disposition"] == "AVAILABLE"
            and not l["support_tagged"]]
    lots.sort(key=lambda l: (l["produced_at"], l["created_at"], l["id"]))
    remaining = o["lf"]
    consumed_ids = []
    for l in lots:
        if remaining <= 0:
            break
        consumed_ids.append(l["id"])
        l["disposition"] = "SHIPPED"
        touch(l)
        remaining -= l["lf"]
    o["shipped_lot_ids"] = consumed_ids
    pb = dbmod.db.price_books[o["price_book_id"]]
    invoiced = calcs.invoice_cents(o, pb, today)
    o["invoiced_cents"] = invoiced
    o["actual_ship_date"] = today.isoformat()
    dealer = dbmod.db.dealers[o["dealer_id"]]
    dealer["outstanding_cents"] += invoiced
    touch(dealer)
    o["status"] = "SHIPPED"
    touch(o)
    touch(plant)
    # consume the reservation's remaining share against shipment
    for ac in dbmod.db.allocation_commitments.values():
        if ac["dealer_id"] == o["dealer_id"] and ac["product_line_id"] == o["product_line_id"] \
                and ac["status"] == "OPEN":
            remaining = ac.get("remaining_lf", ac["reserved_lf"])
            consumed = min(o["lf"], remaining)
            ac["remaining_lf"] = remaining - consumed
            plant["reserved_fg_store"][o["product_line_id"]] = max(
                0, plant["reserved_fg_store"].get(o["product_line_id"], 0) - consumed)
            if ac["remaining_lf"] <= 0:
                ac["status"] = "CONSUMED"
            touch(ac)
            break
    return ok_object(dict(o))


@bp.post("/decking/shipment-orders/<oid>/deliver")
@require_roles("Dealer")
def deliver_order(oid):
    o = get_path("shipment_orders", oid)
    if g.user_id != o["dealer_id"]:
        raise_err(ERR_UNAUTHORIZED, "dealer may only deliver own orders")
    if o["status"] != "SHIPPED":
        raise_err(ERR_INVALID_STATE, f"order is {o['status']}")
    o["status"] = "DELIVERED"
    ship_year = date.fromisoformat(o["actual_ship_date"]).year
    for sc in dbmod.db.stocking_commitments.values():
        if sc["dealer_id"] == o["dealer_id"] and sc["product_line_id"] == o["product_line_id"] \
                and sc["season_year"] == ship_year and sc["status"] == "OPEN":
            sc["fulfilled_lf"] += o["lf"]
            if sc["fulfilled_lf"] >= sc["committed_lf"]:
                sc["status"] = "MET"
            touch(sc)
            break
    touch(o)
    return ok_object(dict(o))


@bp.post("/decking/shipment-orders/<oid>/cancel")
@require_roles("DealerSalesRep")
def cancel_order(oid):
    o = get_path("shipment_orders", oid)
    if o["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, f"order is {o['status']}")
    o["status"] = "CANCELLED"
    touch(o)
    return ok_object(dict(o))
