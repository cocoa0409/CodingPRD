"""Vendors, order placement with routing, and order settlement."""

from datetime import timedelta

from flask import Blueprint

import calc
from core import (ROLE_DESIGNER, ROLE_FRANCHISEE, ROLE_FRANCHISOR, ROLE_VENDOR_REP,
                  append_ledger, auth, check_range, fail, get_body, get_opening,
                  get_order, get_quote, get_vendor, list_response, money, new_row,
                  openings_of_order, rederive_territory, rederive_vendor, req_enum,
                  req_enum_list, req_fk, req_int, req_list, req_str, respond_object,
                  require_territory_active, require_territory_ownership_row, royalty_on,
                  serialize, store, territory_of_order, territory_of_quote, touch)
from routes_quote import flip_if_expired

bp = Blueprint("order", __name__)

REMAKE_POLICIES = ("FULL_VENDOR_90D", "SHARED_50_50", "NO_REMAKE")
VENDOR_STATUSES = ("ACTIVE", "SUSPENDED")
ORDER_OCCUPYING = ("PLACED", "SHIPPED", "RECEIVED", "REMAKE_REQUESTED")


# --------------------------------------------------------------------------
# Vendors (PRD 3.7)
# --------------------------------------------------------------------------
@bp.route("/blinds/vendors", methods=["POST"])
def create_vendor():
    auth(ROLE_FRANCHISOR)
    body = get_body()
    name = req_str(body, "name", 1, 120)
    base_lead_time_days = req_int(body, "base_lead_time_days")
    motorization_extra_days = body.get("motorization_extra_days")
    motorization_extra_days = (0 if motorization_extra_days is None
                               else req_int(body, "motorization_extra_days"))
    cutoff_hour_utc = body.get("cutoff_hour_utc")
    cutoff_hour_utc = (17 if cutoff_hour_utc is None
                       else req_int(body, "cutoff_hour_utc"))
    remake_policy = req_enum(body, "remake_policy", REMAKE_POLICIES)
    concurrent_capacity = body.get("concurrent_capacity")
    concurrent_capacity = (2 if concurrent_capacity is None
                           else req_int(body, "concurrent_capacity"))
    supported_lift_systems = req_enum_list(body, "supported_lift_systems",
                                           calc.LIFT_SYSTEMS, 1, 4)
    if "supported_hub_platforms" in body and body["supported_hub_platforms"] is not None:
        supported_hub_platforms = req_enum_list(body, "supported_hub_platforms",
                                                calc.HUB_PLATFORMS, 0, 4)
    else:
        supported_hub_platforms = []
    status = body.get("status")
    status = "ACTIVE" if status is None else req_enum(body, "status", VENDOR_STATUSES)
    check_range(1 <= base_lead_time_days <= 120,
                "base_lead_time_days must be between 1 and 120")
    check_range(0 <= motorization_extra_days <= 60,
                "motorization_extra_days must be between 0 and 60")
    check_range(0 <= cutoff_hour_utc <= 23, "cutoff_hour_utc must be between 0 and 23")
    check_range(concurrent_capacity >= 1, "concurrent_capacity must be at least 1")
    for other in store.vendors.values():
        if other["name"] == name:
            fail("ERR_INVALID_REQUEST", "vendor name is already in use")
    row = new_row({
        "name": name,
        "base_lead_time_days": base_lead_time_days,
        "motorization_extra_days": motorization_extra_days,
        "cutoff_hour_utc": cutoff_hour_utc,
        "remake_policy": remake_policy,
        "concurrent_capacity": concurrent_capacity,
        "supported_lift_systems": list(supported_lift_systems),
        "supported_hub_platforms": list(supported_hub_platforms),
        "status": status,
        "open_order_count": 0,
    })
    store.vendors[row["id"]] = row
    return respond_object(serialize(row), 201)


@bp.route("/blinds/vendors/<vendor_id>", methods=["GET"])
def read_vendor(vendor_id):
    auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE)
    return respond_object(serialize(get_vendor(vendor_id)), 200)


# --------------------------------------------------------------------------
# Placement helpers
# --------------------------------------------------------------------------
def _is_motorized(openings):
    return any((o.get("motorization_option") or "NONE") != "NONE" for o in openings)


