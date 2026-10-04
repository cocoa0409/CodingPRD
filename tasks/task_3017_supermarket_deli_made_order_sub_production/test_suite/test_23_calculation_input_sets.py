"""Which rows enter each store-level aggregate, and at what rounding point."""

from test_helpers import (
    api_client,
    clerk_headers,
    create_waste_record,
    get_success_data,
    manager_headers,
    platform_admin_headers,
    produce_batch,
    scale_operator_headers,
    set_clock,
    setup_deli_master_data,
    setup_price_file,
    validate_success,
)

LIABILITY_ITEM = {
    "sku": "CC-PROSC-99",
    "name": "Prosciutto",
    "category": "COLD_CUT",
    "unit_cost_cents": 1000,
    "retail_price_per_lb_cents": 1499,
    "case_life_minutes": 120,
    "markdown_window_minutes": 0,
    "allergen_flags": ["MILK"],
    "slicer_required": False,
}


def test_label_total_rounds_half_up_at_the_tie():
    """PRD §3.6: "a derived `total_price_cents` equal to the net weight multiplied
    by the unit price, rounded half up to a whole cent."

    1.2345 x 899 = 1109.81 and 1.2350 x 899 = 1110.26, so the tie-break resolves
    upward rather than to even.

    Design: Corner/calculations/label_total_rounds_half_up_at_the_five_milli_lb_tie
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(slicer_count=1)
    price_file = master.price_file

    lower = validate_success(
        api_client.create_label(
            {"store_id": master.s, "subject_type": "PRODUCTION_BATCH",
             "subject_ref_id": master.j2["id"], "net_weight_lbs": 1.234, "unit_price_cents": 899},
            scale_operator_headers(),
        ),
        expected_status=201,
    )
    upper = validate_success(
        api_client.create_label(
            {"store_id": master.s, "subject_type": "PRODUCTION_BATCH",
             "subject_ref_id": master.j2["id"], "net_weight_lbs": 1.235, "unit_price_cents": 899},
            scale_operator_headers(),
        ),
        expected_status=201,
    )
    assert lower["total_price_cents"] == 1109
    assert upper["total_price_cents"] == 1110
    assert lower["price_file_id"] == price_file["id"]
    assert upper["price_file_id"] == price_file["id"]


def test_protection_index_counts_only_unlapsed_live_rows():
    """PRD §2.7: "each `Associate` in the store whose `status` is ACTIVE but who
    holds no `Certification` of type `SLICER_OPERATION` with `status` ACTIVE and
    an `expires_at` strictly after the logical clock subtracts 12; each
    `WasteRecord` in the store sitting in `DRAFT`, `MARKED_DOWN` or `DISCARDED`
    subtracts 6; each `SlicerAsset` in the store whose `sanitation_status` is
    `NEEDS_SANITATION` subtracts 4."
    PRD §2.7: "The subtraction result is then clamped at a floor of zero, so the
    protection index is never negative."

    Design: Corner/calculations/attendance_health_excludes_abandoned_and_expired_rows
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=420, store_number="101", store_name="Store One",
                                    slicer_count=1)

    for index in range(1, 10):
        associate = get_success_data(
            api_client.create_associate(
                {"store_id": master.s, "employee_number": f"E-20{index:02d}",
                 "full_name": f"Lapsed {index}", "primary_role": "DELI_CLERK"},
                platform_admin_headers(),
            )
        )
        get_success_data(
            api_client.create_certification(
                {"store_id": master.s, "associate_id": associate["id"],
                 "cert_type": "SLICER_OPERATION", "issued_at": "2026-09-01T00:00:00Z",
                 "expires_at": "2026-10-01T00:00:00Z"},
                platform_admin_headers(),
            )
        )

    slicer = master.slicers[0]
    for index in range(1, 4):
        produce_batch(master.s, master.j2["id"], master.a1["id"], f"B-{index:02d}", 125,
                      produced_lbs=125, slicer_id=slicer["id"])

    set_clock("2026-11-01T00:00:00Z")
    report = validate_success(api_client.get_posture_report(master.s, platform_admin_headers()))
    assert report["protection_index"] == 0, (
        "nine lapsed certifications at 12 each plus the clamped floor bottom the score out"
    )
    assert report["diffusion_index"] == 100
    assert report["posture_reason"] == "REVOCATION_TRIGGERED"
    assert report["certified_slicer_operator_count"] == 1, (
        "only the certification that has not lapsed counts toward the store's staffing"
    )


