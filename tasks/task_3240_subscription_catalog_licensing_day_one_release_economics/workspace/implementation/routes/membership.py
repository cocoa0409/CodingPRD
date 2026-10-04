"""Subscriber, Subscription, EngagementEvent."""
from flask import Blueprint, request

from checks import page, query_paging
from clock import add_months, q4
from db import db
from errors import fail
from request_ctx import (ctx, expect_query, run, want_int, want_num, want_str)
from response import ok_array, ok_object
from services import calc
from services.store import (cascade_cancel, entitlements_of_subscription,
                            refresh_tier_counts)

bp = Blueprint("membership", __name__)

TIER_CODES = ("ESSENTIAL", "PREMIUM", "ULTIMATE")
PERIODS = ("MONTHLY", "ANNUAL")
CHANNELS = ("CONSOLE", "PC", "CLOUD", "ONLINE_PLAY")
TIER_ORDER = {"ESSENTIAL": 0, "PREMIUM": 1, "ULTIMATE": 2}


def _region(code):
    row = db.regions.get(code)
    if row is None:
        fail("ERR_REGION_NOT_FOUND", "No region exists with code %s." % code)
    return row


def _subscriber(sid):
    row = db.subscribers.get(sid)
    if row is None:
        fail("ERR_SUBSCRIBER_NOT_FOUND", "No subscriber exists with id %s." % sid)
    return row


def _tier(code):
    row = db.tiers.get(code)
    if row is None:
        fail("ERR_TIER_NOT_FOUND", "No subscription tier exists with code %s." % code)
    return row


def _subscription(sid):
    row = db.subscriptions.get(sid)
    if row is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND", "No subscription exists with id %s." % sid)
    return row


def _title(tid):
    row = db.titles.get(tid)
    if row is None:
        fail("ERR_TITLE_NOT_FOUND", "No title exists with id %s." % tid)
    return row


def _own_subscriber(row, actor_id, actor_role):
    if actor_role == "Subscriber" and row["id"] != actor_id:
        fail("ERR_FORBIDDEN_ROLE",
             "Subscriber %s may not read another subscriber's account." % actor_id)


def _own_subscription(row, actor_id, actor_role):
    if actor_role == "Subscriber" and row["subscriber_id"] != actor_id:
        fail("ERR_FORBIDDEN_ROLE",
             "Subscriber %s may not act on another subscriber's subscription." % actor_id)


def _nothing(_c):
    return None


# --------------------------------------------------------------------------
# Subscriber
# --------------------------------------------------------------------------
@bp.route("/catalog/subscribers", methods=["POST"])
def create_subscriber():
    c = ctx(["Anonymous", "CatalogAdmin"], full=True)
    run(c, _shape_subscriber, on_resolve=_resolve_subscriber_region,
        on_eligibility=_unique_email)
    region = c.extra["region"]
    row = db.new_row()
    row.update({
        "email": c.get("email"),
        "display_name": c.get("display_name"),
        "home_region_code": region["region_code"],
        "status": "ACTIVE",
        "wallet_credit_cents": c.int_of("wallet_credit_cents", 0),
    })
    db.subscribers[row["id"]] = row
    return ok_object(db.public(row), 201)


def _shape_subscriber(c):
    want_str(c, "email", required=True)
    want_str(c, "display_name", required=True)
    want_str(c, "home_region_code", required=True)
    want_int(c, "wallet_credit_cents", lo=0)


def _resolve_subscriber_region(c):
    c.extra["region"] = _region(c.get("home_region_code"))


def _unique_email(c):
    email = c.get("email")
    for row in db.subscribers.values():
        if row["email"] == email:
            fail("ERR_INVALID_REQUEST", "Email %s is already registered." % email)


@bp.route("/catalog/subscribers/<subscriber_id>", methods=["GET"])
def read_subscriber(subscriber_id):
    c = ctx(["Subscriber", "CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update(
        {"subscriber": _subscriber(subscriber_id)}))
    row = c.extra["subscriber"]
    _own_subscriber(row, c.actor_id, c.actor_role)
    return ok_object(db.public(row))