def _basic_eligibility(vendor, openings, motorized):
    """The first three of the four conditions of PRD 3.7."""
    if vendor["status"] != "ACTIVE":
        return False
    supported = vendor["supported_lift_systems"]
    for opening in openings:
        if opening.get("lift_system") not in supported:
            return False
    if motorized and not vendor["supported_hub_platforms"]:
        return False
    return True


def _stamp_placement(order, vendor, motorized):
    effective, days, promised = calc.compute_lead_time(
        vendor, store.clock, motorized, order["remake_count"])
    order["placed_at"] = store.clock
    order["effective_placement_date"] = effective
    order["lead_time_days"] = days
    order["promised_ship_date"] = promised
    order["status"] = "PLACED"
    return effective, promised


def _select_vendor(openings, motorized, order_cost_cents, territory):
    """PRD 3.7: the routing selector, then the fiscal check, in that order."""
    candidates = []
    for vendor in store.vendors.values():
        if not _basic_eligibility(vendor, openings, motorized):
            continue
        effective, days, promised = calc.compute_lead_time(vendor, store.clock,
                                                          motorized, 0)
        if not calc.capacity_admits(vendor, effective, promised):
            continue
        candidates.append((promised, vendor))
    if not candidates:
        fail("ERR_NO_ELIGIBLE_VENDOR", "no vendor can manufacture this order")
    candidates.sort(key=lambda pair: (
        "%04d-%02d-%02d" % (pair[0].year, pair[0].month, pair[0].day),
        pair[1]["open_order_count"],
        pair[1]["created_at"],
        pair[1]["id"],
    ))
    return candidates[0][1]


def _check_credit(territory, order_cost_cents):
    """Ladder stage 19 -- evaluated last of all."""
    if territory is None:
        return
    exposure = territory["open_order_exposure_cents"] + order_cost_cents
    if exposure > territory["credit_limit_cents"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED",
             "exposure of %s exceeds the credit limit" % exposure)


@bp.route("/blinds/vendor-orders", methods=["POST"])
def create_order():
    actor = auth(ROLE_FRANCHISEE)
    body = get_body()
    quote = req_fk(body, "quote_id", get_quote)
    raw_ids = body.get("opening_ids")
    if isinstance(raw_ids, list):
        for raw in raw_ids:
            if isinstance(raw, str):
                get_opening(raw)
    req_fk(body, "preferred_vendor_id", get_vendor)
    if quote is not None:
        require_territory_ownership_row(actor, territory_of_quote(quote))
    quote = get_quote(req_str(body, "quote_id", 1, None))
    opening_ids = req_list(body, "opening_ids", 1, 40)
    expected_version = req_int(body, "expected_quote_version")
    preferred_vendor_id = body.get("preferred_vendor_id")
    if preferred_vendor_id is not None:
        preferred_vendor_id = req_str(body, "preferred_vendor_id", 1, None)
    openings = [store.openings[oid] for oid in opening_ids]
    for opening in openings:
        if opening.get("quote_id") != quote["id"]:
            fail("ERR_OPENING_NOT_ON_QUOTE",
                 "opening %s does not belong to the quote" % opening["id"])
    if expected_version != quote["version"]:
        fail("ERR_STALE_QUOTE_VERSION", "quote version is %s" % quote["version"])
    territory = territory_of_quote(quote)
    require_territory_active(territory)
    flip_if_expired(quote)
    if quote["status"] != "ACCEPTED":
        fail("ERR_QUOTE_NOT_ACCEPTED", "quote status is %s" % quote["status"])
    for opening in openings:
        if opening.get("install_outcome") != "PENDING":
            fail("ERR_OPENING_ALREADY_ORDERED",
                 "opening %s is already resolved" % opening["id"])
    for order in store.vendor_orders.values():
        if order["status"] not in ORDER_OCCUPYING:
            continue
        for opening in openings:
            if opening["id"] in order["opening_ids"]:
                fail("ERR_OPENING_ALREADY_ORDERED",
                     "opening %s already sits on a live order" % opening["id"])
    lead = store.leads.get(quote["lead_id"])
    if calc.cordless_violated(openings, lead):
        fail("ERR_CORD_HAZARD_NOT_PERMITTED",
             "a child-occupied opening requires a cordless or motorized lift")
    motorized = _is_motorized(openings)
    order_cost = calc.order_cost_cents(openings)
    if preferred_vendor_id is not None:
        vendor = get_vendor(preferred_vendor_id)
        if not _basic_eligibility(vendor, openings, motorized):
            fail("ERR_NO_ELIGIBLE_VENDOR", "the pinned vendor is not eligible")
        effective, days, promised = calc.compute_lead_time(vendor, store.clock,
                                                           motorized, 0)
        if not calc.capacity_admits(vendor, effective, promised):
            fail("ERR_VENDOR_CAPACITY_EXCEEDED",
                 "the pinned vendor has no production capacity in that window")
    else:
        vendor = _select_vendor(openings, motorized, order_cost, territory)
    _check_credit(territory, order_cost)
    row = new_row({
        "quote_id": quote["id"],
        "vendor_id": vendor["id"],
        "opening_ids": list(opening_ids),
        "status": "PLACED",
        "remake_count": 0,
        "credit_scope": "NONE",
        "placed_at": None,
        "effective_placement_date": None,
        "lead_time_days": 0,
        "promised_ship_date": None,
        "shipped_at": None,
        "received_at": None,
        "order_cost_cents": order_cost,
        "remake_cost_cents": 0,
        "vendor_absorbed_cents": 0,
        "territory_absorbed_cents": 0,
        "customer_absorbed_cents": 0,
    })
    _stamp_placement(row, vendor, motorized)
    store.vendor_orders[row["id"]] = row
    rederive_vendor(vendor)
    if territory is not None:
        rederive_territory(territory)
    touch(quote)
    return respond_object(serialize(row), 201)


