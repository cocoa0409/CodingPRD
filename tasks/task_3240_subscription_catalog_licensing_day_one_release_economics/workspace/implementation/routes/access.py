"""Entitlement and Purchase."""
from flask import Blueprint, request

from checks import page, query_paging
from db import db
from errors import fail
from request_ctx import (ctx, expect_query, run, want_int, want_str)
from response import ok_array, ok_object
from services import calc
from services.store import access_channels, refresh_subscriber_impact

bp = Blueprint("access", __name__)

ENTITLEMENT_STATUSES = ("ACTIVE", "GRACE", "REVOKED")


def _entitlement(eid):
    row = db.entitlements.get(eid)
    if row is None:
        fail("ERR_ENTRY_NOT_FOUND", "No entitlement exists with id %s." % eid)
    return row


def _purchase(pid):
    row = db.purchases.get(pid)
    if row is None:
        fail("ERR_ENTRY_NOT_FOUND", "No purchase exists with id %s." % pid)
    return row


def _subscriber(sid):
    row = db.subscribers.get(sid)
    if row is None:
        fail("ERR_SUBSCRIBER_NOT_FOUND", "No subscriber exists with id %s." % sid)
    return row


def _title(tid):
    row = db.titles.get(tid)
    if row is None:
        fail("ERR_TITLE_NOT_FOUND", "No title exists with id %s." % tid)
    return row


def _region(code):
    row = db.regions.get(code)
    if row is None:
        fail("ERR_REGION_NOT_FOUND", "No region exists with code %s." % code)
    return row


def _nothing(_c):
    return None


# --------------------------------------------------------------------------
# Entitlement
# --------------------------------------------------------------------------
@bp.route("/catalog/entitlements", methods=["GET"])
def list_entitlements():
    c = ctx(["Subscriber", "CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ("subscription_id", "title_id", "region_code", "entry_id",
                     "status", "limit", "offset"))
    limit, offset = query_paging()
    rows = db.sorted_rows(db.entitlements)
    if c.actor_role == "Subscriber":
        mine = set(r["id"] for r in db.subscriptions.values()
                   if r["subscriber_id"] == c.actor_id)
        rows = [r for r in rows if r["subscription_id"] in mine]
    for key in ("subscription_id", "title_id", "region_code", "entry_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    window, total = page(rows, limit, offset)
    return ok_array([db.public(r) for r in window], limit, offset, total)


@bp.route("/catalog/entitlements/<entitlement_id>", methods=["GET"])
def read_entitlement(entitlement_id):
    c = ctx(["Subscriber", "CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update(
        {"entitlement": _entitlement(entitlement_id)}))
    row = c.extra["entitlement"]
    if c.actor_role == "Subscriber":
        subscription = db.subscriptions.get(row["subscription_id"])
        if subscription is None or subscription["subscriber_id"] != c.actor_id:
            fail("ERR_FORBIDDEN_ROLE",
                 "Subscriber %s may not read another subscriber's entitlement." % c.actor_id)
    return ok_object(db.public(row))


def _revoke_state(c):
    row = c.extra["entitlement"]
    if row["status"] == "REVOKED":
        fail("ERR_ENTITLEMENT_ALREADY_REVOKED",
             "Entitlement %s is already revoked." % row["id"])


@bp.route("/catalog/entitlements/<entitlement_id>/revoke", methods=["POST"])
def revoke_entitlement(entitlement_id):
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update(
        {"entitlement": _entitlement(entitlement_id)}), on_state=_revoke_state)
    row = c.extra["entitlement"]
    row["status"] = "REVOKED"
    db.touch(row)
    entry = db.entries.get(row.get("entry_id"))
    if entry is not None:
        refresh_subscriber_impact(entry)
    return ok_object(db.public(row))


def _restore_state(c):
    row = c.extra["entitlement"]
    subscription = db.subscriptions.get(row["subscription_id"])
    if subscription is not None and subscription["lifecycle_status"] == "CANCELLED":
        fail("ERR_SUBSCRIPTION_TERMINAL",
             "Subscription %s is cancelled." % subscription["id"])
    entry = db.entries.get(row.get("entry_id"))
    readable = False
    if entry is not None:
        if entry["status"] in ("ADDED", "REMOVING"):
            readable = True
        elif entry["release_class"] == "BACK_CATALOG":
            readable = True
        elif row.get("retained_until") is not None and row["retained_until"] > db.clock:
            readable = True
    if not readable:
        fail("ERR_ENTRY_ALREADY_DELISTED",
             "The entitlement's entry is no longer readable by this subscription.")


@bp.route("/catalog/entitlements/<entitlement_id>/restore", methods=["POST"])
def restore_entitlement(entitlement_id):
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update(
        {"entitlement": _entitlement(entitlement_id)}), on_state=_restore_state)
    row = c.extra["entitlement"]
    subscription = db.subscriptions.get(row["subscription_id"])
    tier = db.tiers.get(subscription["tier_code"]) if subscription else None
    row["status"] = "ACTIVE"
    if tier is not None:
        row["access_channels"] = access_channels(tier)
    db.touch(row)
    entry = db.entries.get(row.get("entry_id"))
    if entry is not None:
        refresh_subscriber_impact(entry)
    return ok_object(db.public(row))


