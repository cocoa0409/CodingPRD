"""Subscriptions, billing cycles, invoices, and dunning (PRD §3.7)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import serialize
import store
from helpers import (auth, bad_request, body, envelope, err, list_response,
                     need_enum, need_int, need_str, no_undeclared, not_found)

bp = Blueprint("subscriptions", __name__)

FREQUENCIES = {"MONTHLY", "QUARTERLY"}
SUBSCRIBER_DISCOUNT = Decimal("0.90")   # 10% off, applied per unit first
SHIPPING_TIER1_MAX = 3
SHIPPING_TIER1_CENTS = 495
SHIPPING_TIER2_MAX = 10
SHIPPING_TIER2_CENTS = 895
MAX_INVOICE_ATTEMPTS = 3


@bp.route("/mint/subscriptions", methods=["POST"])
def enroll():
    uid, _ = auth("Collector")
    b = body()
    # Body FK resolution, then the rung-5 gate: product must be ON_SALE.
    product = None
    if isinstance(b.get("product_id"), str):
        product = store.db["products"].get(b["product_id"])
        if product is None:
            err("ERR_UNKNOWN_PRODUCT", 422, "Unknown product_id")
    if product is not None and product["status"] != "ON_SALE":
        err("ERR_PRODUCT_NOT_ORDERABLE", 422,
            "Subscriptions require an ON_SALE product")
    # Rung 9: shape, then quantity, then duplicate, then eligibility.
    no_undeclared(b, {"product_id", "units_per_cycle", "frequency"})
    if product is None:
        pid = need_str(b, "product_id")
        product = store.db["products"].get(pid)
        if product is None:
            err("ERR_UNKNOWN_PRODUCT", 422, "Unknown product_id")
        if product["status"] != "ON_SALE":
            err("ERR_PRODUCT_NOT_ORDERABLE", 422,
                "Subscriptions require an ON_SALE product")
    units = need_int(b, "units_per_cycle")
    if units < 1:
        err("ERR_QUANTITY_INVALID", 400, "units_per_cycle must be at least 1")
    frequency = need_enum(b, "frequency", FREQUENCIES)
    if any(s["collector_id"] == uid and s["product_id"] == product["id"]
           and s["status"] in ("ACTIVE", "DUNNING")
           for s in store.db["subscriptions"].values()):
        err("ERR_DUPLICATE_SUBSCRIPTION", 409,
            "A live subscription already exists for this product")
    if not product["subscription_eligible"]:
        err("ERR_SUBSCRIPTION_NOT_ELIGIBLE_PRODUCT", 422,
            "Product is not subscription eligible")
    s = store.mint_entity({
        "collector_id": uid,
        "product_id": product["id"],
        "units_per_cycle": units,
        "frequency": frequency,
        "status": "ACTIVE",
        "next_billing_date": store.now_dt().date().isoformat(),
        "cycles_billed": 0,
    })
    store.db["subscriptions"][s["id"]] = s
    return envelope(serialize.subscription(s), status=201)


@bp.route("/mint/subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = auth("Collector", "ProgramManager", "PlatformAdmin")
    items = list(store.db["subscriptions"].values())
    if role == "Collector":
        filt = request.args.get("collector_id")
        if filt is not None and filt != uid:
            err("ERR_FORBIDDEN_OWNERSHIP", 403,
                "Collector list filter must name the caller's own collector_id")
        items = [s for s in items if s["collector_id"] == uid]
    else:
        filt = request.args.get("collector_id")
        if filt is not None:
            items = [s for s in items if s["collector_id"] == filt]
    for param in ("product_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s[param] == v]
    return list_response(items, serialize.subscription)


def _get_subscription_or_404(sid):
    s = store.db["subscriptions"].get(sid)
    if s is None:
        not_found("Subscription not found")
    return s


def _own_subscription_or_forbid(s, uid):
    if s["collector_id"] != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", 403,
            "Subscription belongs to another collector")


@bp.route("/mint/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    uid, role = auth("Collector", "ProgramManager", "PlatformAdmin")
    s = _get_subscription_or_404(sid)
    if role == "Collector":
        _own_subscription_or_forbid(s, uid)
    return envelope(serialize.subscription(s))


@bp.route("/mint/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    uid, _ = auth("Collector")
    s = _get_subscription_or_404(sid)
    _own_subscription_or_forbid(s, uid)
    if s["status"] not in ("ACTIVE", "DUNNING"):
        err("ERR_INVALID_STATE_TRANSITION", 422,
            "Only an ACTIVE or DUNNING subscription may be cancelled")
    no_undeclared(body(), set())
    s["status"] = "CANCELLED"
    store.bump(s)
    return envelope(serialize.subscription(s))


@bp.route("/mint/subscriptions/<sid>/billing-cycle", methods=["POST"])
def billing_cycle(sid):
    auth("PlatformAdmin")
    s = _get_subscription_or_404(sid)
    b = body()
    # Rung 5: state precondition, then the OCC version check.
    if s["status"] != "ACTIVE":
        err("ERR_SUBSCRIPTION_NOT_ACTIVE", 422,
            "Billing cycles may run only against ACTIVE subscriptions")
    expected = b.get("expected_subscription_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool) \
                or expected != s["version"]:
            err("ERR_STALE_VERSION", 412,
                "expected_subscription_version does not match the current version")
    # Rung 8: the logical clock date must have reached next_billing_date.
    due = store.parse_iso_date(s["next_billing_date"])
    if store.now_dt().date() < due:
        err("ERR_BILLING_NOT_DUE", 422, "The billing cycle is not yet due")
    # Rung 9: shape.
    no_undeclared(b, {"expected_subscription_version"})
    if expected is None:
        bad_request("Missing required field: expected_subscription_version")
    # Price the cycle: per-unit 10% discount rounded half-up to whole cents
    # BEFORE multiplying by units; then the shipping tier is added.
    product = store.db["products"][s["product_id"]]
    unit_net = int((Decimal(product["price_cents"]) * SUBSCRIBER_DISCOUNT).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    if s["units_per_cycle"] <= SHIPPING_TIER1_MAX:
        shipping = SHIPPING_TIER1_CENTS
    elif s["units_per_cycle"] <= SHIPPING_TIER2_MAX:
        shipping = SHIPPING_TIER2_CENTS
    else:
        shipping = 0
    inv = store.mint_entity({
        "subscription_id": s["id"],
        "period_index": s["cycles_billed"] + 1,
        "amount_cents": unit_net * s["units_per_cycle"] + shipping,
        "attempts": 0,
        "status": "PENDING",
    })
    store.db["invoices"][inv["id"]] = inv
    # Advance the schedule by frequency and count the cycle.
    months = 1 if s["frequency"] == "MONTHLY" else 3
    s["next_billing_date"] = store.add_months(due, months).isoformat()
    s["cycles_billed"] += 1
    store.bump(s)
    return envelope(serialize.invoice(inv), status=201)


@bp.route("/mint/subscriptions/<sid>/invoices", methods=["GET"])
def list_invoices(sid):
    uid, role = auth("Collector", "ProgramManager", "PlatformAdmin")
    s = _get_subscription_or_404(sid)
    if role == "Collector":
        _own_subscription_or_forbid(s, uid)
    items = [i for i in store.db["invoices"].values()
             if i["subscription_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return list_response(items, serialize.invoice)


@bp.route("/mint/subscription-invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    uid, _ = auth("Collector")
    inv = store.db["invoices"].get(iid)
    if inv is None:
        not_found("Subscription invoice not found")
    sub = store.db["subscriptions"].get(inv["subscription_id"])
    if sub is None or sub["collector_id"] != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", 403,
            "Invoice belongs to another collector's subscription")
    if inv["status"] == "PENDING":
        pass
    elif inv["status"] == "FAILED" and inv["attempts"] < MAX_INVOICE_ATTEMPTS:
        pass
    else:
        err("ERR_INVOICE_NOT_PAYABLE", 422,
            "Invoice is not payable in its current state")
    b = body()
    no_undeclared(b, {"outcome"})
    outcome = need_enum(b, "outcome", {"SUCCEEDED", "FAILED"})
    # Every attempt, success or failure, increments attempts.
    inv["attempts"] += 1
    if outcome == "SUCCEEDED":
        inv["status"] = "PAID"
        if sub["status"] == "DUNNING":
            sub["status"] = "ACTIVE"
            store.bump(sub)
    else:
        if inv["attempts"] >= MAX_INVOICE_ATTEMPTS:
            # The third recorded failure writes the invoice off and cancels
            # the subscription for nonpayment.
            inv["status"] = "WRITTEN_OFF"
            sub["status"] = "CANCELLED_NONPAYMENT"
            store.bump(sub)
        else:
            inv["status"] = "FAILED"
            if sub["status"] == "ACTIVE":
                sub["status"] = "DUNNING"
                store.bump(sub)
    store.bump(inv)
    return envelope(serialize.invoice(inv))