@bp.route("/blinds/vendor-orders/<order_id>", methods=["GET"])
def read_order(order_id):
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER, ROLE_VENDOR_REP)
    order = get_order(order_id)
    require_territory_ownership_row(actor, territory_of_order(order))
    return respond_object(serialize(order), 200)


@bp.route("/blinds/vendor-orders", methods=["GET"])
def list_orders():
    actor = auth(ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_VENDOR_REP)
    rows = list(store.vendor_orders.values())
    return list_response(rows, ("quote_id", "vendor_id", "status"))


# --------------------------------------------------------------------------
# Settlement (PRD 3.8)
# --------------------------------------------------------------------------
@bp.route("/blinds/vendor-orders/<order_id>/ship", methods=["POST"])
def ship_order(order_id):
    actor = auth(ROLE_VENDOR_REP)
    order = get_order(order_id)
    if actor.user_id != order["vendor_id"]:
        fail("ERR_ROLE_NOT_PERMITTED", "the order belongs to another manufacturer")
    if order["status"] != "PLACED":
        fail("ERR_ORDER_NOT_SHIPPABLE", "order status is %s" % order["status"])
    order["status"] = "SHIPPED"
    order["shipped_at"] = store.clock
    touch(order)
    return respond_object(serialize(order), 200)


@bp.route("/blinds/vendor-orders/<order_id>/receive", methods=["POST"])
def receive_order(order_id):
    actor = auth(ROLE_FRANCHISEE)
    order = get_order(order_id)
    territory = territory_of_order(order)
    require_territory_ownership_row(actor, territory)
    if order["status"] != "SHIPPED":
        fail("ERR_ORDER_NOT_SHIPPED", "order status is %s" % order["status"])
    order["status"] = "RECEIVED"
    order["received_at"] = store.clock
    touch(order)
    vendor = store.vendors.get(order["vendor_id"])
    if vendor is not None:
        rederive_vendor(vendor)
    if territory is not None:
        rederive_territory(territory)
    return respond_object(serialize(order), 200)


def apply_remake_waterfall(order, origin, liable_party=None):
    """PRD 3.8: the three buckets plus the conditional chargeback row."""
    vendor = store.vendors.get(order["vendor_id"])
    cost = order["order_cost_cents"]
    absorbed = calc.remake_waterfall(cost, origin, vendor, liable_party)
    order["remake_cost_cents"] = cost
    order["vendor_absorbed_cents"] = absorbed[0]
    order["territory_absorbed_cents"] = absorbed[1]
    order["customer_absorbed_cents"] = absorbed[2]
    territory = territory_of_order(order)
    if absorbed[1] > 0 and territory is not None:
        append_ledger(territory, "REMAKE_CHARGEBACK", absorbed[1], cost,
                      "VENDOR_ORDER", order["id"], "remake_replacement")
    return territory