def test_store_liability_excludes_unclaimed_platter_rows():
    """PRD §3.3: "The store's total waste liability sums `total_liability_cents`
    over every waste record in the store whose status is `DISCARDED` or
    `VERIFIED`, whose creation instant is strictly before the logical clock —
    records created at exactly the clock instant are excluded — and whose
    `reason` is not `UNCLAIMED_PLATTER`."
    PRD §3.3: "Records in `DRAFT` or `VOIDED` contribute nothing to either figure."

    Design: Corner/calculations/waste_liability_input_set_excludes_unclaimed_platters
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=0)
    item = validate_success(
        api_client.create_item(LIABILITY_ITEM, platform_admin_headers()), expected_status=201)

    first = produce_batch(master.s, item["id"], master.a1["id"], "B-500", 5, produced_lbs=5)
    second = produce_batch(master.s, item["id"], master.a1["id"], "B-1300", 13, produced_lbs=13)
    third = produce_batch(master.s, item["id"], master.a1["id"], "B-6200", 20, produced_lbs=20)

    # LIABILITY_ITEM has markdown_window_minutes=0, and PRD 3.3 permits the
    # direct discard from DRAFT once the markdown window has closed, so the clock
    # moves past the batches' 120 minute case life first.
    set_clock("2026-09-02T08:30:00Z")
    records = [
        create_waste_record(master.s, batch["id"], master.a2["id"], reason=reason,
                            acting_associate_id=master.a1["id"])
        for batch, reason in ((first, "QUALITY"), (second, "QUALITY"), (third, "UNCLAIMED_PLATTER"))
    ]
    for record, pounds in zip(records, (5, 13, 20)):
        validate_success(
            api_client.discard_waste_record(record["id"], pounds, clerk_headers(master.a1["id"]))
        )

    first_now = validate_success(api_client.get_waste_record(records[0]["id"], platform_admin_headers()))
    second_now = validate_success(api_client.get_waste_record(records[1]["id"], platform_admin_headers()))
    third_now = validate_success(api_client.get_waste_record(records[2]["id"], platform_admin_headers()))
    assert first_now["total_liability_cents"] == 5000
    assert second_now["total_liability_cents"] == 13250
    assert third_now["total_liability_cents"] == 20250, (
        "the unclaimed-platter row is priced but excluded from the store aggregate"
    )

    store = validate_success(api_client.get_store(master.s, platform_admin_headers()))
    assert store["verified_waste_liability_cents"] == 0, "nothing has been verified yet"
    assert store["pending_waste_verification_count"] == 3, (
        "the unclaimed-platter row is still counted for verification scheduling"
    )


def test_the_fee_tier_is_selected_from_the_blended_discounted_base():
    """PRD §3.3: "Third, a discounted base is computed as 0.70 multiplied by
    `discard_value_cents`, plus 0.30 multiplied by that prior-liability base,
    rounded half up to whole cents."
    PRD §3.3: "A discounted base at or above 5000 cents and below 15000 cents
    takes a fee of 250 cents."

    A first record of 5.0 lbs on 1000-cent stock settles at 5000 cents, so the
    next record's base of 0.70 * 13000 + 0.30 * 5000 = 10600 lands in the second
    tier rather than the first, while the raw 13000 alone would not.

    Design: Corner/calculations/prior_tier_base_boundary_at_exactly_five_thousand
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=300, store_number="103", store_name="Store Three",
                                    slicer_count=0)
    item = validate_success(api_client.create_item(LIABILITY_ITEM, platform_admin_headers()), expected_status=201)
    small = produce_batch(master.s, item["id"], master.a1["id"], "B-500", 5, produced_lbs=5)
    large = produce_batch(master.s, item["id"], master.a1["id"], "B-1300", 13, produced_lbs=13)

    first = create_waste_record(master.s, small["id"], master.a2["id"], reason="QUALITY",
                                acting_associate_id=master.a1["id"])
    settled = validate_success(
        api_client.discard_waste_record(first["id"], 5, clerk_headers(master.a1["id"]))
    )
    assert settled["total_liability_cents"] == 5000, "the prior tier base is a settled 5000"

    second = create_waste_record(master.s, large["id"], master.a2["id"], reason="QUALITY",
                                 acting_associate_id=master.a1["id"])
    priced = validate_success(
        api_client.discard_waste_record(second["id"], 13, clerk_headers(master.a1["id"]))
    )
    assert priced["discard_value_cents"] == 13000
    assert priced["handling_fee_cents"] == 250, (
        "the tier is selected from the blended base rather than from the raw discard value"
    )


