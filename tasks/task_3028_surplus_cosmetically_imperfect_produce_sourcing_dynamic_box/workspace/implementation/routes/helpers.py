"""Route-layer helpers shared by every resource group."""

from flask import request

import auth
import params
import store
from common import ApiError


def actor():
    return auth.authenticate()


def admin(actor_row, allowed=None):
    auth.require_roles(actor_row, allowed or ("PlatformAdmin",))


def fetch(collection, row_id, error_id, label):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id, 404, "No %s exists with the given id." % label)
    return row


def fetch_customer(customer_id):
    return fetch(store.CUSTOMERS, customer_id, "ERR_CUSTOMER_NOT_FOUND", "Customer")


def fetch_center(center_id):
    return fetch(store.FULFILLMENT_CENTERS, center_id,
                 "ERR_FULFILLMENT_CENTER_NOT_FOUND", "FulfillmentCenter")


def fetch_supplier(supplier_id):
    return fetch(store.SUPPLIERS, supplier_id, "ERR_SUPPLIER_NOT_FOUND", "Supplier")


def fetch_lot(lot_id):
    return fetch(store.SUPPLY_LOTS, lot_id, "ERR_SUPPLY_LOT_NOT_FOUND", "SupplyLot")


def fetch_bid(bid_id):
    return fetch(store.SOURCING_BIDS, bid_id, "ERR_BID_NOT_FOUND", "SourcingBid")


def fetch_order(order_id):
    return fetch(store.BOX_ORDERS, order_id, "ERR_BOX_ORDER_NOT_FOUND", "BoxOrder")


def fetch_item(item_id):
    return fetch(store.BOX_BUILD_ITEMS, item_id, "ERR_BUILD_ITEM_NOT_FOUND",
                 "BoxBuildItem")


def fetch_claim(claim_id):
    return fetch(store.QUALITY_CLAIMS, claim_id, "ERR_CLAIM_NOT_FOUND", "QualityClaim")


def fetch_subscription(subscription_id):
    return fetch(store.SUBSCRIPTIONS, subscription_id,
                 "ERR_SUBSCRIPTION_NOT_FOUND", "Subscription")


def list_response(rows, **filters):
    """§2.3: filter, order by creation ascending, paginate, publish the meta."""
    limit, offset = params.pagination_args()
    window = params.paginate(rows, limit, offset)
    return store.serialise_many(window), limit, offset, store.by_created(rows)


def require_version(payload, field, row, label):
    """§2.10: the OCC comparison runs before the from-state test."""
    supplied = payload.get(field)
    if supplied is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "%s is required for this operation." % field)
    try:
        supplied = int(supplied)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "%s must be an integer." % field)
    if supplied != row.get("version"):
        raise ApiError("ERR_STALE_VERSION", 412,
                       "The supplied %s does not match the %s's current version."
                       % (field, label))
    return supplied


def optional_version(payload, field, row, label):
    """A request that supplies the OCC field is still held to it (§2.10)."""
    if payload.get(field) is None:
        return None
    return require_version(payload, field, row, label)


def json_body():
    return params.body()