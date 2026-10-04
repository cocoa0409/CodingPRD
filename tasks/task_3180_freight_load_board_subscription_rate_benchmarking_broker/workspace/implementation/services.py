import math
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from response import APIError
from util import (
    ANALYTICS_ADDON_CENTS,
    BASE_FUEL_CENTS,
    CONTRIBUTION_MIN,
    CONTRIBUTION_WINDOW_DAYS,
    CREDIT_WINDOW_DAYS,
    DISPUTE_WINDOW_DAYS,
    GRACE_DAYS_AFTER_PERIOD,
    MAX_FSC_PCT,
    OVERAGE_TIER1_RATE_CENTS,
    OVERAGE_TIER2_RATE_CENTS,
    PLAN_BASE_CENTS,
    REFUND_WINDOW_HOURS,
    STEP_CENTS,
    STEP_PCT,
    iso_ms,
    new_id,
    now_dt,
    parse_dt,
)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def new_resource(db, extra_fields):
    now = db.clock
    res = {"id": new_id(), "created_at": iso_ms(now), "updated_at": iso_ms(now), "version": 1}
    res.update(extra_fields)
    return res


def touch(db, res):
    res["updated_at"] = iso_ms(db.clock)
    res["version"] = res.get("version", 1) + 1


def not_found(error_id, name):
    raise APIError(error_id, 404, f"{name} not found")


def get_broker(db, org_id):
    org = db.broker_orgs.get(org_id)
    if org is None:
        not_found("ERR_ORG_NOT_FOUND", "Broker org")
    return org


def get_carrier(db, org_id):
    org = db.carrier_orgs.get(org_id)
    if org is None:
        not_found("ERR_ORG_NOT_FOUND", "Carrier org")
    return org


def get_plan(db, plan_id):
    plan = db.subscription_plans.get(plan_id)
    if plan is None:
        not_found("ERR_PLAN_NOT_FOUND", "Subscription plan")
    return plan


def get_subscription(db, sub_id):
    sub = db.subscriptions.get(sub_id)
    if sub is None:
        not_found("ERR_SUBSCRIPTION_NOT_FOUND", "Subscription")
    return sub


def get_load(db, load_id):
    load = db.load_posts.get(load_id)
    if load is None:
        not_found("ERR_LOAD_POST_NOT_FOUND", "Load post")
    return load


def get_truck(db, truck_id):
    truck = db.truck_posts.get(truck_id)
    if truck is None:
        not_found("ERR_TRUCK_POST_NOT_FOUND", "Truck post")
    return truck


def get_booking(db, booking_id):
    booking = db.bookings.get(booking_id)
    if booking is None:
        not_found("ERR_BOOKING_NOT_FOUND", "Booking")
    return booking


def get_txn(db, txn_id):
    txn = db.rate_transactions.get(txn_id)
    if txn is None:
        not_found("ERR_RATE_TRANSACTION_NOT_FOUND", "Rate transaction")
    return txn


def get_credit_event(db, event_id):
    ev = db.credit_report_events.get(event_id)
    if ev is None:
        not_found("ERR_CREDIT_EVENT_NOT_FOUND", "Credit report event")
    return ev


def get_dispute(db, dispute_id):
    d = db.credit_disputes.get(dispute_id)
    if d is None:
        not_found("ERR_DISPUTE_NOT_FOUND", "Credit dispute")
    return d


def get_alert(db, alert_id):
    a = db.fraud_alerts.get(alert_id)
    if a is None:
        not_found("ERR_FRAUD_ALERT_NOT_FOUND", "Fraud alert")
    return a


def get_verification(db, ver_id):
    v = db.authority_verifications.get(ver_id)
    if v is None:
        not_found("ERR_AUTHORITY_VERIFICATION_NOT_FOUND", "Authority verification")
    return v


# ---------------------------------------------------------------------------
# Lazy transitions & clock-driven state
# ---------------------------------------------------------------------------

def lazy_expire_load(db, load):
    if load["status"] == "OPEN":
        end = parse_dt(load["pickup_window_end"])
        if end is not None and db.clock >= end:
            load["status"] = "EXPIRED"
            touch(db, load)


def lazy_expire_truck(db, truck):
    if truck["status"] == "AVAILABLE":
        until = parse_dt(truck["available_until"])
        if until is not None and db.clock >= until:
            truck["status"] = "EXPIRED"
            touch(db, truck)


