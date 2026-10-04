"""Waste liability: the discount base reads earlier records' settled totals."""

from test_helpers import (
    api_client,
    clerk_headers,
    create_waste_record,
    get_success_data,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    validate_success,
)

ITEM = {
    "sku": "CC-PROSC-01",
    "name": "Prosciutto",
    "category": "COLD_CUT",
    "unit_cost_cents": 1000,
    "retail_price_per_lb_cents": 1499,
    "case_life_minutes": 120,
    "markdown_window_minutes": 0,
    "allergen_flags": ["MILK"],
    "slicer_required": False,
}


def _setup_two_records():
    """Two held batches of 1000-cent stock whose markdown window never opens, so a
    direct discard from DRAFT is legal, and one DRAFT waste record per batch."""
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=0)
    item = validate_success(
        api_client.create_item(ITEM, platform_admin_headers()), expected_status=201
    )
    small = produce_batch(master.s, item["id"], master.a1["id"], "B-020", 5, produced_lbs=5)
    large = produce_batch(master.s, item["id"], master.a1["id"], "B-021", 13, produced_lbs=13)

    set_clock("2026-09-02T09:00:00Z")
    small_record = create_waste_record(
        master.s, small["id"], master.a2["id"], reason="QUALITY",
        acting_associate_id=master.a1["id"],
    )
    large_record = create_waste_record(
        master.s, large["id"], master.a2["id"], reason="QUALITY",
        acting_associate_id=master.a1["id"],
    )
    return master, small_record, large_record


def test_first_discard_tiers_against_an_empty_prior_settled_base():
    """PRD §3.3: "Second, a prior-liability base is accumulated over every other
    waste record in the same store whose creation instant is strictly before this
    record's creation instant — records sharing the identical creation instant
    are excluded — and whose status is `VERIFIED` or one of `DISCARDED` and
    `MARKED_DOWN`; records whose `reason` is `UNCLAIMED_PLATTER` are excluded
    from this accumulation entirely."
    PRD §3.3: "A discounted base below 5000 cents takes a fee of 0 cents."

    Design: Difficulty/combinatorial_formula/waste_liability_prior_record_order_dependency
    """
    master, small_record, _ = _setup_two_records()
    first = validate_success(
        api_client.discard_waste_record(
            small_record["id"], 5, clerk_headers(master.a1["id"])
        )
    )
    assert first["discard_value_cents"] == 5000, "5.0 lbs of 1000-cent stock prices at 5000 cents"
    assert first["handling_fee_cents"] == 0, (
        "the first discard's discounted base of 3500 cents sits below the first tier"
    )
    assert first["total_liability_cents"] == 5000


def test_second_discard_reads_the_first_records_settled_total_into_its_tier_base():
    """PRD §3.3: "Third, a discounted base is computed as 0.70 multiplied by
    `discard_value_cents`, plus 0.30 multiplied by that prior-liability base,
    rounded half up to whole cents."
    PRD §3.3: "A discounted base at or above 5000 cents and below 15000 cents
    takes a fee of 250 cents."

    Design: Difficulty/combinatorial_formula/waste_liability_prior_record_order_dependency
    """
    master, small_record, large_record = _setup_two_records()
    first = validate_success(
        api_client.discard_waste_record(small_record["id"], 5, clerk_headers(master.a1["id"]))
    )
    assert first["total_liability_cents"] == 5000

    second = validate_success(
        api_client.discard_waste_record(large_record["id"], 13, clerk_headers(master.a1["id"]))
    )
    assert second["discard_value_cents"] == 13000, "13.0 lbs of 1000-cent stock"
    assert second["handling_fee_cents"] == 250, (
        "0.70 * 13000 + 0.30 * 5000 = 10600 cents, which lands in the 250-cent band"
    )
    assert second["total_liability_cents"] == 13250

    store = get_success_data(api_client.get_store(master.s, platform_admin_headers()))
    assert store["pending_waste_verification_count"] == 2, (
        "both DISCARDED records remain outstanding for verification"
    )