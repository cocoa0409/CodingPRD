"""The logical clock, on-air talent, the product catalogue and viewers
(PRD 2.5, 3.1, 3.2, 3.8, 3.9)."""

from flask import Blueprint, request

import calc
import serializers as ser
from envelope import respond, respond_list
from errors import ApiError
from guards import (
    ALL_ROLES, ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_MERCH, ROLE_SHOW_PRODUCER,
    authenticate, body, get_host, get_product, get_viewer, opt_int, opt_str,
    req_dt, req_fraction, req_int, req_str,
)
from store import db, fmt_dt, new_record, now, set_clock, touch

bp = Blueprint("core", __name__)


# ------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate([ROLE_ADMIN])
    payload = body()
    value = req_dt(payload, "current_utc")
    previous = set_clock(value)
    return respond({
        "current_utc": fmt_dt(value),
        "previous_utc": fmt_dt(previous),
    })


# --------------------------------------------------------------------- hosts
@bp.post("/hosts")
def create_host():
    authenticate([ROLE_SHOW_PRODUCER, ROLE_ADMIN])
    payload = body()
    full_name = req_str(payload, "full_name")
    handle = req_str(payload, "handle", 3, 30)
    commission_pct = req_fraction(payload, "commission_pct", 0.0, 0.30)
    for existing in db.hosts.values():
        if existing["handle"] == handle:
            raise ApiError("ERR_INVALID_REQUEST", "handle is already in use.")
    record = new_record()
    record.update({
        "full_name": full_name,
        "handle": handle,
        "commission_pct": commission_pct,
        "disclosure_certification_expires_at": None,
        "effectiveness_score_live": 0,
        "effectiveness_score_attributed": 0,
    })
    db.hosts[record["id"]] = record
    return respond(ser.host_out(record), 201)


@bp.get("/hosts/<host_id>")
def read_host(host_id):
    authenticate(ALL_ROLES)
    return respond(ser.host_out(get_host(host_id)))


@bp.post("/hosts/<host_id>/disclosure-certifications")
def certify_host(host_id):
    authenticate([ROLE_COMPLIANCE])
    host = get_host(host_id)
    payload = body()
    certified_until = req_dt(payload, "certified_until")
    host["disclosure_certification_expires_at"] = certified_until
    touch(host)
    return respond(ser.host_out(host))


@bp.get("/hosts/<host_id>/performance")
def host_performance(host_id):
    authenticate([ROLE_SHOW_PRODUCER, ROLE_MERCH, ROLE_ADMIN])
    host = get_host(host_id)
    variant = request.args.get("variant")
    if variant is None:
        variant = "LIVE_WINDOW"
    if variant not in ("LIVE_WINDOW", "ATTRIBUTED_72H"):
        raise ApiError("ERR_INVALID_REQUEST", "variant is not a permitted value.")
    show_id = request.args.get("show_id")
    result = calc.host_effectiveness(host, variant, show_id)
    if variant == "ATTRIBUTED_72H":
        host["effectiveness_score_attributed"] = result["effectiveness_score"]
    else:
        host["effectiveness_score_live"] = result["effectiveness_score"]
    touch(host)
    data = {"host_id": host["id"], "variant": variant}
    data.update(result)
    return respond(data)


# ------------------------------------------------------------------ products
@bp.post("/products")
def create_product():
    authenticate([ROLE_MERCH])
    payload = body()
    sku = req_str(payload, "sku")
    title = req_str(payload, "title")
    base_price_cents = req_int(payload, "base_price_cents", 100, 5000000)
    unit_cost_cents = req_int(payload, "unit_cost_cents", 0)
    if unit_cost_cents >= base_price_cents:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "unit_cost_cents must be strictly less than base_price_cents.")
    on_hand_qty = req_int(payload, "on_hand_qty", 0)
    claim_text = opt_str(payload, "claim_text")
    for existing in db.products.values():
        if existing["sku"] == sku:
            raise ApiError("ERR_INVALID_REQUEST", "sku is already in use.")
    record = new_record()
    record.update({
        "sku": sku,
        "title": title,
        "base_price_cents": base_price_cents,
        "unit_cost_cents": unit_cost_cents,
        "on_hand_qty": on_hand_qty,
        "claim_text": claim_text,
        "claim_substantiation_status": "UNSUBSTANTIATED",
        "substantiated_by_user_id": None,
        "substantiated_at": None,
    })
    db.products[record["id"]] = record
    return respond(ser.product_out(record), 201)


@bp.get("/products/<product_id>")
def read_product(product_id):
    authenticate(ALL_ROLES)
    return respond(ser.product_out(get_product(product_id)))


@bp.post("/products/<product_id>/inventory-adjustments")
def adjust_inventory(product_id):
    authenticate([ROLE_MERCH])
    product = get_product(product_id)
    payload = body()
    req_str(payload, "reason")
    on_hand_delta = opt_int(payload, "on_hand_delta", default=0)
    unit_cost_cents = opt_int(payload, "unit_cost_cents", 0)
    reserved, committed, _ = calc.product_pools(product)
    new_on_hand = product["on_hand_qty"] + on_hand_delta
    if new_on_hand - reserved - committed < 0:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY")
    product["on_hand_qty"] = new_on_hand
    if unit_cost_cents is not None:
        product["unit_cost_cents"] = unit_cost_cents
    touch(product)
    return respond(ser.product_out(product))


@bp.post("/products/<product_id>/claim-substantiations")
def substantiate_claim(product_id):
    user_id, _ = authenticate([ROLE_COMPLIANCE])
    product = get_product(product_id)
    payload = body()
    decision = req_str(payload, "decision")
    if decision not in ("UNSUBSTANTIATED", "SUBSTANTIATED", "REJECTED"):
        raise ApiError("ERR_INVALID_REQUEST", "decision is not a permitted value.")
    opt_str(payload, "evidence_ref")
    product["claim_substantiation_status"] = decision
    if decision == "SUBSTANTIATED":
        product["substantiated_by_user_id"] = user_id
        product["substantiated_at"] = now()
    elif decision == "REJECTED":
        product["substantiated_by_user_id"] = None
        product["substantiated_at"] = None
    touch(product)
    return respond(ser.product_out(product))


# ------------------------------------------------------------------- viewers
@bp.post("/viewers")
def create_viewer():
    authenticate([ROLE_ADMIN])
    payload = body()
    display_name = req_str(payload, "display_name")
    email = req_str(payload, "email")
    for existing in db.viewers.values():
        if existing["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email is already in use.")
    record = new_record()
    record.update({
        "display_name": display_name,
        "email": email,
        "chat_status": "ACTIVE",
        "strike_count": 0,
        "muted_until": None,
    })
    db.viewers[record["id"]] = record
    return respond(ser.viewer_out(record), 201)


@bp.get("/viewers/<viewer_id>")
def read_viewer(viewer_id):
    authenticate(ALL_ROLES)
    return respond(ser.viewer_out(get_viewer(viewer_id)))