def lazy_expire_verification(db, ver, touch_on_change=True):
    if ver["status"] == "VERIFIED":
        covered = ver.get("covered_until")
        covered_dt = parse_dt(covered) if covered else None
        if covered_dt is not None and db.clock >= covered_dt:
            ver["status"] = "EXPIRED"
            if touch_on_change:
                touch(db, ver)


def lazy_suspend_past_due_subscriptions(db):
    for sub in db.subscriptions.values():
        if sub["status"] == "PAST_DUE":
            end = parse_dt(sub["period_end"])
            if end is not None and db.clock >= end + timedelta(days=GRACE_DAYS_AFTER_PERIOD):
                sub["status"] = "SUSPENDED"
                touch(db, sub)


def apply_eager_clock_transitions(db):
    for load in db.load_posts.values():
        lazy_expire_load(db, load)
    for truck in db.truck_posts.values():
        lazy_expire_truck(db, truck)
    for ver in db.authority_verifications.values():
        compute_insurance(db, ver)
        lazy_expire_verification(db, ver, touch_on_change=False)
    lazy_suspend_past_due_subscriptions(db)


# ---------------------------------------------------------------------------
# Credit score computation
# ---------------------------------------------------------------------------

def _avg4(values):
    total = sum(values)
    return float(Decimal(total) / Decimal(len(values)))


def recompute_broker_credit(db, broker):
    now = db.clock
    window_start = now - timedelta(days=CREDIT_WINDOW_DAYS)
    published = []
    dispute_amt = 0
    removed_amt = 0
    included_amt = 0
    dispute_count = 0
    for ev in db.credit_report_events.values():
        if ev["broker_org_id"] != broker["id"]:
            continue
        if ev["status"] == "UNDER_DISPUTE":
            dispute_amt += ev["invoice_amount_cents"]
            dispute_count += 1
        elif ev["status"] == "REMOVED":
            removed_amt += ev["invoice_amount_cents"]
    for ev in db.credit_report_events.values():
        if ev["broker_org_id"] != broker["id"] or ev["status"] != "PUBLISHED":
            continue
        reported = parse_dt(ev["reported_at"])
        if reported is None or not (window_start <= reported <= now):
            continue
        published.append(ev)
        included_amt += ev["invoice_amount_cents"]

    count = len(published)
    broker["credit_event_count"] = count + dispute_count
    broker["included_amount_cents"] = included_amt
    broker["under_dispute_amount_cents"] = dispute_amt
    broker["removed_amount_cents"] = removed_amt

    if count == 0:
        broker["days_to_pay_simple"] = None
        broker["days_to_pay_weighted"] = None
        broker["credit_score"] = 70
        broker["credit_badge"] = "STANDARD"
        return

    simple = Decimal(sum(ev["days_to_pay"] for ev in published)) / Decimal(count)
    weighted_num = sum(Decimal(ev["days_to_pay"]) * Decimal(ev["invoice_amount_cents"]) for ev in published)
    weighted_den = sum(Decimal(ev["invoice_amount_cents"]) for ev in published)
    weighted = weighted_num / weighted_den if weighted_den != 0 else simple

    q = Decimal("0.0001")
    broker["days_to_pay_simple"] = float(simple.quantize(q, rounding=ROUND_HALF_UP))
    broker["days_to_pay_weighted"] = float(weighted.quantize(q, rounding=ROUND_HALF_UP))

    avg = weighted if count >= 5 else simple
    raw = Decimal(100) - max(Decimal(0), avg - Decimal(30)) * Decimal(2)
    confidence = min(Decimal(1), Decimal(count) / Decimal(10))
    score = Decimal(70) + (raw - Decimal(70)) * confidence
    score = score.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    score = max(Decimal(0), min(Decimal(100), score))
    score = int(score)
    broker["credit_score"] = score
    if score >= 80:
        broker["credit_badge"] = "GOLD"
    elif score >= 60:
        broker["credit_badge"] = "STANDARD"
    elif score >= 40:
        broker["credit_badge"] = "WATCH"
    else:
        broker["credit_badge"] = "CRITICAL"


# ---------------------------------------------------------------------------
# Insurance coverage
# ---------------------------------------------------------------------------

