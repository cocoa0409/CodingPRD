"""White-Label Delivery-as-a-Service Fulfillment API (PRD: workspace/PRD.md).

Flask app: validation layers per PRD section 2.6 —
  1 auth context -> 2 role authorization -> 3 path-id existence (left-to-right)
  -> 4 body FK existence (declared input order) -> 5 OCC -> 6 state
  -> 7 temporal conflicts -> 8 business constraints -> 9 fiscal sufficiency.
Payload shape errors are ERR_INVALID_REQUEST (400).
"""
import os
from datetime import timedelta
from decimal import Decimal

from flask import Flask, request

import db
import errors
import middleware as mw
import response as resp
import services as svc

app = Flask(__name__)


@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return resp.error(err)


@app.errorhandler(404)
def handle_404(err):
    return resp.error(errors.ApiError("ERR_INVALID_REQUEST", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return resp.error(errors.ApiError("ERR_INVALID_REQUEST", 405, "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return resp.error(err)
    return resp.error(errors.ApiError("ERR_INVALID_REQUEST", 400, str(err)))


def _paginate(items):
    limit, offset = mw.pagination_args()
    items = sorted(items, key=lambda e: e["created_at"])
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def _touch(e):
    svc.touch(e)


# ===========================================================================
# Test-driving controls: clock and surge (PlatformAdmin only)
# ===========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    mw.require_role("PlatformAdmin")
    b = mw.body()
    dt = mw.req_dt(b, "current_utc")
    db.set_clock(dt)
    return resp.ok({"current_utc": mw.iso(dt)})


@app.post("/_surge/set_current")
def set_surge():
    mw.require_role("PlatformAdmin")
    b = mw.body()
    m = mw.req_num(b, "multiplier")
    db.set_surge(m)
    return resp.ok({"multiplier": m})


# ===========================================================================
# Merchants
# ===========================================================================
@app.post("/merchants")
def create_merchant():
    mw.require_role("PlatformAdmin")
    b = mw.body()
    name = mw.req_str(b, "name")
    billing = mw.req_int(b, "billing_balance_cents")
    split = mw.opt_int(b, "default_refund_split_merchant_pct", 50)
    if split < 0 or split > 100:
        raise errors.bad_request("default_refund_split_merchant_pct must be 0..100")
    late_enabled = mw.opt_bool(b, "late_credit_enabled", True)
    m = svc.new_common()
    m.update({
        "name": name,
        "status": "ONBOARDING",
        "billing_balance_cents": billing,
        "credit_balance_cents": 0,
        "default_refund_split_merchant_pct": split,
        "late_credit_enabled": late_enabled,
    })
    db.merchants[m["id"]] = m
    return resp.ok(svc.merchant_view(m), 201)


@app.get("/merchants")
def list_merchants():
    mw.require_role("PlatformAdmin", "SupportAgent")
    items = list(db.merchants.values())
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.merchant_view(m) for m in page], limit, offset, total)


@app.get("/merchants/<mid>")
def get_merchant(mid):
    mw.require_role("PlatformAdmin", "SupportAgent", "Merchant")
    m = svc.get_merchant(mid)
    return resp.ok(svc.merchant_view(m))


@app.patch("/merchants/<mid>")
def update_merchant(mid):
    mw.require_role("PlatformAdmin", "Merchant")
    m = svc.get_merchant(mid)
    b = mw.body()
    if "default_refund_split_merchant_pct" in b:
        v = mw.req_int(b, "default_refund_split_merchant_pct")
        if v < 0 or v > 100:
            raise errors.bad_request("default_refund_split_merchant_pct must be 0..100")
        m["default_refund_split_merchant_pct"] = v
    if "late_credit_enabled" in b:
        v = b["late_credit_enabled"]
        if not isinstance(v, bool):
            raise errors.bad_request("late_credit_enabled must be a boolean")
        m["late_credit_enabled"] = v
    _touch(m)
    return resp.ok(svc.merchant_view(m))


@app.post("/merchants/<mid>/activate")
def activate_merchant(mid):
    mw.require_role("PlatformAdmin")
    m = svc.get_merchant(mid)
    if m["status"] != "ONBOARDING":
        raise errors.invalid_state("Only an ONBOARDING merchant can be activated")
    m["status"] = "ACTIVE"
    _touch(m)
    return resp.ok(svc.merchant_view(m))


@app.post("/merchants/<mid>/suspend")
def suspend_merchant(mid):
    mw.require_role("PlatformAdmin")
    m = svc.get_merchant(mid)
    if m["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE merchant can be suspended")
    svc.suspend_merchant_cascade(m)
    return resp.ok(svc.merchant_view(m))


@app.post("/merchants/<mid>/resume")
def resume_merchant(mid):
    mw.require_role("PlatformAdmin")
    m = svc.get_merchant(mid)
    if m["status"] != "SUSPENDED":
        raise errors.invalid_state("Only a SUSPENDED merchant can be resumed")
    m["status"] = "ACTIVE"
    _touch(m)
    return resp.ok(svc.merchant_view(m))


# ===========================================================================
# Stores
# ===========================================================================
@app.post("/merchants/<mid>/stores")
def create_store(mid):
    mw.require_role("Merchant", "PlatformAdmin")
    svc.get_merchant(mid)
    b = mw.body()
    name = mw.req_str(b, "name")
    address_text = mw.req_str(b, "address_text")
    lat = mw.req_num(b, "lat")
    lng = mw.req_num(b, "lng")
    radius = mw.req_int(b, "delivery_radius_m")
    tz = mw.req_str(b, "timezone")
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
    except Exception:
        raise errors.bad_request("timezone must be a valid IANA timezone")
    s = svc.new_common()
    s.update({
        "merchant_id": mid,
        "name": name,
        "address_text": address_text,
        "lat": lat,
        "lng": lng,
        "delivery_radius_m": radius,
        "timezone": tz,
        "status": "ACTIVE",
    })
    db.stores[s["id"]] = s
    return resp.ok(svc.store_view(s), 201)


@app.get("/merchants/<mid>/stores")
def list_stores(mid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent")
    svc.get_merchant(mid)
    items = [s for s in db.stores.values() if s["merchant_id"] == mid]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.store_view(s) for s in page], limit, offset, total)


@app.get("/stores/<sid>")
def get_store(sid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent")
    s = svc.get_store(sid)
    return resp.ok(svc.store_view(s))


@app.patch("/stores/<sid>")
def update_store(sid):
    mw.require_role("Merchant", "PlatformAdmin")
    s = svc.get_store(sid)
    b = mw.body()
    if "delivery_radius_m" in b:
        s["delivery_radius_m"] = mw.req_int(b, "delivery_radius_m")
    if "timezone" in b:
        tz = mw.req_str(b, "timezone")
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(tz)
        except Exception:
            raise errors.bad_request("timezone must be a valid IANA timezone")
        s["timezone"] = tz
    if "status" in b:
        st = mw.req_enum(b, "status", {"ACTIVE", "CLOSED"})
        s["status"] = st
    _touch(s)
    return resp.ok(svc.store_view(s))


# ===========================================================================
# Serviceability overrides and check
# ===========================================================================
@app.post("/stores/<sid>/serviceability-overrides")
def create_override(sid):
    mw.require_role("Merchant", "PlatformAdmin")
    svc.get_store(sid)
    b = mw.body()
    pattern = mw.req_str(b, "address_pattern")
    effect = mw.req_enum(b, "effect", {"ALLOW", "DENY"})
    o = svc.new_common()
    o.update({
        "store_id": sid,
        "address_pattern": pattern,
        "effect": effect,
    })
    db.overrides[o["id"]] = o
    return resp.ok(svc.override_view(o), 201)


@app.get("/stores/<sid>/serviceability-overrides")
def list_overrides(sid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent")
    svc.get_store(sid)
    items = [o for o in db.overrides.values() if o["store_id"] == sid]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.override_view(o) for o in page], limit, offset, total)


@app.post("/stores/<sid>/check-serviceability")
def check_serviceability(sid):
    mw.require_role("Merchant", "PlatformAdmin")
    s = svc.get_store(sid)
    b = mw.body()
    dlat = mw.req_num(b, "dropoff_lat")
    dlng = mw.req_num(b, "dropoff_lng")
    addr = mw.req_str(b, "address_text")
    serviceable, distance_m, effect = svc.serviceability(s, dlat, dlng, addr)
    return resp.ok({
        "serviceable": serviceable,
        "distance_m": distance_m,
        "matched_override_effect": effect,
    })


# ===========================================================================
# Pricing policies
# ===========================================================================
def _validate_bands(bands):
    if not isinstance(bands, list) or len(bands) == 0:
        raise errors.bad_request("distance_bands must be a non-empty array")
    for band in bands:
        if not isinstance(band, dict):
            raise errors.bad_request("distance_bands entries must be objects")
        for f in ("max_m", "base_cents", "per_100m_cents"):
            v = band.get(f)
            if isinstance(v, bool) or not isinstance(v, int):
                raise errors.bad_request("distance_bands.%s must be an integer" % f)


def _validate_tiers(tiers):
    if not isinstance(tiers, list):
        raise errors.bad_request("value_tiers must be an array")
    for t in tiers:
        if not isinstance(t, dict):
            raise errors.bad_request("value_tiers entries must be objects")
        for f in ("min_order_value_cents", "surcharge_cents"):
            v = t.get(f)
            if isinstance(v, bool) or not isinstance(v, int):
                raise errors.bad_request("value_tiers.%s must be an integer" % f)


def _validate_peaks(windows):
    if not isinstance(windows, list):
        raise errors.bad_request("peak_windows must be an array")
    for w in windows:
        if not isinstance(w, dict):
            raise errors.bad_request("peak_windows entries must be objects")
        for f in ("start_local_hhmm", "end_local_hhmm"):
            v = w.get(f)
            if isinstance(v, bool) or not isinstance(v, str):
                raise errors.bad_request("peak_windows.%s must be a string" % v)


@app.post("/merchants/<mid>/pricing-policies")
def create_policy(mid):
    mw.require_role("Merchant", "PlatformAdmin")
    svc.get_merchant(mid)
    b = mw.body()
    bands = mw.req_field(b, "distance_bands")
    tiers = mw.req_field(b, "value_tiers")
    peaks = mw.req_field(b, "peak_windows")
    _validate_bands(bands)
    _validate_tiers(tiers)
    _validate_peaks(peaks)
    uplift = mw.req_num(b, "peak_uplift_pct")
    passthrough = mw.req_num(b, "surge_passthrough_pct")
    eff_from = mw.req_dt(b, "effective_from")
    eff_until = mw.req_dt(b, "effective_until")
    if not eff_until > eff_from:
        raise errors.bad_request("effective_until must be after effective_from")
    p = svc.new_common()
    p.update({
        "merchant_id": mid,
        "distance_bands": bands,
        "value_tiers": tiers,
        "peak_windows": peaks,
        "peak_uplift_pct": uplift,
        "surge_passthrough_pct": passthrough,
        "effective_from": eff_from,
        "effective_until": eff_until,
        "status": "DRAFT",
    })
    db.policies[p["id"]] = p
    return resp.ok(svc.policy_view(p), 201)


@app.get("/merchants/<mid>/pricing-policies")
def list_policies(mid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent")
    svc.get_merchant(mid)
    items = [p for p in db.policies.values() if p["merchant_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.policy_view(p) for p in page], limit, offset, total)


@app.get("/pricing-policies/<pid>")
def get_policy(pid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent")
    p = svc.get_policy(pid)
    return resp.ok(svc.policy_view(p))


@app.post("/merchants/<mid>/pricing-policies/<pid>/activate")
def activate_policy(mid, pid):
    mw.require_role("Merchant")
    m = svc.get_merchant(mid)
    p = svc.get_policy(pid)
    b = mw.body()
    expected = mw.req_int(b, "expected_merchant_version")
    # OCC (layer 5)
    if expected != m["version"]:
        raise errors.ApiError("ERR_STALE_MERCHANT_VERSION", 412,
                              "expected_merchant_version does not match Merchant.version")
    # state (layer 6)
    if p["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT policy can be activated")
    # temporal (layer 7): half-open window overlap vs other ACTIVE policies
    for other in db.policies.values():
        if other["merchant_id"] == mid and other["status"] == "ACTIVE" and other["id"] != pid:
            if p["effective_from"] < other["effective_until"] and other["effective_from"] < p["effective_until"]:
                raise errors.ApiError("ERR_POLICY_WINDOW_OVERLAP", 409,
                                      "Effective window overlaps another ACTIVE policy")
    for other in db.policies.values():
        if other["merchant_id"] == mid and other["status"] == "ACTIVE":
            other["status"] = "ARCHIVED"
            svc.touch(other)
    p["status"] = "ACTIVE"
    svc.touch(p)
    svc.touch(m)
    return resp.ok(svc.policy_view(p))


# ===========================================================================
# Delivery quotes
# ===========================================================================
def _refresh_quote_status(q):
    if q["status"] == "ACTIVE" and db.now() >= q["valid_until"]:
        q["status"] = "EXPIRED"
        svc.touch(q)


@app.post("/delivery-quotes")
def create_quote():
    uid, role = mw.require_role("Merchant")
    b = mw.body()
    store_id = mw.req_str(b, "store_id")
    dlat = mw.req_num(b, "dropoff_lat")
    dlng = mw.req_num(b, "dropoff_lng")
    addr = mw.req_str(b, "address_text")
    order_value = mw.req_int(b, "order_value_cents")
    pickup_ready_at = mw.req_dt(b, "pickup_ready_at")
    # body FK existence
    s = svc.get_store(store_id)
    # business: address serviceability (layer 8)
    serviceable, distance_m, _effect = svc.serviceability(s, dlat, dlng, addr)
    if not serviceable:
        raise errors.ApiError("ERR_ADDRESS_NOT_SERVICEABLE", 409,
                              "Delivery address denied by override or beyond store radius")
    # ACTIVE pricing policy whose window contains the clock
    policy = None
    for p in db.policies.values():
        if p["merchant_id"] == uid and p["status"] == "ACTIVE" \
                and p["effective_from"] <= db.now() < p["effective_until"]:
            policy = p
            break
    if policy is None:
        raise errors.ApiError("ERR_NO_ACTIVE_PRICING_POLICY", 409,
                              "Merchant has no ACTIVE pricing policy whose window contains the clock")
    comp = svc.fee_components(policy, s, distance_m, order_value, pickup_ready_at, db.surge_multiplier)
    q = svc.new_common()
    q.update({
        "merchant_id": uid,
        "store_id": store_id,
        "dropoff_lat": dlat,
        "dropoff_lng": dlng,
        "address_text": addr,
        "order_value_cents": order_value,
        "pickup_ready_at": pickup_ready_at,
        "distance_m": distance_m,
        "band_fee_cents": comp["band_fee_cents"],
        "value_surcharge_cents": comp["value_surcharge_cents"],
        "peak_uplift_cents": comp["peak_uplift_cents"],
        "surge_component_cents": comp["surge_component_cents"],
        "quoted_fee_cents": comp["total"],
        "pricing_policy_id": policy["id"],
        "quoted_surge_multiplier": db.surge_multiplier,
        "valid_until": db.now() + timedelta(minutes=svc.QUOTE_VALIDITY_MINUTES),
        "status": "ACTIVE",
    })
    db.quotes[q["id"]] = q
    return resp.ok(svc.quote_view(q), 201)


@app.get("/delivery-quotes")
def list_quotes():
    mw.require_role("Merchant", "PlatformAdmin")
    items = list(db.quotes.values())
    for q in items:
        _refresh_quote_status(q)
    merchant_id = request.args.get("merchant_id")
    store_id = request.args.get("store_id")
    policy_id = request.args.get("pricing_policy_id")
    if merchant_id is not None:
        items = [q for q in items if q["merchant_id"] == merchant_id]
    if store_id is not None:
        items = [q for q in items if q["store_id"] == store_id]
    if policy_id is not None:
        items = [q for q in items if q["pricing_policy_id"] == policy_id]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.quote_view(q) for q in page], limit, offset, total)


@app.get("/delivery-quotes/<qid>")
def get_quote(qid):
    mw.require_role("Merchant", "PlatformAdmin")
    q = svc.get_quote(qid)
    _refresh_quote_status(q)
    return resp.ok(svc.quote_view(q))


# ===========================================================================
# Delivery orders
# ===========================================================================
@app.post("/delivery-orders")
def create_order():
    uid, role = mw.require_role("Merchant")
    b = mw.body()
    quote_id = mw.req_str(b, "quote_id")
    customer_reference = mw.req_str(b, "customer_reference")
    idem_key = mw.req_str(b, "idempotency_key")
    # body FK existence
    q = svc.get_quote(quote_id)
    # idempotency: merchant-scoped key returns the original order.
    # No new resource is created on a replay, so per §4 ("Operations that
    # create a new resource return 201 Created") the replay returns 200.
    for o in db.orders.values():
        if o["merchant_id"] == uid and o["idempotency_key"] == idem_key:
            return resp.ok(svc.order_view(o), 200)
    _refresh_quote_status(q)
    if q["status"] != "ACTIVE":
        raise errors.ApiError("ERR_QUOTE_EXPIRED", 409, "Quote used at or after valid_until")
    o = svc.new_common()
    o.update({
        "quote_id": quote_id,
        "merchant_id": q["merchant_id"],
        "store_id": q["store_id"],
        "batch_id": None,
        "customer_reference": customer_reference,
        "idempotency_key": idem_key,
        "promised_at": None,
        "fulfillment_status": "QUOTED",
        "billing_status": "PENDING",
        "quoted_fee_cents": q["quoted_fee_cents"],
        "final_fee_cents": None,
        "merchant_invoice_cents": None,
        "batch_fee_share_cents": None,
        "late_credit_cents": 0,
        "delivered_at": None,
        "undeliverable_reason": None,
    })
    db.orders[o["id"]] = o
    q["status"] = "CONSUMED"
    svc.touch(q)
    return resp.ok(svc.order_view(o), 201)


@app.get("/delivery-orders")
def list_orders():
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent", "Courier")
    items = list(db.orders.values())
    for param, field in (("merchant_id", "merchant_id"), ("store_id", "store_id"),
                         ("quote_id", "quote_id"), ("batch_id", "batch_id"),
                         ("fulfillment_status", "fulfillment_status"),
                         ("billing_status", "billing_status")):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o[field] == v]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.order_view(o) for o in page], limit, offset, total)