# --------------------------------------------------------------------------
# Purchase
# --------------------------------------------------------------------------
def _shape_purchase(c):
    want_str(c, "subscriber_id", required=True)
    want_str(c, "title_id", required=True)
    want_str(c, "entry_id", required=True)
    want_str(c, "region_code", required=True)
    want_int(c, "quantity", lo=1)


def _resolve_purchase_refs(c):
    """Body ids resolve in the order the endpoint's input list declares them."""
    c.extra["subscriber"] = _subscriber(c.get("subscriber_id"))
    c.extra["title"] = _title(c.get("title_id"))
    entry = db.entries.get(c.get("entry_id"))
    if entry is None:
        fail("ERR_ENTRY_NOT_FOUND", "No catalog entry exists with id %s." % c.get("entry_id"))
    c.extra["entry"] = entry
    c.extra["region"] = _region(c.get("region_code"))


def _purchase_eligibility(c):
    entry = c.extra["entry"]
    title = c.extra["title"]
    if entry["title_id"] != title["id"]:
        fail("ERR_ENTRY_TITLE_MISMATCH",
             "Entry %s does not belong to title %s." % (entry["id"], title["id"]))


@bp.route("/catalog/purchases", methods=["POST"])
def create_purchase():
    c = ctx(["Subscriber"], full=True)
    run(c, _shape_purchase, on_resolve=_resolve_purchase_refs,
        on_eligibility=_purchase_eligibility)
    subscriber = c.extra["subscriber"]
    if c.actor_role == "Subscriber" and subscriber["id"] != c.actor_id:
        fail("ERR_FORBIDDEN_ROLE",
             "Subscriber %s may not buy on another subscriber's behalf." % c.actor_id)
    title = c.extra["title"]
    entry = c.extra["entry"]
    region = c.extra["region"]
    quantity = c.int_of("quantity", 1)
    tier = _buyer_tier(subscriber)
    figures = calc.purchase_figures(title, region, tier, entry, subscriber, quantity)
    row = db.new_row()
    row.update({
        "subscriber_id": subscriber["id"],
        "title_id": title["id"],
        "entry_id": entry["id"],
        "quantity": quantity,
        "region_code": region["region_code"],
        "list_price_cents_per_unit": figures["list_price_cents_per_unit"],
        "discount_pct_applied": figures["discount_pct_applied"],
        "wallet_applied_cents": figures["wallet_applied_cents"],
        "wallet_restored_cents": 0,
        "unit_sales_credit_cents": figures["unit_sales_credit_cents"],
        "total_charged_cents": figures["total_charged_cents"],
        "status": "COMPLETED",
    })
    row["created_at_dt"] = db.clock
    db.purchases[row["id"]] = row
    subscriber["wallet_credit_cents"] -= figures["wallet_applied_cents"]
    db.touch(subscriber)
    return ok_object(db.public(row), 201)


DEFAULT_TIER = {"member_discount_pct": 0, "discount_retention_days": 0}


def _buyer_tier(subscriber):
    rows = [r for r in db.subscriptions.values()
            if r["subscriber_id"] == subscriber["id"]]
    if not rows:
        return DEFAULT_TIER
    live = [r for r in rows if r["lifecycle_status"] in ("ACTIVE", "GRACE")]
    pool = live or rows
    pool.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return db.tiers.get(pool[0]["tier_code"]) or DEFAULT_TIER


@bp.route("/catalog/purchases/<purchase_id>", methods=["GET"])
def read_purchase(purchase_id):
    c = ctx(["Subscriber", "CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ())
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update(
        {"purchase": _purchase(purchase_id)}))
    row = c.extra["purchase"]
    if c.actor_role == "Subscriber" and row["subscriber_id"] != c.actor_id:
        fail("ERR_FORBIDDEN_ROLE",
             "Subscriber %s may not read another subscriber's purchase." % c.actor_id)
    return ok_object(db.public(row))


def _reverse_state(c):
    row = c.extra["purchase"]
    if row["status"] == "REFUNDED":
        fail("ERR_PURCHASE_ALREADY_REVERSED",
             "Purchase %s has already been reversed." % row["id"])


@bp.route("/catalog/purchases/<purchase_id>/reverse", methods=["POST"])
def reverse_purchase(purchase_id):
    c = ctx(["CatalogAdmin"], full=True)
    run(c, _nothing, on_resolve=lambda cc: cc.extra.update(
        {"purchase": _purchase(purchase_id)}), on_state=_reverse_state)
    row = c.extra["purchase"]
    restored = int(row.get("wallet_applied_cents", 0))
    row["status"] = "REFUNDED"
    row["wallet_restored_cents"] = restored
    db.touch(row)
    subscriber = db.subscribers.get(row["subscriber_id"])
    if subscriber is not None:
        subscriber["wallet_credit_cents"] += restored
        db.touch(subscriber)
    return ok_object(db.public(row))


@bp.route("/catalog/purchases", methods=["GET"])
def list_purchases():
    c = ctx(["Subscriber", "CatalogAdmin", "CatalogAnalyst"])
    expect_query(c, ("subscriber_id", "title_id", "entry_id", "region_code",
                     "limit", "offset"))
    limit, offset = query_paging()
    rows = db.sorted_rows(db.purchases)
    if c.actor_role == "Subscriber":
        rows = [r for r in rows if r["subscriber_id"] == c.actor_id]
    for key in ("subscriber_id", "title_id", "entry_id", "region_code"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    window, total = page(rows, limit, offset)
    return ok_array([db.public(r) for r in window], limit, offset, total)
