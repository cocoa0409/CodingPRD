"""Shipments, embargo penalties, oversell, and retailer ledger invariants."""
from test_helpers import (
    ApiErrorId,
    BRAND,
    assert_shipment,
    create_commitment,
    create_evergreen_line,
    create_shipment,
    create_sku,
    fixtures,
    make_retailer_ops_headers,
    record_sale,
    set_clock,
    setup_evergreen_line_with_sku,
    setup_retail_open_review,
    setup_review_with_commitment,
    validate_error,
    validate_success,
)


def _get_retailer(api, retailer_id):
    return validate_success(api.get_retailer(retailer_id, BRAND))


def _get_shipment(api, shipment_id):
    return validate_success(api.get_shipment(shipment_id, BRAND))


def test_record_sale_after_street_date_assesses_no_penalty(api):
    """PRD §3.7: "If the clock is at or after the shipment's `street_date`, no
    penalty arises and `penalty_status` stays `NONE`."

    Design: Corner/state_machines/shipment_record_sale_after_street_date_assesses_no_penalty
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku(street="2026-09-01T00:00:00Z")
    retailer, review, commitment = setup_review_with_commitment(
        sku, committed_units=500, unit_price_cents=100, shelf_slots=4
    )
    shipment = create_shipment(commitment["id"], planned_ship_date="2026-09-01T00:00:00Z", units=500)

    resp = api.record_sale(shipment["id"], {"units_sold": 200}, make_retailer_ops_headers(retailer["id"]))
    data = validate_success(resp)
    assert_shipment(data)
    assert data["status"] == "SOLD"
    assert data["sold_units"] == 200
    assert data["penalty_cents"] == 0
    assert data["penalty_status"] == "NONE"

    retailer_data = _get_retailer(api, retailer["id"])
    assert retailer_data["credit_balance_cents"] == 0
    assert retailer_data["violation_count"] == 0


def test_shipment_oversold_rejected_on_repeat_record_sale(api):
    """PRD §3.7: "Additional recordings on an already-`SOLD` shipment accumulate:
    `units_sold` must be at least 1, and the running total `sold_units` plus
    `units_sold` must not exceed the shipment's `units`, or the recording is
    rejected with `ERR_SHIPMENT_OVERSOLD` (HTTP 422)."

    Design: Corner/validations/shipment_oversold_rejected_on_repeat_record_sale
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku(street="2026-09-01T00:00:00Z")
    retailer, review, commitment = setup_review_with_commitment(
        sku, committed_units=1000, unit_price_cents=100, shelf_slots=4
    )
    shipment = create_shipment(commitment["id"], planned_ship_date="2026-09-01T00:00:00Z", units=1000)
    record_sale(shipment["id"], retailer, 800)

    resp = api.record_sale(shipment["id"], {"units_sold": 300}, make_retailer_ops_headers(retailer["id"]))
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_OVERSOLD, expected_status=422)