@app.get("/delivery-orders/<oid>")
def get_order(oid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent", "Courier")
    o = svc.get_order(oid)
    return resp.ok(svc.order_view(o))


@app.post("/delivery-orders/<oid>/accept")
def accept_order(oid):
    uid, role = mw.require_role("Merchant")
    o = svc.get_order(oid)
    b = mw.body()
    promised_at = mw.req_dt(b, "promised_at")
    if o["fulfillment_status"] != "QUOTED":
        raise errors.invalid_state("Only a QUOTED order can be accepted")
    merchant = db.merchants[o["merchant_id"]]
    if merchant["status"] != "ACTIVE":
        raise errors.ApiError("ERR_MERCHANT_SUSPENDED", 409,
                              "Merchant not ACTIVE for order acceptance")
    store = db.stores[o["store_id"]]
    if store["status"] != "ACTIVE":
        raise errors.ApiError("ERR_STORE_NOT_ACTIVE", 409,
                              "Store not ACTIVE for order acceptance")
    if merchant["billing_balance_cents"] < o["quoted_fee_cents"]:
        raise errors.ApiError("ERR_INSUFFICIENT_BILLING_BALANCE", 402,
                              "billing_balance_cents below quoted_fee_cents at accept")
    o["promised_at"] = promised_at
    o["fulfillment_status"] = "ACCEPTED"
    o["billing_status"] = "AUTHORIZED"
    svc.touch(o)
    merchant["billing_balance_cents"] -= o["quoted_fee_cents"]
    merchant["updated_at"] = mw.iso(db.now())
    svc.emit_event(o["id"], "ORDER_ACCEPTED")
    return resp.ok(svc.order_view(o))


@app.post("/delivery-orders/<oid>/cancel")
def cancel_order(oid):
    mw.require_role("Merchant")
    o = svc.get_order(oid)
    if o["fulfillment_status"] not in ("QUOTED", "ACCEPTED"):
        raise errors.invalid_state("Only QUOTED or ACCEPTED orders can be cancelled")
    was_accepted = o["fulfillment_status"] == "ACCEPTED"
    o["fulfillment_status"] = "CANCELLED"
    o["billing_status"] = "VOIDED"
    svc.touch(o)
    if was_accepted:
        merchant = db.merchants[o["merchant_id"]]
        merchant["billing_balance_cents"] += o["quoted_fee_cents"]
        merchant["updated_at"] = mw.iso(db.now())
        svc.emit_event(o["id"], "CANCELLED")
    return resp.ok(svc.order_view(o))


@app.post("/delivery-orders/<oid>/mark-ready")
def mark_ready(oid):
    mw.require_role("Merchant")
    o = svc.get_order(oid)
    if o["fulfillment_status"] != "ACCEPTED":
        raise errors.invalid_state("Only an ACCEPTED order can be marked ready")
    o["fulfillment_status"] = "READY_FOR_PICKUP"
    svc.touch(o)
    return resp.ok(svc.order_view(o))


@app.post("/delivery-orders/<oid>/confirm-pickup")
def confirm_pickup(oid):
    uid, role = mw.require_role("Courier")
    o = svc.get_order(oid)
    if o["fulfillment_status"] != "READY_FOR_PICKUP":
        raise errors.invalid_state("Only a READY_FOR_PICKUP order can be picked up")
    batch = db.batches.get(o["batch_id"]) if o.get("batch_id") else None
    if batch is None or batch["status"] != "DISPATCHED" or batch["courier_id"] != uid:
        raise errors.invalid_state("Courier must hold the order's DISPATCHED batch")
    o["fulfillment_status"] = "PICKED_UP"
    svc.touch(o)
    svc.emit_event(o["id"], "PICKED_UP")
    return resp.ok(svc.order_view(o))


@app.post("/delivery-orders/<oid>/start-transit")
def start_transit(oid):
    mw.require_role("Courier")
    o = svc.get_order(oid)
    if o["fulfillment_status"] != "PICKED_UP":
        raise errors.invalid_state("Only a PICKED_UP order can start transit")
    o["fulfillment_status"] = "IN_TRANSIT"
    svc.touch(o)
    svc.emit_event(o["id"], "IN_TRANSIT")
    return resp.ok(svc.order_view(o))


@app.post("/delivery-orders/<oid>/complete-delivery")
def complete_delivery(oid):
    mw.require_role("Courier")
    o = svc.get_order(oid)
    if o["fulfillment_status"] != "IN_TRANSIT":
        raise errors.invalid_state("Only an IN_TRANSIT order can be completed")
    o["fulfillment_status"] = "DELIVERED"
    o["delivered_at"] = db.now()
    svc.settle_order_billing(o)
    o["late_credit_cents"] = svc.late_credit(o, db.now())
    svc.touch(o)
    svc.maybe_complete_batch(o)
    svc.emit_event(o["id"], "DELIVERED")
    return resp.ok(svc.order_view(o))


@app.post("/delivery-orders/<oid>/report-undeliverable")
def report_undeliverable(oid):
    mw.require_role("Courier")
    o = svc.get_order(oid)
    b = mw.body()
    reason = mw.req_enum(b, "reason_code",
                         {"CUSTOMER_UNAVAILABLE", "ADDRESS_ISSUE", "DAMAGED_IN_TRANSIT"})
    if o["fulfillment_status"] not in ("PICKED_UP", "IN_TRANSIT"):
        raise errors.invalid_state("Only PICKED_UP or IN_TRANSIT orders can be reported undeliverable")
    o["fulfillment_status"] = "UNDELIVERABLE"
    o["undeliverable_reason"] = reason
    svc.settle_order_billing(o)
    o["late_credit_cents"] = svc.late_credit(o, db.now())
    svc.touch(o)
    svc.emit_event(o["id"], "UNDELIVERABLE")
    return resp.ok(svc.order_view(o))


@app.post("/delivery-orders/<oid>/disposition")
def create_disposition(oid):
    mw.require_role("Merchant")
    o = svc.get_order(oid)
    b = mw.body()
    resolution = mw.req_enum(b, "resolution", {"RETURN_TO_STORE", "DISPOSE"})
    if o["fulfillment_status"] != "UNDELIVERABLE":
        raise errors.ApiError("ERR_DISPOSITION_NOT_REQUIRED", 409,
                              "Disposition requested for an order not in UNDELIVERABLE")
    d = svc.new_common()
    if resolution == "RETURN_TO_STORE":
        return_fee = svc.RETURN_FEE_CENTS
        o["fulfillment_status"] = "RETURN_IN_PROGRESS"
    else:
        return_fee = 0
        o["fulfillment_status"] = "DISPOSAL_PENDING"
    d.update({
        "delivery_order_id": o["id"],
        "resolution": resolution,
        "return_fee_cents": return_fee,
        "status": "PENDING",
    })
    db.dispositions[d["id"]] = d
    svc.touch(o)
    if resolution == "RETURN_TO_STORE":
        merchant = db.merchants[o["merchant_id"]]
        merchant["billing_balance_cents"] -= svc.RETURN_FEE_CENTS
        merchant["updated_at"] = mw.iso(db.now())
        svc.emit_event(o["id"], "RETURN_IN_PROGRESS")
    return resp.ok(svc.disposition_view(d), 201)


@app.get("/delivery-orders/<oid>/disposition")
def list_order_dispositions(oid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent", "Courier")
    svc.get_order(oid)
    items = [d for d in db.dispositions.values() if d["delivery_order_id"] == oid]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.disposition_view(d) for d in page], limit, offset, total)


