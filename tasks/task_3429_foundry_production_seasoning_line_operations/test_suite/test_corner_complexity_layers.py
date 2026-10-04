"""Corner queue (complexity_layers): optimistic concurrency pins on the two
creation endpoints that carry expected-version fields."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_melt_batch_payload,
    create_order,
    create_product,
    create_retail_allocation_payload,
    get_inventory_record,
    get_inventory_record_for_product,
    release_order,
    validate_error,
    validate_paginated,
)

_FM = TEST_USERS["foundry_manager_headers"]
_OP = TEST_USERS["melt_operator_headers"]
_RP = TEST_USERS["retail_planner_headers"]


def test_stale_order_version_melt_create_rejected(api):
    """PRD §2.6: "If the order's current `version` has advanced since that
    observation — because another writer created a melt batch, released the order,
    or otherwise mutated it — the create is rejected with
    `ERR_STALE_ORDER_VERSION` (HTTP 412), preventing the client from booking a
    furnace window against an order it has not observed."
    The client captured version 1 at create; release advanced the order to 2.

    Design: Corner/complexity_layers/stale_order_version_melt_create_rejected
    """
    product = create_product()
    order = create_order(product["id"])
    stale_version = order["version"]  # 1
    release_order(order["id"])  # -> 2
    payload = create_melt_batch_payload(order["id"], stale_version)
    resp = api.create_melt_batch(payload, _OP)
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)
    _, meta = validate_paginated(api.list_melt_batches(
        _FM, params={"production_order_id": order["id"]}))
    assert meta["total_count"] == 0


def test_stale_inventory_version_allocation_rejected(api):
    """PRD §2.6: "A mismatch with the inventory record's current `version` is
    rejected with `ERR_STALE_INVENTORY_VERSION` (HTTP 412), so a planner never
    reserves units against availability that no longer exists."
    The request carries one behind the current version; the record is unmoved.

    Design: Corner/complexity_layers/stale_inventory_version_allocation_rejected
    """
    product = create_product()
    record = get_inventory_record_for_product(product["id"])
    payload = create_retail_allocation_payload(
        record["id"], record["version"] - 1, allocated_qty=1)
    resp = api.create_retail_allocation(payload, _RP)
    validate_error(resp, ApiErrorId.ERR_STALE_INVENTORY_VERSION)
    after = get_inventory_record(record["id"])
    assert after["version"] == record["version"]
    assert after["reserved_units"] == 0
