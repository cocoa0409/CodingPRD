"""
Spend status boundaries and post-event analysis.

Covers the inclusive `OVERSPEND_WARNING` band and the cent that separates it
from `WITHIN_BUDGET`, the short-circuit an analysis takes when the promoted
window holds no consumption facts, the full lift / cannibalization / ROI walk,
the baseline pinned at creation and reused by every recompute, and the
one-analysis-per-promotion rule.
"""

from typing import Any, Dict, Tuple

from test_helpers import (
    ANALYST_HEADERS,
    DEFAULT_CLOCK_INSTANT,
    DIRECTOR_HEADERS,
    KAM_HEADERS,
    MONDAY_AUG_03,
    MONDAY_AUG_10,
    MONDAY_AUG_17,
    MONDAY_AUG_24,
    MONDAY_AUG_31,
    MONDAY_JUL_06,
    MONDAY_JUL_13,
    MONDAY_JUL_20,
    MONDAY_JUL_27,
    SPECIALIST_HEADERS,
    AccrualMethod,
    AllocationPosture,
    ApiErrorId,
    BaselineMethod,
    Channel,
    DataStatus,
    DeductionValidationPolicy,
    DeductionStatus,
    DisputeStatus,
    EventType,
    FactSource,
    FactType,
    PerformanceFlag,
    PromotionLifecycleStatus,
    SpendStatus,
    TradingStatus,
    analyze_promotion_payload,
    assert_money,
    assert_post_event_analysis,
    assert_ratio,
    create_accrual_payload,
    create_promotion_payload,
    create_tpr_tactic_payload,
    current_allocation_version,
    instant,
    open_dispute,
    read_allocation,
    read_analysis,
    read_customer,
    read_deduction,
    read_dispute,
    read_promotion,
    record_recovery_payload,
    run_activation,
    set_clock,
    setup_analysis,
    setup_approved_allocation,
    setup_brand,
    setup_customer,
    setup_matched_deduction,
    setup_program,
    setup_volume_fact,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Local builders (the frozen fixtures are used where they fit) ─────────────

def _reference_data(api, *, budget: float, accrual_default: str,
                    brand: Dict[str, Any] = None,
                    customer: Dict[str, Any] = None) -> Tuple[dict, dict, dict]:
    """A program with one brand and one customer, all figures pinned."""
    program = setup_program(api, total_budget_amount=budget,
                            accrual_method_default=accrual_default)
    brand_fields = {
        "name": "Crisp Oat Cereal",
        "list_price_per_case": 24.00,
        "cogs_per_case": 8.70,
        "baseline_units_per_week": 1200,
    }
    brand_fields.update(brand or {})
    customer_fields = {
        "name": "MegaMart",
        "channel": Channel.GROCERY.value,
        "deduction_validation_policy": DeductionValidationPolicy.EVIDENCE_BASED.value,
    }
    customer_fields.update(customer or {})
    brand_row = setup_brand(api, program["id"], **brand_fields)
    customer_row = setup_customer(api, program["id"], **customer_fields)
    return program, brand_row, customer_row


def _plan_promotion(api, allocation_id: str, *, name: str, window_start: str,
                    window_end: str, accrual_method: str) -> Dict[str, Any]:
    """A `DRAFT` promotion planned against the allocation's live version."""
    expected_version = current_allocation_version(api, allocation_id)
    return validate_success(
        api.create_promotion(
            create_promotion_payload(
                allocation_id, expected_version, name=name,
                window_start=window_start, window_end=window_end,
                accrual_method=accrual_method,
            ),
            KAM_HEADERS,
        ),
        expected_status=201,
    )


def _add_tpr_line(api, promotion_id: str, *, planned_units: int, rate_per_case: float,
                  window_start: str, window_end: str) -> Dict[str, Any]:
    """One `TPR` line on a `DRAFT` promotion."""
    return validate_success(
        api.create_tactic(
            promotion_id,
            create_tpr_tactic_payload(
                planned_units=planned_units, rate_per_case=rate_per_case,
                window_start=window_start, window_end=window_end,
            ),
            KAM_HEADERS,
        ),
        expected_status=201,
    )


def _submit_and_approve(api, promotion_id: str) -> Dict[str, Any]:
    """Take a `DRAFT` promotion to `APPROVED`."""
    validate_success(api.submit_promotion(promotion_id, KAM_HEADERS))
    return validate_success(api.approve_promotion(promotion_id, DIRECTOR_HEADERS))


def _post_accrual(api, promotion_id: str, period_start: str) -> Dict[str, Any]:
    """Post one week of accrual and return the created entry."""
    return validate_success(
        api.create_accrual(promotion_id, create_accrual_payload(period_start),
                           ANALYST_HEADERS),
        expected_status=201,
    )


class TestSpendRatioWarningBoundary:
    """The warning band is entered at exactly 0.9000 and not a ten-thousandth earlier."""

    @staticmethod
    def _fixture(api) -> Dict[str, Any]:
        set_clock(api, instant(MONDAY_AUG_03))
        program, brand, customer = _reference_data(
            api, budget=5000000.00, accrual_default=AccrualMethod.CONSUMPTION.value
        )
        allocation = setup_approved_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=100000.00,
            baseline_units=80000, planned_incremental_units=40000,
        )
        high = _plan_promotion(
            api, allocation["id"], name="Promotion H",
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
            accrual_method=AccrualMethod.CONSUMPTION.value,
        )
        low = _plan_promotion(
            api, allocation["id"], name="Promotion L",
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
            accrual_method=AccrualMethod.CONSUMPTION.value,
        )
        for promotion in (high, low):
            _add_tpr_line(
                api, promotion["id"], planned_units=8000, rate_per_case=1.25,
                window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
            )
        high = _submit_and_approve(api, high["id"])
        low = _submit_and_approve(api, low["id"])
        run_activation(api)
        setup_volume_fact(
            api, customer["id"], brand["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=MONDAY_AUG_03, units=7344, source=FactSource.EDI_852.value,
        )
        setup_volume_fact(
            api, customer["id"], brand["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=MONDAY_AUG_10, units=7343, source=FactSource.EDI_852.value,
        )
        return {
            "program": program,
            "brand": brand,
            "customer": customer,
            "allocation": allocation,
            "high": high,
            "low": low,
        }

    def test_a_ratio_of_exactly_the_warning_ratio_is_a_warning(self, api):
        """
        9180.00 against a 10200.00 plan is exactly 0.9000 and lands in the warning band.

        PRD: "Otherwise `spend_ratio` is `recognized_spend_amount` divided by `planned_total_spend`, rounded half up to 4 decimal places, and `spend_status` follows exact boundaries: a ratio strictly greater than 1.0000 is `OVERSPENT`; a ratio at or above 0.9000 but not exceeding 1.0000 is `OVERSPEND_WARNING`; anything below 0.9000 is `WITHIN_BUDGET`."
        PRD: "A ratio of exactly 0.9000 is therefore `OVERSPEND_WARNING`, a ratio of exactly 1.0000 is still `OVERSPEND_WARNING`, and a ratio of 1.0001 is `OVERSPENT`."

        Design: Difficulty/boundary_precision_check/spend_ratio_exactly_at_overspend_warning_ratio
        """
        context = self._fixture(api)

        entry = _post_accrual(api, context["high"]["id"], MONDAY_AUG_03)
        assert_money(entry["amount"], 9180.00, "amount")

        promotion = read_promotion(api, context["high"]["id"])
        assert_money(promotion["planned_total_spend"], 10200.00, "planned_total_spend")
        assert_money(promotion["recognized_spend_amount"], 9180.00, "recognized_spend_amount")
        assert_ratio(promotion["spend_ratio"], 0.9000, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.OVERSPEND_WARNING.value

    def test_a_ratio_a_ten_thousandth_below_the_band_is_within_budget(self, api):
        """
        9178.75 against the same plan is 0.8999 and stays below the warning band.

        PRD: "`recognized_spend_amount` is the **greater** of two views — the accrual-book view, `gross_accrued_amount` minus `reversed_accrual_amount`, and the deduction-book view, `consumed_deduction_amount` — rounded to 2 decimal places."
        PRD: "A ratio of exactly 0.9000 is therefore `OVERSPEND_WARNING`, a ratio of exactly 1.0000 is still `OVERSPEND_WARNING`, and a ratio of 1.0001 is `OVERSPENT`."

        Design: Difficulty/boundary_precision_check/spend_ratio_exactly_at_overspend_warning_ratio
        """
        context = self._fixture(api)

        entry = _post_accrual(api, context["low"]["id"], MONDAY_AUG_10)
        assert_money(entry["amount"], 9178.75, "amount")

        promotion = read_promotion(api, context["low"]["id"])
        assert_money(promotion["planned_total_spend"], 10200.00, "planned_total_spend")
        assert_money(promotion["recognized_spend_amount"], 9178.75, "recognized_spend_amount")
        assert_ratio(promotion["spend_ratio"], 0.8999, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value

    def test_the_warning_band_raises_no_overspend_event_on_the_parents(self, api):
        """
        Neither promotion reaches `OVERSPENT`, so posture, penalty points and status hold.

        PRD: "The asymmetry is in the consequence, not the axis: **the first time** a promotion reaches `OVERSPENT`, the owning allocation's `overspend_event_count` is incremented by 1, which drives that allocation's `posture` from `OPEN` to `RESTRICTED` — and when the promotion later recovers, `overspend_event_count` is *not* decremented, so the allocation stays `RESTRICTED`."
        PRD: "`accrued_amount` is the sum, across **all** child promotions regardless of lifecycle, of each promotion's `gross_accrued_amount` minus its `reversed_accrual_amount`, rounded to 2 decimal places."

        Design: Difficulty/boundary_precision_check/spend_ratio_exactly_at_overspend_warning_ratio
        """
        context = self._fixture(api)

        _post_accrual(api, context["high"]["id"], MONDAY_AUG_03)
        _post_accrual(api, context["low"]["id"], MONDAY_AUG_10)

        allocation = read_allocation(api, context["allocation"]["id"])
        assert allocation["overspend_event_count"] == 0
        assert allocation["posture"] == AllocationPosture.OPEN.value
        assert_money(allocation["accrued_amount"], 18358.75, "accrued_amount")

        customer = read_customer(api, context["customer"]["id"])
        assert customer["compliance_penalty_points"] == 0
        assert customer["trading_status"] == TradingStatus.ACTIVE.value


class TestAnalysisWithoutConsumptionFacts:
    """An empty promoted window short-circuits the measurement chain."""

    @staticmethod
    def _fixture(api) -> Dict[str, Any]:
        set_clock(api, instant(MONDAY_AUG_03))
        program, brand, customer = _reference_data(
            api, budget=5000000.00, accrual_default=AccrualMethod.SHIPMENT.value,
            customer={"channel": Channel.MASS.value},
        )
        allocation = setup_approved_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.NEW_ITEM.value, planned_amount=100000.00,
            baseline_units=40000, planned_incremental_units=20000,
        )
        promotion = _plan_promotion(
            api, allocation["id"], name="Dark Store Launch",
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_17,
            accrual_method=AccrualMethod.SHIPMENT.value,
        )
        _add_tpr_line(
            api, promotion["id"], planned_units=2000, rate_per_case=1.25,
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_17,
        )
        promotion = _submit_and_approve(api, promotion["id"])
        run_activation(api)
        setup_volume_fact(
            api, customer["id"], brand["id"], fact_type=FactType.SHIPMENT.value,
            period_start=MONDAY_JUL_20, units=800, source=FactSource.EDI_856.value,
        )
        accrual = _post_accrual(api, promotion["id"], MONDAY_JUL_20)
        set_clock(api, instant(MONDAY_AUG_17))
        run_activation(api)
        return {
            "allocation": allocation,
            "promotion": promotion,
            "accrual": accrual,
        }

    def test_the_measurement_chain_is_zeroed_when_no_consumption_fact_exists(self, api):
        """
        With only a shipment fact on file the promoted window is empty and every figure is 0.

        PRD: "When **no** `CONSUMPTION` fact at all exists inside the promoted window, `data_status` is `INSUFFICIENT_DATA` and the analysis short-circuits: `baseline_weekly_units`, `baseline_units`, `lift_units`, `cannibalization_units`, `net_incremental_units` and `incremental_gross_profit` are all 0.00, `post_period_units` is 0, `roi` is null, and only `net_spend` is still computed."
        PRD: "`SHIPMENT` facts are never read here, even for a promotion that accrues on the shipment basis — accrual and measurement deliberately disagree about which journal is the truth."

        Design: Difficulty/boundary_precision_check/analyze_with_empty_consumption_fact_set_yields_null_roi
        """
        context = self._fixture(api)
        assert_money(context["accrual"]["amount"], 1000.00, "accrual amount")

        analysis = setup_analysis(api, context["promotion"]["id"],
                                  BaselineMethod.TRAILING.value)

        assert_post_event_analysis(analysis)
        assert analysis["data_status"] == DataStatus.INSUFFICIENT_DATA.value
        assert analysis["promo_consumption_units"] == 0
        assert analysis["post_period_units"] == 0
        assert_money(analysis["baseline_weekly_units"], 0.00, "baseline_weekly_units")
        assert_money(analysis["baseline_units"], 0.00, "baseline_units")
        assert_money(analysis["lift_units"], 0.00, "lift_units")
        assert_money(analysis["cannibalization_units"], 0.00, "cannibalization_units")
        assert_money(analysis["net_incremental_units"], 0.00, "net_incremental_units")
        assert_money(analysis["incremental_gross_profit"], 0.00, "incremental_gross_profit")

    def test_roi_is_null_rather_than_zero_while_net_spend_is_still_computed(self, api):
        """
        The absent rating is null and the 1000.00 of recognized spend still lands in `net_spend`.

        PRD: "`roi` is `incremental_gross_profit` divided by `net_spend`, rounded half up to 4 decimal places, and is null whenever `net_spend` is at or below 0.00 or `data_status` is `INSUFFICIENT_DATA` — division by a non-positive denominator is not a rating, it is an absence of one."
        PRD: "Recovered total is the sum of `recovered_amount` over `RECOVERED` disputes whose deductions are matched to this promotion, rounded to 2 decimal places, and `net_spend` is the promotion's `recognized_spend_amount` minus that total, rounded to 2 decimal places."

        Design: Difficulty/boundary_precision_check/analyze_with_empty_consumption_fact_set_yields_null_roi
        """
        context = self._fixture(api)

        analysis = setup_analysis(api, context["promotion"]["id"],
                                  BaselineMethod.TRAILING.value)

        assert analysis["roi"] is None, "an absent rating is null, never 0.0000"
        assert_money(analysis["net_spend"], 1000.00, "net_spend")
        assert analysis["baseline_method"] == BaselineMethod.TRAILING.value

        stored = read_analysis(api, analysis["id"])
        assert stored["roi"] is None
        assert_money(stored["net_spend"], 1000.00, "net_spend")

    def test_a_null_roi_leaves_the_promotion_unrated_and_off_the_at_risk_figure(self, api):
        """
        A null rating is `UNRATED`, so the allocation's `at_risk_amount` stays at 0.00.

        PRD: "The promotion's `performance_flag` follows directly: a null `roi` gives `UNRATED`, an `roi` below 1.0000 gives `UNDERPERFORMING`, and an `roi` at or above 1.0000 gives `ON_TRACK`, so an `roi` of exactly 1.0000 is `ON_TRACK`."
        PRD: "`at_risk_amount` is the sum of the `net_spend` figure from the post-event analysis of every child promotion whose `performance_flag` is `UNDERPERFORMING`, rounded to 2 decimal places; because a promotion has at most one analysis, that reference is unambiguous."

        Design: Difficulty/boundary_precision_check/analyze_with_empty_consumption_fact_set_yields_null_roi
        """
        context = self._fixture(api)

        setup_analysis(api, context["promotion"]["id"], BaselineMethod.TRAILING.value)

        promotion = read_promotion(api, context["promotion"]["id"])
        assert promotion["performance_flag"] == PerformanceFlag.UNRATED.value
        assert promotion["lifecycle_status"] == PromotionLifecycleStatus.ANALYZED.value
        assert_ratio(promotion["spend_ratio"], 0.4000, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["at_risk_amount"], 0.00, "at_risk_amount")


def _analysis_ready_promotion(api) -> Dict[str, Any]:
    """An `ENDED` promotion with four trailing, two promoted and two post weeks on file."""
    set_clock(api, DEFAULT_CLOCK_INSTANT)
    program, brand, customer = _reference_data(
        api, budget=500000.00, accrual_default=AccrualMethod.CONSUMPTION.value
    )
    allocation = setup_approved_allocation(
        api, program["id"], customer["id"], brand["id"],
        event_type=EventType.SEASONAL.value, planned_amount=100000.00,
        baseline_units=40000, planned_incremental_units=20000,
    )
    promotion = _plan_promotion(
        api, allocation["id"], name="August Cereal Event",
        window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_17,
        accrual_method=AccrualMethod.CONSUMPTION.value,
    )
    _add_tpr_line(
        api, promotion["id"], planned_units=8000, rate_per_case=1.250,
        window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_17,
    )
    promotion = _submit_and_approve(api, promotion["id"])
    weeks = {
        MONDAY_JUL_06: 1000,
        MONDAY_JUL_13: 1100,
        MONDAY_JUL_20: 900,
        MONDAY_JUL_27: 1000,
        MONDAY_AUG_03: 2500,
        MONDAY_AUG_10: 2300,
        MONDAY_AUG_17: 800,
        MONDAY_AUG_24: 900,
    }
    for period_start, units in weeks.items():
        setup_volume_fact(
            api, customer["id"], brand["id"], fact_type=FactType.CONSUMPTION.value,
            period_start=period_start, units=units, source=FactSource.EDI_852.value,
        )
    set_clock(api, instant(MONDAY_AUG_17))
    run_activation(api)
    first_accrual = _post_accrual(api, promotion["id"], MONDAY_AUG_03)
    second_accrual = _post_accrual(api, promotion["id"], MONDAY_AUG_10)
    return {
        "program": program,
        "brand": brand,
        "customer": customer,
        "allocation": allocation,
        "promotion": promotion,
        "first_accrual": first_accrual,
        "second_accrual": second_accrual,
    }


class TestPostEventAnalysisChain:
    """The measurement walk from trailing baseline through cannibalization to ROI."""

    def test_post_event_analysis_walks_lift_cannibalization_and_roi(self, api):
        """
        A 1000.00 weekly baseline gives 2800.00 of lift, 300.00 of clawback and 38250.00 of profit.

        PRD: "Under `TRAILING`, `baseline_weekly_units` is the sum of `units` across the trailing window's facts divided by 4 — the retailer's own recent average across the four whole weeks immediately before the promotion — rounded half up to 2 decimal places, so a soft pre-period flatters the promotion by inflating measured lift."
        PRD: "`baseline_units` is `baseline_weekly_units` multiplied by the promotion's week count, rounded to 2 decimal places."
        PRD: "`lift_units` is `promo_consumption_units` minus `baseline_units`, rounded to 2 decimal places, and may legitimately be negative when a promotion sold less than the baseline."
        PRD: "Expected post-period volume is `baseline_weekly_units` multiplied by 2, rounded to 2 decimal places, and `cannibalization_units` is the greater of 0 and that expected figure minus `post_period_units`, rounded to 2 decimal places — a post-promotion trough is pantry-loading clawed back from the lift, while a post-period that beats baseline is clamped to zero rather than credited."
        PRD: "`net_incremental_units` is `lift_units` minus `cannibalization_units`, rounded to 2 decimal places, and `incremental_gross_profit` is that figure multiplied by the brand's `unit_margin`, rounded to 2 decimal places."

        Design: Corner/calculations/post_event_analysis_walks_lift_cannibalization_and_roi
        """
        context = _analysis_ready_promotion(api)
        assert_money(context["brand"]["unit_margin"], 15.30, "unit_margin")
        assert_money(context["first_accrual"]["amount"], 3125.00, "first accrual")
        assert_money(context["second_accrual"]["amount"], 2875.00, "second accrual")

        analysis = setup_analysis(api, context["promotion"]["id"],
                                  BaselineMethod.TRAILING.value)

        assert_post_event_analysis(analysis)
        assert analysis["data_status"] == DataStatus.COMPLETE.value
        assert analysis["baseline_method"] == BaselineMethod.TRAILING.value
        assert_money(analysis["baseline_weekly_units"], 1000.00, "baseline_weekly_units")
        assert_money(analysis["baseline_units"], 2000.00, "baseline_units")
        assert analysis["promo_consumption_units"] == 4800
        assert_money(analysis["lift_units"], 2800.00, "lift_units")
        assert analysis["post_period_units"] == 1700
        assert_money(analysis["cannibalization_units"], 300.00, "cannibalization_units")
        assert_money(analysis["net_incremental_units"], 2500.00, "net_incremental_units")
        assert_money(analysis["incremental_gross_profit"], 38250.00,
                     "incremental_gross_profit")

    def test_the_roi_rating_drives_the_promotion_flag_and_the_spend_view(self, api):
        """
        38250.00 of profit over 6000.00 of net spend rates 6.3750 and flags the promotion `ON_TRACK`.

        PRD: "`roi` is `incremental_gross_profit` divided by `net_spend`, rounded half up to 4 decimal places, and is null whenever `net_spend` is at or below 0.00 or `data_status` is `INSUFFICIENT_DATA` — division by a non-positive denominator is not a rating, it is an absence of one."
        PRD: "The promotion's `performance_flag` follows directly: a null `roi` gives `UNRATED`, an `roi` below 1.0000 gives `UNDERPERFORMING`, and an `roi` at or above 1.0000 gives `ON_TRACK`, so an `roi` of exactly 1.0000 is `ON_TRACK`."
        PRD: "`at_risk_amount` is the sum of the `net_spend` figure from the post-event analysis of every child promotion whose `performance_flag` is `UNDERPERFORMING`, rounded to 2 decimal places; because a promotion has at most one analysis, that reference is unambiguous."

        Design: Corner/calculations/post_event_analysis_walks_lift_cannibalization_and_roi
        """
        context = _analysis_ready_promotion(api)

        analysis = setup_analysis(api, context["promotion"]["id"],
                                  BaselineMethod.TRAILING.value)

        assert_money(analysis["net_spend"], 6000.00, "net_spend")
        assert_ratio(analysis["roi"], 6.3750, "roi")

        promotion = read_promotion(api, context["promotion"]["id"])
        assert promotion["lifecycle_status"] == PromotionLifecycleStatus.ANALYZED.value
        assert promotion["performance_flag"] == PerformanceFlag.ON_TRACK.value
        assert_money(promotion["planned_total_spend"], 10200.00, "planned_total_spend")
        assert_money(promotion["recognized_spend_amount"], 6000.00, "recognized_spend_amount")
        assert_ratio(promotion["spend_ratio"], 0.5882, "spend_ratio")
        assert promotion["spend_status"] == SpendStatus.WITHIN_BUDGET.value

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["at_risk_amount"], 0.00, "at_risk_amount")


class TestAnalysisRecomputeKeepsPinnedBaseline:
    """A recompute re-reads the money but never re-chooses the baseline basis."""

    def test_analysis_recompute_after_a_recovery_keeps_the_pinned_baseline(self, api):
        """
        Recovered cash lowers `net_spend` to 5500.00 and lifts `roi`, on the pinned trailing basis.

        PRD: "Recovered cash is money back, so it lowers `net_spend` on the promotion's post-event analysis where one exists and lifts `roi` accordingly; the customer's `open_deduction_amount` drops because a `RECOVERED` deduction is closed."
        PRD: "The request supplies a `baseline_method` of `TRAILING` or `SEASONAL`, which is pinned onto the row at creation and reused verbatim by every later recompute, so a basis can never be silently switched underneath a published number."
        PRD: "Recovered total is the sum of `recovered_amount` over `RECOVERED` disputes whose deductions are matched to this promotion, rounded to 2 decimal places, and `net_spend` is the promotion's `recognized_spend_amount` minus that total, rounded to 2 decimal places."

        Design: Corner/calculations/analysis_recompute_after_a_recovery_keeps_the_pinned_baseline
        """
        context = _analysis_ready_promotion(api)
        analysis = setup_analysis(api, context["promotion"]["id"],
                                  BaselineMethod.TRAILING.value)
        assert_ratio(analysis["roi"], 6.3750, "roi before")
        assert_money(analysis["net_spend"], 6000.00, "net_spend before")

        deduction = setup_matched_deduction(
            api, context["customer"]["id"], context["promotion"]["id"],
            claim_reference="MM-CLAIM-0008", claimed_amount=500.00,
            deduction_date=MONDAY_AUG_17,
        )
        dispute = open_dispute(api, deduction["id"], 500.00)

        recovered = validate_success(
            api.record_dispute_recovery(
                dispute["id"], record_recovery_payload(500.00), SPECIALIST_HEADERS
            )
        )

        assert recovered["status"] == DisputeStatus.RECOVERED.value
        assert read_dispute(api, dispute["id"])["status"] == DisputeStatus.RECOVERED.value
        assert read_deduction(api, deduction["id"])["status"] == DeductionStatus.RECOVERED.value

        recomputed = read_analysis(api, analysis["id"])
        assert_money(recomputed["net_spend"], 5500.00, "net_spend")
        assert_ratio(recomputed["roi"], 6.9545, "roi")
        assert recomputed["baseline_method"] == BaselineMethod.TRAILING.value
        assert_money(recomputed["baseline_weekly_units"], 1000.00, "baseline_weekly_units")
        assert_money(recomputed["incremental_gross_profit"], 38250.00,
                     "incremental_gross_profit")

        promotion = read_promotion(api, context["promotion"]["id"])
        assert_money(promotion["recognized_spend_amount"], 6000.00, "recognized_spend_amount")
        assert promotion["performance_flag"] == PerformanceFlag.ON_TRACK.value


class TestAtMostOneAnalysis:
    """A promotion is analysed once, and the lifecycle check is not what refuses the second."""

    def test_a_promotion_carries_at_most_one_analysis(self, api):
        """
        A second analysis on an `ANALYZED` promotion is refused as already existing.

        PRD: "Analysis is available only for a promotion whose `lifecycle_status` is `ENDED` or `ANALYZED`, and a promotion may carry at most one analysis: a second attempt satisfies the lifecycle check and is then refused with `ERR_ANALYSIS_ALREADY_EXISTS` (HTTP 409)."
        PRD: "The request supplies a `baseline_method` of `TRAILING` or `SEASONAL`, which is pinned onto the row at creation and reused verbatim by every later recompute, so a basis can never be silently switched underneath a published number."

        Design: Corner/errors/a_promotion_carries_at_most_one_analysis
        """
        program, brand, customer = _reference_data(
            api, budget=500000.00, accrual_default=AccrualMethod.CONSUMPTION.value
        )
        allocation = setup_approved_allocation(
            api, program["id"], customer["id"], brand["id"],
            event_type=EventType.SEASONAL.value, planned_amount=50000.00,
            baseline_units=20000, planned_incremental_units=10000,
        )
        promotion = _plan_promotion(
            api, allocation["id"], name="One Week Event",
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_10,
            accrual_method=AccrualMethod.CONSUMPTION.value,
        )
        _add_tpr_line(
            api, promotion["id"], planned_units=3000, rate_per_case=1.000,
            window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_10,
        )
        promotion = _submit_and_approve(api, promotion["id"])
        assert_money(promotion["planned_total_spend"], 3000.00, "planned_total_spend")
        set_clock(api, instant(MONDAY_AUG_10))
        run_activation(api)

        first = setup_analysis(api, promotion["id"], BaselineMethod.TRAILING.value)
        assert first["data_status"] == DataStatus.INSUFFICIENT_DATA.value
        assert first["roi"] is None

        validate_error(
            api.analyze_promotion(
                promotion["id"],
                analyze_promotion_payload(BaselineMethod.SEASONAL.value),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ANALYSIS_ALREADY_EXISTS.value,
        )

        rows, meta = validate_paginated(
            api.list_promotion_post_event_analyses(promotion["id"], ANALYST_HEADERS)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [first["id"]]
        assert rows[0]["baseline_method"] == BaselineMethod.TRAILING.value

        stored_promotion = read_promotion(api, promotion["id"])
        assert stored_promotion["lifecycle_status"] == PromotionLifecycleStatus.ANALYZED.value
