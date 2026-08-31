"""Orders, order lines, take-back collections and the credit ledger."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import core
import enums
import store
import views
from core import (D, authenticate, body, caller_id, fail, is_customer_caller, now,
                  opt_bool, opt_num, opt_str, pagination, q_enum, q_str, req_enum,
                  req_int, req_num, req_str, rhu)

bp = Blueprint("commerce", __name__)

ORDER_READ_ROLES = ["PlatformAdmin", "SalesRep", "ProductManager", "ComplianceOfficer",
                    "Customer"]
COLLECTION_READ_ROLES = ["PlatformAdmin", "SalesRep", "QCTechnician", "QualityManager",
                         "ComplianceOfficer", "Customer"]


def _scope_check(customer_id):
    if is_customer_caller() and caller_id() != customer_id:
        fail("ERR_CUSTOMER_SCOPE_VIOLATION")


def _scoped_filter(requested_customer_id):
    if is_customer_caller():
        if requested_customer_id is not None and requested_customer_id != caller_id():
            fail("ERR_CUSTOMER_SCOPE_VIOLATION")
        return caller_id()
    return requested_customer_id


# ==========================================================================
# Order
# ==========================================================================
@bp.post("/orders")
def create_order():
    authenticate(["SalesRep"])
    b = body()
    customer_id = req_str(b, "customer_id")
    delivery_mode = req_enum(b, "delivery_mode", enums.DELIVERY_MODES)
    takeback_linked = opt_bool(b, "takeback_linked", False)
    customer = store.must_get("Customer", customer_id)
    record = {
        "customer_id": customer["id"],
        "delivery_mode": delivery_mode,
        "takeback_linked": takeback_linked,
        "status": "DRAFT",
        "subtotal_cents": 0,
        "total_volume_l": Decimal("0.00"),
        "freight_surcharge_cents": 0,
        "pre_credit_total_cents": 0,
        "takeback_credit_applied_cents": 0,
        "total_cents": 0,
        "hold_reason": None,
    }
    return views.one(store.insert("Order", record), 201)


@bp.get("/orders/<oid>")
def read_order(oid):
    authenticate(ORDER_READ_ROLES)
    order = store.must_get("Order", oid)
    _scope_check(order["customer_id"])
    return views.one(order)


@bp.get("/orders")
def list_orders():
    authenticate(ORDER_READ_ROLES)
    limit, offset = pagination()
    customer_id = q_str("customer_id")
    status = q_enum("status", enums.ORDER_STATUSES)
    delivery_mode = q_enum("delivery_mode", enums.DELIVERY_MODES)
    customer_id = _scoped_filter(customer_id)
    rows = store.where("Order", customer_id=customer_id, status=status,
                       delivery_mode=delivery_mode)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/orders/<oid>/lines")
def create_order_line(oid):
    authenticate(["SalesRep"])
    b = body()
    config_id = req_str(b, "package_configuration_id")
    quantity_units = req_int(b, "quantity_units", gt=0)

    order = store.must_get("Order", oid)                             # rung 4
    config = store.must_get("PackageConfiguration", config_id)       # rung 5
    if order["status"] != "DRAFT":                                   # rung 10
        fail("ERR_INVALID_STATE")
    if config["status"] != "ACTIVE":                                 # rung 15
        fail("ERR_CONFIG_NOT_ACTIVE")

    customer = store.get("Customer", order["customer_id"])
    line = store.insert("OrderLine", {
        "order_id": order["id"],
        "package_configuration_id": config["id"],
        "quantity_units": quantity_units,
        "volume_l": Decimal("0.00"),
        "unit_price_cents": 0,
        "line_total_cents": 0,
        "status": "OPEN",
    })
    calc.price_line(line, config, customer)
    cascades.recompute_line_totals_only(order)
    store.touch(order)
    return views.one(line, 201)


@bp.get("/orders/<oid>/lines")
def list_order_lines(oid):
    authenticate(ORDER_READ_ROLES)
    limit, offset = pagination()
    status = q_enum("status", enums.ORDER_LINE_STATUSES)
    order = store.must_get("Order", oid)
    _scope_check(order["customer_id"])
    rows = store.where("OrderLine", order_id=oid, status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/orders/<oid>/confirm")
def confirm_order(oid):
    authenticate(["SalesRep"])
    order = store.must_get("Order", oid)
    if order["status"] != "DRAFT":                                   # rung 10
        fail("ERR_INVALID_STATE")
    open_lines = [l for l in cascades.order_lines(order["id"]) if l["status"] == "OPEN"]
    if not open_lines:
        fail("ERR_INVALID_STATE", "The order carries no OPEN line.")
    for line in open_lines:                                          # rung 15
        config = store.get("PackageConfiguration", line["package_configuration_id"])
        if config is None or config["status"] != "ACTIVE":
            fail("ERR_CONFIG_NOT_ACTIVE")
    customer = store.get("Customer", order["customer_id"])
    if order["takeback_linked"]:                                     # rung 32
        if customer is None or customer["takeback_agreement_status"] != "ACTIVE":
            fail("ERR_TAKEBACK_AGREEMENT_INACTIVE")

    result = cascades.compute_totals(order)
    if customer is not None and \
            result["pre_credit_total_cents"] > customer["credit_limit_cents"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED")                            # rung 36

    cascades.commit_totals(order, result)
    order["status"] = "CONFIRMED"
    store.touch(order)
    return views.one(order)


@bp.post("/orders/<oid>/hold")
def hold_order(oid):
    authenticate(["SalesRep"])
    b = body()
    reason = req_str(b, "reason")
    order = store.must_get("Order", oid)
    if order["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE")
    order["status"] = "HOLD"
    order["hold_reason"] = reason
    store.touch(order)
    return views.one(order)


@bp.post("/orders/<oid>/resume")
def resume_order(oid):
    authenticate(["SalesRep"])
    order = store.must_get("Order", oid)
    if order["status"] != "HOLD":                                    # rung 10
        fail("ERR_INVALID_STATE")
    lines = cascades.order_lines(order["id"])
    live = [l for l in lines if l["status"] in ("OPEN", "HOLD")]
    for line in live:                                                # rung 15
        config = store.get("PackageConfiguration", line["package_configuration_id"])
        if config is None or config["status"] != "ACTIVE":
            fail("ERR_CONFIG_NOT_ACTIVE")

    open_ids = set(l["id"] for l in live)
    result = cascades.compute_totals(order, open_line_ids=open_ids)
    customer = store.get("Customer", order["customer_id"])
    if customer is not None and \
            result["pre_credit_total_cents"] > customer["credit_limit_cents"]:
        fail("ERR_CREDIT_LIMIT_EXCEEDED")                            # rung 36

    for line in lines:
        if line["status"] == "HOLD":
            line["status"] = "OPEN"
            store.touch(line)
    cascades.commit_totals(order, result)
    order["status"] = "CONFIRMED"
    order["hold_reason"] = None
    store.touch(order)
    return views.one(order)


@bp.post("/orders/<oid>/invoice")
def invoice_order(oid):
    authenticate(["SalesRep"])
    order = store.must_get("Order", oid)
    if order["status"] != "CONFIRMED" or order["total_cents"] <= 0:
        fail("ERR_INVALID_STATE")
    order["status"] = "INVOICED"
    store.touch(order)
    return views.one(order)


@bp.post("/orders/<oid>/void")
def void_order(oid):
    authenticate(["SalesRep"])
    b = body()
    req_str(b, "reason")
    order = store.must_get("Order", oid)
    if order["status"] not in ("DRAFT", "CONFIRMED", "HOLD"):
        fail("ERR_INVALID_STATE")
    settle_money = order["status"] in ("CONFIRMED", "HOLD")

    for line in cascades.order_lines(order["id"]):
        if line["status"] in ("OPEN", "HOLD"):
            line["status"] = "CANCELLED"
            store.touch(line)

    order["status"] = "VOID"
    if settle_money:
        order["takeback_credit_applied_cents"] = 0
        order["total_cents"] = order["pre_credit_total_cents"]
    store.touch(order)

    if settle_money:
        customer = store.get("Customer", order["customer_id"])
        if customer is not None:
            cascades.refresh_customer_balance(customer, stamp_event=False)
    return views.one(order)


@bp.post("/orders/<oid>/apply-takeback-credit")
def apply_takeback_credit(oid):
    authenticate(["SalesRep"])
    b = body()
    expected = req_int(b, "expected_customer_version")               # rung 3
    order = store.must_get("Order", oid)                             # rung 4
    customer = store.get("Customer", order["customer_id"])
    if customer is None or expected != customer["version"]:          # rung 9
        fail("ERR_STALE_CUSTOMER_VERSION")
    if order["status"] != "CONFIRMED":                               # rung 10
        fail("ERR_INVALID_STATE")
    if not order["takeback_linked"] or customer["takeback_credit_balance_cents"] <= 0:
        fail("ERR_NO_TAKEBACK_CREDIT")                               # rung 37

    cap = calc.credit_cap(order["pre_credit_total_cents"])
    order["takeback_credit_applied_cents"] = min(
        customer["takeback_credit_balance_cents"], cap)
    order["total_cents"] = (order["pre_credit_total_cents"]
                            - order["takeback_credit_applied_cents"])
    store.touch(order)
    cascades.refresh_customer_balance(customer, stamp_event=True)
    return views.one(order)


# ==========================================================================
# TakebackCollection
# ==========================================================================
@bp.post("/takeback-collections")
def create_collection():
    authenticate(["SalesRep", "Customer"])
    b = body()
    customer_id = req_str(b, "customer_id")
    order_id = opt_str(b, "order_id")
    scheduled_volume_l = opt_num(b, "scheduled_volume_l")

    customer = store.must_get("Customer", customer_id)               # rung 5
    if order_id is not None:
        store.must_get("Order", order_id)
    _scope_check(customer["id"])                                     # rung 6
    if customer["takeback_agreement_status"] != "ACTIVE":            # rung 32
        fail("ERR_TAKEBACK_AGREEMENT_INACTIVE")

    record = {
        "customer_id": customer["id"],
        "order_id": order_id,
        "scheduled_volume_l": scheduled_volume_l,
        "collected_volume_l": None,
        "water_pct": None,
        "sediment_pct": None,
        "status": "SCHEDULED",
        "credit_variant": None,
        "credit_cents": 0,
        "reject_reason": None,
    }
    return views.one(store.insert("TakebackCollection", record), 201)


@bp.get("/takeback-collections/<cid>")
def read_collection(cid):
    authenticate(COLLECTION_READ_ROLES)
    collection = store.must_get("TakebackCollection", cid)
    _scope_check(collection["customer_id"])
    return views.one(collection)


@bp.get("/takeback-collections")
def list_collections():
    authenticate(COLLECTION_READ_ROLES)
    limit, offset = pagination()
    customer_id = q_str("customer_id")
    order_id = q_str("order_id")
    status = q_enum("status", enums.COLLECTION_STATUSES)
    customer_id = _scoped_filter(customer_id)
    rows = store.where("TakebackCollection", customer_id=customer_id,
                       order_id=order_id, status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/takeback-collections/<cid>/collect")
def collect(cid):
    authenticate(["SalesRep"])
    b = body()
    collected_volume_l = req_num(b, "collected_volume_l", ge=0)
    collection = store.must_get("TakebackCollection", cid)
    if collection["status"] != "SCHEDULED":                          # rung 10
        fail("ERR_INVALID_STATE")
    customer = store.get("Customer", collection["customer_id"])
    if customer is None or customer["takeback_agreement_status"] != "ACTIVE":
        fail("ERR_TAKEBACK_AGREEMENT_INACTIVE")                      # rung 32
    collection["collected_volume_l"] = collected_volume_l
    collection["status"] = "COLLECTED"
    store.touch(collection)
    return views.one(collection)


@bp.post("/takeback-collections/<cid>/assay")
def assay(cid):
    authenticate(["QCTechnician"])
    b = body()
    water_pct = req_num(b, "water_pct", ge=0, le=100)
    sediment_pct = req_num(b, "sediment_pct", ge=0, le=100)
    collection = store.must_get("TakebackCollection", cid)
    if collection["status"] != "COLLECTED":                          # rung 10
        fail("ERR_INVALID_STATE")
    collection["water_pct"] = water_pct
    collection["sediment_pct"] = sediment_pct
    if D(water_pct) + D(sediment_pct) > calc.MAX_CONTAMINATION_PCT:
        collection["status"] = "REJECTED"
        collection["reject_reason"] = "CONTAMINATION_ABOVE_LIMIT"
    else:
        collection["status"] = "ASSAYED"
    store.touch(collection)
    return views.one(collection)


@bp.post("/takeback-collections/<cid>/credit")
def credit_collection(cid):
    authenticate(["SalesRep"])
    collection = store.must_get("TakebackCollection", cid)
    if collection["status"] not in ("COLLECTED", "ASSAYED"):         # rung 10
        fail("ERR_INVALID_STATE")
    customer = store.get("Customer", collection["customer_id"])
    variant = calc.takeback_variant(collection, customer)
    collection["credit_variant"] = variant
    collection["credit_cents"] = calc.takeback_credit_cents(collection, variant)
    collection["status"] = "CREDITED"
    store.touch(collection)
    if customer is not None:
        cascades.refresh_customer_balance(customer, stamp_event=True)
    return views.one(collection)
