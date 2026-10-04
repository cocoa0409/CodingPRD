from flask import Blueprint, request
from db import STORE, new_entity, touch, logical_now
from errors import (ApiError, err_invalid_request, err_invalid_state,
                    ERR_STALE_CONFIGURATION_VERSION, ERR_CREDIT_LIMIT_EXCEEDED,
                    ERR_INVALID_ORDER_QUANTITY)
from middleware import require_roles, require_ownership
from helpers import (get_json_body, require_field, optional_field, get_pagination,
                     paginate, store_lookup, ser_order, ser_order_line, iso_z,
                     iso_z_logical)
from response import success_object, success_list
from services.core import price_order, promised_ship_date, rescore_queue

bp = Blueprint("orders", __name__)

SHIP_MODES = {"SINGLE_ADDRESS", "DROP_SHIP_EMPLOYEES"}


@bp.post("/api/orders")
def create_order():
    uid, role = require_roles("CustomerUser")
    body = get_json_body()
    account_id = require_field(body, "account_id", str)
    store_lookup("accounts", account_id)
    require_ownership(account_id, uid, role)
    po = require_field(body, "po_number", str)
    ent = new_entity()
    ent.update({
        "account_id": account_id,
        "po_number": po,
        "build_status": "DRAFT",
        "ship_status": "PENDING",
        "promised_ship_date": None,
        "total_cents": 0,
        "discount_cents": 0,
        "submitted_at": None,
    })
    STORE.orders[ent["id"]] = ent
    return success_object(ser_order(ent), 201)


@bp.get("/api/orders/<oid>")
def get_order(oid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser", "FactoryOps")
    ent = store_lookup("orders", oid)
    require_ownership(ent["account_id"], uid, role)
    return success_object(ser_order(ent))


@bp.get("/api/accounts/<aid>/orders")
def list_account_orders(aid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    store_lookup("accounts", aid)
    require_ownership(aid, uid, role)
    limit, offset = get_pagination()
    items = [o for o in STORE.orders.values() if o["account_id"] == aid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_order(o) for o in items], limit, offset, total)


@bp.post("/api/orders/<oid>/lines")
def add_order_line(oid):
    uid, role = require_roles("CustomerUser")
    order = store_lookup("orders", oid)
    require_ownership(order["account_id"], uid, role)
    if order["build_status"] != "DRAFT":
        raise err_invalid_state("Order is not DRAFT")
    body = get_json_body()
    configuration_id = require_field(body, "configuration_id", str)
    store_lookup("configurations", configuration_id)
    qty = require_field(body, "qty", int)
    ship_to_mode = require_field(body, "ship_to_mode", str, enum=SHIP_MODES)
    if qty < 1:
        raise ApiError(ERR_INVALID_ORDER_QUANTITY, "Line qty must be >= 1", 422)
    ent = new_entity()
    ent.update({
        "order_id": oid,
        "configuration_id": configuration_id,
        "qty": qty,
        "line_total_cents": 0,
        "ship_to_mode": ship_to_mode,
        "status": "OPEN",
    })
    STORE.order_lines[ent["id"]] = ent
    return success_object(ser_order_line(ent), 201)


@bp.get("/api/orders/<oid>/lines")
def list_order_lines(oid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser", "FactoryOps")
    order = store_lookup("orders", oid)
    require_ownership(order["account_id"], uid, role)
    limit, offset = get_pagination()
    items = [l for l in STORE.order_lines.values() if l["order_id"] == oid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_order_line(l) for l in items], limit, offset, total)


@bp.get("/api/order-lines/<lid>")
def get_order_line(lid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser", "FactoryOps")
    line = store_lookup("order_lines", lid)
    order = STORE.orders.get(line["order_id"])
    if order:
        require_ownership(order["account_id"], uid, role)
    return success_object(ser_order_line(line))


@bp.get("/api/order-lines")
def list_order_lines_global():
    require_roles("PlatformAdmin", "AccountManager", "FactoryOps")
    limit, offset = get_pagination()
    items = list(STORE.order_lines.values())
    for f in ("order_id", "configuration_id"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l[f] == v]
    items, total = paginate(items, limit, offset)
    return success_list([ser_order_line(l) for l in items], limit, offset, total)


@bp.post("/api/orders/<oid>/submit")
def submit_order(oid):
    uid, role = require_roles("CustomerUser")
    order = store_lookup("orders", oid)
    require_ownership(order["account_id"], uid, role)
    if order["build_status"] != "DRAFT":
        raise err_invalid_state("Order is not DRAFT")
    body = get_json_body()
    expected = require_field(body, "expected_configuration_version", int)
    lines = [l for l in STORE.order_lines.values() if l["order_id"] == oid]
    if not lines:
        raise err_invalid_state("Order has no lines")
    # OCC guard (priority 5)
    for line in lines:
        cfg = STORE.configurations.get(line["configuration_id"])
        if cfg is None:
            continue
        if cfg["version"] != expected:
            raise ApiError(ERR_STALE_CONFIGURATION_VERSION,
                           "expected_configuration_version does not match configuration's current version",
                           412)
    # state rule: every line's configuration VALIDATED or LOCKED
    for line in lines:
        cfg = STORE.configurations.get(line["configuration_id"])
        if cfg is None or cfg["status"] not in ("VALIDATED", "LOCKED"):
            raise err_invalid_state("Every line's configuration must be VALIDATED or LOCKED")
    account = STORE.accounts.get(order["account_id"])
    # fiscal rule
    total, discount = price_order(order, lines, account)
    if account["outstanding_cents"] + total > account["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED,
                       "outstanding_cents + order total would exceed credit limit", 402)
    # commit
    submitted_dt = logical_now()
    order["submitted_at"] = iso_z_logical(submitted_dt)
    psd = promised_ship_date(order, lines, account, submitted_dt)
    order["promised_ship_date"] = iso_z_logical(psd)
    order["total_cents"] = total
    order["discount_cents"] = discount
    order["build_status"] = "SUBMITTED"
    touch(order)
    account["outstanding_cents"] += total
    touch(account)
    cfg_ids = set()
    for line in lines:
        touch(line)
        cfg_ids.add(line["configuration_id"])
        job = new_entity()
        job.update({
            "order_id": oid,
            "order_line_id": line["id"],
            "sequence_rank": None,
            "qty": line["qty"],
            "shortage_component_id": None,
            "status": "QUEUED",
        })
        STORE.build_jobs[job["id"]] = job
    for cid in cfg_ids:
        cfg = STORE.configurations.get(cid)
        if cfg is not None:
            touch(cfg)
    rescore_queue()
    return success_object(ser_order(order))


@bp.post("/api/orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = require_roles("CustomerUser")
    order = store_lookup("orders", oid)
    require_ownership(order["account_id"], uid, role)
    if order["build_status"] == "DRAFT":
        order["build_status"] = "CANCELLED"
        touch(order)
        return success_object(ser_order(order))
    if order["build_status"] != "SUBMITTED":
        raise err_invalid_state("Order cannot be cancelled from its current state")
    jobs = [j for j in STORE.build_jobs.values() if j["order_id"] == oid]
    if any(j["status"] in ("ALLOCATED", "BUILDING", "COMPLETE") for j in jobs):
        raise err_invalid_state("Order has allocated or started build jobs")
    for j in jobs:
        if j["status"] == "QUEUED":
            j["status"] = "CANCELLED"
            touch(j)
    account = STORE.accounts.get(order["account_id"])
    if account is not None:
        account["outstanding_cents"] -= order["total_cents"]
        touch(account)
    order["build_status"] = "CANCELLED"
    touch(order)
    return success_object(ser_order(order))
