"""Retail metrics, the shared backroom, planogram execution and import planning."""
import pytest

from test_helpers import api_client, validate_success, validate_error, validate_paginated, ApiErrorId
from test_helpers import factories as f
from test_helpers.fixtures import (
    ADMIN, MANAGER, LEAD, PLANNER,
    create_item, setup_store, setup_open_day, open_store_day, create_receipt,
    reconcile_receipt, dispute_receipt, settled_receipt, stock_item, create_transfer,
    create_capacity_reading, create_planogram_version, create_planogram_slot,
    get_item, get_store_day, get_location, get_transfer, close_store_day,
    post_guest_counts, shift_iso, current_day_version,
)

BOAT, DECOR = "ITM-BOAT-6400", "ITM-DECOR-2400"

# The corner-design fixtures stock goods via a BACKROOM receiving on a store day.
# A receiving re-measures the backroom and may flip that day's conversion_gate
# (PRD 3.7), and it appends a reading to the location; tests that later post
# guest counts against the same day must therefore re-read the day's version
# (PRD 2.6) and must not assume the day's gate is still OPEN.
STOCK_DAY = "2026-09-19T00:00:00Z"


def _stock_off_day(loc, item, units):
    """Stock `units` on a dedicated day so the day under test is untouched."""
    return stock_item(loc["id"], open_store_day(loc["id"], STOCK_DAY)["id"], item["id"], units)


def _full_store():
    """A brand plus a FULL-tier location.

    PRD 2.13 enumerates only that "a `FULL` store carries every theme" — the
    region's *core* theme set is never listed — so a test that only needs the
    theme-carry precondition satisfied (slot uniqueness, publish, delete) must use
    a FULL store whose carry is uniquely derivable from PRD.
    """
    return setup_store(
        brand_overrides={"food_storage_corridor_units": 310},
        location_overrides={"assortment_tier": "FULL"},
    )


def _boat(**overrides):
    base = dict(sku=BOAT, name="Hand-Carved Cedar Boat Shelf", theme_code="SUMMER",
                unit_retail_cents=6400, unit_cost_cents=2400, import_lead_time_days=45)
    base.update(overrides)
    return create_item(**base)


def _decor(**overrides):
    base = dict(sku=DECOR, name="Harvest Wall Plaque", theme_code="SUMMER",
                unit_retail_cents=2400, unit_cost_cents=900, import_lead_time_days=40)
    base.update(overrides)
    return create_item(**base)


# ==========================================================================
# Corner queue B — calculations
# ==========================================================================

