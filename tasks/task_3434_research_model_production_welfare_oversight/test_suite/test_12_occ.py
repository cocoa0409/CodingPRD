"""Optimistic concurrency control on the two OCC-guarded writes: allocation
creation and shipment creation against a stale CustomerOrder.version.
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    allocate_order_to_cohort,
    api_client,
    create_allocation_payload,
    create_shipment_for_order,
    create_shipment_payload,
    read_order,
    setup_allocated_order,
    setup_sourcing_order,
    validate_error,
)

_FM = TEST_USERS["facility_manager_headers"]
_LOGI = TEST_USERS["logistics_headers"]


def test_occ_stale_version_on_allocation_create():
    """PRD Section 2.8: "Two write endpoints mutate state derived from a
    `CustomerOrder` and are therefore guarded by optimistic concurrency
    control on the order's `version`: creating an allocation, and creating a
    shipment. Each such request must carry a non-optional
    `expected_order_version` field equal to the target order's current
    `version` as the client last observed it. If the order's `version` has
    advanced since that observation — for example because another allocation
    was created or released against the same order in the meantime, each a
    legitimate mutation under the order state machine — the write is rejected
    with `ERR_STALE_VERSION` (HTTP 412), and no part of it is applied."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_allocation_create
    """
    bundle = setup_sourcing_order(
        quantity_male=6, quantity_female=6,
        cohorts=[{"count_male": 20, "count_female": 20, "hold": True}],
    )
    order = bundle["order"]
    cohort = bundle["cohorts"][0]
    stale_version = order["version"]

    allocation, order = allocate_order_to_cohort(order, cohort, 2, 2)
    assert allocation["status"] == "RESERVED"

    # Replaying the pre-allocation version is rejected and writes nothing.
    payload = create_allocation_payload(
        order["id"], cohort["id"], stale_version, qty_male=2, qty_female=2
    )
    resp = api_client.create_allocation(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    order = read_order(order["id"])
    assert order["allocated_male"] == 2
    assert order["allocated_female"] == 2


def test_occ_stale_version_on_shipment_create():
    """PRD Section 2.8: "Two write endpoints mutate state derived from a
    `CustomerOrder` and are therefore guarded by optimistic concurrency
    control on the order's `version`: creating an allocation, and creating a
    shipment. Each such request must carry a non-optional
    `expected_order_version` field equal to the target order's current
    `version` as the client last observed it. If the order's `version` has
    advanced since that observation — for example because another allocation
    was created or released against the same order in the meantime, each a
    legitimate mutation under the order state machine — the write is rejected
    with `ERR_STALE_VERSION` (HTTP 412), and no part of it is applied."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_shipment_create
    """
    bundle = setup_allocated_order(quantity_male=2, quantity_female=2)
    order = bundle["order"]
    stale_version = order["version"]

    shipment, order = create_shipment_for_order(order)
    assert shipment["status"] == "PLANNED"
    assert order["status"] == "SCHEDULED"

    # The shipment write advanced the order's version; replaying the stale
    # version on a second shipment create is rejected before any other gate.
    payload = create_shipment_payload(order["id"], stale_version)
    resp = api_client.create_shipment(payload, _LOGI)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    assert read_order(order["id"])["status"] == "SCHEDULED"
