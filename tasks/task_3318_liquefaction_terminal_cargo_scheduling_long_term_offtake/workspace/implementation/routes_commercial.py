"""Customers, SPAs, logical clock."""
from flask import Blueprint, request

import db
from errors import ok_object, paginate, fail
from util import (auth, require_role, body, req_str, opt_str, req_enum, req_int,
                  req_num, stamp_new, touch, pub)
from services import apply_spa_expiry

bp = Blueprint("commercial", __name__)

CREDIT_RATINGS = {"AAA", "AA", "A", "BBB"}
COMMODITY_INDEXES = {"HENRY_HUB", "TTF", "JKM"}
READ_ROLES = ["TerminalOperator", "CommercialManager", "GasScheduler", "MarineScheduler", "CustomerRep"]


@bp.post("/api/customers")
def create_customer():
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    data = body()
    legal_name = req_str(data, "legal_name")
    credit_rating = req_enum(data, "credit_rating", CREDIT_RATINGS)
    billing_currency = opt_str(data, "billing_currency", "USD")
    cust = stamp_new({
        "legal_name": legal_name,
        "credit_rating": credit_rating,
        "billing_currency": billing_currency,
    })
    db.customers[cust["id"]] = cust
    return ok_object(pub(cust), 201)


@bp.get("/api/customers/<cid>")
def get_customer(cid):
    auth()
    cust = db.customers.get(cid)
    if not cust:
        fail("ERR_NOT_FOUND", "customer not found")
    return ok_object(pub(cust))


@bp.get("/api/customers/<cid>/spas")
def list_customer_spas(cid):
    auth()
    cust = db.customers.get(cid)
    if not cust:
        fail("ERR_NOT_FOUND", "customer not found")
    items = [s for s in db.spas.values() if s["customer_id"] == cid]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    for s in items:
        apply_spa_expiry(s)
    return paginate([pub(s) for s in items], request.args)


@bp.post("/api/spas")
def create_spa():
    user_id, role = auth()
    require_role(role, ["CommercialManager"])
    data = body()
    customer_id = data.get("customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        fail("ERR_INVALID_REQUEST", "customer_id is required")
    contract_year_start = req_int(data, "contract_year_start")
    term_years = req_int(data, "term_years", min_value=1)
    acq = req_int(data, "annual_contract_quantity_mmbtu")
    if acq <= 0:
        fail("ERR_INVALID_REQUEST", "annual_contract_quantity_mmbtu must be > 0")
    fee = req_num(data, "fixed_liquefaction_fee_usd_per_mmbtu")
    multiplier = req_num(data, "commodity_multiplier")
    index = req_enum(data, "commodity_index", COMMODITY_INDEXES)
    dest = req_enum(data, "destination_flexibility", {"FOB", "DES"})
    title = req_enum(data, "title_transfer_point", {"LOADING_FLANGE", "DISCHARGE_PORT"})
    notice = req_int(data, "cancellation_notice_days", min_value=0)
    tol = req_num(data, "tolerance_pct", min_value=0, max_value=1)
    est = req_num(data, "estimated_index_price_usd_per_mmbtu", min_value=0, min_exclusive=True)
    # existence of body FK (priority 3) before schema? Schema already consumed above;
    # FK existence check here.
    if customer_id not in db.customers:
        fail("ERR_NOT_FOUND", "customer_id does not exist")
    spa = stamp_new({
        "customer_id": customer_id,
        "contract_year_start": contract_year_start,
        "term_years": term_years,
        "annual_contract_quantity_mmbtu": acq,
        "fixed_liquefaction_fee_usd_per_mmbtu": fee,
        "commodity_multiplier": multiplier,
        "commodity_index": index,
        "destination_flexibility": dest,
        "title_transfer_point": title,
        "cancellation_notice_days": notice,
        "tolerance_pct": tol,
        "estimated_index_price_usd_per_mmbtu": est,
        "status": "EXECUTED",
    })
    db.spas[spa["id"]] = spa
    return ok_object(pub(spa), 201)


@bp.get("/api/spas/<sid>")
def get_spa(sid):
    auth()
    spa = db.spas.get(sid)
    if not spa:
        fail("ERR_NOT_FOUND", "spa not found")
    apply_spa_expiry(spa)
    return ok_object(pub(spa))


@bp.get("/api/spas/<sid>/adps")
def list_spa_adps(sid):
    auth()
    spa = db.spas.get(sid)
    if not spa:
        fail("ERR_NOT_FOUND", "spa not found")
    apply_spa_expiry(spa)
    items = [a for a in db.adps.values() if a["spa_id"] == sid]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    return paginate([pub(a) for a in items], request.args)


@bp.post("/api/spas/<sid>/commence-deliveries")
def commence_deliveries(sid):
    user_id, role = auth()
    require_role(role, ["CommercialManager"])
    spa = db.spas.get(sid)
    if not spa:
        fail("ERR_NOT_FOUND", "spa not found")
    apply_spa_expiry(spa)
    if spa["status"] != "EXECUTED":
        fail("ERR_SPA_INVALID_STATE", "SPA is not in EXECUTED")
    if not any(t["status"] == "COMMERCIAL_OPERATION" for t in db.trains.values()):
        fail("ERR_NO_COMMERCIAL_TRAIN", "no train in COMMERCIAL_OPERATION")
    spa["status"] = "DELIVERIES_COMMENCED"
    touch(spa)
    return ok_object(pub(spa))


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    user_id, role = auth()
    require_role(role, ["TerminalOperator"])
    data = body()
    to_iso8601 = data.get("to_iso8601")
    if not isinstance(to_iso8601, str):
        fail("ERR_INVALID_REQUEST", "to_iso8601 is required")
    from util import parse_dt
    dt = parse_dt(to_iso8601, "to_iso8601")
    db.set_clock(dt)
    from util import dt_to_iso
    return ok_object({"current_utc": dt_to_iso(db.get_clock())})