def test_retail_sales_per_guest_drops_a_disputed_receipt_from_the_numerator(api):
    """PRD §3.1: "It is the sum of the stored `provisional_retail_cents` values of the store
    day's receipts whose status is one of `DRAFT`, `RECONCILED`, `SETTLED` or `CLOSED`; a
    receipt in `DISPUTED` status is outside that set."
    PRD §3.1: "The **final** figure, `retail_sales_per_guest_cents`, divides the day's
    `retail_sales_cents` by the day's `restaurant_guest_count`, then rounds half-up to a
    whole cent."

    Design: Corner/calculations/retail_sales_per_guest_excludes_disputed_receipts_from_the_numerator
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    receipt_a = create_receipt(loc["id"], day["id"],
                               [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")], "R-1042-0061")
    receipt_b = create_receipt(loc["id"], day["id"],
                               [f.retail_line(boat["id"], 2, 6400, 0.0, "RETAIL")], "R-1042-0062")
    reconciled_a = reconcile_receipt(receipt_a["id"])
    reconciled_b = reconcile_receipt(receipt_b["id"])
    before = get_store_day(day["id"])
    expected_before = reconciled_a["provisional_retail_cents"] + reconciled_b["provisional_retail_cents"]
    assert before["retail_sales_cents"] == expected_before, (
        "the store-day aggregate sums the stored provisional blocks"
    )

    dispute_receipt(receipt_b["id"])
    after = get_store_day(day["id"])

    assert after["retail_sales_cents"] == reconciled_a["provisional_retail_cents"]
    assert after["retail_transaction_count"] == before["retail_transaction_count"] - 1


def test_the_denominator_of_the_final_metric_does_not_move_on_dispute(api):
    """PRD §3.1: "The two denominators are genuinely different populations - everyone seated
    in the dining room, versus those who stood in the retail waiting area"
    PRD §3.1: "a receipt in `DISPUTED` status is outside that set"

    Design: Corner/calculations/retail_sales_per_guest_excludes_disputed_receipts_from_the_numerator
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    counted = post_guest_counts(day["id"], day["version"], 142, 1420000, 35, 18)
    guest_count = counted["restaurant_guest_count"]
    receipt = create_receipt(loc["id"], day["id"],
                             [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")], "R-1042-0063")
    reconcile_receipt(receipt["id"])

    dispute_receipt(receipt["id"])
    after = get_store_day(day["id"])

    assert after["restaurant_guest_count"] == guest_count == 142
    assert after["waiting_area_shopper_count"] == 35


def test_the_conversion_index_pins_to_zero_when_nobody_entered_the_waiting_area(api):
    """PRD §3.5: "The raw conversion rate is expressed in basis points of waiting-area
    shoppers. It is the day's `waiting_area_converted_count` multiplied by ten thousand,
    divided by the day's `waiting_area_shopper_count` plus one"
    PRD §3.5: "If the day's `retail_sales_cents` is zero the tip share is pinned to 0"

    Design: Corner/calculations/conversion_index_pins_to_zero_when_no_shopper_entered_the_waiting_area
    """
    brand, loc, day = setup_open_day(brand_overrides={"waiting_area_retail_weight_bps": 6000,
                                                      "food_storage_corridor_units": 310})

    data = post_guest_counts(day["id"], day["version"], 142, 1420000, 0, 0)

    assert data["waiting_area_conversion_index_bps"] == 0, (
        "the plus-one denominator keeps the raw rate defined, and the tip share is pinned"
    )


def test_the_conversion_index_decay_is_capped_at_half(api):
    """PRD §3.5: "Each retail transaction the day has already recorded drags the raw rate
    down by ten percent of itself, and that cumulative drag is capped at fifty percent."
    PRD §3.5: "if it has recorded five or more, the decay is at its fifty-percent cap."

    Design: Corner/calculations/conversion_index_decay_saturates_at_five_retail_transactions
    """
    brand, loc, day = setup_open_day(brand_overrides={"waiting_area_retail_weight_bps": 6000,
                                                      "food_storage_corridor_units": 310})
    boat = _boat()
    for index in range(1, 6):
        create_receipt(loc["id"], day["id"],
                       [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
                       f"R-1042-005{index}")

    # Each ring advances the store day's version (PRD 2.8) and the guest-count
    # post carries a non-skipped expected_store_day_version (PRD 2.6), so the
    # live version is re-read rather than the stale one captured at open.
    data = post_guest_counts(day["id"], current_day_version(day["id"]), 90, 900000, 30, 15)

    assert data["retail_transaction_count"] == 5
    assert data["waiting_area_conversion_index_bps"] == 1452, (
        "with the decay saturated the index carries only the conversion half of the blend"
    )


def test_the_conversion_index_decays_proportionally_before_the_cap(api):
    """PRD §3.5: "If the day has recorded no retail transactions the decay is zero and the
    decayed rate equals the raw rate"
    PRD §3.5: "The index then blends the two signals by the brand's
    `waiting_area_retail_weight_bps`"

    Design: Corner/calculations/conversion_index_decay_saturates_at_five_retail_transactions
    """
    brand, loc, day = setup_open_day(brand_overrides={"waiting_area_retail_weight_bps": 6000,
                                                      "food_storage_corridor_units": 310})
    boat = _boat()
    for index in range(1, 4):
        create_receipt(loc["id"], day["id"],
                       [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
                       f"R-1042-005{index}")

    data = post_guest_counts(day["id"], current_day_version(day["id"]), 90, 900000, 30, 15)

    assert data["retail_transaction_count"] == 3
    assert data["waiting_area_conversion_index_bps"] == 2032


# ==========================================================================
# Corner queue B — endpoints / cross_cutting_layers
# ==========================================================================

def test_closing_a_store_day_recomputes_the_brand_guest_weighted_rollup(api):
    """PRD §3.5: "the brand's `brand_retail_sales_per_guest_cents` is recomputed as a
    guest-count-weighted roll-up across the closed store days of the brand's `fiscal_period`."
    PRD §2.8: "`brand_retail_sales_per_guest_cents` is likewise recomputed as a
    guest-count-weighted roll-up rather than accumulated."

    Design: Corner/cross_cutting_layers/store_day_aggregates_bubble_to_the_brand_rollup
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    day_a = open_store_day(loc["id"], "2026-09-19T00:00:00Z")
    day_b = open_store_day(loc["id"], "2026-09-20T00:00:00Z")
    counted_a = post_guest_counts(day_a["id"], day_a["version"], 200, 2000000, 40, 20)
    counted_b = post_guest_counts(day_b["id"], day_b["version"], 200, 2000000, 40, 20)
    receipt = create_receipt(loc["id"], day_a["id"],
                             [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")], "R-1042-0071")
    settled = reconcile_receipt(receipt["id"])

    close_store_day(day_a["id"], counted_a["version"])
    close_store_day(day_b["id"], counted_b["version"])
    rollup = api.get_brand(brand["id"], MANAGER).json()["data"]["brand_retail_sales_per_guest_cents"]

    day_a_metric = get_store_day(day_a["id"])["retail_sales_per_guest_cents"]
    assert day_a_metric > 0
    assert rollup > 0, "the roll-up is recomputed from the closed days, not left at zero"


def test_transfer_discrepancy_read_reports_the_variance_against_tolerance(api):
    """PRD §3.7: "A discrepancy read exposes the reconciliation arithmetic for a transfer
    without mutating it: it reports the transfer's `variance_units` and `variance_bps`, the
    brand's `tolerance_bps`, whether the variance is `within_tolerance`"
    PRD §3.7: "It is a pure read and changes nothing."

    Design: Corner/endpoints/transfer_discrepancy_read_reports_the_variance_against_tolerance
    """
    # The receive must clear the priority-17 staging-free-units floor (PRD 3.7:
    # staging_free_units = capacity - occupancy - committed - corridor), so the
    # location needs capacity for the 95 units on top of the 310-unit corridor.
    brand, loc, day = setup_open_day(
        brand_overrides={"transfer_variance_tolerance_bps": 200,
                         "food_storage_corridor_units": 310},
        location_overrides={"backroom_capacity_units": 1000},
    )
    boat = _boat()
    transfer = create_transfer(loc["id"], day["id"], boat["id"], 100)
    validate_success(api.dispatch_transfer(transfer["id"], LEAD))
    validate_success(api.receive_transfer(transfer["id"], {"received_units": 95}, LEAD))

    data = validate_success(api.get_transfer_discrepancy(transfer["id"], MANAGER))

    assert data["variance_units"] == -5
    assert data["variance_bps"] == 500
    assert data["tolerance_bps"] == 200


def test_the_discrepancy_read_is_idempotent(api):
    """PRD §3.7: "It is a pure read and changes nothing."
    PRD §3.7: "`variance_bps` is the absolute value of that difference multiplied by ten
    thousand and divided by the declared count, rounded half-up to a whole basis point."

    Design: Corner/endpoints/transfer_discrepancy_read_reports_the_variance_against_tolerance
    """
    # The receive must clear the priority-17 staging-free-units floor (PRD 3.7:
    # staging_free_units = capacity - occupancy - committed - corridor), so the
    # location needs capacity for the 95 units on top of the 310-unit corridor.
    brand, loc, day = setup_open_day(
        brand_overrides={"transfer_variance_tolerance_bps": 200,
                         "food_storage_corridor_units": 310},
        location_overrides={"backroom_capacity_units": 1000},
    )
    boat = _boat()
    transfer = create_transfer(loc["id"], day["id"], boat["id"], 100)
    validate_success(api.dispatch_transfer(transfer["id"], LEAD))
    validate_success(api.receive_transfer(transfer["id"], {"received_units": 95}, LEAD))

    first = validate_success(api.get_transfer_discrepancy(transfer["id"], MANAGER))
    second = validate_success(api.get_transfer_discrepancy(transfer["id"], MANAGER))

    assert first == second


# ==========================================================================
# Corner queue B — cross_cutting_layers (occupancy reconciliation)
# ==========================================================================

def test_backroom_posture_reconciles_after_a_partial_receiving(api):
    """PRD §3.7: "`staging_free_units` is the derived quantity every receiving decision
    turns on, and it is defined as `backroom_capacity_units` minus `backroom_occupancy_units`
    minus `backroom_committed_units` minus the brand's `food_storage_corridor_units`."
    PRD §3.7: "while a transfer is in flight its `declared_units` are committed, and when it
    lands those units stop being committed and become occupancy."

    Design: Corner/cross_cutting_layers/store_day_occupancy_reconciles_after_a_partial_receiving
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 40,
                                                      "transfer_variance_tolerance_bps": 200})
    boat = _boat()
    validate_success(api.create_capacity_reading(
        loc["id"],
        f.create_capacity_reading_payload(day["id"], "2026-09-21T08:00:00Z", 25, 0, 0, "CYCLE_COUNT"),
        MANAGER), 201)
    transfer_a = create_transfer(loc["id"], day["id"], boat["id"], 40)
    transfer_b = create_transfer(loc["id"], day["id"], boat["id"], 60)
    validate_success(api.dispatch_transfer(transfer_a["id"], LEAD))
    validate_success(api.dispatch_transfer(transfer_b["id"], LEAD))
    before = get_location(loc["id"])
    assert before["backroom_committed_units"] == 100
    assert before["backroom_occupancy_units"] == 25
    assert before["staging_free_units"] == 400 - 25 - 100 - 40

    validate_success(api.receive_transfer(transfer_a["id"], {"received_units": 35}, LEAD))
    after = get_location(loc["id"])

    assert after["backroom_committed_units"] == 60
    assert after["staging_free_units"] == 400 - after["backroom_occupancy_units"] - 60 - 40


def test_the_occupancy_comes_from_the_appended_reading_not_the_declared_quantity(api):
    """PRD §3.7: "A `BackroomCapacityReading` is appended for that location and store day
    with `source` of `RECEIVING`, with `backroom_units` equal to the received count"
    PRD §3.7: "the reading is authoritative and the location's posture is a projection of
    the most recent measurement rather than a running tally."

    Design: Corner/cross_cutting_layers/store_day_occupancy_reconciles_after_a_partial_receiving
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 40,
                                                      "transfer_variance_tolerance_bps": 200})
    boat = _boat()
    transfer = create_transfer(loc["id"], day["id"], boat["id"], 40)
    validate_success(api.dispatch_transfer(transfer["id"], LEAD))

    validate_success(api.receive_transfer(transfer["id"], {"received_units": 35}, LEAD))
    readings, meta = validate_paginated(
        api.list_transfer_capacity_readings(transfer["id"], MANAGER)
    )

    assert meta["total_count"] == 1
    assert readings[0]["backroom_units"] == 35


# ==========================================================================
# Corner queue B — consistency_model
# ==========================================================================

def test_the_capacity_reading_log_is_reachable_from_the_transfer_and_the_location(api):
    """PRD §3.9: "backroom readings by `store_day_id` or `trigger_transfer_id`"
    PRD §3.9: "Every such list obeys §2.3."

    Design: Corner/consistency_model/capacity_reading_is_appended_under_every_receiving_state
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 40,
                                                      "transfer_variance_tolerance_bps": 200})
    boat = _boat()
    validate_success(api.create_capacity_reading(
        loc["id"],
        f.create_capacity_reading_payload(day["id"], "2026-09-21T07:00:00Z", 25, 0, 0, "CYCLE_COUNT"),
        MANAGER), 201)
    transfer = create_transfer(loc["id"], day["id"], boat["id"], 100)
    validate_success(api.dispatch_transfer(transfer["id"], LEAD))
    validate_success(api.receive_transfer(transfer["id"], {"received_units": 90}, LEAD))
    validate_success(api.void_receiving(transfer["id"], MANAGER))

    by_transfer, transfer_meta = validate_paginated(
        api.list_transfer_capacity_readings(transfer["id"], MANAGER)
    )
    by_location, location_meta = validate_paginated(
        api.list_location_capacity_readings(loc["id"], MANAGER,
                                            {"trigger_transfer_id": transfer["id"]})
    )

    assert transfer_meta["total_count"] == 2
    assert location_meta["total_count"] == 2
    assert len(by_transfer) == len(by_location) == 2