@app.post("/dispositions/<did>/complete")
def complete_disposition(did):
    mw.require_role("Courier")
    d = svc.get_disposition(did)
    b = mw.body()
    outcome = mw.req_enum(b, "outcome", {"RETURNED", "DISPOSED"})
    if d["status"] != "PENDING":
        raise errors.invalid_state("Only a PENDING disposition can be completed")
    expected = "RETURNED" if d["resolution"] == "RETURN_TO_STORE" else "DISPOSED"
    if outcome != expected:
        raise errors.bad_request("outcome does not match disposition resolution")
    d["status"] = "COMPLETED"
    svc.touch(d)
    o = db.orders[d["delivery_order_id"]]
    o["fulfillment_status"] = "RETURNED_TO_STORE" if outcome == "RETURNED" else "DISPOSED"
    svc.touch(o)
    svc.maybe_complete_batch(o)
    svc.emit_event(o["id"], "RETURNED_TO_STORE" if outcome == "RETURNED" else "DISPOSED")
    return resp.ok(svc.disposition_view(d))


@app.post("/delivery-orders/<oid>/tracking-events")
def create_tracking_event(oid):
    mw.require_role("Courier", "PlatformAdmin")
    svc.get_order(oid)
    b = mw.body()
    event_type = mw.req_enum(b, "event_type", {
        "ORDER_ACCEPTED", "COURIER_ASSIGNED", "PICKED_UP", "IN_TRANSIT", "DELIVERED",
        "UNDELIVERABLE", "RETURN_IN_PROGRESS", "RETURNED_TO_STORE", "DISPOSED",
        "CANCELLED", "NOTE"})
    note = mw.opt_str(b, "note", "")
    visibility = mw.opt_enum(b, "visibility", {"MERCHANT_VISIBLE", "INTERNAL_ONLY"},
                             "MERCHANT_VISIBLE")
    e = svc.emit_event(oid, event_type, note, visibility)
    return resp.ok(svc.tracking_view(e), 201)


