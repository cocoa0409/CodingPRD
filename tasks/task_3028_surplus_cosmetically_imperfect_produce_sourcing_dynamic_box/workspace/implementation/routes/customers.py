"""Customers (§3.1, §2.6)."""

from flask import Blueprint

import common
import envelope
import params
import store
from routes import helpers

bp = Blueprint("customers", __name__)


@bp.post("/produce/customers/register")
def register():
    actor = helpers.actor()
    helpers.admin(actor, ("Anonymous", "PlatformAdmin"))
    payload = params.body()
    params.missing(payload, ["email", "full_name", "service_region"])
    params.check_enum("service_region", payload.get("service_region"), common.REGIONS)

    for existing in store.CUSTOMERS.values():
        if existing["email"] == payload["email"]:
            from common import ApiError

            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "email is unique across all Customers.")

    explicit_center_id = payload.get("home_fulfillment_center_id")
    if explicit_center_id is not None:
        helpers.fetch_center(explicit_center_id)

    customer = store.new_row({
        "email": payload["email"],
        "full_name": payload["full_name"],
        "service_region": payload["service_region"],
        "home_fulfillment_center_id": explicit_center_id,
        "dietary_allergy_codes": params.as_string_list(
            "dietary_allergy_codes", payload.get("dietary_allergy_codes")),
        "grandfathered_service_fee": bool(
            payload.get("grandfathered_service_fee", False)),
        "_home_center_explicit": explicit_center_id is not None,
    })

    if explicit_center_id is None:
        # §2.6: the regional assignment runs before the row is committed, so a
        # region with no active center refuses the registration outright rather
        # than storing a half-built subscriber with no home center.
        from services import centers

        centers.assign_home_center(customer)

    store.CUSTOMERS[customer["id"]] = customer
    return envelope.object_response(store.serialise(customer), 201)


@bp.get("/produce/customers/<customer_id>")
def read(customer_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    customer = helpers.fetch_customer(customer_id)
    if actor["role"] == common.ROLE_CUSTOMER and actor["id"] != customer["id"]:
        from common import ApiError

        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only read its own record.")
    return envelope.object_response(store.serialise(customer))


@bp.get("/produce/customers")
def list_all():
    actor = helpers.actor()
    helpers.admin(actor)
    rows = list(store.CUSTOMERS.values())
    rows = params.query_filter(rows, "home_fulfillment_center_id")
    rows = params.query_filter(rows, "service_region")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/customers/<customer_id>/box-orders")
def list_box_orders(customer_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    customer = helpers.fetch_customer(customer_id)
    if actor["role"] == common.ROLE_CUSTOMER and actor["id"] != customer["id"]:
        from common import ApiError

        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only read its own orders.")
    rows = store.of(store.BOX_ORDERS, customer_id=customer_id)
    from services import orders as orders_svc
    for row in rows:
        orders_svc.tick(row)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/customers/<customer_id>/subscriptions")
def list_subscriptions(customer_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    customer = helpers.fetch_customer(customer_id)
    if actor["role"] == common.ROLE_CUSTOMER and actor["id"] != customer["id"]:
        from common import ApiError

        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only read its own subscriptions.")
    rows = store.of(store.SUBSCRIPTIONS, customer_id=customer_id)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))