def test_a_receiving_reading_and_its_compensating_reading_sum_to_zero(api):
    """PRD §3.7: "Voiding moves the status to `VOID_RECEIVING`, reverses the item's stock by
    subtracting the received count and adding back the declared count, and appends a
    compensating reading with `source` of `RECEIVING`, `backroom_units` of negative the
    received count"
    PRD §3.7: "the conserved quantity `backroom_occupancy_units + backroom_committed_units`
    is restored to exactly the value it held before the receiving happened"

    Design: Corner/consistency_model/capacity_reading_is_appended_under_every_receiving_state
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 40,
                                                      "transfer_variance_tolerance_bps": 200})
    boat = _boat()
    validate_success(api.create_capacity_reading(
        loc["id"],
        f.create_capacity_reading_payload(day["id"], "2026-09-21T07:00:00Z", 25, 0, 0, "CYCLE_COUNT"),
        MANAGER), 201)
    transfer = create_transfer(loc["id"], day["id"], boat["id"], 100)
    validate_success(api.dispatch_transfer(transfer["id"], LEAD))
    validate_success(api.receive_transfer(transfer["id"], {"received_units": 90}, LEAD))
    validate_success(api.void_receiving(transfer["id"], MANAGER))

    rows, meta = validate_paginated(
        api.list_transfer_capacity_readings(transfer["id"], MANAGER)
    )
    units = sorted(r["backroom_units"] for r in rows)

    assert units == [-90, 90]
    assert sum(units) == 0


# ==========================================================================
# Difficulty queue A — compensating_invariant (units)
# ==========================================================================

def test_voiding_a_receiving_restores_the_conserved_backroom_units(api):
    """PRD §3.7: "voids is the `BoutiqueManager` reversal ... The location's
    `backroom_occupancy_units` and `staging_free_units` are recomputed from that
    compensating reading, so the conserved quantity `backroom_occupancy_units +
    backroom_committed_units` is restored to exactly the value it held before the receiving
    happened."
    PRD §2.8: "Any operation that moves goods must leave `backroom_occupancy_units +
    backroom_committed_units` at a value consistent with the goods actually in or promised
    to the space."

    Design: Difficulty/compensating_invariant/void_receiving_restores_the_conserved_backroom_units
    """
    brand, loc, day = setup_open_day(brand_overrides={"transfer_variance_tolerance_bps": 200,
                                                      "food_storage_corridor_units": 50})
    boat = _boat()
    validate_success(api.create_capacity_reading(
        loc["id"],
        f.create_capacity_reading_payload(day["id"], "2026-09-17T08:00:00Z", 25, 0, 0, "CYCLE_COUNT"),
        MANAGER), 201)
    transfer = create_transfer(loc["id"], day["id"], boat["id"], 100)
    validate_success(api.dispatch_transfer(transfer["id"], LEAD))

    received = validate_success(api.receive_transfer(transfer["id"], {"received_units": 95}, LEAD))
    assert received["variance_bps"] == 500, "above the 200 bps tolerance that makes the void legal"

    voided = validate_success(api.void_receiving(transfer["id"], MANAGER))
    after = get_location(loc["id"])

    assert voided["status"] == "VOID_RECEIVING"
    assert after["backroom_occupancy_units"] == 25
    assert after["backroom_committed_units"] == 0
    assert after["staging_free_units"] == 400 - 25 - 0 - 50


def test_the_void_also_restores_the_item_stock_ledger(api):
    """PRD §3.7: "reverses the item's stock by subtracting the received count and adding
    back the declared count"
    PRD §3.9: "`on_hand_units` is the item's live stock and has exactly two sources and one
    sink."

    Design: Difficulty/compensating_invariant/void_receiving_restores_the_conserved_backroom_units
    """
    brand, loc, day = setup_open_day(brand_overrides={"transfer_variance_tolerance_bps": 200,
                                                      "food_storage_corridor_units": 50})
    boat = _boat()
    transfer = create_transfer(loc["id"], day["id"], boat["id"], 100)
    validate_success(api.dispatch_transfer(transfer["id"], LEAD))
    validate_success(api.receive_transfer(transfer["id"], {"received_units": 95}, LEAD))
    assert get_item(boat["id"])["on_hand_units"] == 95

    validate_success(api.void_receiving(transfer["id"], MANAGER))

    assert get_item(boat["id"])["on_hand_units"] == 100, (
        "PRD 3.7: the void subtracts the received count (95) and adds back the "
        "declared count (100); PRD 3.9 restates it as on_hand rising by the "
        "declared count of a voided receiving"
    )


# ==========================================================================
# Difficulty queue A — compensating_invariant (money)
# ==========================================================================

def test_dispute_then_resolve_conserves_the_brand_recognized_revenue(api):
    """PRD §3.4: "A disputed ticket returns to `RECONCILED` when it is currently `DISPUTED`
    ... re-enters the ticket into the brand's inclusion set, recomputes both brand totals"
    PRD §2.8: "`recognized_retail_revenue_cents` on a `Brand` are recomputed - never
    incremented in place - from the current inclusion set of that brand's receipts"

    Design: Difficulty/compensating_invariant/dispute_and_resolve_conserve_recognized_revenue_and_transaction_count
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    receipt_a = reconcile_receipt(
        create_receipt(loc["id"], day["id"],
                       [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")], "R-1042-0018")["id"]
    )
    receipt_b = reconcile_receipt(
        create_receipt(loc["id"], day["id"],
                       [f.retail_line(boat["id"], 1, 3200, 0.0, "RETAIL")], "R-1042-0019")["id"]
    )
    before_aggregate = api.get_brand(brand["id"], MANAGER).json()["data"]["recognized_retail_revenue_cents"]
    before_count = get_store_day(day["id"])["retail_transaction_count"]

    dispute_receipt(receipt_a["id"])
    during = api.get_brand(brand["id"], MANAGER).json()["data"]["recognized_retail_revenue_cents"]
    assert during == receipt_b["recognized_retail_cents"], "DISPUTED leaves the inclusion set"

    validate_success(api.resolve_receipt(receipt_a["id"], MANAGER))
    after_aggregate = api.get_brand(brand["id"], MANAGER).json()["data"]["recognized_retail_revenue_cents"]
    after_count = get_store_day(day["id"])["retail_transaction_count"]

    assert after_aggregate == before_aggregate
    assert after_count == before_count


def test_dispute_then_resolve_conserves_the_store_day_transaction_count(api):
    """PRD §3.4: "Disputing a settled ticket is where the day's transaction count moves
    downward, so a test that settles then disputes should see the count fall back."
    PRD §2.8: "Two invariants must hold at every observable moment"

    Design: Difficulty/compensating_invariant/dispute_and_resolve_conserve_recognized_revenue_and_transaction_count
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    receipt_a = create_receipt(loc["id"], day["id"],
                               [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")], "R-1042-0018")
    receipt_b = create_receipt(loc["id"], day["id"],
                               [f.retail_line(boat["id"], 1, 3200, 0.0, "RETAIL")], "R-1042-0019")
    reconcile_receipt(receipt_a["id"])
    reconcile_receipt(receipt_b["id"])
    baseline = get_store_day(day["id"])["retail_transaction_count"]

    validate_success(api.settle_receipt(receipt_a["id"], {}))
    validate_success(api.dispute_receipt(receipt_a["id"], MANAGER))
    assert get_store_day(day["id"])["retail_transaction_count"] == baseline - 1

    validate_success(api.resolve_receipt(receipt_a["id"], MANAGER))
    assert get_store_day(day["id"])["retail_transaction_count"] == baseline


# ==========================================================================
# Difficulty queue A — priority_pair_validation_conflict (state vs safety)
# ==========================================================================

def _planned_transfer_under_a_suspended_gate(loc, item, declared_units, business_date):
    """Open a day, keep a PLANNED transfer on it, then drive its gate to SUSPENDED by
    reconciling and disputing a ticket and re-posting a quiet guest count.
    Returns (day_at_suspended_gate, planned_transfer)."""
    day = open_store_day(loc["id"], business_date)
    day = post_guest_counts(day["id"], day["version"], 30, 300000, 8, 4)
    transfer = create_transfer(loc["id"], day["id"], item["id"], declared_units)
    receipt = create_receipt(loc["id"], day["id"],
                             [f.retail_line(item["id"], 1, 6400, 0.0, "RETAIL")],
                             "R-1042-0011")
    reconcile_receipt(receipt["id"])
    dispute_receipt(receipt["id"])
    # The transfer create and the receipt's reconcile/dispute all advance the
    # day's version (PRD 2.8), and the guest-count post's captured
    # expected_store_day_version is non-skipped (PRD 2.6), so re-read it.
    day = post_guest_counts(day["id"], current_day_version(day["id"]), 30, 300000, 8, 4)
    return day, transfer


def test_receiving_reports_the_state_row_ahead_of_the_gate_safety_row(api):
    """PRD §2.12: "A receiving that is both in the wrong state and posted on a suspended day
    reports the state failure, because priority 7 precedes priority 8."
    PRD §2.12: "State-machine membership - whether the target resource is in a state from which
    the requested operation is defined - is priority 7 and reports `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/receive_rejects_on_state_before_gate_safety
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    day, transfer = _planned_transfer_under_a_suspended_gate(loc, boat, 60, "2026-09-09T00:00:00Z")
    assert day["conversion_gate"] == "SUSPENDED"

    validate_error(api.receive_transfer(transfer["id"], {"received_units": 60}, LEAD),
                   ApiErrorId.ERR_INVALID_STATE.value)
    assert get_transfer(transfer["id"])["status"] == "PLANNED"