def compute_insurance(db, ver):
    windows = []
    for w in ver.get("insurance_windows") or []:
        if not isinstance(w, dict):
            continue
        ef = parse_dt(w.get("effective_from"))
        et = parse_dt(w.get("effective_to"))
        if ef is None or et is None:
            continue
        windows.append((ef, et))
    windows.sort(key=lambda w: (w[0], w[1]))

    if not windows:
        ver["covered_until"] = None
        ver["coverage_gap_detected"] = False
        ver["insurance_ok"] = False
        return

    covered_until = windows[0][1]
    gap = False
    for ef, et in windows[1:]:
        if ef <= covered_until:
            if et > covered_until:
                covered_until = et
        else:
            gap = True
    ver["covered_until"] = iso_ms(covered_until)
    ver["coverage_gap_detected"] = gap
    first_from = windows[0][0]
    ver["insurance_ok"] = (not gap) and (first_from <= db.clock < covered_until)


# ---------------------------------------------------------------------------
# Subscription pricing & counters
# ---------------------------------------------------------------------------

def compute_period_price(sub, plan):
    base = PLAN_BASE_CENTS[plan["code"]]
    overage = max(0, sub["posts_used"] - plan["monthly_posting_allowance"])
    tier1 = min(overage, plan["overage_tier1_limit"])
    tier2 = max(0, overage - plan["overage_tier1_limit"])
    addon = ANALYTICS_ADDON_CENTS[plan["analytics_depth"]]
    return base + tier1 * OVERAGE_TIER1_RATE_CENTS + tier2 * OVERAGE_TIER2_RATE_CENTS + addon


def sub_view(db, sub):
    plan = db.subscription_plans.get(sub["plan_id"])
    if plan is not None:
        sub["period_price_cents"] = compute_period_price(sub, plan)
    return sub


def find_active_subscription(db, *, broker_org_id=None, carrier_org_id=None):
    for sub in db.subscriptions.values():
        if broker_org_id is not None and sub.get("broker_org_id") == broker_org_id:
            return sub
        if carrier_org_id is not None and sub.get("carrier_org_id") == carrier_org_id:
            return sub
    return None


def require_active_subscription(db, *, broker_org_id=None, carrier_org_id=None):
    sub = find_active_subscription(db, broker_org_id=broker_org_id, carrier_org_id=carrier_org_id)
    if sub is None:
        raise APIError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "Organization has no subscription")
    if sub["status"] != "ACTIVE":
        raise APIError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, "Subscription is not ACTIVE")
    return sub


# ---------------------------------------------------------------------------
# Data contribution flag
# ---------------------------------------------------------------------------

def recompute_contribution_flag(db, org, *, is_broker):
    now = db.clock
    window_start = now - timedelta(days=CONTRIBUTION_WINDOW_DAYS)
    count = 0
    for txn in db.rate_transactions.values():
        if txn["status"] != "ACCEPTED":
            continue
        if is_broker and txn.get("reporter_broker_org_id") != org["id"]:
            continue
        if not is_broker and txn.get("reporter_carrier_org_id") != org["id"]:
            continue
        td = parse_dt(txn["transaction_date"])
        if td is None or not (window_start <= td <= now):
            continue
        count += 1
    org["data_contribution_flag"] = count >= CONTRIBUTION_MIN


# ---------------------------------------------------------------------------
# Safety gate (authority + fraud)
# ---------------------------------------------------------------------------

def _has_confirmed_fraud(db, *, broker_org_id=None, carrier_org_id=None):
    for a in db.fraud_alerts.values():
        if a["status"] != "CONFIRMED":
            continue
        if broker_org_id is not None and a.get("target_broker_org_id") == broker_org_id:
            return True
        if carrier_org_id is not None and a.get("target_carrier_org_id") == carrier_org_id:
            return True
    return False


def _verified_authority(db, *, broker_org_id=None, carrier_org_id=None):
    for v in db.authority_verifications.values():
        if broker_org_id is not None and v.get("broker_org_id") != broker_org_id:
            continue
        if carrier_org_id is not None and v.get("carrier_org_id") != carrier_org_id:
            continue
        compute_insurance(db, v)
        lazy_expire_verification(db, v)
        if v["status"] == "VERIFIED":
            return v
    return None


def check_safety_gate(db, *, broker_org_id=None, carrier_org_id=None):
    ver = _verified_authority(db, broker_org_id=broker_org_id, carrier_org_id=carrier_org_id)
    if ver is None:
        raise APIError("ERR_AUTHORITY_NOT_VERIFIED", 409, "Acting org has no VERIFIED authority record")
    if not ver["insurance_ok"]:
        raise APIError("ERR_INSURANCE_NOT_VERIFIED", 409, "Acting org's insurance coverage is not satisfied")
    if _has_confirmed_fraud(db, broker_org_id=broker_org_id, carrier_org_id=carrier_org_id):
        raise APIError("ERR_ORG_HAS_CONFIRMED_FRAUD", 409, "Acting org is the target of a CONFIRMED fraud alert")