def test_bread_demand_rounds_the_forecast_and_the_waste_factor_before_case_rounding():
    """PRD §3.5: "Forecast units are the baseline multiplied by one plus the raw
    uplift, rounded half up to a whole number of units. Bread units are the
    forecast units plus the forecast units multiplied by a bread waste factor of
    0.12, also rounded half up to a whole number. Finally, `required_bread_units`
    is the bread units divided by 12 units per case, rounded up to the next whole
    case, then multiplied back by 12."

    Design: Corner/calculations/promotion_bread_demand_rounds_then_ceils_to_full_cases
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)

    # PRD §3.5 requires the clock to sit inside the half-open week to activate.
    set_clock("2026-09-08T00:00:00Z")
    # baseline * 1.10, +12%, then ceil to whole cases of 12.
    expected = {
        600: 744,
        636: 792,
        672: 828,
        720: 888,
        1500: 1848,
    }
    results = {}
    for baseline in expected:
        promotion = get_success_data(
            api_client.create_promotion(
                {
                    "promo_code": f"FEAT-{baseline}",
                    "deli_item_id": master.j1["id"],
                    "week_start_date": "2026-09-07T00:00:00Z",
                    "week_end_date": "2026-09-14T00:00:00Z",
                    "forecast_uplift_pct": 0.1,
                    "trailing_baseline_units": baseline,
                },
                platform_admin_headers(),
            )
        )
        activated = validate_success(
            api_client.activate_promotion(promotion["id"], manager_headers(master.a2["id"]))
        )
        results[baseline] = activated["required_bread_units"]

    assert results == expected
    assert all(value % 12 == 0 for value in results.values()), (
        "every demand figure is a whole number of cases"
    )


def test_catering_quote_applies_tier_then_adjustment_then_rush():
    """PRD §3.7: "The base total is the `platter_count` multiplied by the chosen
    per-platter rate. The service fee is the base total multiplied by the
    adjustment rate, rounded half up to a whole cent — and this is the only
    rounding in the whole computation. The rush fee is 2600 cents when
    `lead_time_hours` is below 24, and zero otherwise."
    PRD §3.7: "The certified-planner adjustment is a rate of negative five percent
    when the order's `lead_time_hours` is below 24 and the
    `certified_planner_associate_id` holds an ACTIVE `FOOD_HANDLING`
    certification, and zero percent otherwise."

    Design: Corner/calculations/catering_quote_evaluation_order_tier_then_adjustment_then_rush
    """
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=240, store_number="102", store_name="Store Two",
                                    slicer_count=0)

    rush = get_success_data(
        api_client.create_catering_order(
            {"store_id": master.s, "platter_deli_item_id": master.p1["id"],
             "customer_name": "Rush Party", "platter_count": 7, "headcount": 12,
             "lead_time_hours": 6, "pickup_window_start": "2026-09-02T12:00:00Z",
             "pickup_window_end": "2026-09-02T12:30:00Z", "deposit_cents": 5000,
             "certified_planner_associate_id": master.a1["id"], "request_id": "REQ-RUSH"},
            clerk_headers(master.a1["id"]),
        )
    )
    planned = get_success_data(
        api_client.create_catering_order(
            {"store_id": master.s, "platter_deli_item_id": master.p1["id"],
             "customer_name": "Planned Party", "platter_count": 7, "headcount": 12,
             "lead_time_hours": 30, "pickup_window_start": "2026-09-04T12:00:00Z",
             "pickup_window_end": "2026-09-04T12:30:00Z", "deposit_cents": 5000,
             "certified_planner_associate_id": master.a1["id"], "request_id": "REQ-PLAN"},
            clerk_headers(master.a1["id"]),
        )
    )

    rush_confirmed = validate_success(
        api_client.confirm_catering_order(rush["id"], clerk_headers(master.a1["id"]))
    )
    planned_confirmed = validate_success(
        api_client.confirm_catering_order(planned["id"], clerk_headers(master.a1["id"]))
    )
    assert rush_confirmed["quote_total_cents"] == 12575, (
        "seven platters take the 1500 cent tier, then the certified discount, then the rush fee"
    )
    assert planned_confirmed["quote_total_cents"] == 10500, (
        "the same count above the rush limit takes neither the adjustment nor the rush fee"
    )
    assert rush_confirmed["quote_total_cents"] - planned_confirmed["quote_total_cents"] == 2075, (
        "the rush order differs by the 2600 cent rush fee less the 525 cent discount"
    )