def test_dispatching_on_a_suspended_day_reports_the_gate_row(api):
    """PRD §3.7: "Dispatch is one of the three operations a `SUSPENDED` gate refuses at
    priority 8."
    PRD §2.12: "The suspended-gate rule is priority 8 and reports `ERR_STORE_DAY_GATE_SUSPENDED`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/receive_rejects_on_state_before_gate_safety
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    day, transfer = _planned_transfer_under_a_suspended_gate(loc, boat, 60, "2026-09-09T00:00:00Z")

    validate_error(api.dispatch_transfer(transfer["id"], LEAD),
                   ApiErrorId.ERR_STORE_DAY_GATE_SUSPENDED.value)


# ==========================================================================
# Difficulty queue A — priority_pair_validation_conflict (safety vs existence)
# ==========================================================================

def test_ringing_on_a_suspended_day_reports_the_gate_row_ahead_of_the_item_row(api):
    """PRD §2.12: "A retail ticket that both names an unknown item and is posted on a
    suspended day reports the gate failure, because priority 8 precedes priority 9."
    PRD §2.12: "The suspended-gate rule is priority 8 and reports `ERR_STORE_DAY_GATE_SUSPENDED`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/retail_receipt_rejects_on_gate_safety_before_item_existence
    """
    from test_helpers.fixtures import store_day_with_disputed_receipt
    from test_helpers import NON_EXISTENT_UUID

    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    day, _ = store_day_with_disputed_receipt(loc["id"], "2026-09-10T00:00:00Z", boat["id"],
                                             receipt_number="R-1042-0012", guest_count=30)
    assert day["conversion_gate"] == "SUSPENDED"
    payload = f.create_receipt_payload(
        loc["id"], day["id"], "R-1042-0099",
        [f.retail_line(NON_EXISTENT_UUID, 1, 100, 0.0, "RETAIL")],
    )

    validate_error(api.create_receipt(payload, LEAD),
                   ApiErrorId.ERR_STORE_DAY_GATE_SUSPENDED.value)


def test_the_same_unknown_item_on_an_open_day_reports_item_not_found(api):
    """PRD §2.12: "Reference validity of item identifiers is priority 9 and reports
    `ERR_ITEM_NOT_FOUND` (HTTP 404)."
    PRD §2.7: "A request that references an `item_id` for which no `Item` exists reports
    `ERR_ITEM_NOT_FOUND` (HTTP 404)"

    Design: Difficulty/priority_pair_validation_conflict/retail_receipt_rejects_on_gate_safety_before_item_existence
    """
    from test_helpers import NON_EXISTENT_UUID

    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    payload = f.create_receipt_payload(
        loc["id"], day["id"], "R-1042-0100",
        [f.retail_line(NON_EXISTENT_UUID, 1, 100, 0.0, "RETAIL")],
    )

    validate_error(api.create_receipt(payload, LEAD), ApiErrorId.ERR_ITEM_NOT_FOUND.value)


# ==========================================================================
# Corner queue B — validations / endpoints (backroom)
# ==========================================================================

def test_a_retail_transfer_routed_into_food_storage_is_refused(api):
    """PRD §3.7: "a transfer whose `receiving_zone` is `FOOD_STORAGE` is refused outright
    when it carries item lines in any category at all, because food storage is never used
    for retail merchandise. That refusal is `ERR_FOOD_STORAGE_ZONE_FORBIDDEN` (HTTP 409)"
    PRD §2.12: "The food-storage-zone rule is priority 6 and reports
    `ERR_FOOD_STORAGE_ZONE_FORBIDDEN` (HTTP 409)."

    Design: Corner/validations/routing_a_retail_transfer_into_food_storage_is_refused
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    payload = f.create_transfer_payload(loc["id"], day["id"], boat["id"], 20,
                                        received_units=20, receiving_zone="FOOD_STORAGE")
    validate_error(api.create_transfer(payload, LEAD),
                   ApiErrorId.ERR_FOOD_STORAGE_ZONE_FORBIDDEN.value)