# ---------------------------------------------------------------------------
# Suspension cascades
# ---------------------------------------------------------------------------

def _cancel_bookings_for_broker(db, broker_id):
    for booking in db.bookings.values():
        if booking["status"] != "BOOKED":
            continue
        load = db.load_posts.get(booking["load_post_id"])
        if load is None or load["broker_org_id"] != broker_id:
            continue
        booking["status"] = "CANCELLED"
        touch(db, booking)
        truck = db.truck_posts.get(booking["truck_post_id"])
        if truck is not None and truck["status"] == "BOOKED":
            truck["status"] = "AVAILABLE"
            touch(db, truck)


def _cancel_bookings_for_carrier(db, carrier_id):
    for booking in db.bookings.values():
        if booking["status"] != "BOOKED":
            continue
        truck = db.truck_posts.get(booking["truck_post_id"])
        if truck is None or truck["carrier_org_id"] != carrier_id:
            continue
        booking["status"] = "CANCELLED"
        touch(db, booking)
        load = db.load_posts.get(booking["load_post_id"])
        if load is not None and load["status"] == "BOOKED":
            load["status"] = "OPEN"
            load["visibility"] = "LISTED"
            touch(db, load)


def suspend_broker(db, broker, *, fraud=False, credit=False):
    broker["status"] = "SUSPENDED"
    touch(db, broker)
    for load in db.load_posts.values():
        if load["broker_org_id"] != broker["id"]:
            continue
        if load["status"] == "OPEN":
            load["status"] = "WITHDRAWN"
            load["visibility"] = "DELISTED"
            touch(db, load)
        elif load["status"] == "BOOKED":
            load["visibility"] = "DELISTED"
            touch(db, load)
    sub = find_active_subscription(db, broker_org_id=broker["id"])
    if sub is not None and sub["status"] == "ACTIVE":
        sub["status"] = "SUSPENDED"
        touch(db, sub)
    if fraud or credit:
        _cancel_bookings_for_broker(db, broker["id"])
    if fraud:
        for txn in db.rate_transactions.values():
            if txn.get("reporter_broker_org_id") == broker["id"] and txn["status"] == "ACCEPTED":
                txn["status"] = "EXCLUDED"
                touch(db, txn)


def suspend_carrier(db, carrier, *, fraud=False):
    carrier["status"] = "SUSPENDED"
    touch(db, carrier)
    for truck in db.truck_posts.values():
        if truck["carrier_org_id"] == carrier["id"] and truck["status"] == "AVAILABLE":
            truck["status"] = "WITHDRAWN"
            touch(db, truck)
    sub = find_active_subscription(db, carrier_org_id=carrier["id"])
    if sub is not None and sub["status"] == "ACTIVE":
        sub["status"] = "SUSPENDED"
        touch(db, sub)
    if fraud:
        _cancel_bookings_for_carrier(db, carrier["id"])
        for txn in db.rate_transactions.values():
            if txn.get("reporter_carrier_org_id") == carrier["id"] and txn["status"] == "ACCEPTED":
                txn["status"] = "EXCLUDED"
                touch(db, txn)


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

def require_fields(body, fields):
    if not isinstance(body, dict):
        raise APIError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    for f in fields:
        if body.get(f) is None:
            raise APIError("ERR_INVALID_REQUEST", 400, f"Missing required field: {f}")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise APIError("ERR_INVALID_REQUEST", 400, f"Invalid value for {field}")


def require_positive_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise APIError("ERR_INVALID_REQUEST", 400, f"{field} must be a positive integer")


def require_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool):
        raise APIError("ERR_INVALID_REQUEST", 400, f"{field} must be an integer")


def parse_limit_offset():
    from flask import request

    def _parse(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise APIError("ERR_INVALID_REQUEST", 400, f"Invalid {name}")
        return v

    limit = _parse("limit", 10)
    offset = _parse("offset", 0)
    if limit < 1 or limit > 100:
        raise APIError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise APIError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


def sorted_by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))


def org_for_role(db, role, user_id):
    if role == "BrokerAdmin":
        return get_broker(db, user_id), "broker"
    if role == "CarrierAdmin":
        return get_carrier(db, user_id), "carrier"
    return None, None


def check_org_active(org):
    if org["status"] != "ACTIVE":
        raise APIError("ERR_ORG_NOT_ACTIVE", 409, "Organization is not ACTIVE")