@app.get("/delivery-orders/<oid>/tracking-events")
def list_tracking_events(oid):
    uid, role = mw.require_role("Merchant", "Courier", "SupportAgent", "PlatformAdmin")
    svc.get_order(oid)
    items = [e for e in db.tracking_events.values() if e["delivery_order_id"] == oid]
    if role == "Merchant":
        items = [e for e in items if e["visibility"] == "MERCHANT_VISIBLE"]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.tracking_view(e) for e in page], limit, offset, total)


# ===========================================================================
# Couriers
# ===========================================================================
@app.post("/couriers")
def create_courier():
    mw.require_role("PlatformAdmin")
    b = mw.body()
    name = mw.req_str(b, "name")
    capacity = mw.opt_int(b, "max_active_deliveries", 4)
    c = svc.new_common()
    c.update({
        "name": name,
        "status": "ACTIVE",
        "max_active_deliveries": capacity,
    })
    db.couriers[c["id"]] = c
    return resp.ok(svc.courier_view(c), 201)


@app.get("/couriers")
def list_couriers():
    mw.require_role("PlatformAdmin", "SupportAgent")
    items = list(db.couriers.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.courier_view(c) for c in page], limit, offset, total)


@app.get("/couriers/<cid>")
def get_courier(cid):
    mw.require_role("PlatformAdmin", "SupportAgent", "Courier")
    c = svc.get_courier(cid)
    return resp.ok(svc.courier_view(c))