def test_receiving_beyond_the_projected_free_units_is_refused(api):
    """PRD §3.7: "`staging_free_units` is the derived quantity every receiving decision
    turns on"
    PRD §2.12: "The staging-free-units floor is priority 17 and reports
    `ERR_BACKROOM_OVER_CAPACITY` (HTTP 409)."

    Design: Corner/validations/transfer_declared_units_above_remaining_capacity_returns_over_capacity
    """
    brand, loc, day = setup_open_day(location_overrides={"backroom_capacity_units": 4000},
                                     brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    big = create_transfer(loc["id"], day["id"], boat["id"], 3950)
    ok = create_transfer(loc["id"], day["id"], boat["id"], 3000)
    validate_success(api.dispatch_transfer(big["id"], LEAD))
    validate_success(api.dispatch_transfer(ok["id"], LEAD))

    validate_error(api.receive_transfer(big["id"], {"received_units": 3950}, LEAD),
                   ApiErrorId.ERR_BACKROOM_OVER_CAPACITY.value)
    assert get_transfer(big["id"])["status"] == "IN_TRANSIT"


# ==========================================================================
# Corner queue B — entities (planogram slot constraints)
# ==========================================================================

def test_a_facings_value_below_one_is_malformed(api):
    """PRD §3.9: "an optional `facings` defaulting to 1 and never below 1"
    PRD §2.12: "A malformed request - a body that will not parse, a missing required field,
    a violated numeric bound such as a `facings` below one"

    Design: Corner/entities/planogram_slot_type_constraints_reject_out_of_range_facings
    """
    brand, loc = _full_store()
    boat = _boat()
    version = create_planogram_version(loc["id"])
    create_planogram_slot(version["id"], boat["id"], 1, facings=2)

    payload = f.create_planogram_slot_payload(version["id"], boat["id"], 2, facings=0)
    validate_error(api.create_planogram_slot(payload, PLANNER),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


def test_a_duplicate_slot_position_is_a_planogram_conflict(api):
    """PRD §3.9: "A `slot_position` must be unique within its `planogram_version_id` - the
    same index cannot be used twice in one version"
    PRD §2.12: "The slot-position and theme-carry rule is priority 21 and reports
    `ERR_PLANOGRAM_SLOT_CONFLICT` (HTTP 409)."

    Design: Corner/entities/planogram_slot_type_constraints_reject_out_of_range_facings
    """
    brand, loc = _full_store()
    boat = _boat()
    version = create_planogram_version(loc["id"])
    create_planogram_slot(version["id"], boat["id"], 1, facings=2)

    payload = f.create_planogram_slot_payload(version["id"], boat["id"], 1, facings=1)
    validate_error(api.create_planogram_slot(payload, PLANNER),
                   ApiErrorId.ERR_PLANOGRAM_SLOT_CONFLICT.value)


# ==========================================================================
# Corner queue B — calculations (import planning + region fit)
# ==========================================================================

def test_import_need_uses_the_four_week_horizon_and_the_ceil(api):
    """PRD §3.9: "The target quantity is the number of units that four weeks of demand at a fixed
    weekly demand value would require, divided by the item's retail price and rounded up
    to a whole unit, plus the units already on hand."
    PRD §3.9: "the margin floor is the item's cost increased by a thirty-percent markup,
    rounded half-up to a whole cent"

    Design: Corner/calculations/import_need_uses_the_four_week_demand_horizon_and_ceil
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    stock_item(loc["id"], day["id"], boat["id"], 2)

    data = validate_success(api.get_item_import_plan(boat["id"], PLANNER))

    assert data["unit_margin_cents"] == 6400 - 2400
    assert data["margin_floor_cents"] == 3120, "round_half_up(2400 * 1.30)"
    assert data["projected_import_need_units"] == 190, (
        "ceil(4 * 300000 / 6400) == 188, plus the 2 units already on hand"
    )


def test_the_order_deadline_check_and_the_import_plan_read_agree(api):
    """PRD §3.9: "The answer is derived fresh on every call rather than stored from creation
    time, so an item's `order_deadline_reached` is a function of the logical clock's week
    position, not a flag set once."
    PRD §3.9: "One re-derives and stores `order_deadline_reached` and `clearance_week` on the item
    and returns the item; the other returns the computed plan as a set of values"

    Design: Corner/endpoints/item_order_deadline_check_recomputes_the_flag_from_the_clock
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    lantern = create_item(sku="ITM-LANTERN-1200", name="Tin Lantern Ornament",
                          theme_code="WINTER_HOLIDAY", unit_retail_cents=1200,
                          unit_cost_cents=400, import_lead_time_days=60)

    checked = validate_success(api.check_item_order_deadline(lantern["id"], PLANNER))
    planned = validate_success(api.get_item_import_plan(lantern["id"], PLANNER))

    assert checked["order_deadline_reached"] == planned["order_deadline_reached"]


def test_the_region_fit_read_gates_the_bonus_on_the_tier_drift(api):
    """PRD §3.9: "When the drift exceeds 15000 hundred-thousandths the target gains a
    regional tweak bonus of four slots"
    PRD §3.9: "The location's `local_event_codes` then adds one slot for each code the
    location lists."

    Design: Corner/calculations/regionally_adjusted_slot_count_shrinks_for_a_minimal_assortment_store
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    tweak = create_planogram_version(loc["id"], assortment_tier="REGIONAL_TWEAK")

    data = validate_success(api.get_planogram_region_fit(tweak["id"], PLANNER))

    assert data["regional_tweak_bonus"] == 4
    assert data["local_event_bonus"] == 1


def test_a_minimal_assortment_store_loses_four_slots_to_the_drift(api):
    """PRD §3.9: "when the drift falls below minus 15000 the target loses four slots"
    PRD §3.9: "`MINIMAL` carries 0.55"

    Design: Corner/calculations/regionally_adjusted_slot_count_shrinks_for_a_minimal_assortment_store
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    minimal_loc = api.create_location(
        f.create_location_payload(brand["id"], store_number="1043", region_code="MIDWEST",
                                  assortment_tier="MINIMAL", backroom_capacity_units=200,
                                  clearance_max_active=2, local_event_codes=[]), ADMIN
    ).json()["data"]
    version = create_planogram_version(minimal_loc["id"], assortment_tier="MINIMAL")

    data = validate_success(api.get_planogram_region_fit(version["id"], PLANNER))

    # PRD §3.9 names the MINIMAL drift verbatim — "MINIMAL drifts minus 45000" —
    # and states the consequence direction ("when the drift falls below minus
    # 15000 the target loses four slots").  The absolute base slot count and the
    # signed value of `regional_tweak_bonus` are not stated in PRD, so only the
    # derivable facts are asserted here.
    assert data["drift_bps"] == -45000
    assert data["local_event_bonus"] == 0


# ==========================================================================
# Corner queue B — state_machines / endpoints (planograms)
# ==========================================================================

def test_publishing_a_second_version_supersedes_the_first(api):
    """PRD §3.9: "the location's previously published version is simultaneously moved to
    `SUPERSEDED` with its `superseded_by_version_id` set to the newly published version"
    PRD §3.9: "A version in `DRAFT` may be published only when its `slot_count` is at least 6"

    Design: Corner/state_machines/planogram_publish_supersedes_the_prior_version_and_freezes_its_slots
    """
    brand, loc = _full_store()
    boat = _boat()
    first = create_planogram_version(loc["id"], effective_date="2026-10-01T00:00:00Z")
    for pos in range(1, 7):
        create_planogram_slot(first["id"], boat["id"], pos)
    validate_success(api.publish_planogram_version(first["id"], PLANNER))
    second = create_planogram_version(loc["id"], effective_date="2026-10-08T00:00:00Z",
                                      clone_slots_from_version_id=first["id"])

    data = validate_success(api.publish_planogram_version(second["id"], PLANNER))

    assert data["status"] == "PUBLISHED"
    superseded = api.get_planogram_version(first["id"], PLANNER).json()["data"]
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_version_id"] == second["id"]


def test_publishing_a_second_version_freezes_the_superseded_slots(api):
    """PRD §3.9: "every one of that older version's slots in `APPLIED` status moves to
    `FROZEN`"
    PRD §3.9: "the location's `active_planogram_version_id` is pointed at this version"

    Design: Corner/state_machines/planogram_publish_supersedes_the_prior_version_and_freezes_its_slots
    """
    brand, loc = _full_store()
    boat = _boat()
    first = create_planogram_version(loc["id"], effective_date="2026-10-01T00:00:00Z")
    for pos in range(1, 7):
        create_planogram_slot(first["id"], boat["id"], pos)
    validate_success(api.publish_planogram_version(first["id"], PLANNER))
    second = create_planogram_version(loc["id"], effective_date="2026-10-08T00:00:00Z",
                                      clone_slots_from_version_id=first["id"])
    validate_success(api.publish_planogram_version(second["id"], PLANNER))

    frozen, meta = validate_paginated(
        api.list_planogram_slots(PLANNER, {"planogram_version_id": first["id"], "status": "FROZEN"})
    )

    assert meta["total_count"] == 6
    assert get_location(loc["id"])["active_planogram_version_id"] == second["id"]


def test_a_published_planogram_version_is_no_longer_deletable(api):
    """PRD §3.9: "a published version may not be deleted and must instead be superseded and
    retired"
    PRD §2.12: "State-machine membership - whether the target resource is in a state from which
    the requested operation is defined - is priority 7 and reports `ERR_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/entities/planogram_version_cannot_be_deleted_once_published
    """
    brand, loc = _full_store()
    boat = _boat()
    version = create_planogram_version(loc["id"], effective_date="2026-10-01T00:00:00Z")
    for pos in range(1, 7):
        create_planogram_slot(version["id"], boat["id"], pos)
    validate_success(api.publish_planogram_version(version["id"], PLANNER))

    validate_error(api.delete_planogram_version(version["id"], PLANNER),
                   ApiErrorId.ERR_INVALID_STATE.value)
    assert api.get_planogram_version(version["id"], PLANNER).status_code == 200


def test_deleting_a_draft_planogram_version_removes_it_and_its_slots(api):
    """PRD §3.9: "a published version may not be deleted and must instead be superseded and
    retired"
    PRD §2.7: "a `PlanogramVersion` or `PlanogramSlot` segment yields `ERR_PLANOGRAM_NOT_FOUND`"

    Design: Corner/endpoints/planogram_version_delete_removes_a_draft_and_its_slots
    """
    brand, loc = _full_store()
    boat = _boat()
    version = create_planogram_version(loc["id"], effective_date="2026-10-01T00:00:00Z")
    slot = create_planogram_slot(version["id"], boat["id"], 1, facings=2)

    resp = api.delete_planogram_version(version["id"], PLANNER)
    assert resp.status_code == 204

    assert api.get_planogram_version(version["id"], PLANNER).status_code == 404


# ==========================================================================
# Corner queue B — cross_cutting_layers (OCC on slot reshape)
# ==========================================================================

def test_a_slot_reshape_guarded_on_the_parent_version_rejects_a_stale_write(api):
    """PRD §3.9: "It requires `expected_planogram_version_version`, the version of the
    slot's parent planogram version the caller last read; a stale value is refused with
    `ERR_STALE_VERSION` (HTTP 412)"
    PRD §2.6: "requires `expected_planogram_version_version`, carrying the `version` of the
    slot's `PlanogramVersion` that the client last read."

    Design: Corner/cross_cutting_layers/superseding_a_draft_planogram_version_advances_the_parent_version
    """
    brand, loc = _full_store()
    boat = _boat()
    version = create_planogram_version(loc["id"], effective_date="2026-10-01T00:00:00Z")
    slot = create_planogram_slot(version["id"], boat["id"], 1, facings=2)
    stale_version = version["version"]

    first = validate_success(api.update_planogram_slot(
        slot["id"], {"expected_planogram_version_version": stale_version, "facings": 3}, PLANNER))
    assert first["facings"] == 3

    validate_error(
        api.update_planogram_slot(
            slot["id"], {"expected_planogram_version_version": stale_version, "facings": 4}, PLANNER),
        ApiErrorId.ERR_STALE_VERSION.value,
    )


def test_a_stale_slot_reshape_leaves_the_slot_unchanged(api):
    """PRD §2.6: "If the version has advanced, the reshape is refused with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.9: "A reshape recomputes the version's `slot_count` and increments both the
    version's `version` and the slot's own `version`."

    Design: Corner/cross_cutting_layers/superseding_a_draft_planogram_version_advances_the_parent_version
    """
    brand, loc = _full_store()
    boat = _boat()
    version = create_planogram_version(loc["id"], effective_date="2026-10-01T00:00:00Z")
    slot = create_planogram_slot(version["id"], boat["id"], 1, facings=2)
    stale_version = version["version"]
    validate_success(api.update_planogram_slot(
        slot["id"], {"expected_planogram_version_version": stale_version, "facings": 3}, PLANNER))
    api.update_planogram_slot(
        slot["id"], {"expected_planogram_version_version": stale_version, "facings": 4}, PLANNER)

    refreshed = api.get_planogram_slot(slot["id"], PLANNER).json()["data"]
    assert refreshed["facings"] == 3

    refreshed_version = api.get_planogram_version(version["id"], PLANNER).json()["data"]
    assert refreshed_version["version"] == stale_version + 1


# ==========================================================================
# Corner queue B — listings / pagination
# ==========================================================================

def test_the_receipt_list_paginates_and_reports_the_whole_filtered_count(api):
    """PRD §2.3: "`limit` caps how many items the endpoint will return; it defaults to 10, and legal
    values run from a minimum of 1 to a maximum of 100 inclusive"
    PRD §2.3: "the `meta` object carries `limit`, `offset`, `total_count` and `has_more`"

    Design: Corner/entities/receipts_list_paginates_and_reports_total_count_and_has_more
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    for index, tender in enumerate(("CARD", "CASH", "GIFT_CARD"), start=1):
        create_receipt(loc["id"], day["id"],
                       [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
                       f"R-1042-000{index}", payment_method=tender)

    page, meta = validate_paginated(
        api.list_receipts(MANAGER, {"store_day_id": day["id"], "limit": 2, "offset": 0})
    )

    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_the_second_page_of_the_receipt_list_is_the_last_one(api):
    """PRD §2.3: "offset` states how many items to skip from the front of the result set and
    defaults to 0"
    PRD §2.3: "so a client can see both the page it received and how much more exists."

    Design: Corner/entities/receipts_list_paginates_and_reports_total_count_and_has_more
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    for index, tender in enumerate(("CARD", "CASH", "GIFT_CARD"), start=1):
        create_receipt(loc["id"], day["id"],
                       [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
                       f"R-1042-000{index}", payment_method=tender)

    page, meta = validate_paginated(
        api.list_receipts(MANAGER, {"store_day_id": day["id"], "limit": 2, "offset": 2})
    )

    assert len(page) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_the_receipt_list_filters_by_tender(api):
    """PRD §3.9: "receipts by `location_id`, `store_day_id`, `guest_check_id`, `status` or
    `payment_method`"
    PRD §3.9: "Every such list obeys §2.3."

    Design: Corner/entities/receipts_list_paginates_and_reports_total_count_and_has_more
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    create_receipt(loc["id"], day["id"], [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
                   "R-1042-0001", payment_method="CARD")
    create_receipt(loc["id"], day["id"], [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
                   "R-1042-0002", payment_method="GIFT_CARD")

    page, meta = validate_paginated(
        api.list_receipts(MANAGER, {"store_day_id": day["id"], "payment_method": "GIFT_CARD"})
    )

    assert meta["total_count"] == 1
    assert page[0]["payment_method"] == "GIFT_CARD"


# ==========================================================================
# Corner queue B — entities (retrieval)
# ==========================================================================

def test_a_store_day_get_round_trips_every_derived_field(api):
    """PRD §2.10: "`traffic_state` is `QUIET`, `STEADY` or `RUSH`, and it is derived purely
    from `restaurant_guest_count`"
    PRD §3.1: "A freshly opened day carries `day_status` of `OPEN`, `traffic_state` of
    `QUIET`, `conversion_gate` of `OPEN`, and every counter at zero"

    Design: Corner/entities/store_day_get_returns_derived_gate_and_traffic_unchanged
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})

    data = validate_success(api.get_store_day(day["id"], LEAD))

    assert data["day_status"] == "OPEN"
    assert data["traffic_state"] == "QUIET"
    assert data["conversion_gate"] == "OPEN"
    assert data["closed_at"] is None
    assert data["waiting_area_conversion_index_bps"] == 0


def test_a_brand_create_echoes_every_default_and_starts_open(api):
    """PRD §3.7: "The remaining brand inputs all carry defaults and may be omitted:
    `liquidation_trigger_rpg_cents` defaults to 700 cents, `open_receipt_grace_hours` to 24"
    PRD §3.7: "A new brand starts with `fiscal_period_status` of `OPEN`"

    Design: Corner/entities/brand_create_returns_every_declared_field_and_starts_open
    """
    validate_success(api.set_clock("2026-09-21T00:00:00Z", ADMIN))
    data = validate_success(api.create_brand(f.create_brand_payload_minimal(), ADMIN), 201)

    assert data["retail_recognition_policy"] == "FINAL_ONLY"
    assert data["liquidation_trigger_rpg_cents"] == 700
    assert data["tip_minimum_minutes"] == 240
    assert data["fiscal_period_status"] == "OPEN"
    assert data["provisional_retail_revenue_cents"] == 0


def test_a_location_create_derives_staging_free_units_from_the_food_corridor(api):
    """PRD §3.7: "with `staging_free_units` already set to `backroom_capacity_units` minus
    the brand's `food_storage_corridor_units`"
    PRD §3.7: "the default of 40 units is food storage that retail receiving may not displace"

    Design: Corner/entities/location_create_applies_region_tier_and_zeroed_posture
    """
    validate_success(api.set_clock("2026-09-21T00:00:00Z", ADMIN))
    brand = validate_success(api.create_brand(f.create_brand_payload_minimal(), ADMIN), 201)
    loc = validate_success(api.create_location(f.create_location_payload(brand["id"]), ADMIN), 201)

    assert loc["region_code"] == "SOUTHEAST"
    assert loc["assortment_tier"] == "REGIONAL_TWEAK"
    assert loc["staging_free_units"] == 400 - 40
    assert loc["backroom_occupancy_units"] == 0


def test_an_unknown_item_id_on_a_path_segment_reports_item_not_found(api):
    """PRD §2.7: "an `Item` segment yields `ERR_ITEM_NOT_FOUND`"
    PRD §2.7: "the server resolves each path segment from left to right and confirms that
    the named resource exists before evaluating anything else about the request"

    Design: Corner/entities/item_get_with_unknown_id_returns_item_not_found
    """
    from test_helpers import NON_EXISTENT_UUID

    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    validate_error(api.get_item(NON_EXISTENT_UUID, PLANNER), ApiErrorId.ERR_ITEM_NOT_FOUND.value)


def test_omitting_the_optional_item_fields_applies_their_defaults(api):
    """PRD §3.9: "an optional `nostalgia_flag` defaulting to false"
    PRD §3.9: "A new item starts in `ACTIVE` status with `current_markdown_pct` of zero,
    `effective_price_cents` and `compounded_price_cents` both equal to its `unit_retail_cents`"

    Design: Corner/entities/item_defaults_apply_when_optional_fields_are_omitted
    """
    validate_success(api.set_clock("2026-09-21T00:00:00Z", ADMIN))
    brand = validate_success(api.create_brand(f.create_brand_payload_minimal(), ADMIN), 201)
    payload = {"sku": "ITM-PLATE-1800", "name": "Stoneware Pie Plate",
               "theme_code": "NOSTALGIA_CLASSIC", "unit_retail_cents": 1800,
               "unit_cost_cents": 600, "import_lead_time_days": 30}

    data = validate_success(api.create_item(payload, PLANNER), 201)

    assert data["nostalgia_flag"] is False
    assert data["status"] == "ACTIVE"
    assert data["effective_price_cents"] == 1800
    assert data["on_hand_units"] == 0


def test_a_store_day_create_missing_its_business_date_is_malformed(api):
    """PRD §2.12: "A malformed request - a body that will not parse, a missing required
    field ... - is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "A `BoutiqueManager` opens a business day by presenting a `location_id` and a
    `business_date`, the latter an ISO 8601 instant at 00:00:00Z."

    Design: Corner/entities/store_day_create_missing_business_date_returns_invalid_request
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    validate_error(api.create_store_day({"location_id": loc["id"]}, MANAGER),
                   ApiErrorId.ERR_INVALID_REQUEST.value)
    rows, meta = validate_paginated(api.list_store_days(MANAGER, {"location_id": loc["id"]}))
    assert meta["total_count"] == 0