def replace_order(order, origin, liable_party=None):
    """RECEIVED -> REMAKE_REQUESTED -> PLACED, all inside the one request."""
    vendor = store.vendors.get(order["vendor_id"])
    order["status"] = "REMAKE_REQUESTED"
    order["credit_scope"] = "REPLACEMENT"
    order["remake_count"] = order["remake_count"] + 1
    territory = apply_remake_waterfall(order, origin, liable_party)
    order["shipped_at"] = None
    order["received_at"] = None
    _stamp_placement(order, vendor, _is_motorized(openings_of_order(order)))
    touch(order)
    if vendor is not None:
        rederive_vendor(vendor)
    if territory is not None:
        rederive_territory(territory)
    return order


def _full_credit(order):
    """PRD 3.8: the compensating action of an acceptance."""
    territory = apply_remake_waterfall(order, "FRANCHISEE_REQUEST")
    order["credit_scope"] = "FULL_CREDIT"
    order["status"] = "CANCELLED"
    touch(order)
    openings = openings_of_order(order)
    for opening in openings:
        opening["credited"] = True
        touch(opening)
    quote = store.quotes.get(order["quote_id"])
    if quote is not None:
        credited_subtotal = sum(o["list_price_cents"] for o in openings)
        credited_discount = money(credited_subtotal * quote["discount_pct"])
        credited_basis = credited_subtotal - credited_discount
        old_recognized = quote["recognized_net_sales_cents"]
        new_recognized = old_recognized - credited_basis
        quote["credited_net_sales_cents"] = (
            quote["credited_net_sales_cents"] + credited_basis)
        quote["recognized_net_sales_cents"] = new_recognized
        touch(quote)
        if territory is not None:
            territory["net_sales_cents"] = territory["net_sales_cents"] - credited_basis
            delta = (royalty_on(territory, new_recognized)
                     - royalty_on(territory, old_recognized))
            append_ledger(territory, "ROYALTY_REVERSAL", delta, credited_basis,
                          "VENDOR_ORDER", order["id"], "remake_full_credit")
    if territory is not None:
        rederive_territory(territory)
    return order


@bp.route("/blinds/vendor-orders/<order_id>/remake", methods=["POST"])
def remake_order(order_id):
    actor = auth(ROLE_FRANCHISEE)
    order = get_order(order_id)
    require_territory_ownership_row(actor, territory_of_order(order))
    body = get_body()
    credit_scope = req_enum(body, "credit_scope", ("REPLACEMENT", "FULL_CREDIT"))
    if order["status"] != "RECEIVED":
        fail("ERR_ORDER_NOT_RECEIVED", "order status is %s" % order["status"])
    vendor = store.vendors.get(order["vendor_id"])
    if vendor is not None and vendor["remake_policy"] == "NO_REMAKE":
        fail("ERR_REMAKE_NOT_OFFERED", "the manufacturer offers no remake")
    if order["remake_count"] >= calc.ORDER_MAX_REMAKES:
        fail("ERR_REMAKE_LIMIT_REACHED", "the remake cap of two is reached")
    if (vendor is not None and vendor["remake_policy"] == "FULL_VENDOR_90D"
            and order["received_at"] is not None):
        deadline = order["received_at"] + timedelta(days=calc.VENDOR_REMAKE_WINDOW_DAYS)
        if store.clock > deadline:
            fail("ERR_REMAKE_WINDOW_CLOSED", "the ninety-day remake window is closed")
    if credit_scope == "FULL_CREDIT":
        for opening in openings_of_order(order):
            if opening.get("install_outcome") != "PENDING":
                fail("ERR_OPENINGS_ALREADY_RESOLVED",
                     "opening %s is already resolved" % opening["id"])
        _full_credit(order)
    else:
        replace_order(order, "FRANCHISEE_REQUEST")
    return respond_object(serialize(order), 200)
