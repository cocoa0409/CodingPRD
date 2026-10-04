"""Instant-Needs MFC API — Flask entry point and route table.

Implements PRD.md for task_3013. All temporal reasoning uses the logical
clock (db.now()); the store starts empty on every boot.
"""

import os
import re
from datetime import timedelta
from decimal import Decimal

from flask import Flask, request

import db
import errors
import middleware as mw
import response as resp
import services as svc

app = Flask(__name__)

OPS = ["SiteOps"]
ALL_READ = ["SiteOps", "Picker", "Driver", "Customer"]

IN_FLIGHT_ORDER_STATES = {"PLACED", "PICKING", "AWAITING_HANDOFF", "OUT_FOR_DELIVERY"}


@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return resp.error(err)


@app.errorhandler(404)
def handle_404(err):
    return resp.error(errors.ApiError("ERR_INVALID_REQUEST", "resource not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return resp.error(errors.ApiError("ERR_INVALID_REQUEST", "method not allowed", 405))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return resp.error(err)
    return resp.error(errors.ApiError("ERR_INVALID_REQUEST", str(err), 400))


def _list_response(records, filters, serializer):
    """filters: list of (query_param, record_field) exact-match filters."""
    for param, field in filters:
        raw = request.args.get(param)
        if raw is not None:
            records = [r for r in records if str(r.get(field)) == raw]
    limit, offset = mw.parse_pagination(request.args)
    page, total = mw.paginate(records, limit, offset)
    return resp.success_list([serializer(r) for r in page], limit, offset, total)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/mfc/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    data = mw.get_json()
    current_utc = data.get("current_utc")
    dt = svc.parse_dt(current_utc)
    if dt is None:
        raise errors.err_invalid_request("current_utc must be an ISO 8601 UTC instant")
    db.set_now(dt)
    return resp.success({"current_utc": db.fmt_ts(dt)})


# ===========================================================================
# Sites
# ===========================================================================
@app.route("/mfc/sites", methods=["POST"])
def create_site():
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    data = mw.get_json()

    code = data.get("code")
    name = data.get("name")
    radius = data.get("delivery_radius_miles")
    fee_schedule = data.get("fee_schedule")
    waiver = data.get("fee_waiver_threshold_cents")
    max_lines = data.get("batch_max_lines")
    max_items = data.get("batch_max_items")
    horizon = data.get("expiry_horizon_days")
    peak_windows = data.get("peak_windows", [])

    if not code or not isinstance(code, str):
        raise errors.err_invalid_request("code is required")
    if any(s["code"] == code for s in db.sites.values()):
        raise errors.err_duplicate_resource("site code must be unique")
    if not name or not isinstance(name, str):
        raise errors.err_invalid_request("name is required")
    if not svc.is_num(radius) or radius <= 0:
        raise errors.err_invalid_request("delivery_radius_miles must be > 0")
    if not isinstance(fee_schedule, dict):
        raise errors.err_invalid_request("fee_schedule is required")
    for f in svc.FEE_FIELDS:
        v = fee_schedule.get(f)
        if not svc.is_int(v) or v < 0:
            raise errors.err_invalid_request(f"fee_schedule.{f} must be an integer >= 0")
    if not svc.is_int(waiver) or waiver < 0:
        raise errors.err_invalid_request("fee_waiver_threshold_cents must be an integer >= 0")
    if not svc.is_int(max_lines) or max_lines < 1:
        raise errors.err_invalid_request("batch_max_lines must be an integer >= 1")
    if not svc.is_int(max_items) or max_items < 1:
        raise errors.err_invalid_request("batch_max_items must be an integer >= 1")
    if not svc.is_int(horizon) or horizon < 0:
        raise errors.err_invalid_request("expiry_horizon_days must be an integer >= 0")
    if peak_windows is None:
        peak_windows = []
    if not isinstance(peak_windows, list):
        raise errors.err_invalid_request("peak_windows must be a list")
    for w in peak_windows:
        if not isinstance(w, dict):
            raise errors.err_invalid_request("peak_windows entries must be objects")
        if w.get("day_of_week") not in svc.DAYS:
            raise errors.err_invalid_request("peak_windows day_of_week must be MON..SUN")
        for k in ("start", "end"):
            v = w.get(k)
            if not isinstance(v, str) or not re.match(r"^\d{2}:\d{2}$", v):
                raise errors.err_invalid_request(f"peak_windows {k} must be HH:MM")
            hh, mm = int(v[:2]), int(v[3:])
            # "24:00" is accepted as the end-of-day boundary.
            if mm > 59 or hh > 24 or (hh == 24 and mm != 0):
                raise errors.err_invalid_request(f"peak_windows {k} must be a valid HH:MM time")

    site = db.new_common({
        "id": db.new_id(),
        "code": code,
        "name": name,
        "delivery_radius_miles": radius,
        "fee_schedule": {f: fee_schedule[f] for f in svc.FEE_FIELDS},
        "fee_waiver_threshold_cents": waiver,
        "batch_max_lines": max_lines,
        "batch_max_items": max_items,
        "expiry_horizon_days": horizon,
        "peak_windows": peak_windows,
        "status": "OPERATING",
    })
    db.sites[site["id"]] = site
    return resp.success(svc.serialize_site(site), status=201)


@app.route("/mfc/sites", methods=["GET"])
def list_sites():
    uid, role = mw.user_context()
    mw.require_role(role, ALL_READ)
    return _list_response(list(db.sites.values()), [], svc.serialize_site)


@app.route("/mfc/sites/<siteId>", methods=["GET"])
def get_site(siteId):
    uid, role = mw.user_context()
    mw.require_role(role, ALL_READ)
    site = svc.get_site(siteId)
    return resp.success(svc.serialize_site(site))


@app.route("/mfc/sites/<siteId>/capacity-profile", methods=["PUT"])
def update_capacity_profile(siteId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    site = svc.get_site(siteId)
    data = mw.get_json()

    if "expected_site_version" not in data or not svc.is_int(data.get("expected_site_version")):
        raise errors.err_invalid_request("expected_site_version is required")
    if data["expected_site_version"] != site["version"]:
        raise errors.err_stale_version()

    updatable = {
        "batch_max_lines": (1, None),
        "batch_max_items": (1, None),
        "expiry_horizon_days": (0, None),
        "fee_waiver_threshold_cents": (0, None),
    }
    for field, (lo, hi) in updatable.items():
        if field in data:
            v = data[field]
            if not svc.is_int(v) or v < lo:
                raise errors.err_invalid_request(f"{field} must be an integer >= {lo}")
            site[field] = v
    db.touch(site)
    return resp.success(svc.serialize_site(site))


@app.route("/mfc/sites/<siteId>/suspend", methods=["POST"])
def suspend_site(siteId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    site = svc.get_site(siteId)
    if site["status"] != "OPERATING":
        raise errors.err_invalid_state("Site must be OPERATING to suspend")
    for b in db.pick_batches.values():
        if b["site_id"] == siteId and b["status"] in ("OPEN", "SEALED"):
            raise errors.err_site_busy()
    for o in db.orders.values():
        if o["site_id"] == siteId and o["status"] in ("PICKING", "AWAITING_HANDOFF", "OUT_FOR_DELIVERY"):
            raise errors.err_site_busy()
    site["status"] = "SUSPENDED"
    db.touch(site)
    return resp.success(svc.serialize_site(site))


@app.route("/mfc/sites/<siteId>/resume", methods=["POST"])
def resume_site(siteId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    site = svc.get_site(siteId)
    if site["status"] != "SUSPENDED":
        raise errors.err_invalid_state("Site must be SUSPENDED to resume")
    site["status"] = "OPERATING"
    db.touch(site)
    return resp.success(svc.serialize_site(site))


@app.route("/mfc/sites/<siteId>/demand-forecast", methods=["GET"])
def demand_forecast(siteId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    site = svc.get_site(siteId)
    precip_raw = request.args.get("precipitation_prob")
    precip = Decimal("0")
    if precip_raw is not None:
        try:
            precip = Decimal(str(precip_raw))
        except Exception:
            raise errors.err_invalid_request("precipitation_prob must be a number in [0, 1]")
        if precip < 0 or precip > 1:
            raise errors.err_invalid_request("precipitation_prob must be in [0, 1]")

    now = db.now()
    window_start = now - timedelta(days=7)
    hours = []
    for h in range(24):
        hour_dt = now + timedelta(hours=h)
        hod = hour_dt.hour
        base = 0
        for o in db.orders.values():
            if o["site_id"] == siteId and o["status"] == "DELIVERED":
                placed = o["created_at"]
                if window_start <= placed <= now and placed.hour == hod:
                    base += 1
        night_mult = Decimal("1") + svc.NIGHT_LIFT_PCT if (hod >= 22 or hod < 4) else Decimal("1")
        weather_mult = Decimal("1") + (precip * svc.WEATHER_LIFT_PCT)
        projected = svc.round_half_up_int(Decimal(base) * night_mult * weather_mult)
        hours.append({
            "hour_of_day": hod,
            "hour_utc": db.fmt_ts(hour_dt.replace(minute=0, second=0, microsecond=0)),
            "baseline_orders": base,
            "night_multiplier": float(night_mult),
            "weather_multiplier": float(weather_mult),
            "projected_orders": projected,
        })
    return resp.success({"site_id": siteId, "hours": hours})


# ===========================================================================
# Products
# ===========================================================================
@app.route("/mfc/products", methods=["POST"])
def create_product():
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    data = mw.get_json()

    sku = data.get("sku")
    name = data.get("name")
    price = data.get("price_cents")
    pclass = data.get("product_class")

    if not sku or not isinstance(sku, str):
        raise errors.err_invalid_request("sku is required")
    if any(p["sku"] == sku for p in db.products.values()):
        raise errors.err_duplicate_resource("sku must be unique")
    if not name or not isinstance(name, str):
        raise errors.err_invalid_request("name is required")
    if not svc.is_int(price) or price <= 0:
        raise errors.err_invalid_request("price_cents must be an integer > 0")
    if pclass not in svc.PRODUCT_CLASSES:
        raise errors.err_invalid_request("product_class must be STANDARD, AGE_RESTRICTED, or PERISHABLE")

    product = db.new_common({
        "id": db.new_id(),
        "sku": sku,
        "name": name,
        "price_cents": price,
        "product_class": pclass,
        "status": "ACTIVE",
    })
    db.products[product["id"]] = product
    return resp.success(svc.serialize_product(product), status=201)


@app.route("/mfc/products", methods=["GET"])
def list_products():
    uid, role = mw.user_context()
    mw.require_role(role, ALL_READ)
    return _list_response(
        list(db.products.values()),
        [("product_class", "product_class"), ("status", "status")],
        svc.serialize_product,
    )


@app.route("/mfc/products/<productId>", methods=["GET"])
def get_product(productId):
    uid, role = mw.user_context()
    mw.require_role(role, ALL_READ)
    product = svc.get_product(productId)
    return resp.success(svc.serialize_product(product))


@app.route("/mfc/products/<productId>/retire", methods=["POST"])
def retire_product(productId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    product = svc.get_product(productId)
    if product["status"] != "ACTIVE":
        raise errors.err_invalid_state("Product must be ACTIVE to retire")
    for o in db.orders.values():
        if o["status"] in IN_FLIGHT_ORDER_STATES:
            for line in o["lines"]:
                if line["product_id"] == productId:
                    raise errors.err_product_in_use()
    product["status"] = "RETIRED"
    db.touch(product)
    return resp.success(svc.serialize_product(product))


# ===========================================================================
# Inventory balances and stock adjustments
# ===========================================================================
@app.route("/mfc/inventory-balances", methods=["POST"])
def create_balance():
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    data = mw.get_json()
    site_id = data.get("site_id")
    product_id = data.get("product_id")
    min_par = data.get("min_par_level", 0)

    if not isinstance(site_id, str) or not site_id:
        raise errors.err_invalid_request("site_id is required")
    site = db.sites.get(site_id)
    if site is None:
        raise errors.err_site_not_found()
    if not isinstance(product_id, str) or not product_id:
        raise errors.err_invalid_request("product_id is required")
    product = db.products.get(product_id)
    if product is None:
        raise errors.err_product_not_found()
    if not svc.is_int(min_par) or min_par < 0:
        raise errors.err_invalid_request("min_par_level must be an integer >= 0")
    if svc.find_balance(site_id, product_id) is not None:
        raise errors.err_duplicate_resource("balance already exists for (site, product)")

    balance = db.new_common({
        "id": db.new_id(),
        "site_id": site_id,
        "product_id": product_id,
        "on_hand": 0,
        "reserved": 0,
        "min_par_level": min_par,
        "on_order": 0,
    })
    db.balances[balance["id"]] = balance
    return resp.success(svc.serialize_balance(balance), status=201)


@app.route("/mfc/inventory-balances", methods=["GET"])
def list_balances():
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Picker"])
    return _list_response(
        list(db.balances.values()),
        [("site_id", "site_id"), ("product_id", "product_id")],
        svc.serialize_balance,
    )


@app.route("/mfc/inventory-balances/<balanceId>", methods=["GET"])
def get_balance(balanceId):
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Picker"])
    balance = db.balances.get(balanceId)
    if balance is None:
        raise errors.err_invalid_request("balance not found")
    return resp.success(svc.serialize_balance(balance))


@app.route("/mfc/inventory-balances/<balanceId>/adjustments", methods=["POST"])
def stock_adjustment(balanceId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    balance = db.balances.get(balanceId)
    if balance is None:
        raise errors.err_invalid_request("balance not found")
    data = mw.get_json()
    kind = data.get("kind")
    if kind not in ("RECEIPT", "SHRINK_DISPOSE"):
        raise errors.err_invalid_request("kind must be RECEIPT or SHRINK_DISPOSE")

    if kind == "RECEIPT":
        qty = data.get("qty")
        if not svc.is_int(qty) or qty < 1:
            raise errors.err_invalid_request("qty is required and must be >= 1")
        balance["on_hand"] += qty
        applied = qty
    else:
        lot_id = data.get("lot_id")
        if not isinstance(lot_id, str) or not lot_id:
            raise errors.err_invalid_request("lot_id is required for SHRINK_DISPOSE")
        lot = db.lots.get(lot_id)
        if lot is None:
            raise errors.err_stock_lot_not_found()
        qty = data.get("qty")
        if not svc.is_int(qty) or qty < 1:
            raise errors.err_invalid_request("qty is required and must be >= 1")
        if svc.lot_status(lot) != "EXPIRED" or qty > lot["remaining_qty"]:
            raise errors.err_shrink_exceeds_lot()
        lot["remaining_qty"] -= qty
        db.touch(lot)
        balance["on_hand"] -= qty
        applied = qty

    db.touch(balance)
    return resp.success({
        "balance_id": balance["id"],
        "on_hand": balance["on_hand"],
        "applied_qty": applied,
    }, status=201)


# ===========================================================================
# Stock lots
# ===========================================================================
@app.route("/mfc/stock-lots", methods=["GET"])
def list_lots():
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Picker"])
    records = list(db.lots.values())
    for param, field in (("site_id", "site_id"), ("product_id", "product_id")):
        raw = request.args.get(param)
        if raw is not None:
            records = [r for r in records if str(r.get(field)) == raw]
    status_filter = request.args.get("status")
    if status_filter is not None:
        records = [r for r in records if svc.lot_status(r) == status_filter]
    limit, offset = mw.parse_pagination(request.args)
    page, total = mw.paginate(records, limit, offset)
    return resp.success_list([svc.serialize_lot(r) for r in page], limit, offset, total)


@app.route("/mfc/stock-lots/<lotId>", methods=["GET"])
def get_lot(lotId):
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Picker"])
    lot = svc.get_lot(lotId)
    return resp.success(svc.serialize_lot(lot))


# ===========================================================================
# Customers and wallets
# ===========================================================================
@app.route("/mfc/customers", methods=["POST"])
def create_customer():
    uid, role = mw.user_context()
    mw.require_role(role, ["Customer"])
    data = mw.get_json()
    email = data.get("email")
    full_name = data.get("full_name")
    dob_raw = data.get("date_of_birth")

    if not email or not isinstance(email, str):
        raise errors.err_invalid_request("email is required")
    if any(c["email"] == email for c in db.customers.values()):
        raise errors.err_duplicate_resource("email must be unique")
    if not full_name or not isinstance(full_name, str):
        raise errors.err_invalid_request("full_name is required")
    dob = svc.parse_dt(dob_raw)
    if dob is None:
        raise errors.err_invalid_request("date_of_birth must be an ISO 8601 date or datetime")

    customer = db.new_common({
        "id": db.new_id(),
        "email": email,
        "full_name": full_name,
        "date_of_birth": dob,
        "wallet_credit_cents": 0,
        "status": "ACTIVE",
    })
    db.customers[customer["id"]] = customer
    return resp.success(svc.serialize_customer(customer), status=201)


@app.route("/mfc/customers", methods=["GET"])
def list_customers():
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    return _list_response(
        list(db.customers.values()),
        [("status", "status")],
        svc.serialize_customer,
    )


@app.route("/mfc/customers/<customerId>", methods=["GET"])
def get_customer(customerId):
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Customer"])
    customer = svc.get_customer(customerId)
    if role == "Customer" and uid != customerId:
        raise errors.err_unauthorized("Customer may only view self")
    return resp.success(svc.serialize_customer(customer))


@app.route("/mfc/customers/<customerId>/wallet/adjustments", methods=["POST"])
def wallet_adjustment(customerId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    customer = svc.get_customer(customerId)
    data = mw.get_json()
    amount = data.get("amount_cents")
    reason = data.get("reason")
    if not svc.is_int(amount):
        raise errors.err_invalid_request("amount_cents must be an integer")
    if not reason or not isinstance(reason, str):
        raise errors.err_invalid_request("reason is required")
    customer["wallet_credit_cents"] = max(0, customer["wallet_credit_cents"] + amount)
    db.touch(customer)
    return resp.success(svc.serialize_customer(customer), status=201)


# ===========================================================================
# Memberships
# ===========================================================================
@app.route("/mfc/memberships", methods=["POST"])
def create_membership():
    uid, role = mw.user_context()
    mw.require_role(role, ["Customer"])
    data = mw.get_json()
    customer_id = data.get("customer_id")
    tier = data.get("tier")
    fee = data.get("monthly_fee_cents")
    auto_renew = data.get("auto_renew", True)

    if not isinstance(customer_id, str) or not customer_id:
        raise errors.err_invalid_request("customer_id is required")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise errors.err_customer_not_found()
    if uid != customer_id:
        raise errors.err_unauthorized("Customer may only enroll self")
    if tier != "FAM":
        raise errors.err_invalid_request("tier must be FAM")
    if not svc.is_int(fee) or fee < 0:
        raise errors.err_invalid_request("monthly_fee_cents must be an integer >= 0")
    if not isinstance(auto_renew, bool):
        raise errors.err_invalid_request("auto_renew must be a boolean")
    if svc.membership_for(customer_id) is not None:
        raise errors.err_duplicate_resource("at most one membership per customer")

    now = db.now()
    membership = db.new_common({
        "id": db.new_id(),
        "customer_id": customer_id,
        "tier": tier,
        "status": "ACTIVE",
        "monthly_fee_cents": fee,
        "current_period_start": now,
        "current_period_end": now + timedelta(days=30),
        "periods_paid": 0,
        "period_orders_count": 0,
        "period_credit_earned_cents": 0,
        "auto_renew": auto_renew,
        "tenure_discount_bps": 0,
    })
    db.memberships[membership["id"]] = membership
    return resp.success(svc.serialize_membership(membership), status=201)


@app.route("/mfc/memberships", methods=["GET"])
def list_memberships():
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Customer"])
    records = list(db.memberships.values())
    if role == "Customer":
        records = [m for m in records if m["customer_id"] == uid]
    return _list_response(
        records,
        [("customer_id", "customer_id"), ("status", "status")],
        svc.serialize_membership,
    )


@app.route("/mfc/memberships/<membershipId>", methods=["GET"])
def get_membership(membershipId):
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Customer"])
    membership = svc.get_membership(membershipId)
    if role == "Customer" and uid != membership["customer_id"]:
        raise errors.err_unauthorized("Customer may only view own membership")
    return resp.success(svc.serialize_membership(membership))


@app.route("/mfc/memberships/<membershipId>/close-period", methods=["POST"])
def close_period(membershipId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    membership = svc.get_membership(membershipId)
    data = mw.get_json()
    paid = data.get("period_fee_paid")
    if not isinstance(paid, bool):
        raise errors.err_invalid_request("period_fee_paid must be a boolean")
    if membership["status"] not in ("ACTIVE", "LAPSED"):
        raise errors.err_invalid_state("Membership must be ACTIVE to close a period")
    if db.now() < membership["current_period_end"]:
        raise errors.err_invalid_state("logical clock has not reached current_period_end")

    # Pinned evaluation order (PRD §3.4):
    # 1) fee charged with the discount in force BEFORE this close
    _fee_charged = svc.round_half_up_cents(
        Decimal(membership["monthly_fee_cents"]) * (Decimal(1) - Decimal(membership["tenure_discount_bps"]) / Decimal(10000))
    )
    # 2) increment periods_paid when paid
    if paid:
        membership["periods_paid"] += 1
    # 3) recompute tenure discount AFTER the increment (for the next period)
    membership["tenure_discount_bps"] = (
        svc.TENURE_DISCOUNT_BPS if membership["periods_paid"] >= svc.TENURE_THRESHOLD_PERIODS else 0
    )
    # 4) advance the period window
    membership["current_period_start"] = membership["current_period_end"]
    membership["current_period_end"] = membership["current_period_start"] + timedelta(days=30)
    # 5) reset period counters
    membership["period_orders_count"] = 0
    membership["period_credit_earned_cents"] = 0
    # 6) lapse when unpaid
    if not paid:
        membership["status"] = "LAPSED"
    else:
        membership["status"] = "ACTIVE"
    db.touch(membership)
    return resp.success(svc.serialize_membership(membership))


def _membership_lifecycle_write(membershipId, action):
    uid, role = mw.user_context()
    mw.require_role(role, ["Customer"])
    membership = svc.get_membership(membershipId)
    if uid != membership["customer_id"]:
        raise errors.err_unauthorized("Customer may only act on own membership")
    if action == "renew":
        required_state = "LAPSED"
    else:
        required_state = "ACTIVE"
    if membership["status"] != required_state:
        raise errors.err_invalid_state(f"Membership must be {required_state}")
    data = mw.get_json()
    if "expected_customer_version" not in data or not svc.is_int(data.get("expected_customer_version")):
        raise errors.err_invalid_request("expected_customer_version is required")
    customer = svc.get_customer(membership["customer_id"])
    if data["expected_customer_version"] != customer["version"]:
        raise errors.err_stale_version()

    if action == "renew":
        now = db.now()
        membership["status"] = "ACTIVE"
        membership["current_period_start"] = now
        membership["current_period_end"] = now + timedelta(days=30)
    else:
        membership["status"] = "CANCELLED"
    db.touch(membership)
    db.touch(customer)
    return resp.success(svc.serialize_membership(membership))


@app.route("/mfc/memberships/<membershipId>/renew", methods=["POST"])
def renew_membership(membershipId):
    return _membership_lifecycle_write(membershipId, "renew")


@app.route("/mfc/memberships/<membershipId>/cancel", methods=["POST"])
def cancel_membership(membershipId):
    return _membership_lifecycle_write(membershipId, "cancel")


# ===========================================================================
# Replenish orders
# ===========================================================================
@app.route("/mfc/replenish-orders", methods=["POST"])
def create_replenish_order():
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    data = mw.get_json()
    site_id = data.get("site_id")
    reference = data.get("reference")
    lines = data.get("lines")
    expected_at_raw = data.get("expected_at")
    idem_key = data.get("idempotency_key")

    if not isinstance(site_id, str) or not site_id:
        raise errors.err_invalid_request("site_id is required")
    site = db.sites.get(site_id)
    if site is None:
        raise errors.err_site_not_found()
    if not reference or not isinstance(reference, str):
        raise errors.err_invalid_request("reference is required")
    if not isinstance(lines, list) or len(lines) < 1:
        raise errors.err_invalid_request("lines must be a non-empty array")
    clean_lines = []
    for line in lines:
        if not isinstance(line, dict):
            raise errors.err_invalid_request("each line must be an object")
        pid = line.get("product_id")
        qty = line.get("qty")
        cost = line.get("unit_cost_cents")
        if not isinstance(pid, str) or not pid:
            raise errors.err_invalid_request("line product_id is required")
        product = db.products.get(pid)
        if product is None:
            raise errors.err_product_not_found()
        if not svc.is_int(qty) or qty < 1:
            raise errors.err_invalid_request("line qty must be an integer >= 1")
        if not svc.is_int(cost) or cost < 0:
            raise errors.err_invalid_request("line unit_cost_cents must be an integer >= 0")
        clean_lines.append({"product_id": pid, "qty": qty, "unit_cost_cents": cost})
    expected_at = svc.parse_dt(expected_at_raw)
    if expected_at is None:
        raise errors.err_invalid_request("expected_at must be an ISO 8601 UTC instant")
    if not idem_key or not isinstance(idem_key, str):
        raise errors.err_invalid_request("idempotency_key is required")

    # Idempotency: replayed POST with the same key per site returns the original.
    for r in db.replenish_orders.values():
        if r["site_id"] == site_id and r["idempotency_key"] == idem_key:
            return resp.success(svc.serialize_replenish(r), status=201)
    if any(r["site_id"] == site_id and r["reference"] == reference for r in db.replenish_orders.values()):
        raise errors.err_duplicate_resource("reference must be unique per site")

    order = db.new_common({
        "id": db.new_id(),
        "site_id": site_id,
        "reference": reference,
        "lines": clean_lines,
        "expected_at": expected_at,
        "status": "DRAFT",
        "idempotency_key": idem_key,
    })
    db.replenish_orders[order["id"]] = order
    return resp.success(svc.serialize_replenish(order), status=201)


@app.route("/mfc/replenish-orders", methods=["GET"])
def list_replenish_orders():
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    return _list_response(
        list(db.replenish_orders.values()),
        [("site_id", "site_id"), ("status", "status")],
        svc.serialize_replenish,
    )


@app.route("/mfc/replenish-orders/<replenishOrderId>", methods=["GET"])
def get_replenish_order(replenishOrderId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    order = svc.get_replenish(replenishOrderId)
    return resp.success(svc.serialize_replenish(order))


@app.route("/mfc/replenish-orders/<replenishOrderId>/place", methods=["POST"])
def place_replenish_order(replenishOrderId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    order = svc.get_replenish(replenishOrderId)
    if order["status"] != "DRAFT":
        raise errors.err_invalid_state("ReplenishOrder must be DRAFT to place")
    site = svc.get_site(order["site_id"])
    if svc.effective_status(site) != "OPERATING":
        raise errors.err_site_not_operating()
    for line in order["lines"]:
        balance = svc.find_balance(order["site_id"], line["product_id"])
        if balance is None:
            raise errors.err_invalid_request("no inventory balance for (site, product)")
        balance["on_order"] += line["qty"]
        db.touch(balance)
    order["status"] = "PLACED"
    db.touch(order)
    return resp.success(svc.serialize_replenish(order))


@app.route("/mfc/replenish-orders/<replenishOrderId>/finalize", methods=["POST"])
def finalize_replenish_order(replenishOrderId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    order = svc.get_replenish(replenishOrderId)
    if order["status"] != "PLACED":
        raise errors.err_invalid_state("ReplenishOrder must be PLACED to finalize")
    data = mw.get_json()
    lot_expiries = data.get("lot_expiries") or {}
    if not isinstance(lot_expiries, dict):
        raise errors.err_invalid_request("lot_expiries must be an object keyed by product_id")

    # Pre-validate: every perishable line requires an expiry; every balance exists.
    for line in order["lines"]:
        product = svc.get_product(line["product_id"])
        if svc.find_balance(order["site_id"], line["product_id"]) is None:
            raise errors.err_invalid_request("no inventory balance for (site, product)")
        if product["product_class"] == "PERISHABLE":
            exp = svc.parse_dt(lot_expiries.get(line["product_id"]))
            if exp is None:
                raise errors.err_invalid_request("lot_expiries must supply an expiry for every perishable line")

    # All-or-nothing: apply only after full validation.
    for line in order["lines"]:
        product = svc.get_product(line["product_id"])
        balance = svc.find_balance(order["site_id"], line["product_id"])
        balance["on_order"] -= line["qty"]
        balance["on_hand"] += line["qty"]
        db.touch(balance)
        if product["product_class"] == "PERISHABLE":
            exp = svc.parse_dt(lot_expiries[line["product_id"]])
            suffix = 0
            while True:
                lot_code = line["product_id"] if suffix == 0 else f"{line['product_id']}-{suffix}"
                # ensure uniqueness per (site, product) — generated codes embed the
                # replenish order id to stay unique across receipts
                lot_code = f"LOT-{order['id'][:8]}-{line['product_id'][:8]}" + (f"-{suffix}" if suffix else "")
                clash = any(
                    l["site_id"] == order["site_id"] and l["product_id"] == line["product_id"] and l["lot_code"] == lot_code
                    for l in db.lots.values()
                )
                if not clash:
                    break
                suffix += 1
            lot = db.new_common({
                "id": db.new_id(),
                "site_id": order["site_id"],
                "product_id": line["product_id"],
                "lot_code": lot_code,
                "received_qty": line["qty"],
                "remaining_qty": line["qty"],
                "expires_at": exp,
            })
            db.lots[lot["id"]] = lot
    order["status"] = "FINALIZED"
    db.touch(order)
    return resp.success(svc.serialize_replenish(order))


@app.route("/mfc/replenish-orders/<replenishOrderId>/cancel", methods=["POST"])
def cancel_replenish_order(replenishOrderId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    order = svc.get_replenish(replenishOrderId)
    if order["status"] != "PLACED":
        raise errors.err_invalid_state("ReplenishOrder must be PLACED to cancel")
    for line in order["lines"]:
        balance = svc.find_balance(order["site_id"], line["product_id"])
        if balance is not None:
            balance["on_order"] -= line["qty"]
            db.touch(balance)
    order["status"] = "CANCELLED"
    db.touch(order)
    return resp.success(svc.serialize_replenish(order))


# ===========================================================================
# Pickers and drivers
# ===========================================================================
@app.route("/mfc/pickers", methods=["POST"])
def create_picker():
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    data = mw.get_json()
    site_id = data.get("site_id")
    name = data.get("name")
    status = data.get("status", "ACTIVE")
    if not isinstance(site_id, str) or not site_id:
        raise errors.err_invalid_request("site_id is required")
    if db.sites.get(site_id) is None:
        raise errors.err_site_not_found()
    if not name or not isinstance(name, str):
        raise errors.err_invalid_request("name is required")
    if status not in ("ACTIVE", "INACTIVE"):
        raise errors.err_invalid_request("status must be ACTIVE or INACTIVE")
    picker = db.new_common({
        "id": db.new_id(),
        "site_id": site_id,
        "name": name,
        "status": status,
    })
    db.pickers[picker["id"]] = picker
    return resp.success(svc.serialize_picker(picker), status=201)


@app.route("/mfc/pickers", methods=["GET"])
def list_pickers():
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Picker"])
    return _list_response(
        list(db.pickers.values()),
        [("site_id", "site_id"), ("status", "status")],
        svc.serialize_picker,
    )


@app.route("/mfc/pickers/<pickerId>", methods=["GET"])
def get_picker(pickerId):
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Picker"])
    picker = svc.get_picker(pickerId)
    return resp.success(svc.serialize_picker(picker))


@app.route("/mfc/drivers", methods=["POST"])
def create_driver():
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    data = mw.get_json()
    site_id = data.get("site_id")
    name = data.get("name")
    max_run = data.get("max_run_orders")
    status = data.get("status", "AVAILABLE")
    if not isinstance(site_id, str) or not site_id:
        raise errors.err_invalid_request("site_id is required")
    if db.sites.get(site_id) is None:
        raise errors.err_site_not_found()
    if not name or not isinstance(name, str):
        raise errors.err_invalid_request("name is required")
    if not svc.is_int(max_run) or max_run < 1:
        raise errors.err_invalid_request("max_run_orders must be an integer >= 1")
    if status not in ("AVAILABLE", "OFF_DUTY", "SUSPENDED"):
        raise errors.err_invalid_request("status must be AVAILABLE, OFF_DUTY, or SUSPENDED")
    driver = db.new_common({
        "id": db.new_id(),
        "site_id": site_id,
        "name": name,
        "max_run_orders": max_run,
        "status": status,
    })
    db.drivers[driver["id"]] = driver
    return resp.success(svc.serialize_driver(driver), status=201)


@app.route("/mfc/drivers", methods=["GET"])
def list_drivers():
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Driver"])
    return _list_response(
        list(db.drivers.values()),
        [("site_id", "site_id"), ("status", "status")],
        svc.serialize_driver,
    )


@app.route("/mfc/drivers/<driverId>", methods=["GET"])
def get_driver(driverId):
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Driver"])
    driver = svc.get_driver(driverId)
    return resp.success(svc.serialize_driver(driver))


# ===========================================================================
# Orders
# ===========================================================================
@app.route("/mfc/orders", methods=["POST"])
def create_order():
    uid, role = mw.user_context()
    mw.require_role(role, ["Customer"])
    data = mw.get_json()
    customer_id = data.get("customer_id")
    site_id = data.get("site_id")
    lines = data.get("lines")
    distance = data.get("delivery_distance_miles")

    # Existence of body FKs in input declaration order: customer_id, then site_id,
    # then each line's product_id.
    if not isinstance(customer_id, str) or not customer_id:
        raise errors.err_invalid_request("customer_id is required")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise errors.err_customer_not_found()
    if uid != customer_id:
        raise errors.err_unauthorized("customer_id must equal the placing customer's identity")
    if not isinstance(site_id, str) or not site_id:
        raise errors.err_invalid_request("site_id is required")
    site = db.sites.get(site_id)
    if site is None:
        raise errors.err_site_not_found()
    if not isinstance(lines, list) or len(lines) < 1:
        raise errors.err_invalid_request("lines must be a non-empty array")
    clean_lines = []
    products = []
    for line in lines:
        if not isinstance(line, dict):
            raise errors.err_invalid_request("each line must be an object")
        pid = line.get("product_id")
        qty = line.get("qty")
        if not isinstance(pid, str) or not pid:
            raise errors.err_invalid_request("line product_id is required")
        product = db.products.get(pid)
        if product is None:
            raise errors.err_product_not_found()
        if not svc.is_int(qty) or qty < 1:
            raise errors.err_invalid_request("line qty must be an integer >= 1")
        clean_lines.append({"product_id": pid, "qty": qty})
        products.append(product)
    if not svc.is_num(distance) or distance < 0:
        raise errors.err_invalid_request("delivery_distance_miles must be a number >= 0")

    # Business-safety gates in priority order.
    if svc.effective_status(site) != "OPERATING":
        raise errors.err_site_not_operating()
    if distance > site["delivery_radius_miles"]:
        raise errors.err_delivery_radius_exceeded()
    for product in products:
        if product["status"] != "ACTIVE":
            raise errors.err_product_unsellable()

    # Money fields in pinned order (PRD §3.5):
    # 1) basket
    subtotal = sum(p["price_cents"] * l["qty"] for p, l in zip(products, clean_lines))
    contains_age_restricted = any(p["product_class"] == "AGE_RESTRICTED" for p in products)

    # 2) wallet absorption (before fee computation; floor 0)
    applicable = min(customer["wallet_credit_cents"], max(0, subtotal - svc.WALLET_FLOOR_CENTS))
    if applicable > 0:
        customer["wallet_credit_cents"] -= applicable
        db.touch(customer)

    # 3) tax — per-line round half-up, then sum
    tax = 0
    for p, l in zip(products, clean_lines):
        if p["product_class"] == "AGE_RESTRICTED":
            line_tax = svc.round_half_up_cents(Decimal(l["qty"]) * Decimal(p["price_cents"]) * svc.TOBACCO_TAX_RATE)
            tax += line_tax

    # 4) delivery fee on the raw subtotal
    fs = site["fee_schedule"]
    fee = fs["base_cents"]
    billable_miles = max(Decimal("0"), Decimal(str(distance)) - Decimal(str(fs["included_miles"])))
    fee += svc.round_half_up_cents(billable_miles * Decimal(fs["per_mile_cents"]))
    if svc.is_peak(site, db.now()):
        fee += fs["peak_surcharge_cents"]
    fee = max(fs["min_fee_cents"], min(fs["max_fee_cents"], fee))
    membership = svc.membership_for(customer_id)
    if membership is not None and membership["status"] == "ACTIVE" and subtotal >= site["fee_waiver_threshold_cents"]:
        fee = 0

    total = subtotal + tax + fee - applicable

    order = db.new_common({
        "id": db.new_id(),
        "customer_id": customer_id,
        "site_id": site_id,
        "lines": clean_lines,
        "delivery_distance_miles": distance,
        "contains_age_restricted": contains_age_restricted,
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "delivery_fee_cents": fee,
        "loyalty_credit_applied_cents": applicable,
        "total_cents": total,
        "pick_batch_id": None,
        "status": "PLACED",
    })
    db.orders[order["id"]] = order
    return resp.success(svc.serialize_order(order), status=201)


@app.route("/mfc/orders", methods=["GET"])
def list_orders():
    uid, role = mw.user_context()
    mw.require_role(role, ALL_READ)
    records = list(db.orders.values())
    if role == "Customer":
        records = [o for o in records if o["customer_id"] == uid]
    return _list_response(
        records,
        [("customer_id", "customer_id"), ("site_id", "site_id"),
         ("status", "status"), ("pick_batch_id", "pick_batch_id")],
        svc.serialize_order,
    )


@app.route("/mfc/orders/<orderId>", methods=["GET"])
def get_order(orderId):
    uid, role = mw.user_context()
    mw.require_role(role, ALL_READ)
    order = svc.get_order(orderId)
    if role == "Customer" and uid != order["customer_id"]:
        raise errors.err_unauthorized("Customer may only view own orders")
    return resp.success(svc.serialize_order(order))


@app.route("/mfc/orders/<orderId>/cancel", methods=["POST"])
def cancel_order(orderId):
    uid, role = mw.user_context()
    mw.require_role(role, ["Customer", "SiteOps"])
    order = svc.get_order(orderId)
    data = mw.get_json()
    reason = data.get("reason")
    if reason not in ("CUSTOMER", "RETURN_TO_STOCK"):
        raise errors.err_invalid_request("reason must be CUSTOMER or RETURN_TO_STOCK")
    # A reason that mismatches the acting role is an invalid request for that
    # actor (PRD §3.8: "any other reason ... is rejected (ERR_INVALID_REQUEST)").
    if (role == "Customer" and reason != "CUSTOMER") or (role == "SiteOps" and reason != "RETURN_TO_STOCK"):
        raise errors.err_invalid_request("reason does not match the acting role")

    customer = svc.get_customer(order["customer_id"])

    if reason == "CUSTOMER":
        if role != "Customer":
            raise errors.err_unauthorized("reason CUSTOMER requires the owning customer")
        if uid != order["customer_id"]:
            raise errors.err_unauthorized("Customer may only cancel own orders")
        if order["status"] != "PLACED":
            raise errors.err_invalid_state("Order must be PLACED for a CUSTOMER cancel")
        customer["wallet_credit_cents"] += order["loyalty_credit_applied_cents"]
        db.touch(customer)
        order["status"] = "CANCELLED"
        db.touch(order)
        svc.maybe_close_batch(order["pick_batch_id"]) if order["pick_batch_id"] else None
        return resp.success(svc.serialize_order(order))

    # RETURN_TO_STOCK
    if role != "SiteOps":
        raise errors.err_unauthorized("reason RETURN_TO_STOCK requires SiteOps")
    if order["status"] != "HANDOFF_FAILED":
        raise errors.err_invalid_state("Order must be HANDOFF_FAILED for a RETURN_TO_STOCK cancel")
    for line in order["lines"]:
        product = svc.get_product(line["product_id"])
        if product["product_class"] == "PERISHABLE":
            continue  # perishable lines are written off, never restocked
        lot_code = f"RMA-{order['id']}-{product['id']}"
        existing = None
        for l in db.lots.values():
            if l["site_id"] == order["site_id"] and l["product_id"] == product["id"] and l["lot_code"] == lot_code:
                existing = l
                break
        if existing is None:
            lot = db.new_common({
                "id": db.new_id(),
                "site_id": order["site_id"],
                "product_id": product["id"],
                "lot_code": lot_code,
                "received_qty": line["qty"],
                "remaining_qty": line["qty"],
                "expires_at": svc.parse_dt("2099-12-31T00:00:00Z"),
            })
            db.lots[lot["id"]] = lot
        else:
            existing["received_qty"] += line["qty"]
            existing["remaining_qty"] += line["qty"]
            db.touch(existing)
        balance = svc.find_balance(order["site_id"], product["id"])
        if balance is not None:
            balance["on_hand"] += line["qty"]
            db.touch(balance)
    customer["wallet_credit_cents"] += order["loyalty_credit_applied_cents"]
    db.touch(customer)
    order["status"] = "CANCELLED"
    db.touch(order)
    if order["pick_batch_id"]:
        svc.maybe_close_batch(order["pick_batch_id"])
    return resp.success(svc.serialize_order(order))


# ===========================================================================
# Pick batches
# ===========================================================================
@app.route("/mfc/pick-batches", methods=["POST"])
def create_batch():
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Picker"])
    data = mw.get_json()
    site_id = data.get("site_id")
    picker_id = data.get("picker_id")
    if not isinstance(site_id, str) or not site_id:
        raise errors.err_invalid_request("site_id is required")
    if db.sites.get(site_id) is None:
        raise errors.err_site_not_found()
    if not isinstance(picker_id, str) or not picker_id:
        raise errors.err_invalid_request("picker_id is required")
    picker = db.pickers.get(picker_id)
    if picker is None:
        raise errors.err_picker_not_found()
    if picker["status"] != "ACTIVE":
        raise errors.err_invalid_request("only ACTIVE pickers may own batches")
    if role == "Picker" and uid != picker_id:
        raise errors.err_unauthorized("Picker may only open batches for self")
    batch = db.new_common({
        "id": db.new_id(),
        "site_id": site_id,
        "picker_id": picker_id,
        "order_ids": [],
        "sealed_at": None,
        "sealed_by_id": None,
        "status": "OPEN",
    })
    db.pick_batches[batch["id"]] = batch
    return resp.success(svc.serialize_batch(batch), status=201)


@app.route("/mfc/pick-batches", methods=["GET"])
def list_batches():
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Picker"])
    return _list_response(
        list(db.pick_batches.values()),
        [("site_id", "site_id"), ("picker_id", "picker_id"),
         ("sealed_by_id", "sealed_by_id"), ("status", "status")],
        svc.serialize_batch,
    )


@app.route("/mfc/pick-batches/<batchId>", methods=["GET"])
def get_batch(batchId):
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Picker"])
    batch = svc.get_batch(batchId)
    return resp.success(svc.serialize_batch(batch))


@app.route("/mfc/pick-batches/<batchId>/orders", methods=["POST"])
def append_order(batchId):
    uid, role = mw.user_context()
    mw.require_role(role, ["Picker"])
    batch = svc.get_batch(batchId)
    data = mw.get_json()
    order_id = data.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        raise errors.err_invalid_request("order_id is required")
    order = db.orders.get(order_id)
    if order is None:
        raise errors.err_order_not_found()
    site = svc.get_site(batch["site_id"])

    if batch["status"] != "OPEN":
        raise errors.err_invalid_state("PickBatch must be OPEN to append")
    if order["status"] != "PLACED":
        raise errors.err_invalid_state("Order must be PLACED to append")
    if order["site_id"] != batch["site_id"]:
        raise errors.err_invalid_request("order site must match batch site")

    # Capacity ceilings (priority 9): line cap inclusive, item cap on overflow.
    incoming_items = sum(l["qty"] for l in order["lines"])
    if len(batch["order_ids"]) >= site["batch_max_lines"]:
        raise errors.err_batch_full()
    if svc.batch_item_total(batch) + incoming_items > site["batch_max_items"]:
        raise errors.err_batch_full()

    # Perishable FRESH-lot cover (priority 10).
    for line in order["lines"]:
        product = svc.get_product(line["product_id"])
        if product["product_class"] == "PERISHABLE":
            if svc.fresh_lot_cover(batch["site_id"], product["id"]) < line["qty"]:
                raise errors.err_product_unsellable()

    # Stock availability (priority 11).
    for line in order["lines"]:
        balance = svc.find_balance(batch["site_id"], line["product_id"])
        available = (balance["on_hand"] - balance["reserved"]) if balance else 0
        if available < line["qty"]:
            raise errors.err_insufficient_stock()

    # Age pre-screen (priority 7) at the logical clock.
    if order["contains_age_restricted"]:
        customer = svc.get_customer(order["customer_id"])
        if svc.years_between(customer["date_of_birth"], db.now()) < svc.MIN_AGE_RESTRICTED:
            raise errors.err_age_verification_required()

    # Reserve cascade.
    for line in order["lines"]:
        balance = svc.find_balance(batch["site_id"], line["product_id"])
        balance["reserved"] += line["qty"]
        db.touch(balance)
    order["pick_batch_id"] = batch["id"]
    order["status"] = "PICKING"
    db.touch(order)
    batch["order_ids"].append(order["id"])
    db.touch(batch)
    return resp.success(svc.serialize_batch(batch))


@app.route("/mfc/pick-batches/<batchId>/seal", methods=["POST"])
def seal_batch(batchId):
    uid, role = mw.user_context()
    mw.require_role(role, ["Picker"])
    batch = svc.get_batch(batchId)
    if batch["status"] != "OPEN":
        raise errors.err_invalid_state("PickBatch must be OPEN to seal")
    # Segregation of duties is a business-safety rule and precedes capacity.
    if uid == batch["picker_id"]:
        raise errors.err_self_seal_forbidden()
    if not batch["order_ids"]:
        raise errors.err_batch_empty()
    sealer = db.pickers.get(uid)
    if sealer is None or sealer["status"] != "ACTIVE":
        raise errors.err_unauthorized("only ACTIVE pickers may seal batches")

    for oid in batch["order_ids"]:
        order = db.orders[oid]
        for line in order["lines"]:
            product = svc.get_product(line["product_id"])
            balance = svc.find_balance(batch["site_id"], line["product_id"])
            if balance is not None:
                balance["reserved"] -= line["qty"]
                balance["on_hand"] -= line["qty"]
                db.touch(balance)
            if product["product_class"] == "PERISHABLE":
                remaining = line["qty"]
                lots = [
                    l for l in db.lots.values()
                    if l["site_id"] == batch["site_id"]
                    and l["product_id"] == product["id"]
                    and svc.lot_status(l) == "FRESH"
                ]
                lots.sort(key=lambda l: (l["expires_at"], l["created_at"]))
                for lot in lots:
                    if remaining <= 0:
                        break
                    take = min(lot["remaining_qty"], remaining)
                    lot["remaining_qty"] -= take
                    remaining -= take
                    db.touch(lot)
        order["status"] = "AWAITING_HANDOFF"
        db.touch(order)

    batch["status"] = "SEALED"
    batch["sealed_at"] = db.now()
    batch["sealed_by_id"] = uid
    db.touch(batch)
    return resp.success(svc.serialize_batch(batch))


# ===========================================================================
# Delivery bags
# ===========================================================================
@app.route("/mfc/delivery-bags", methods=["POST"])
def create_bag():
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    data = mw.get_json()
    order_id = data.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        raise errors.err_invalid_request("order_id is required")
    order = db.orders.get(order_id)
    if order is None:
        raise errors.err_order_not_found()
    if order["status"] != "AWAITING_HANDOFF":
        raise errors.err_invalid_state("Order must be AWAITING_HANDOFF to create a bag")
    if any(b["order_id"] == order_id for b in db.delivery_bags.values()):
        raise errors.err_duplicate_resource("at most one delivery bag per order")
    bag = db.new_common({
        "id": db.new_id(),
        "order_id": order_id,
        "driver_id": None,
        "assigned_at": None,
        "delivery_status": "UNASSIGNED",
        "handoff_status": "NONE",
        "scanned_id_last4": None,
    })
    db.delivery_bags[bag["id"]] = bag
    return resp.success(svc.serialize_bag(bag), status=201)


@app.route("/mfc/delivery-bags", methods=["GET"])
def list_bags():
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Driver"])
    return _list_response(
        list(db.delivery_bags.values()),
        [("order_id", "order_id"), ("driver_id", "driver_id"),
         ("delivery_status", "delivery_status")],
        svc.serialize_bag,
    )


@app.route("/mfc/delivery-bags/<bagId>", methods=["GET"])
def get_bag(bagId):
    uid, role = mw.user_context()
    mw.require_role(role, ["SiteOps", "Driver"])
    bag = svc.get_bag(bagId)
    return resp.success(svc.serialize_bag(bag))


@app.route("/mfc/delivery-bags/<bagId>/assign", methods=["POST"])
def assign_bag(bagId):
    uid, role = mw.user_context()
    mw.require_role(role, OPS)
    bag = svc.get_bag(bagId)
    order = svc.get_order(bag["order_id"])
    if bag["delivery_status"] != "UNASSIGNED":
        raise errors.err_invalid_state("DeliveryBag must be UNASSIGNED to assign")
    if order["status"] != "AWAITING_HANDOFF":
        raise errors.err_invalid_state("Parent order must be AWAITING_HANDOFF")
    data = mw.get_json()
    driver_id = data.get("driver_id")

    if driver_id is not None:
        if not isinstance(driver_id, str) or not driver_id:
            raise errors.err_invalid_request("driver_id must be a string")
        driver = db.drivers.get(driver_id)
        if driver is None:
            raise errors.err_driver_not_found()
    else:
        site_id = order["site_id"]
        candidates = [
            d for d in db.drivers.values()
            if d["site_id"] == site_id
            and d["status"] == "AVAILABLE"
            and svc.driver_run_size(d["id"]) < d["max_run_orders"]
        ]
        if not candidates:
            raise errors.err_no_driver_available()
        candidates.sort(key=lambda d: (svc.driver_run_size(d["id"]), d["created_at"]))
        driver = candidates[0]

    bag["driver_id"] = driver["id"]
    bag["assigned_at"] = db.now()
    bag["delivery_status"] = "ASSIGNED"
    db.touch(bag)
    return resp.success(svc.serialize_bag(bag))


@app.route("/mfc/delivery-bags/<bagId>/handoff-scan", methods=["POST"])
def handoff_scan(bagId):
    uid, role = mw.user_context()
    mw.require_role(role, ["Driver"])
    bag = svc.get_bag(bagId)
    order = svc.get_order(bag["order_id"])
    if not order["contains_age_restricted"]:
        raise errors.err_handoff_not_required()
    if bag["handoff_status"] != "NONE":
        raise errors.err_invalid_state("handoff already resolved")
    if bag["delivery_status"] != "ASSIGNED":
        raise errors.err_invalid_state("scanning happens after dispatch, before departure")
    if uid != bag["driver_id"]:
        raise errors.err_unauthorized("acting driver must be the bag's assignee")
    data = mw.get_json()
    scanned_birthdate = svc.parse_dt(data.get("scanned_birthdate"))
    scanned_id_last4 = data.get("scanned_id_last4")
    if scanned_birthdate is None:
        raise errors.err_invalid_request("scanned_birthdate must be an ISO 8601 date or datetime")
    if not isinstance(scanned_id_last4, str) or not scanned_id_last4:
        raise errors.err_invalid_request("scanned_id_last4 is required")

    bag["scanned_id_last4"] = scanned_id_last4
    age = svc.years_between(scanned_birthdate, db.now())
    if age >= svc.MIN_AGE_RESTRICTED:
        bag["handoff_status"] = "AGE_VERIFIED"
    else:
        bag["handoff_status"] = "REFUSED"
    db.touch(bag)
    return resp.success(svc.serialize_bag(bag))


@app.route("/mfc/delivery-bags/<bagId>/depart", methods=["POST"])
def depart_bag(bagId):
    uid, role = mw.user_context()
    mw.require_role(role, ["Driver"])
    bag = svc.get_bag(bagId)
    order = svc.get_order(bag["order_id"])
    if bag["delivery_status"] != "ASSIGNED":
        raise errors.err_bag_not_assigned()
    if uid != bag["driver_id"]:
        raise errors.err_unauthorized("acting driver must be the bag's assignee")
    if order["contains_age_restricted"] and bag["handoff_status"] != "AGE_VERIFIED":
        raise errors.err_handoff_not_verified()
    order["status"] = "OUT_FOR_DELIVERY"
    db.touch(order)
    bag["delivery_status"] = "OUT_FOR_DELIVERY"
    db.touch(bag)
    return resp.success(svc.serialize_bag(bag))


@app.route("/mfc/delivery-bags/<bagId>/complete", methods=["POST"])
def complete_bag(bagId):
    uid, role = mw.user_context()
    mw.require_role(role, ["Driver"])
    bag = svc.get_bag(bagId)
    order = svc.get_order(bag["order_id"])
    if bag["delivery_status"] != "OUT_FOR_DELIVERY":
        raise errors.err_invalid_state("DeliveryBag must be OUT_FOR_DELIVERY to complete")
    if uid != bag["driver_id"]:
        raise errors.err_unauthorized("acting driver must be the bag's assignee")

    order["status"] = "DELIVERED"
    db.touch(order)
    bag["delivery_status"] = "DELIVERED"
    db.touch(bag)

    # Loyalty accrual (dual variant): absorb -> earn 0; record -> earn capped 3%.
    if order["loyalty_credit_applied_cents"] > 0:
        earned = 0
    else:
        earned = min(
            svc.LOYALTY_CAP_CENTS,
            svc.round_half_up_cents(
                svc.LOYALTY_RATE * Decimal(order["subtotal_cents"] + order["delivery_fee_cents"])
            ),
        )
    customer = svc.get_customer(order["customer_id"])
    customer["wallet_credit_cents"] += earned
    db.touch(customer)
    membership = svc.membership_for(order["customer_id"])
    if membership is not None:
        membership["period_orders_count"] += 1
        membership["period_credit_earned_cents"] += earned
        db.touch(membership)

    if order["pick_batch_id"]:
        svc.maybe_close_batch(order["pick_batch_id"])
    return resp.success(svc.serialize_bag(bag))


@app.route("/mfc/delivery-bags/<bagId>/fail-handoff", methods=["POST"])
def fail_handoff(bagId):
    uid, role = mw.user_context()
    mw.require_role(role, ["Driver"])
    bag = svc.get_bag(bagId)
    order = svc.get_order(bag["order_id"])
    if bag["handoff_status"] != "REFUSED":
        raise errors.err_refusal_required()
    if uid != bag["driver_id"]:
        raise errors.err_unauthorized("acting driver must be the bag's assignee")
    order["status"] = "HANDOFF_FAILED"
    db.touch(order)
    bag["delivery_status"] = "FAILED"
    db.touch(bag)
    return resp.success(svc.serialize_bag(bag))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
