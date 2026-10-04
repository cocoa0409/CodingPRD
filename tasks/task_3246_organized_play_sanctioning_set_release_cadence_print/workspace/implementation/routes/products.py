"""Collector product configurations and distributor allocation orders.

  POST /op/product-configurations                   define a configuration
  GET  /op/product-configurations                   list configurations
  GET  /op/product-configurations/{id}              retrieve one
  POST /op/product-configurations/{id}/transition   INCREASE_REPRINT_RUN
  POST /op/allocation-orders                        place an order
  GET  /op/allocation-orders                        list orders
  GET  /op/allocation-orders/{id}                   retrieve one
  POST /op/allocation-orders/{id}/transition        APPROVE / FULFILL_PARTIAL / DENY
"""

from flask import Blueprint, request

import db as store
import models
import response as envelope
from errors import fail
from middleware import (
    ROLE_OPS_ADMIN, ROLE_DISTRIBUTOR, ROLE_STORE_ORGANIZER,
    STRING, INTEGER,
    require_role, check_body, check_query_enums, require_action,
)

bp = Blueprint("products", __name__)

CONFIGURATION_KINDS = ("DRAFT_BOOSTER", "COLLECTOR_BOOSTER", "BUNDLE")
ORDER_STATUSES = ("PENDING", "APPROVED", "DENIED", "PARTIALLY_FULFILLED")
CONFIG_ACTIONS = ("INCREASE_REPRINT_RUN",)
ORDER_ACTIONS = ("APPROVE", "FULFILL_PARTIAL", "DENY")


# --------------------------------------------------------------------------
# Product configurations
# --------------------------------------------------------------------------

@bp.route("/op/product-configurations", methods=["POST"])
def create_configuration():
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("set_release_id", "configuration_kind", "pack_count", "print_run_units"),
        types={
            "set_release_id": STRING,
            "configuration_kind": STRING,
            "pack_count": INTEGER,
            "print_run_units": INTEGER,
        },
        enums={"configuration_kind": CONFIGURATION_KINDS},
    )

    release = store.db.set_releases.get(body["set_release_id"])
    if release is None:
        fail("ERR_NOT_FOUND", "SetRelease %s does not exist." % body["set_release_id"])

    row = store.insert_product_configuration(
        body["set_release_id"], body["configuration_kind"],
        body["pack_count"], body["print_run_units"])
    return envelope.object_response(models.product_configuration_view(row), status=201)


@bp.route("/op/product-configurations", methods=["GET"])
def list_configurations():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_DISTRIBUTOR, ROLE_STORE_ORGANIZER))
    check_query_enums(request, {"configuration_kind": CONFIGURATION_KINDS})
    rows = list(store.db.product_configurations.values())
    for name in ("set_release_id", "configuration_kind"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response([models.product_configuration_view(r) for r in rows],
                                  limit, offset)


@bp.route("/op/product-configurations/<config_id>", methods=["GET"])
def get_configuration(config_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_DISTRIBUTOR, ROLE_STORE_ORGANIZER))
    row = store.db.product_configurations.get(config_id)
    if row is None:
        fail("ERR_NOT_FOUND", "ProductConfiguration %s does not exist." % config_id)
    return envelope.object_response(models.product_configuration_view(row))


@bp.route("/op/product-configurations/<config_id>/transition", methods=["POST"])
def transition_configuration(config_id):
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("action",),
        optional=("additional_units",),
        types={"action": STRING, "additional_units": INTEGER},
    )
    require_action(body, CONFIG_ACTIONS)

    row = store.db.product_configurations.get(config_id)
    if row is None:
        fail("ERR_NOT_FOUND", "ProductConfiguration %s does not exist." % config_id)

    additional = body.get("additional_units")
    if additional is None:
        fail("ERR_INVALID_REQUEST",
             "additional_units is required for INCREASE_REPRINT_RUN.")
    if additional < 0:
        fail("ERR_INVALID_REQUEST", "additional_units must not be negative.")

    # The addition raises print_run_units directly and advances version by one.
    row["print_run_units"] = row["print_run_units"] + additional
    store.touch(row)

    # Any partially fulfilled order the new availability now covers is promoted
    # on the spot to APPROVED, taking the remainder of its requested quantity.
    # Orders are considered in submitted_seq order so the promotion is
    # deterministic when the enlargement cannot cover every shortfall.
    shortfalls = sorted(
        (o for o in store.orders_of_configuration(config_id)
         if o["status"] == "PARTIALLY_FULFILLED"),
        key=lambda o: o["submitted_seq"],
    )
    for order in shortfalls:
        available = models.units_available(config_id)
        shortfall = order["quantity"] - order["fulfilled_qty"]
        if available >= shortfall:
            order["fulfilled_qty"] = order["quantity"]
            store.touch(order, status="APPROVED")

    return envelope.object_response(models.product_configuration_view(row))


