"""Fund subscriptions: listing, reading and equity pay-ins."""

from flask import Blueprint, request

import errors
import response
import state
import store
import validate

bp = Blueprint("subscriptions", __name__)

READ_SUB = ("Investor", "Underwriter", "AssetManager", "PlatformAdmin")


@bp.get("/subscriptions")
def list_subscriptions():
    role, user_id = validate.authenticate(request)
    validate.require_role(role, READ_SUB)
    filters = {
        "fund_id": request.args.get("fund_id"),
        "investor_id": request.args.get("investor_id"),
        "status": request.args.get("status"),
    }
    rows = store.listing(store.subscriptions, filters)
    # An entity-backed actor sees only its own rows rather than being rejected.
    if role == "Investor":
        rows = [s for s in rows if s["investor_id"] == user_id]
    limit, offset = response.pagination_args(request)
    window, meta = response.paginate(rows, limit, offset)
    return response.array([store.public(s) for s in window], 200, meta)


@bp.get("/subscriptions/<subscription_id>")
def read_subscription(subscription_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, READ_SUB)
    subscription = validate.get_subscription(subscription_id)
    validate.scope_subscription(role, user_id, subscription)
    state.recompute_subscription(subscription_id)
    return response.ok(store.public(subscription), 200)


@bp.post("/subscriptions/<subscription_id>/payins")
def record_payin(subscription_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, ("Investor", "PlatformAdmin"))
    payload = validate.body(request)
    amount = validate.non_negative(validate.as_int(payload, "amount_cents"), "amount_cents")

    subscription = validate.get_subscription(subscription_id)
    validate.scope_subscription(role, user_id, subscription)

    if subscription["status"] == "DEFAULTED":
        errors.fail(errors.ERR_SUBSCRIPTION_TERMINAL, "A defaulted subscription is terminal.")

    fund = validate.get_fund(subscription["fund_id"])
    if not state.fund_allows_payin(fund):
        errors.fail(errors.ERR_FUND_NOT_FORMING,
                    "The fund has not reached CLOSING or CLOSED, or has wound down.")

    paid_in = int(subscription["paid_in_cents"]) + amount
    committed = int(subscription["committed_cents"])
    if paid_in > committed:
        errors.fail(errors.ERR_OVERPAYMENT, "The pay-in would exceed the commitment.")

    subscription["paid_in_cents"] = paid_in
    if committed > 0 and paid_in == committed:
        subscription["status"] = "FULLY_FUNDED"
    elif paid_in > 0:
        subscription["status"] = "PARTIALLY_FUNDED"
    elif subscription["status"] == "PLEDGED" and fund["status"] == "CLOSED":
        subscription["status"] = "SUBSCRIBED"
    store.touch(subscription)

    state.recompute_subscription(subscription_id)
    state.recompute_investor(subscription["investor_id"])
    state.recompute_fund(subscription["fund_id"])
    return response.ok(store.public(subscription), 200)