@app.patch("/couriers/<cid>")
def update_courier(cid):
    mw.require_role("PlatformAdmin")
    c = svc.get_courier(cid)
    b = mw.body()
    if "status" in b:
        st = mw.req_enum(b, "status", {"ACTIVE", "SUSPENDED"})
        if st == c["status"]:
            raise errors.invalid_state("Courier already in requested status")
        c["status"] = st
    if "max_active_deliveries" in b:
        c["max_active_deliveries"] = mw.req_int(b, "max_active_deliveries")
    _touch(c)
    return resp.ok(svc.courier_view(c))


# ===========================================================================
# Delivery batches
# ===========================================================================
@app.post("/delivery-batches")
def create_batch():
    mw.require_role("PlatformAdmin")
    b = mw.body()
    store_id = mw.req_str(b, "store_id")
    courier_id = mw.req_str(b, "courier_id")
    order_ids = mw.req_field(b, "order_ids")
    win_start = mw.req_dt(b, "dispatch_window_start")
    win_end = mw.req_dt(b, "dispatch_window_end")
    expected = mw.req_int(b, "expected_courier_version")
    # body FK existence in declared input order: store_id, courier_id, order_ids
    svc.get_store(store_id)
    courier = svc.get_courier(courier_id)
    if isinstance(order_ids, bool) or not isinstance(order_ids, list):
        raise errors.bad_request("order_ids must be an array")
    orders = []
    for oid in order_ids:
        if isinstance(oid, bool) or not isinstance(oid, str):
            raise errors.bad_request("order_ids entries must be strings")
        orders.append(svc.get_order(oid))
    # OCC (layer 5)
    if expected != courier["version"]:
        raise errors.ApiError("ERR_STALE_COURIER_VERSION", 412,
                              "expected_courier_version does not match Courier.version")
    # business constraints (layer 8)
    if not 1 <= len(order_ids) <= 3:
        raise errors.ApiError("ERR_INVALID_BATCH_SIZE", 409,
                              "Batch order_ids outside 1..3")
    if not win_end > win_start:
        raise errors.bad_request("dispatch_window_end must be after dispatch_window_start")
    for o in orders:
        if o["store_id"] != store_id or o["fulfillment_status"] != "READY_FOR_PICKUP":
            raise errors.ApiError("ERR_BATCHING_RESTRICTION_VIOLATION", 409,
                                  "Batched orders must all belong to the store and be READY_FOR_PICKUP")
    n = len(order_ids)
    batch = svc.new_common()
    batch.update({
        "store_id": store_id,
        "courier_id": courier_id,
        "order_ids": list(order_ids),
        "dispatch_window_start": win_start,
        "dispatch_window_end": win_end,
        "courier_cost_cents": svc.BATCH_BASE_COST_CENTS + svc.BATCH_PER_ORDER_CENTS * n,
        "status": "COURIER_ASSIGNED",
    })
    db.batches[batch["id"]] = batch
    for o in orders:
        o["batch_id"] = batch["id"]
        svc.touch(o)
    svc.touch(courier)
    return resp.ok(svc.batch_view(batch), 201)