def test_embargo_penalty_first_vs_repeat_offender_rates(api):
    """PRD §3.7: "The rate depends on the retailer's history at assessment time, not
    on the shipment: a retailer whose `violation_count` is below 2 pays 10% of that
    base, while a retailer at 2 or more prior penalties pays 25%, with the result
    rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/embargo_penalty_first_vs_repeat_offender
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku(street="2027-01-01T00:00:00Z")

    # Dirty retailer: build violation_count 2 via two pre-street breaches.
    dirty, dirty_review, dirty_commitment = setup_review_with_commitment(
        sku,
        retailer_name="DirtyDiscounter",
        shelf_slots_total=50,
        committed_units=3000,
        unit_price_cents=100,
        shelf_slots=6,
    )
    sh_d1 = create_shipment(dirty_commitment["id"], units=1000)
    sh_d2 = create_shipment(dirty_commitment["id"], units=1000)
    sh_d3 = create_shipment(dirty_commitment["id"], units=1000)
    record_sale(sh_d1["id"], dirty, 10)
    record_sale(sh_d2["id"], dirty, 10)

    # Clean retailer.
    clean, clean_review, clean_commitment = setup_review_with_commitment(
        sku,
        retailer_name="CleanMart",
        shelf_slots_total=50,
        committed_units=1000,
        unit_price_cents=100,
        shelf_slots=4,
    )
    sh_c = create_shipment(clean_commitment["id"], units=1000)

    resp_d = api.record_sale(sh_d3["id"], {"units_sold": 1000}, make_retailer_ops_headers(dirty["id"]))
    data_d = validate_success(resp_d)
    assert data_d["penalty_cents"] == 25000  # 1000*100 * 0.25 repeat tier

    resp_c = api.record_sale(sh_c["id"], {"units_sold": 1000}, make_retailer_ops_headers(clean["id"]))
    data_c = validate_success(resp_c)
    assert data_c["penalty_cents"] == 10000  # 1000*100 * 0.10 first tier

    dirty_data = _get_retailer(api, dirty["id"])
    clean_data = _get_retailer(api, clean["id"])
    assert dirty_data["violation_count"] == 3
    assert clean_data["violation_count"] == 1

    pen_d1 = _get_shipment(api, sh_d1["id"])["penalty_cents"]
    pen_d2 = _get_shipment(api, sh_d2["id"])["penalty_cents"]
    assert dirty_data["credit_balance_cents"] == -(pen_d1 + pen_d2 + 25000)


def test_embargo_penalty_assessed_and_waived_restores_ledger(api):
    """PRD §3.7: "A `BrandManager` may waive an `OPEN` penalty: `penalty_status`
    moves to `WAIVED`, the retailer's `credit_balance_cents` is credited back
    exactly the shipment's `penalty_cents`, and the shipment's `version` increments.
    Waiving never decrements `violation_count`".

    Design: Difficulty/compensating_invariant/embargo_penalty_waive_restores_retailer_ledger
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku(street="2027-01-01T00:00:00Z")
    retailer, review, commitment = setup_review_with_commitment(
        sku, committed_units=1000, unit_price_cents=100, shelf_slots=4
    )
    shipment = create_shipment(commitment["id"], units=1000)

    resp = api.record_sale(shipment["id"], {"units_sold": 500}, make_retailer_ops_headers(retailer["id"]))
    data = validate_success(resp)
    assert data["penalty_cents"] == 5000  # 500*100 * 0.10
    assert data["penalty_status"] == "OPEN"
    retailer_data = _get_retailer(api, retailer["id"])
    assert retailer_data["credit_balance_cents"] == -5000

    resp = api.waive_penalty(shipment["id"], {}, BRAND)
    waived = validate_success(resp)
    assert waived["penalty_status"] == "WAIVED"
    retailer_data = _get_retailer(api, retailer["id"])
    assert retailer_data["credit_balance_cents"] == 0
    assert retailer_data["violation_count"] == 1


def test_embargo_repeat_sale_reassessed_on_cumulative_units(api):
    """PRD §3.7: "A repeat early sale on the same shipment re-assesses the penalty
    against the new cumulative `sold_units`."

    Design: Difficulty/dual_variant_calc/embargo_penalty_first_vs_repeat_offender
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku(street="2027-01-01T00:00:00Z")
    retailer, review, commitment = setup_review_with_commitment(
        sku, committed_units=1000, unit_price_cents=100, shelf_slots=4
    )
    shipment = create_shipment(commitment["id"], units=1000)

    first = validate_success(
        api.record_sale(shipment["id"], {"units_sold": 100}, make_retailer_ops_headers(retailer["id"]))
    )
    # First breach: 100*100*0.10 = 1000.
    assert first["penalty_cents"] == 1000

    second = validate_success(
        api.record_sale(shipment["id"], {"units_sold": 100}, make_retailer_ops_headers(retailer["id"]))
    )
    # Re-assessed on cumulative 200 sold units at the 10% first-tier rate
    # (violation_count was 1 at assessment time): 200*100*0.10 = 2000.
    assert second["penalty_cents"] == 2000
    assert second["sold_units"] == 200

    retailer_data = _get_retailer(api, retailer["id"])
    assert retailer_data["violation_count"] == 2


def test_embargo_waive_twice_leaves_ledger_unchanged(api):
    """PRD §3.7: "Waiving never decrements `violation_count` — the count of penalties
    ever assessed is monotonic, so an assess-then-waive cycle nets the ledger to
    zero drift while still leaving the retailer one step closer to the
    repeat-offender tier. Attempting to waive when no penalty is `OPEN` yields
    `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/embargo_penalty_waive_restores_retailer_ledger
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku(street="2027-01-01T00:00:00Z")
    retailer, review, commitment = setup_review_with_commitment(
        sku, committed_units=1000, unit_price_cents=100, shelf_slots=4
    )
    shipment = create_shipment(commitment["id"], units=1000)

    record_sale(shipment["id"], retailer, 500)
    validate_success(api.waive_penalty(shipment["id"], {}, BRAND))
    # Second waive: penalty is no longer OPEN.
    resp = api.waive_penalty(shipment["id"], {}, BRAND)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    retailer_data = _get_retailer(api, retailer["id"])
    assert retailer_data["credit_balance_cents"] == 0
    assert retailer_data["violation_count"] == 1