# --------------------------------------------------------------------------
# Allocation orders
# --------------------------------------------------------------------------

@bp.route("/op/allocation-orders", methods=["POST"])
def create_order():
    require_role(request, (ROLE_DISTRIBUTOR,))
    body = check_body(
        request,
        required=("distributor_name", "product_configuration_id", "quantity"),
        types={"distributor_name": STRING, "product_configuration_id": STRING,
               "quantity": INTEGER},
    )

    config = store.db.product_configurations.get(body["product_configuration_id"])
    if config is None:
        fail("ERR_NOT_FOUND",
             "ProductConfiguration %s does not exist." % body["product_configuration_id"])

    row = store.insert_allocation_order(
        body["distributor_name"], body["product_configuration_id"], body["quantity"])
    # The sequence number is the sole tie-break the program uses when orders
    # compete for the same units. approval_rank is derived, not stored.
    row["submitted_seq"] = store.next_submitted_seq()
    return envelope.object_response(models.allocation_order_view(row), status=201)


@bp.route("/op/allocation-orders", methods=["GET"])
def list_orders():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_DISTRIBUTOR))
    check_query_enums(request, {"status": ORDER_STATUSES})
    rows = list(store.db.allocation_orders.values())
    for name in ("product_configuration_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response([models.allocation_order_view(r) for r in rows],
                                  limit, offset)


@bp.route("/op/allocation-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_DISTRIBUTOR))
    row = store.db.allocation_orders.get(order_id)
    if row is None:
        fail("ERR_NOT_FOUND", "AllocationOrder %s does not exist." % order_id)
    return envelope.object_response(models.allocation_order_view(row))


@bp.route("/op/allocation-orders/<order_id>/transition", methods=["POST"])
def transition_order(order_id):
    """APPROVE, FULFILL_PARTIAL and DENY are strictly complementary.

    Fulfilment carries the same currency guarantee as event approval: the
    operator must present expected_product_configuration_version, because a
    configuration's remaining units shrink as earlier orders draw the print run
    down. The guard is checked first, then the state rung, then the fiscal rung.
    """
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("action",),
        optional=("expected_product_configuration_version",),
        types={"action": STRING, "expected_product_configuration_version": INTEGER},
    )
    action = require_action(body, ORDER_ACTIONS)

    row = store.db.allocation_orders.get(order_id)
    if row is None:
        fail("ERR_NOT_FOUND", "AllocationOrder %s does not exist." % order_id)

    config = store.db.product_configurations.get(row["product_configuration_id"])
    if config is None:
        fail("ERR_NOT_FOUND", "The order's product configuration no longer exists.")

    expected = body.get("expected_product_configuration_version")
    if expected is not None and expected != config["version"]:
        fail("ERR_STALE_VERSION",
             "expected_product_configuration_version does not match the "
             "configuration's current version.")

    if row["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "Only a PENDING order may be transitioned.")

    available = models.units_available(config["id"])

    if action == "APPROVE":
        if row["quantity"] > available:
            fail("ERR_PRINT_RUN_EXHAUSTED",
                 "The requested quantity exceeds the configuration's available units.")
        row["fulfilled_qty"] = row["quantity"]
        store.touch(row, status="APPROVED")
        store.touch(config)
    elif action == "FULFILL_PARTIAL":
        # Available only when the request exceeds current availability and
        # availability is nevertheless greater than zero.
        if row["quantity"] <= available:
            fail("ERR_INVALID_STATE",
                 "A partial fulfilment requires the request to exceed current "
                 "availability.")
        if available <= 0:
            fail("ERR_INVALID_STATE",
                 "A partial fulfilment requires positive availability.")
        row["fulfilled_qty"] = available
        store.touch(row, status="PARTIALLY_FULFILLED")
        store.touch(config)
    else:  # DENY
        if available != 0:
            fail("ERR_INVALID_STATE",
                 "An order may only be denied once availability has fallen to zero.")
        store.touch(row, status="DENIED")

    return envelope.object_response(models.allocation_order_view(row))