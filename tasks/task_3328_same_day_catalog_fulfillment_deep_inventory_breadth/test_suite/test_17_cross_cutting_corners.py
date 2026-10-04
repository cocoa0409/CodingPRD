"""Cross-cutting corners: OCC, derived-field reconciliation, archival and immediacy."""

from test_helpers import (
    CURATOR,
    DCM,
    ApiErrorId,
    setup_allocated_order,
    setup_order_scenario,
    setup_released_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_stale_version_refuses_the_allocation_and_leaves_the_order_alone(api):
    """PRD §2.7: "If that value does not equal the order's current `version` at the moment
    the write is attempted, the write is rejected with `ERR_STALE_VERSION` (HTTP 412) and
    no other effect is applied."
    PRD §2.7: "A client whose read is stale therefore cannot allocate lines that a
    concurrent revision has removed".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_allocate_is_rejected
    """
    scenario = setup_released_order(
        api,
        lines_spec=[{"price": 1500, "qty": 1, "bundle": 4, "on_hand": 10, "sku": "OC-1001"}],
    )
    order = scenario["order"]
    headers = scenario["acct_headers"]
    # The order arrives already RELEASED, so allocation is legal on it: priority 5
    # (terminal) and priority 6 (state legality) both pass and the stale-version
    # check at priority 7 is the one that fires — the ordering PRD 2.9 pins.
    observed_version = order["version"]

    stale = api.allocate_order(order["id"], {"expected_order_version": observed_version - 1},
                               headers)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    after = validate_success(api.get_order(order["id"], headers))
    assert after["order_status"] == "RELEASED", (
        "the stale call is refused on the version, not on the state"
    )
    assert after["fulfillment_status"] == "AWAITING_RELEASE"
    assert after["version"] == observed_version, (
        "the rejected write advanced no version"
    )

    first = validate_success(api.allocate_order(
        order["id"], {"expected_order_version": observed_version}, headers))
    assert first["fulfillment_status"] == "ALLOCATED"
    assert first["version"] == observed_version + 1, (
        "the order's version advances by exactly 1 on the successful mutation"
    )


def test_cancelling_an_allocated_order_reconciles_the_derived_money_fields(api):
    """PRD §3.5: "A line in `SHORT`, `RESTOCKED` or `RETURNED` is excluded from every
    variant, and its `allocated_small_line_fee_cents` is cleared to 0 rather than left
    standing at a stale figure."
    PRD §3.3: "Every line then returns to `line_status` `PENDING` with `allocated_units`
    reset to 0".

    Design: Corner/cross_cutting_complexity_layers/order_line_count_is_reconciled_on_every_mutation
    """
    scenario = setup_allocated_order(
        api,
        lines_spec=[
            {"price": 12000, "qty": 1, "bundle": 4, "on_hand": 5, "sku": "DR-1001"},
            {"price": 9000, "qty": 1, "bundle": 4, "on_hand": 5, "sku": "DR-1002"},
        ],
    )
    headers = scenario["acct_headers"]
    allocated = validate_success(api.get_order(scenario["order"]["id"], headers))
    assert allocated["line_count"] == 2
    assert allocated["total_small_line_fee_cents"] > 0

    cancelled = validate_success(api.cancel_order(scenario["order"]["id"], headers))

    assert cancelled["line_count"] == 2, (
        "the line rows themselves still belong to the order"
    )
    assert cancelled["total_small_line_fee_cents"] == 0
    assert cancelled["order_total_cents"] == 0, (
        "no line remains in the eligible status set, so both pricing variants fall to zero"
    )

    lines, _meta = validate_paginated(api.list_order_lines(
        scenario["order"]["id"], headers, {"limit": 10, "offset": 0}))
    assert len(lines) == 2
    assert all(line["allocated_small_line_fee_cents"] == 0 for line in lines)


def test_the_shipment_records_a_copy_of_the_centers_cutoff_counter(api):
    """PRD §3.8: "it is copied into a shipment's own `cutoff_sequence_index` at the moment
    the shipment's cutoff is certified, as §3.7 describes — so the shipment records which
    roll of the center's counter it was certified under."
    PRD §2.5: "the `cutoff_sequence_index` counter moves only when the center's daily
    cutoff period is rolled".

    Design: Corner/cross_cutting_complexity_layers/cutoff_sequence_index_is_captured_not_recomputed
    """
    scenario = setup_order_scenario(
        api,
        lines_spec=[{"price": 1500, "qty": 1, "bundle": 8, "on_hand": 20, "sku": "SQ-1001"}],
        target="SHIPPED",
        utc="2026-09-14T10:05:00Z",
    )
    shipment = scenario["shipment"]
    assert shipment["cutoff_sequence_index"] == 0

    validate_success(api.roll_cutoff(scenario["dc"]["id"], DCM))
    validate_success(api.roll_cutoff(scenario["dc"]["id"], DCM))

    dc = validate_success(api.get_distribution_center(scenario["dc"]["id"], DCM))
    assert dc["cutoff_sequence_index"] == 2

    after = validate_success(api.get_shipment(shipment["id"], DCM))
    assert after["cutoff_sequence_index"] == 0, (
        "the shipment holds the value it was stamped with, not a live reference"
    )
    assert after["freight_charge_cents"] == shipment["freight_charge_cents"]


def test_revoking_curation_archives_the_item_rather_than_removing_it(api):
    """PRD §3.1: "A curator may revoke a batch's approval, which moves `review_status` to
    `REVOKED` and returns every item in the batch to `curation_review_state` `UNREVIEWED`".
    PRD §3.1: "An item cannot be approved while its `catalog_status` is `SUSPENDED` for
    damage reasons without first being reinstated by the workflow in §3.9."
    PRD §3.11: "Search visibility, by contrast, is not gated on either: a suspended or
    unreviewed item still appears in catalog results".

    Design: Corner/cross_cutting_complexity_layers/availability_restored_on_cancel_after_soft_deactivation_of_a_row
    """
    scenario = setup_allocated_order(
        api,
        lines_spec=[{"price": 1500, "qty": 3, "bundle": 4, "on_hand": 8, "sku": "SD-1001"}],
    )
    headers = scenario["acct_headers"]
    item = scenario["items"][0]

    validate_success(api.create_item_cross_reference(
        item["id"], {"referenced_manufacturer": "Acme Fasteners",
                     "referenced_part_number": "AC-9001",
                     "compatibility_note": "interchange"}, CURATOR), 201)
    validate_success(api.revoke_curation_review(scenario["review"]["id"], CURATOR))

    after = validate_success(api.get_item(item["id"], CURATOR))
    assert after["curation_review_state"] == "UNREVIEWED"
    assert after["id"] == item["id"], "the item row is still readable"

    attributes, _meta = validate_paginated(api.list_item_attributes(
        item["id"], CURATOR, {"limit": 100, "offset": 0}))
    assert len(attributes) == 1
    references, _meta = validate_paginated(api.list_item_cross_references(
        item["id"], CURATOR, {"limit": 100, "offset": 0}))
    assert len(references) == 1

    validate_success(api.cancel_order(scenario["order"]["id"], headers))

    stock = validate_success(api.get_stock(scenario["stock_rows"][0]["id"], DCM))
    assert stock["reserved_units"] == 0
    assert stock["available_units"] == 8


def test_every_effect_of_one_request_is_visible_in_that_same_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."
    PRD §3.4: "Committing the allocation has a wide footprint, because an order is only as
    real as the units it holds."
    PRD §3.4: "Two pricing passes run immediately after the commit, computing the order's
    small-line handling fees over the newly eligible lines — see §3.5 — and the line-count
    guard is recomputed into `line_count`."

    Design: Corner/consistency_model/immediate_consistency_all_side_effects_visible_in_the_same_response
    """
    scenario = setup_released_order(
        api,
        lines_spec=[{"price": 12000, "qty": 1, "bundle": 8, "on_hand": 10, "sku": "IM-2001"}],
    )
    order = scenario["order"]

    allocated = validate_success(api.allocate_order(
        order["id"], {"expected_order_version": order["version"]},
        scenario["acct_headers"]))

    assert allocated["line_count"] == 1
    assert allocated["allocated_dc_id"] == scenario["dc"]["id"]
    assert allocated["fulfillment_status"] == "ALLOCATED"
    assert allocated["same_day_committed"] is True
    assert "order_total_cents" in allocated
    assert "total_small_line_fee_cents" in allocated

    stock = validate_success(api.get_stock(scenario["stock_rows"][0]["id"], DCM))
    assert stock["reserved_units"] == 1
    assert stock["available_units"] == 9

    reread = validate_success(api.get_order(order["id"], scenario["acct_headers"]))
    assert reread["order_total_cents"] == allocated["order_total_cents"]
    assert reread["line_count"] == allocated["line_count"]
    assert reread["total_small_line_fee_cents"] == allocated["total_small_line_fee_cents"]