@bp.route("/catalog/subscribers", methods=["GET"])
def list_subscribers():
    c = ctx(["CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ("home_region_code", "limit", "offset"))
    limit, offset = query_paging()
    rows = db.sorted_rows(db.subscribers)
    region = request.args.get("home_region_code")
    if region is not None:
        rows = [r for r in rows if r["home_region_code"] == region]
    window, total = page(rows, limit, offset)
    return ok_array([db.public(r) for r in window], limit, offset, total)


# --------------------------------------------------------------------------
# Subscription
# --------------------------------------------------------------------------
def _shape_subscription(c):
    want_str(c, "subscriber_id", required=True)
    want_str(c, "tier_code", allowed=TIER_CODES, required=True)
    want_str(c, "billing_period", allowed=PERIODS, required=True)
    want_int(c, "prepay_amount_cents", lo=0)


def _resolve_subscription_refs(c):
    subscriber = _subscriber(c.get("subscriber_id"))
    c.extra["subscriber"] = subscriber
    c.extra["tier"] = _tier(c.get("tier_code"))
    c.extra["region"] = _region(subscriber["home_region_code"])


def _subscription_eligibility(c):
    tier = c.extra["tier"]
    region = c.extra["region"]
    if TIER_ORDER[tier["tier_code"]] < TIER_ORDER[region["catalog_tier_floor"]]:
        fail("ERR_TIER_UNSUPPORTED_IN_REGION",
             "Tier %s is below the floor of region %s."
             % (tier["tier_code"], region["region_code"]))


def _subscription_fiscal(c):
    tier = c.extra["tier"]
    prepay = c.int_of("prepay_amount_cents", 0)
    credit = float(tier["annual_prepay_credit_ratio"]) * prepay
    if credit > prepay:
        fail("ERR_PREPAY_CREDIT_CAP_EXCEEDED",
             "The annual prepay credit would exceed the amount collected.")


@bp.route("/catalog/subscriptions", methods=["POST"])
def create_subscription():
    c = ctx(["Subscriber", "CatalogAdmin"], full=True)
    run(c, _shape_subscription, on_resolve=_resolve_subscription_refs,
        on_eligibility=_subscription_eligibility, on_fiscal=_subscription_fiscal)
    subscriber = c.extra["subscriber"]
    tier = c.extra["tier"]
    region = c.extra["region"]
    _own_subscriber(subscriber, c.actor_id, c.actor_role)
    period = c.get("billing_period")
    row = db.new_row()
    row.update({
        "subscriber_id": subscriber["id"],
        "tier_code": tier["tier_code"],
        "billing_period": period,
        "prepay_amount_cents": c.int_of("prepay_amount_cents", 0),
        "unpaid_months": 1 if period == "MONTHLY" else 0,
        "monthly_bill_cents": calc.f2(
            calc.regional_monthly_price_cents(tier, region)),
        "monthly_engaged_hours_avg": 0.0,
        "engagement_score": 0.0,
        "billing_status": "PENDING",
        "lifecycle_status": "ACTIVE",
        "cancellation_reason": None,
    })
    row["created_at_dt"] = db.clock
    db.subscriptions[row["id"]] = row
    refresh_tier_counts()
    return ok_object(db.public(row), 201)


@bp.route("/catalog/subscriptions/<subscription_id>", methods=["GET"])
def read_subscription(subscription_id):
    c = ctx(["Subscriber", "CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update(
        {"subscription": _subscription(subscription_id)}))
    row = c.extra["subscription"]
    _own_subscription(row, c.actor_id, c.actor_role)
    return ok_object(db.public(row))


@bp.route("/catalog/subscriptions", methods=["GET"])
def list_subscriptions():
    c = ctx(["CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ("subscriber_id", "tier_code", "lifecycle_status", "limit", "offset"))
    limit, offset = query_paging()
    rows = db.sorted_rows(db.subscriptions)
    for key in ("subscriber_id", "tier_code", "lifecycle_status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    window, total = page(rows, limit, offset)
    return ok_array([db.public(r) for r in window], limit, offset, total)


def _pay_state(c):
    row = c.extra["subscription"]
    if row["lifecycle_status"] == "CANCELLED":
        fail("ERR_SUBSCRIPTION_TERMINAL",
             "Subscription %s is cancelled." % row["id"])
    if row["unpaid_months"] <= 0:
        fail("ERR_NO_UNPAID_MONTHS",
             "Subscription %s has nothing outstanding to settle." % row["id"])


@bp.route("/catalog/subscriptions/<subscription_id>/pay", methods=["POST"])
def pay_subscription(subscription_id):
    c = ctx(["Subscriber"], full=True)
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update(
        {"subscription": _subscription(subscription_id)}), on_state=_pay_state)
    row = c.extra["subscription"]
    _own_subscription(row, c.actor_id, c.actor_role)
    row["unpaid_months"] -= 1
    row["billing_status"] = "PAID"
    db.touch(row)
    if row["unpaid_months"] == 0:
        subscriber = db.subscribers.get(row["subscriber_id"])
        if subscriber is not None and subscriber["status"] == "ACTIVE":
            row["lifecycle_status"] = "ACTIVE"
            db.touch(row)
            for ent in entitlements_of_subscription(row["id"]):
                if ent["status"] == "GRACE":
                    ent["status"] = "ACTIVE"
                    db.touch(ent)
    refresh_tier_counts()
    return ok_object(db.public(row))


def _cancel_state(c):
    row = c.extra["subscription"]
    if row["lifecycle_status"] == "CANCELLED":
        fail("ERR_SUBSCRIPTION_TERMINAL",
             "Subscription %s is already cancelled." % row["id"])


@bp.route("/catalog/subscriptions/<subscription_id>/cancel", methods=["POST"])
def cancel_subscription(subscription_id):
    c = ctx(["Subscriber"], full=True)
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update(
        {"subscription": _subscription(subscription_id)}), on_state=_cancel_state)
    row = c.extra["subscription"]
    _own_subscription(row, c.actor_id, c.actor_role)
    row["lifecycle_status"] = "CANCELLED"
    row["cancellation_reason"] = "USER_INITIATED"
    db.touch(row)
    cascade_cancel(row, db.clock)
    return ok_object(db.public(row))


# --------------------------------------------------------------------------
# EngagementEvent
# --------------------------------------------------------------------------
def _shape_event(c):
    want_str(c, "title_id", required=True)
    want_num(c, "session_hours", lo=0, required=True)
    want_str(c, "channel", allowed=CHANNELS, required=True)
    want_num(c, "engagement_multiplier", lo=0, required=True)


def _resolve_event_refs(c):
    row = c.extra["subscription"]
    c.extra["title"] = _title(c.get("title_id"))
    if row["lifecycle_status"] == "CANCELLED":
        fail("ERR_SUBSCRIPTION_TERMINAL",
             "Subscription %s is cancelled." % row["id"])


def _event_fiscal(c):
    if not c.get("engagement_multiplier") > 0:
        fail("ERR_INVALID_REQUEST", "engagement_multiplier must be greater than zero.")


@bp.route("/catalog/subscriptions/<subscription_id>/engagement-events", methods=["POST"])
def create_event(subscription_id):
    c = ctx(["Subscriber"], full=True)
    run(c, _shape_event, on_resolve=lambda cc: cc.extra.update(
        {"subscription": _subscription(subscription_id)}),
        on_eligibility=_resolve_event_refs, on_fiscal=_event_fiscal)
    row = c.extra["subscription"]
    _own_subscription(row, c.actor_id, c.actor_role)
    event = db.new_row(full=False)
    event.update({
        "subscription_id": row["id"],
        "title_id": c.extra["title"]["id"],
        "session_hours": c.get("session_hours"),
        "channel": c.get("channel"),
        "engagement_multiplier": c.get("engagement_multiplier"),
        "normalized_hours": q4(float(c.get("session_hours"))
                               * float(c.get("engagement_multiplier"))),
    })
    event["created_at_dt"] = db.clock
    db.events[event["id"]] = event
    avg = calc.monthly_engaged_hours_avg(row["id"], db.clock)
    row["monthly_engaged_hours_avg"] = float(avg)
    row["engagement_score"] = float(calc.engagement_score(row["id"], db.clock))
    db.touch(row)
    return ok_object(db.public(event), 201)


@bp.route("/catalog/engagement-events/<event_id>", methods=["GET"])
def read_event(event_id):
    c = ctx(["Subscriber", "CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update({"event": _get_event(event_id)}))
    event = c.extra["event"]
    if c.actor_role == "Subscriber":
        subscription = db.subscriptions.get(event["subscription_id"])
        if subscription is None or subscription["subscriber_id"] != c.actor_id:
            fail("ERR_FORBIDDEN_ROLE",
                 "Subscriber %s may not read another subscriber's event." % c.actor_id)
    return ok_object(db.public(event))


def _get_event(event_id):
    row = db.events.get(event_id)
    if row is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND",
             "No engagement event exists with id %s." % event_id)
    return row


@bp.route("/catalog/engagement-events", methods=["GET"])
def list_events():
    c = ctx(["CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ("subscription_id", "title_id", "limit", "offset"))
    limit, offset = query_paging()
    rows = db.sorted_rows(db.events)
    for key in ("subscription_id", "title_id"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    window, total = page(rows, limit, offset)
    return ok_array([db.public(r) for r in window], limit, offset, total)
