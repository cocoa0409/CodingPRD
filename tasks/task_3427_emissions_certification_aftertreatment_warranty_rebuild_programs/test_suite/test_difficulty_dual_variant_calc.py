"""Dual-variant calculation tests (PRD §3.7 claim proration, §3.9 core credit).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    add_maintenance_record,
    adjudicate,
    assert_claim_financials_balance,
    assert_reman_order,
    assert_service_center,
    assert_warranty_claim,
    grade_core,
    ingest_snapshot,
    set_logical_clock,
    setup_claim_under_review,
    setup_engine_unit,
    setup_full_environment,
    setup_reman_order_awaiting_core,
    setup_reman_order_core_received,
    validate_success,
)

CLAIM_CLOCK = "2026-12-01T00:00:00Z"  # 91 whole days after in-service 2026-09-01


def _environment_with_two_neglect_40_units():
    """Canonical certified program plus two units whose histories each yield a
    neglect score of 40 (1 missed 15000-mile oil interval x 25 points + 1
    DEF_SERVICE with def_quality_ok false x 15 points, no CRITICAL faults):
    UN-201 at 15000 miles / 400 hours, UN-202 at 25000 miles / 600 hours."""
    env = setup_full_environment()
    family, fleet = env["family"], env["fleet"]
    unit_time = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-201")
    unit_miles = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-202")
    ingest_snapshot(
        unit_time["id"], recorded_at="2026-10-15T00:00:00Z", odometer_miles=15000,
        engine_hours=400, fault_codes=[], def_consumption_gal=40.5, nox_sensor_drift_ppm=12,
    )
    ingest_snapshot(
        unit_miles["id"], recorded_at="2026-10-15T00:00:00Z", odometer_miles=25000,
        engine_hours=600, fault_codes=[], def_consumption_gal=62.0, nox_sensor_drift_ppm=9,
    )
    add_maintenance_record(
        unit_time["id"], fleet_id=fleet["id"], performed_at="2026-10-20T00:00:00Z",
        maintenance_type="DEF_SERVICE", odometer_at_service=14000, def_quality_ok=False,
    )
    add_maintenance_record(
        unit_miles["id"], fleet_id=fleet["id"], performed_at="2026-10-20T00:00:00Z",
        maintenance_type="DEF_SERVICE", odometer_at_service=24000, def_quality_ok=False,
    )
    set_logical_clock(CLAIM_CLOCK)
    return env, unit_time, unit_miles


def _file_and_adjudicate_pair(env, unit_time, unit_miles):
    """File one ENGINE_BASE claim on UN-201 and one AFTERTREATMENT_DPF claim on
    UN-202 (identical claimed amounts), move both to UNDER_REVIEW, and decide
    both APPROVE_PARTIAL (score 40 sits in the partial band)."""
    center = env["center"]
    claim_time = setup_claim_under_review(
        unit_time, center, failed_component_class="ENGINE_BASE",
        failure_code="FC-111", claimed_amount_cents=100000,
    )
    claim_miles = setup_claim_under_review(
        unit_miles, center, failed_component_class="AFTERTREATMENT_DPF",
        failure_code="FC-222", claimed_amount_cents=100000,
    )
    decided_time = adjudicate(claim_time["id"], "APPROVE_PARTIAL")
    decided_miles = adjudicate(claim_miles["id"], "APPROVE_PARTIAL")
    return decided_time, decided_miles


def test_base_warranty_proration_uses_elapsed_days_and_daily_rate(api, admin_headers):
    """PRD §3.7: "Under the `BASE_WARRANTY` variant the proration is time-based: the term in days is the standard's `base_warranty_years` multiplied by 365; the elapsed days are the whole days from the unit's `in_service_date` to the claim's submission instant, never negative; the daily rate is the `claimed_amount_cents` divided by the term in days, rounded half-up to whole cents; and the raw customer share is that rounded daily rate multiplied by the elapsed days."
    PRD §3.7: "A claim on a non-emissions class such as `ENGINE_BASE` can therefore only ever carry the `BASE_WARRANTY` variant."
    PRD §3.7: "Under both variants the share is then capped: the cap is half of `claimed_amount_cents` rounded half-up to whole cents, `customer_share_cents` is the smaller of the raw share and the cap, and `approved_amount_cents` is the remainder of the claim after the customer share."

    91 elapsed days from 2026-09-01 to 2026-12-01 against a 2 x 365 = 730-day
    term: daily rate round_half_up(100000 / 730) = 137, raw share 137 x 91 =
    12467 (below the 50000 cap), approved 100000 - 12467 = 87533.

    Design: Difficulty/dual_variant_calc/claim_proration_time_based_vs_mileage_based
    """
    env, unit_time, unit_miles = _environment_with_two_neglect_40_units()
    decided_time, _ = _file_and_adjudicate_pair(env, unit_time, unit_miles)

    assert_warranty_claim(decided_time)
    assert decided_time["status"] == "APPROVED_PARTIAL"
    assert decided_time["coverage_variant"] == "BASE_WARRANTY", (
        f"ENGINE_BASE claim must stamp BASE_WARRANTY, got {decided_time['coverage_variant']}"
    )
    assert decided_time["neglect_score"] == 40, (
        f"1 missed interval x 25 + 1 bad DEF x 15 = 40, got {decided_time['neglect_score']}"
    )
    assert decided_time["customer_share_cents"] == 12467, (
        f"daily rate 137 x 91 elapsed days = 12467, got {decided_time['customer_share_cents']}"
    )
    assert decided_time["approved_amount_cents"] == 87533, (
        f"100000 - 12467 = 87533, got {decided_time['approved_amount_cents']}"
    )
    assert_claim_financials_balance(decided_time)


def test_extended_emissions_proration_uses_accumulated_miles_and_per_mile_rate(api, admin_headers):
    """PRD §3.7: "Under the `EXTENDED_EMISSIONS` variant the proration is mileage-based: the term in miles is the smaller of 100,000 and the standard's `useful_life_miles`; the per-mile rate is the `claimed_amount_cents` divided by that term, rounded half-up to whole cents; and the raw customer share is the rounded per-mile rate multiplied by the unit's `accumulated_miles`."
    PRD §3.7: "When the extended window is open the claim is stamped `EXTENDED_EMISSIONS`; otherwise, when the base window is open, it is stamped `BASE_WARRANTY`; when neither window is open the filing is rejected with `ERR_COVERAGE_EXPIRED` (HTTP 409)."
    PRD §3.7: "Identical claim data therefore yields different customer shares under the two variants."

    Term min(100000, 435000) = 100000 miles: per-mile rate
    round_half_up(100000 / 100000) = 1, raw share 1 x 25000 = 25000 (below the
    50000 cap), approved 75000 — the same claimed amount and the same neglect
    score as the BASE_WARRANTY claim settle differently.

    Design: Difficulty/dual_variant_calc/claim_proration_time_based_vs_mileage_based
    """
    env, unit_time, unit_miles = _environment_with_two_neglect_40_units()
    decided_time, decided_miles = _file_and_adjudicate_pair(env, unit_time, unit_miles)

    assert_warranty_claim(decided_miles)
    assert decided_miles["status"] == "APPROVED_PARTIAL"
    assert decided_miles["coverage_variant"] == "EXTENDED_EMISSIONS", (
        "AFTERTREATMENT_DPF with all extended axes open must stamp EXTENDED_EMISSIONS, "
        f"got {decided_miles['coverage_variant']}"
    )
    assert decided_miles["neglect_score"] == 40
    assert decided_miles["customer_share_cents"] == 25000, (
        f"per-mile rate 1 x 25000 accumulated miles = 25000, got {decided_miles['customer_share_cents']}"
    )
    assert decided_miles["approved_amount_cents"] == 75000, (
        f"100000 - 25000 = 75000, got {decided_miles['approved_amount_cents']}"
    )
    assert_claim_financials_balance(decided_miles)
    assert decided_time["approved_amount_cents"] != decided_miles["approved_amount_cents"], (
        "identical claimed amounts and identical scores must settle differently across variants"
    )


def test_provisional_core_credit_is_flat_sixty_percent_posted_at_confirm(api, admin_headers):
    """PRD §3.9: "Also at creation, the `provisional_core_credit_cents` is computed as 60 percent of the `quoted_core_value_cents` (that is, the quoted core value multiplied by 0.6), rounded half-up to whole cents."
    PRD §3.9: "Confirmation moves the order from `QUOTED` to `AWAITING_CORE` and posts the provisional credit: the center's `core_credit_balance_cents` increases by `provisional_core_credit_cents`, a center mutation that increments the center's `version`."

    Quoted core value 200000 -> provisional round_half_up(200000 x 0.6) = 120000;
    after confirm the center ledger stands at exactly 120000.

    Design: Difficulty/dual_variant_calc/core_credit_provisional_vs_final
    """
    env = setup_full_environment()
    family, fleet, center = env["family"], env["fleet"], env["center"]
    unit = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-301")
    set_logical_clock(CLAIM_CLOCK)

    order = setup_reman_order_awaiting_core(
        unit["id"], center["id"], reman_scope="ENGINE", spec_level="STANDARD",
        quoted_price_cents=500000, quoted_core_value_cents=200000,
        expected_core_return_by="2027-03-01T00:00:00Z",
    )
    assert_reman_order(order)
    assert order["status"] == "AWAITING_CORE"
    assert order["provisional_core_credit_cents"] == 120000, (
        f"round_half_up(200000 x 0.6) = 120000, got {order['provisional_core_credit_cents']}"
    )

    center_now = validate_success(api.get_service_center(center["id"], admin_headers))
    assert_service_center(center_now)
    assert center_now["core_credit_balance_cents"] == 120000, (
        f"confirm posts the provisional credit: expected 120000, got {center_now['core_credit_balance_cents']}"
    )


def test_final_core_credit_grade_b_settles_delta_to_center_ledger(api, admin_headers):
    """PRD §3.9: "Grading a `CORE_RECEIVED` order with a `core_grade` of `A`, `B`, or `C` moves it to `CREDIT_ISSUED` and settles the final credit in a pinned order: the grade value is the `quoted_core_value_cents` multiplied by the grade percentage — the full value (1.0) for grade `A`, 0.75 for grade `B`, and 0.5 for grade `C` — rounded half-up to whole cents; the credit cap is the effective price multiplied by 0.4 (that is, 40 percent), rounded half-up to whole cents; and the `final_core_credit_cents` is the smaller of the two."
    PRD §3.9: "The `invoice_total_cents` is then the effective price minus the final credit."
    PRD §3.9: "The center's ledger absorbs the difference: `core_credit_balance_cents` moves by the final credit minus the provisional credit, with the center's `version` incrementing."

    Grade B value round_half_up(200000 x 0.75) = 150000, cap
    round_half_up(500000 x 0.4) = 200000 -> final 150000; invoice
    500000 - 150000 = 350000; ledger 120000 + (150000 - 120000) = 150000.

    Design: Difficulty/dual_variant_calc/core_credit_provisional_vs_final
    """
    env = setup_full_environment()
    family, fleet, center = env["family"], env["fleet"], env["center"]
    unit = setup_engine_unit(family["id"], fleet["id"], serial_number="UN-301")
    set_logical_clock(CLAIM_CLOCK)

    order = setup_reman_order_core_received(
        unit["id"], center["id"], reman_scope="ENGINE", spec_level="STANDARD",
        quoted_price_cents=500000, quoted_core_value_cents=200000,
        expected_core_return_by="2027-03-01T00:00:00Z",
    )
    graded = grade_core(order["id"], "B")

    assert_reman_order(graded)
    assert graded["status"] == "CREDIT_ISSUED"
    assert graded["provisional_core_credit_cents"] == 120000
    assert graded["final_core_credit_cents"] == 150000, (
        f"min(150000, 200000) = 150000, got {graded['final_core_credit_cents']}"
    )
    assert graded["provisional_core_credit_cents"] != graded["final_core_credit_cents"], (
        "identical quoted inputs yield divergent provisional and final credits"
    )
    assert graded["invoice_total_cents"] == 350000, (
        f"effective price 500000 - final credit 150000 = 350000, got {graded['invoice_total_cents']}"
    )

    center_now = validate_success(api.get_service_center(center["id"], admin_headers))
    assert center_now["core_credit_balance_cents"] == 150000, (
        "ledger absorbs final minus provisional: 120000 + 30000 = 150000, "
        f"got {center_now['core_credit_balance_cents']}"
    )
