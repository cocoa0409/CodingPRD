"""Box orders and build items (§3.4, §3.5)."""

from flask import Blueprint

import common
import envelope
import params
import store
from common import ApiError
from routes import helpers
from services import builds, orders

bp = Blueprint("boxes", __name__)


@bp.post("/produce/box-orders")
def create():
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    payload = params.body()
    params.missing(payload, ["customer_id", "subscription_id",
                             "serving_cycle_index", "cuisine_preference"])
    customer = helpers.fetch_customer(payload["customer_id"])
    subscription = helpers.fetch_subscription(payload["subscription_id"])
    helpers.fetch_center(customer["home_fulfillment_center_id"])
    params.check_enum("cuisine_preference", payload.get("cuisine_preference"),
                      common.CUISINE_PREFERENCES)
    if subscription["customer_id"] != customer["id"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "The subscription does not belong to the customer.")
    if actor["role"] == common.ROLE_CUSTOMER and actor["id"] != customer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only open an order for its own subscription.")

    row = orders.create_order(
        customer, subscription,
        params.as_int("serving_cycle_index", payload["serving_cycle_index"]),
        payload["cuisine_preference"])
    return envelope.object_response(store.serialise(row), 201)


@bp.get("/produce/box-orders")
def list_all():
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN,
                          common.ROLE_FULFILLMENT_OPERATOR))
    rows = list(store.BOX_ORDERS.values())
    if actor["role"] == common.ROLE_CUSTOMER:
        rows = [r for r in rows if r["customer_id"] == actor["id"]]
    elif actor["role"] == common.ROLE_FULFILLMENT_OPERATOR:
        rows = [r for r in rows if r["fulfillment_center_id"] == actor["id"]]
    rows = params.query_filter(rows, "customer_id")
    rows = params.query_filter(rows, "subscription_id")
    rows = params.query_filter(rows, "fulfillment_center_id")
    rows = params.query_filter(rows, "status")
    for row in rows:
        orders.tick(row)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/box-orders/<order_id>")
def read(order_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN,
                          common.ROLE_FULFILLMENT_OPERATOR))
    row = helpers.fetch_order(order_id)
    if actor["role"] == common.ROLE_CUSTOMER and row["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only read its own orders.")
    orders.tick(row)
    return envelope.object_response(store.serialise(row))


@bp.post("/produce/box-orders/<order_id>/finalize")
def finalize(order_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    order = helpers.fetch_order(order_id)
    customer = helpers.fetch_customer(order["customer_id"])
    if actor["role"] == common.ROLE_CUSTOMER and actor["id"] != customer["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only finalise its own order.")
    payload = params.body()
    # §1.2 / §5: the endpoint declares only the version field, so any other
    # key is a malformed request.
    params.reject_unknown(payload, ("expected_box_order_version",))
    # §2.10: the second OCC-protected write; the comparison runs before the
    # from-state test within the state rung.
    helpers.require_version(payload, "expected_box_order_version", order, "BoxOrder")
    orders.finalize(order, customer)
    return envelope.object_response(store.serialise(order))


@bp.post("/produce/box-orders/<order_id>/build")
def build(order_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_FULFILLMENT_OPERATOR,
                          common.ROLE_PLATFORM_ADMIN))
    order = helpers.fetch_order(order_id)
    if actor["role"] == common.ROLE_FULFILLMENT_OPERATOR and \
            order["fulfillment_center_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "The order is outside the acting center's lane.")
    customer = helpers.fetch_customer(order["customer_id"])
    payload = params.body()
    if payload.get("line_plan") is not None and not isinstance(payload["line_plan"], list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "line_plan must be an array.")
    orders.tick(order)
    # The version comparison is delegated to the service so it can sit at its
    # rung in the ladder, after the from-state test and after allergen exclusion.
    orders.build(order, customer, payload.get("line_plan"),
                 payload.get("expected_box_order_version"))
    return envelope.object_response(store.serialise(order))


@bp.post("/produce/box-orders/<order_id>/reroute-back")
def reroute_back(order_id):
    actor = helpers.actor()
    helpers.admin(actor)
    order = helpers.fetch_order(order_id)
    payload = params.body()
    helpers.require_version(payload, "expected_box_order_version", order, "BoxOrder")
    orders.reroute_back(order)
    return envelope.object_response(store.serialise(order))


@bp.post("/produce/box-orders/<order_id>/crash-out")
def crash_out(order_id):
    actor = helpers.actor()
    helpers.admin(actor)
    order = helpers.fetch_order(order_id)
    payload = params.body()
    helpers.require_version(payload, "expected_box_order_version", order, "BoxOrder")
    orders.crash_out(order)
    return envelope.object_response(store.serialise(order))


@bp.get("/produce/box-orders/<order_id>/items")
def list_items(order_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN,
                          common.ROLE_FULFILLMENT_OPERATOR))
    order = helpers.fetch_order(order_id)
    if actor["role"] == common.ROLE_CUSTOMER and order["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only read its own orders.")
    rows = builds.items_of(order_id)
    rows = params.query_filter(rows, "status")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.post("/produce/box-orders/<order_id>/pack")
def pack(order_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_FULFILLMENT_OPERATOR,
                          common.ROLE_PLATFORM_ADMIN))
    order = helpers.fetch_order(order_id)
    if actor["role"] == common.ROLE_FULFILLMENT_OPERATOR and \
            order["fulfillment_center_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "The order is outside the acting center's lane.")
    payload = params.body()
    helpers.require_version(payload, "expected_box_order_version", order, "BoxOrder")
    orders.pack(order)
    return envelope.object_response(store.serialise(order))


@bp.get("/produce/box-orders/<order_id>/cold-chain-packs")
def list_packs(order_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN,
                          common.ROLE_FULFILLMENT_OPERATOR))
    order = helpers.fetch_order(order_id)
    if actor["role"] == common.ROLE_CUSTOMER and order["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only read its own orders.")
    rows = store.of(store.COLD_CHAIN_PACKS, box_order_id=order_id)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/box-build-items/<item_id>")
def read_item(item_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN,
                          common.ROLE_FULFILLMENT_OPERATOR))
    item = helpers.fetch_item(item_id)
    order = store.BOX_ORDERS.get(item["box_order_id"])
    if actor["role"] == common.ROLE_CUSTOMER and order is not None and \
            order["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only read its own orders.")
    return envelope.object_response(store.serialise(item))


@bp.get("/produce/box-build-items/<item_id>/quality-claims")
def list_item_claims(item_id):
    actor = helpers.actor()
    helpers.admin(actor)
    helpers.fetch_item(item_id)
    rows = store.of(store.QUALITY_CLAIMS, box_build_item_id=item_id)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))