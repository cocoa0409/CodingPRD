"""Subscriptions (§3.8).

The scaffold declares ``GET /produce/subscriptions`` twice — once for the
administrator with home-center/cadence/status filters and once for the
customer-and-administrator with a customer/status filter. One handler serves
both, admitting the union of roles and filters, and a Customer sees only its
own rows.
"""

from flask import Blueprint

import common
import envelope
import params
import store
from common import ApiError
from routes import helpers
from services import subscriptions as subs

bp = Blueprint("subscriptions", __name__)


@bp.post("/produce/subscriptions")
def create():
    actor = helpers.actor()
    helpers.admin(actor)
    payload = params.body()
    params.missing(payload, ["customer_id", "cadence"])
    params.check_enum("cadence", payload.get("cadence"), common.CADENCES)
    customer = helpers.fetch_customer(payload["customer_id"])

    row = store.new_row({
        "customer_id": customer["id"],
        "cadence": payload["cadence"],
        "home_fulfillment_center_id": customer["home_fulfillment_center_id"],
        "serving_cycle_index": 1,
        "skipped_cycle_index": None,
        "skipped_on": None,
        "paused_at": None,
        "resumed_at": None,
        "pause_count": 0,
        "status": "ACTIVE",
        "cancellation_reason": None,
    })
    store.SUBSCRIPTIONS[row["id"]] = row
    return envelope.object_response(store.serialise(row), 201)


@bp.get("/produce/subscriptions")
def list_all():
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    rows = list(store.SUBSCRIPTIONS.values())
    if actor["role"] == common.ROLE_CUSTOMER:
        rows = [r for r in rows if r["customer_id"] == actor["id"]]
    rows = params.query_filter(rows, "customer_id")
    rows = params.query_filter(rows, "home_fulfillment_center_id")
    rows = params.query_filter(rows, "cadence")
    rows = params.query_filter(rows, "status")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/subscriptions/<subscription_id>")
def read(subscription_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    row = helpers.fetch_subscription(subscription_id)
    if actor["role"] == common.ROLE_CUSTOMER and row["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only read its own subscriptions.")
    return envelope.object_response(store.serialise(row))


@bp.get("/produce/subscriptions/<subscription_id>/box-orders")
def list_box_orders(subscription_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    row = helpers.fetch_subscription(subscription_id)
    if actor["role"] == common.ROLE_CUSTOMER and row["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only read its own orders.")
    rows = store.of(store.BOX_ORDERS, subscription_id=subscription_id)
    from services import orders as orders_svc
    for row in rows:
        orders_svc.tick(row)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.post("/produce/subscriptions/<subscription_id>/skip")
def skip(subscription_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    row = helpers.fetch_subscription(subscription_id)
    if actor["role"] == common.ROLE_CUSTOMER and row["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only skip its own subscription.")
    payload = params.body()
    # §2.10: this is one of the two OCC-protected writes.
    helpers.require_version(payload, "expected_subscription_version", row,
                            "Subscription")
    subs.skip(row)
    return envelope.object_response(store.serialise(row))


@bp.post("/produce/subscriptions/<subscription_id>/pause")
def pause(subscription_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    row = helpers.fetch_subscription(subscription_id)
    if actor["role"] == common.ROLE_CUSTOMER and row["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only pause its own subscription.")
    subs.pause(row)
    return envelope.object_response(store.serialise(row))


@bp.post("/produce/subscriptions/<subscription_id>/resume")
def resume(subscription_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    row = helpers.fetch_subscription(subscription_id)
    if actor["role"] == common.ROLE_CUSTOMER and row["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only resume its own subscription.")
    # Resume is named in the validation state rung but is not an OCC write.
    subs.resume(row)
    return envelope.object_response(store.serialise(row))


@bp.post("/produce/subscriptions/<subscription_id>/cancel")
def cancel(subscription_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    row = helpers.fetch_subscription(subscription_id)
    if actor["role"] == common.ROLE_CUSTOMER and row["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only cancel its own subscription.")
    payload = params.body()
    params.check_enum("cancellation_reason", payload.get("cancellation_reason"),
                      common.CANCELLATION_REASONS)
    subs.cancel(row, payload.get("cancellation_reason"))
    return envelope.object_response(store.serialise(row))