@app.get("/delivery-batches")
def list_batches():
    mw.require_role("PlatformAdmin", "Courier", "SupportAgent")
    items = list(db.batches.values())
    for param, field in (("courier_id", "courier_id"), ("store_id", "store_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [x for x in items if x[field] == v]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.batch_view(x) for x in page], limit, offset, total)


@app.get("/delivery-batches/<bid>")
def get_batch(bid):
    mw.require_role("PlatformAdmin", "Courier", "SupportAgent", "Merchant")
    b = svc.get_batch(bid)
    return resp.ok(svc.batch_view(b))


@app.post("/delivery-batches/<bid>/dispatch")
def dispatch_batch(bid):
    uid, role = mw.require_role("Courier")
    b = svc.get_batch(bid)
    # state (layer 6)
    if b["status"] != "COURIER_ASSIGNED":
        raise errors.invalid_state("Only a COURIER_ASSIGNED batch can be dispatched")
    courier = db.couriers[b["courier_id"]]
    if courier["status"] != "ACTIVE":
        raise errors.invalid_state("Courier not ACTIVE")
    for oid in b["order_ids"]:
        if db.orders[oid]["fulfillment_status"] != "READY_FOR_PICKUP":
            raise errors.invalid_state("Every order in the batch must be READY_FOR_PICKUP")
    # temporal (layer 7): closed dispatch-window overlap, touching counts
    for other in db.batches.values():
        if other["id"] == b["id"] or other["courier_id"] != b["courier_id"]:
            continue
        if other["status"] != "DISPATCHED":
            continue
        if b["dispatch_window_start"] <= other["dispatch_window_end"] \
                and other["dispatch_window_start"] <= b["dispatch_window_end"]:
            raise errors.ApiError("ERR_COURIER_WINDOW_CONFLICT", 409,
                                  "Dispatch window overlaps another DISPATCHED batch of the courier")
    # business (layer 8): capacity across the courier's DISPATCHED batches
    committed = 0
    for other in db.batches.values():
        if other["courier_id"] == b["courier_id"] and other["status"] == "DISPATCHED":
            committed += len(other["order_ids"])
    if committed + len(b["order_ids"]) > courier["max_active_deliveries"]:
        raise errors.ApiError("ERR_COURIER_CAPACITY_EXCEEDED", 409,
                              "Batch exceeds courier max_active_deliveries")
    # final fee variant + batch fee allocation per order
    orders = [db.orders[oid] for oid in b["order_ids"]]
    for o in orders:
        q = db.quotes[o["quote_id"]]
        policy = db.policies[q["pricing_policy_id"]]
        store = db.stores[o["store_id"]]
        comp = svc.fee_components(policy, store, q["distance_m"], q["order_value_cents"],
                                  q["pickup_ready_at"], db.surge_multiplier)
        o["final_fee_cents"] = comp["total"]
        o["merchant_invoice_cents"] = svc.merchant_invoice(
            comp["base_total"], q["surge_component_cents"],
            comp["surge_component_cents"], policy["surge_passthrough_pct"])
    allocs = svc.batch_fee_allocation(b, orders)
    for o, share in zip(orders, allocs):
        o["batch_fee_share_cents"] = share
        svc.touch(o)
        svc.emit_event(o["id"], "COURIER_ASSIGNED")
    b["status"] = "DISPATCHED"
    svc.touch(b)
    svc.touch(courier)
    return resp.ok(svc.batch_view(b))


@app.post("/delivery-batches/<bid>/fail")
def fail_batch(bid):
    mw.require_role("Courier")
    b = svc.get_batch(bid)
    if b["status"] not in ("COURIER_ASSIGNED", "DISPATCHED"):
        raise errors.invalid_state("Only COURIER_ASSIGNED or DISPATCHED batches can fail")
    was_dispatched = b["status"] == "DISPATCHED"
    b["status"] = "FAILED"
    svc.touch(b)
    for oid in b["order_ids"]:
        o = db.orders[oid]
        if o["fulfillment_status"] in svc.TERMINAL_FULFILLMENT:
            continue
        o["batch_id"] = None
        if was_dispatched and o["fulfillment_status"] == "READY_FOR_PICKUP":
            pass  # never picked up: already READY_FOR_PICKUP
        svc.touch(o)
    return resp.ok(svc.batch_view(b))


# ===========================================================================
# Refund claims
# ===========================================================================
FAULT_CODES = {"COURIER_DELAY", "PLATFORM_OUTAGE", "MERCHANT_FULFILLMENT",
               "CUSTOMER_UNAVAILABLE", "ADDRESS_ISSUE"}


@app.post("/refund-claims")
def create_claim():
    uid, role = mw.require_role("Merchant")
    b = mw.body()
    order_id = mw.req_str(b, "delivery_order_id")
    fault_code = mw.req_enum(b, "fault_code", FAULT_CODES)
    claimed = mw.req_int(b, "claimed_amount_cents")
    # body FK existence
    o = svc.get_order(order_id)
    if o["billing_status"] != "SETTLED":
        raise errors.ApiError("ERR_CLAIM_ORDER_NOT_SETTLED", 409,
                              "Claim filed against an order whose billing_status is not SETTLED")
    if o["merchant_invoice_cents"] is None or claimed > o["merchant_invoice_cents"]:
        raise errors.ApiError("ERR_CLAIM_EXCEEDS_INVOICE", 409,
                              "claimed_amount_cents exceeds order merchant_invoice_cents")
    c = svc.new_common()
    c.update({
        "delivery_order_id": order_id,
        "merchant_id": o["merchant_id"],
        "fault_code": fault_code,
        "claimed_amount_cents": claimed,
        "merchant_share_cents": None,
        "platform_share_cents": None,
        "appeal_count": 0,
        "status": "FILED",
    })
    db.claims[c["id"]] = c
    return resp.ok(svc.claim_view(c), 201)


@app.get("/refund-claims")
def list_claims():
    mw.require_role("Merchant", "SupportAgent", "PlatformAdmin")
    items = list(db.claims.values())
    for param, field in (("delivery_order_id", "delivery_order_id"),
                         ("merchant_id", "merchant_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[field] == v]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.claim_view(c) for c in page], limit, offset, total)


@app.get("/refund-claims/<cid>")
def get_claim(cid):
    mw.require_role("Merchant", "SupportAgent", "PlatformAdmin")
    c = svc.get_claim(cid)
    return resp.ok(svc.claim_view(c))


@app.post("/refund-claims/<cid>/start-review")
def start_review(cid):
    mw.require_role("SupportAgent")
    c = svc.get_claim(cid)
    if c["status"] not in ("FILED", "APPEALED"):
        raise errors.invalid_state("Only FILED or APPEALED claims can start review")
    c["status"] = "UNDER_REVIEW"
    svc.touch(c)
    return resp.ok(svc.claim_view(c))


@app.post("/refund-claims/<cid>/decide")
def decide_claim(cid):
    mw.require_role("SupportAgent")
    c = svc.get_claim(cid)
    b = mw.body()
    decision = mw.req_enum(b, "decision", {"APPROVE", "DENY"})
    if c["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Only UNDER_REVIEW claims can be decided")
    if decision == "DENY":
        c["status"] = "DENIED"
        svc.touch(c)
        return resp.ok(svc.claim_view(c))
    # APPROVE: liability split in pinned order (PRD section 3.8)
    o = db.orders[c["delivery_order_id"]]
    merchant = db.merchants[c["merchant_id"]]
    invoice = o["merchant_invoice_cents"]
    fault = c["fault_code"]
    claimed = c["claimed_amount_cents"]
    if fault in ("COURIER_DELAY", "PLATFORM_OUTAGE"):
        merchant_pct = 0
    elif fault == "MERCHANT_FULFILLMENT":
        merchant_pct = 100
    else:
        merchant_pct = merchant["default_refund_split_merchant_pct"]
    merchant_share = svc.round_half_up(
        svc.dec(claimed) * svc.dec(merchant_pct) / svc.dec(100))
    platform_share = claimed - merchant_share
    if fault in ("COURIER_DELAY", "PLATFORM_OUTAGE"):
        platform_cap = svc.round_half_up(svc.dec(invoice) * svc.PLATFORM_DELAY_CAP_MULTIPLIER)
        if platform_share > platform_cap:
            platform_share = platform_cap
            merchant_share = claimed - platform_share
    c["merchant_share_cents"] = merchant_share
    c["platform_share_cents"] = platform_share
    c["status"] = "APPROVED"
    svc.touch(c)
    return resp.ok(svc.claim_view(c))


@app.post("/refund-claims/<cid>/appeal")
def appeal_claim(cid):
    mw.require_role("Merchant")
    c = svc.get_claim(cid)
    if c["status"] != "DENIED":
        raise errors.invalid_state("Only DENIED claims can be appealed")
    if c["appeal_count"] >= svc.MAX_APPEALS:
        raise errors.ApiError("ERR_APPEAL_LIMIT_EXCEEDED", 409,
                              "Appeal attempted when appeal_count already at maximum")
    c["appeal_count"] += 1
    c["status"] = "APPEALED"
    svc.touch(c)
    return resp.ok(svc.claim_view(c))


@app.post("/refund-claims/<cid>/settle")
def settle_claim(cid):
    mw.require_role("PlatformAdmin")
    c = svc.get_claim(cid)
    if c["status"] != "APPROVED":
        raise errors.invalid_state("Only APPROVED claims can be settled")
    o = db.orders[c["delivery_order_id"]]
    merchant = db.merchants[c["merchant_id"]]
    c["status"] = "SETTLED"
    svc.touch(c)
    o["billing_status"] = "REFUNDED"
    svc.touch(o)
    merchant["billing_balance_cents"] -= c["merchant_share_cents"]
    merchant["updated_at"] = mw.iso(db.now())
    if merchant["billing_balance_cents"] < 0 and merchant["status"] == "ACTIVE":
        svc.suspend_merchant_cascade(merchant)
    return resp.ok(svc.claim_view(c))


@app.post("/refund-claims/<cid>/reverse")
def reverse_claim(cid):
    mw.require_role("PlatformAdmin")
    c = svc.get_claim(cid)
    if c["status"] != "SETTLED":
        raise errors.invalid_state("Only SETTLED claims can be reversed")
    o = db.orders[c["delivery_order_id"]]
    merchant = db.merchants[c["merchant_id"]]
    c["status"] = "REVERSED"
    svc.touch(c)
    merchant["billing_balance_cents"] += c["merchant_share_cents"]
    merchant["updated_at"] = mw.iso(db.now())
    o["billing_status"] = "SETTLED"
    svc.touch(o)
    return resp.ok(svc.claim_view(c))


# ===========================================================================
# SLA reports and service credits
# ===========================================================================
@app.post("/merchants/<mid>/sla-reports")
def create_report(mid):
    mw.require_role("PlatformAdmin")
    svc.get_merchant(mid)
    b = mw.body()
    period_start = mw.req_dt(b, "period_start")
    period_end = mw.req_dt(b, "period_end")
    if not period_end > period_start:
        raise errors.bad_request("period_end must be after period_start")
    r = svc.new_common()
    r.update({
        "merchant_id": mid,
        "period_start": period_start,
        "period_end": period_end,
        "total_deliveries": None,
        "late_deliveries_gross": None,
        "attainment_rate_gross": None,
        "attainment_rate_fault_adjusted": None,
        "status": "OPEN",
    })
    db.reports[r["id"]] = r
    return resp.ok(svc.report_view(r), 201)


@app.get("/merchants/<mid>/sla-reports")
def list_reports(mid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent")
    svc.get_merchant(mid)
    items = [r for r in db.reports.values() if r["merchant_id"] == mid]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.report_view(r) for r in page], limit, offset, total)


@app.get("/sla-reports/<rid>")
def get_report(rid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent")
    r = svc.get_report(rid)
    return resp.ok(svc.report_view(r))


def _rate4(late, total):
    if total == 0:
        return 1.0
    d = (Decimal(1) - Decimal(late) / Decimal(total)).quantize(
        Decimal("0.0001"), rounding=svc.ROUND_HALF_UP)
    return float(d)


@app.post("/sla-reports/<rid>/finalize")
def finalize_report(rid):
    mw.require_role("PlatformAdmin")
    r = svc.get_report(rid)
    if r["status"] != "OPEN":
        raise errors.invalid_state("Only an OPEN report can be finalized")
    merchant = db.merchants[r["merchant_id"]]
    population = [
        o for o in db.orders.values()
        if o["merchant_id"] == r["merchant_id"]
        and o["delivered_at"] is not None
        and r["period_start"] <= o["delivered_at"] < r["period_end"]
    ]
    grace = timedelta(seconds=svc.LATE_GRACE_SECONDS)
    late = [o for o in population if o["delivered_at"] > o["promised_at"] + grace]
    total = len(population)
    late_gross = len(late)
    r["total_deliveries"] = total
    r["late_deliveries_gross"] = late_gross
    r["attainment_rate_gross"] = _rate4(late_gross, total)
    # FAULT_ADJUSTED: exclude late orders with a SETTLED MERCHANT_FULFILLMENT claim
    excluded_ids = set()
    for c in db.claims.values():
        if c["status"] == "SETTLED" and c["fault_code"] == "MERCHANT_FULFILLMENT":
            excluded_ids.add(c["delivery_order_id"])
    adj_population = [o for o in population
                      if not (o in late and o["id"] in excluded_ids)]
    adj_late = [o for o in late if o["id"] not in excluded_ids]
    r["attainment_rate_fault_adjusted"] = _rate4(len(adj_late), len(adj_population))
    r["status"] = "FINALIZED"
    svc.touch(r)
    # credits accrue when gross attainment < 0.97
    if Decimal(str(r["attainment_rate_gross"])) < svc.CREDIT_TRIGGER_ATTAINMENT:
        for o in late:
            cr = svc.new_common()
            cr.update({
                "merchant_id": r["merchant_id"],
                "sla_report_id": r["id"],
                "delivery_order_id": o["id"],
                "amount_cents": o["late_credit_cents"],
                "reason": "LATE_DELIVERY",
                "status": "ACCRUED",
            })
            db.credits[cr["id"]] = cr
            if merchant["late_credit_enabled"]:
                cr["status"] = "APPLIED"
                svc.touch(cr)
                merchant["credit_balance_cents"] += cr["amount_cents"]
                merchant["updated_at"] = mw.iso(db.now())
    return resp.ok(svc.report_view(r))


@app.get("/sla-reports/<rid>/service-credits")
def list_report_credits(rid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent")
    svc.get_report(rid)
    items = [c for c in db.credits.values() if c["sla_report_id"] == rid]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.credit_view(c) for c in page], limit, offset, total)


@app.get("/service-credits")
def list_credits():
    mw.require_role("PlatformAdmin", "SupportAgent")
    items = list(db.credits.values())
    for param, field in (("delivery_order_id", "delivery_order_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[field] == v]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.credit_view(c) for c in page], limit, offset, total)


@app.get("/service-credits/<cid>")
def get_credit(cid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent")
    c = svc.get_credit(cid)
    return resp.ok(svc.credit_view(c))


@app.get("/merchants/<mid>/service-credits")
def list_merchant_credits(mid):
    mw.require_role("Merchant", "PlatformAdmin", "SupportAgent")
    svc.get_merchant(mid)
    items = [c for c in db.credits.values() if c["merchant_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = _paginate(items)
    return resp.ok_list([svc.credit_view(c) for c in page], limit, offset, total)


@app.post("/service-credits/<cid>/apply")
def apply_credit(cid):
    mw.require_role("PlatformAdmin")
    c = svc.get_credit(cid)
    if c["status"] != "ACCRUED":
        raise errors.invalid_state("Only an ACCRUED credit can be applied")
    c["status"] = "APPLIED"
    svc.touch(c)
    merchant = db.merchants[c["merchant_id"]]
    merchant["credit_balance_cents"] += c["amount_cents"]
    merchant["updated_at"] = mw.iso(db.now())
    return resp.ok(svc.credit_view(c))


@app.post("/service-credits/<cid>/void")
def void_credit(cid):
    mw.require_role("PlatformAdmin")
    c = svc.get_credit(cid)
    if c["status"] != "ACCRUED":
        raise errors.invalid_state("Only an ACCRUED credit can be voided")
    c["status"] = "VOIDED"
    svc.touch(c)
    return resp.ok(svc.credit_view(c))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
