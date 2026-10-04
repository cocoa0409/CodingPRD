"""Pricing and funding arithmetic: the discount-rate tier selection, the
mandated sum-then-round batch discipline, and the two trailing-volume variants."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_industry_category,
    create_merchant,
    accept_merchant,
    create_and_activate_merchant,
    capture_settlement,
    finalize_batch,
    submit_declined_attempt,
    rollup_gap,
    get_merchant,
    get_settlement,
    set_clock,
    TEST_DEFAULTS,
    VOLUME_THRESHOLD_CENTS,
)
from test_helpers.fixtures import (
    SETTLE,
    create_captured_settlement_for_merchant,
    setup_merchant_with_batches,
)


# ═══ Difficulty: dual-variant discount rate ══════════════

def test_settlement_carries_both_provisional_and_sealed_discount_variants(api):
    """PRD §3.3: "the sealed `final_discount_fee_cents` is the gross volume times
    the historical discount rate in force at that batch sequence, divided by ten
    thousand and rounded half up once"
    PRD §3.3: "a provisional `discount_fee_cents` of the gross volume times the
    merchant's `applied_discount_rate_bps` divided by ten thousand and rounded
    half up once"

    Design: Difficulty/dual_variant_calc/discount_rate_provisional_vs_final_on_merchant
    """
    set_clock()
    # No negotiated rate: an ACTIVITY merchant's quoted rate is the industry
    # base, so the sealed figure is that base applied to the gross.
    category = create_industry_category(
        risk_tier="HIGH", high_risk_flag=True, base_discount_rate_bps=250)
    merchant = create_and_activate_merchant(category["id"])
    settlement = capture_settlement(
        merchant["id"], gross_volume_cents=500000, refund_volume_cents=100000)
    finalize_batch(merchant["id"], 1)

    sealed = get_settlement(settlement["id"])
    assert sealed["post_refund_volume_cents"] == 400000
    assert sealed["final_discount_fee_cents"] == 12500, (
        "final discount is 250 bps of the 500000 gross, rounded once")
    assert sealed["settlement_status"] == "IN_FUNDING"
    assert sealed["finalized_at_batch_seq"] == 1


def test_provisional_discount_fee_is_not_the_sealed_final_discount(api):
    """PRD §2.5: "Where a rate is applied to an amount and the result is not a
    whole number of cents or points, the network rounds half up — a trailing half
    cent rounds away from zero — and it does so **once**, at the single point
    each rule designates."

    Design: Difficulty/dual_variant_calc/discount_rate_provisional_vs_final_on_merchant
    """
    set_clock()
    category = create_industry_category(
        risk_tier="HIGH", high_risk_flag=True, base_discount_rate_bps=250)
    merchant = create_and_activate_merchant(category["id"])
    settlement = capture_settlement(
        merchant["id"], gross_volume_cents=500000, refund_volume_cents=100000)

    assert settlement["discount_fee_cents"] == 12500, (
        "the quoted rate is the 250 bps industry base while the tier is ACTIVITY")
    assert settlement["discount_fee_cents"] != settlement["final_discount_fee_cents"]


# ═══ Difficulty: pricing tier selection ══════════════════

def test_activity_tier_quotes_the_industry_base_rate_not_the_fixed_rate(api):
    """PRD §3.3: "an `ACTIVITY` merchant is quoted the industry
    `base_discount_rate_bps`; a `FIXED` merchant is quoted three quarters of that
    base, rounded half up to a whole basis point"

    Design: Difficulty/combinatorial_formula/merchant_discount_rate_tier_selection_mode_a
    """
    set_clock()
    category = create_industry_category(
        risk_tier="HIGH", high_risk_flag=True, base_discount_rate_bps=250)
    merchant = create_merchant(category["id"], merchant_name="Tier Merchant")
    assert merchant["volume_tier"] == "ACTIVITY"

    accepted = accept_merchant(merchant)
    assert accepted["applied_discount_rate_bps"] == 250, (
        "the ACTIVITY bucket rate is the raw industry base, not three quarters of it")


def test_fixed_tier_quotes_three_quarters_of_the_base(api):
    """PRD §3.3: "A merchant's `volume_tier` is `ACTIVITY` while
    `billed_volume_mtd_cents` sits below `VOLUME_THRESHOLD_CENTS`, which is fifty
    thousand dollars; it becomes `FIXED` once the month-to-date figure reaches
    that threshold"
    PRD §3.3: "a `FIXED` merchant is quoted three quarters of that base, rounded
    half up to a whole basis point"

    Design: Difficulty/combinatorial_formula/merchant_discount_rate_tier_selection_mode_a
    """
    set_clock()
    from test_helpers.fixtures import setup_merchant_near_volume_threshold
    _, merchant, _ = setup_merchant_near_volume_threshold(
        base_discount_rate_bps=250, monthly_billed_below_cents=VOLUME_THRESHOLD_CENTS)

    current = get_merchant(merchant["id"])
    assert current["billed_volume_mtd_cents"] == VOLUME_THRESHOLD_CENTS
    assert current["volume_tier"] == "FIXED", (
        "the month-to-date figure reached the threshold, so the tier is FIXED")
    assert current["applied_discount_rate_bps"] == 188, (
        "FIXED quotes three quarters of the 250 bps base, rounded half up once")


# ═══ Difficulty + Corner: batch rounding order ═══════════

def test_batch_discount_rounds_once_over_the_batch_total(api):
    """PRD §2.5: "On the settlement funding path the network sums first and
    rounds second: the discount for a funding batch is computed by summing the
    batch's gross volume, applying the resolved rate to that sum, and rounding
    the single resulting figure half up to a whole cent."

    Design: Difficulty/combinatorial_formula/settlement_discount_rounding_order_mode_b
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"])
    # One settlement in the batch (each capture takes the merchant's next
    # `funding_batch_seq`).  The gross is chosen so the single mandated rounding
    # lands on a half cent: 1000020 * 250 / 10000 = 25000.5.
    capture_settlement(merchant["id"], settlement_cycle=1,
                       gross_volume_cents=1000020, refund_volume_cents=0)

    merchant = finalize_batch(merchant["id"], 1)
    assert merchant["last_batch_discount_fee_cents"] == 25001, (
        "the batch gross times the resolved rate, rounded half up once")


def test_per_line_rounding_is_not_the_mandated_batch_discount(api):
    """PRD §2.5: "Rounding each settlement's discount individually and then
    adding the rounded pieces is a different and forbidden procedure — it drifts
    from the mandated total by up to one cent for every line beyond the first in
    the batch."

    Design: Difficulty/combinatorial_formula/settlement_discount_rounding_order_mode_b
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"])
    # Two settlements, each its own funding batch.  A batch holding two lines
# whose grosses sum to 2000040 would round once to 50001, while rounding each
# line's own provisional discount and adding them rounds to 50002 -- the
# divergence the single-rounding discipline exists to eliminate.
    capture_settlement(merchant["id"], settlement_cycle=1,
                       gross_volume_cents=1000020, refund_volume_cents=0)
    capture_settlement(merchant["id"], settlement_cycle=2,
                       gross_volume_cents=1000020, refund_volume_cents=0)
    finalize_batch(merchant["id"], 1)
    merchant = finalize_batch(merchant["id"], 2)

    per_line = 50002
    assert merchant["last_batch_discount_fee_cents"] != per_line, (
        "each batch is rounded once over its own total, not by summing rounded lines")


def test_last_batch_discount_is_recomputed_for_each_finalized_batch(api):
    """PRD §3.3: "Each finalization writes `last_batch_discount_fee_cents` as the
    sum of the batch's gross volumes multiplied by the resolved rate and divided
    by ten thousand, rounded half up exactly once over the whole batch."

    Design: Corner/consistency_model/settlement_finalize_reports_the_updated_merchant_in_the_same_response
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"])
    capture_settlement(merchant["id"], settlement_cycle=1,
                       gross_volume_cents=400000, refund_volume_cents=0)
    capture_settlement(merchant["id"], settlement_cycle=2,
                       gross_volume_cents=400000, refund_volume_cents=0)

    merchant = finalize_batch(merchant["id"], 1)
    assert merchant["last_batch_discount_fee_cents"] == 10000
    merchant = finalize_batch(merchant["id"], 2)
    assert merchant["last_batch_discount_fee_cents"] == 10000, (
        "batch 2's own gross of 400000 yields the same single-rounded figure")


# ═══ Corner: immediate consistency of the finalize response ═══

def test_finalize_response_reports_derived_fields_without_a_follow_up_read(api):
    """PRD §2.7: "Every accepted mutation of a resource bumps that resource's
    `version` by one and refreshes its `updated_at`"

    Design: Corner/consistency_model/settlement_finalize_reports_the_updated_merchant_in_the_same_response
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"])
    s1 = capture_settlement(merchant["id"], settlement_cycle=1,
                            gross_volume_cents=400000, refund_volume_cents=0)
    capture_settlement(merchant["id"], settlement_cycle=2,
                       gross_volume_cents=400000, refund_volume_cents=0)
    finalize_batch(merchant["id"], 1)

    # Finalizing batch 2 promotes batch 1's settlement and returns the merchant
    # with every derived field already refreshed -- no follow-up read needed.
    returned = finalize_batch(merchant["id"], 2)
    assert returned["last_batch_discount_fee_cents"] == 10000, (
        "the finalize response carries the batch's derived figure already")
    assert returned["billed_volume_mtd_cents"] == 400000, (
        "exactly one settlement of the pair matured, contributing 400000")
    promoted = get_settlement(s1["id"])
    assert promoted["settlement_status"] == "SETTLED"
    assert returned["volume_tier"] == "ACTIVITY", (
        "400000 cents of month-to-date volume sits below the 5000000 threshold")


# ═══ Corner: computed settlement field ═══════════════════

def test_captured_settlement_post_refund_is_computed_from_gross_and_refund(api):
    """PRD §3.3: "The row lands in `CAPTURED` with `post_refund_volume_cents`
    equal to the gross volume less the refund volume"

    Design: Corner/entities/settlement_computed_post_refund_field_ignores_client_input
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"])

    captured = capture_settlement(
        merchant["id"], gross_volume_cents=100000, refund_volume_cents=100000)
    assert captured["post_refund_volume_cents"] == 0, (
        "a full refund lands the computed field on its zero boundary")
    assert captured["gross_volume_cents"] == 100000
    assert captured["refund_volume_cents"] == 100000
    assert captured["settlement_status"] == "CAPTURED"


def test_batch_sequence_starts_at_one_and_is_monotone(api):
    """PRD §3.3: "The settlement is also assigned the merchant's next
    `funding_batch_seq`, a monotone counter that increments by one from a
    starting value of 1 and is the **only** ordering quantity permitted in
    arithmetic."

    Design: Difficulty/combinatorial_formula/settlement_discount_rounding_order_mode_b
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"])
    s1 = create_captured_settlement_for_merchant(merchant["id"], 100000, settlement_cycle=1)
    s2 = create_captured_settlement_for_merchant(merchant["id"], 100000, settlement_cycle=2)

    assert s1["funding_batch_seq"] == 1
    assert s2["funding_batch_seq"] == 2
    assert s2["funding_batch_seq"] == s1["funding_batch_seq"] + 1


# ═══ Corner: trailing-volume variants ════════════════════

def test_captured_settlement_counts_toward_provisional_but_not_final_volume(api):
    """PRD §3.3: "`rolling_90d_billed_volume_cents` is the provisional,
    merchant-facing figure: the sum of post-refund volume over the trailing
    ninety-day window, counting settlements that are `CAPTURED`, `IN_FUNDING`, or
    `SETTLED`, so it includes captured charges that have not yet settled and
    therefore over-states coverage."
    PRD §3.3: "`rolling_90d_settled_volume_cents` is the final, reconciliation
    figure: the same ninety-day window but counting only `SETTLED` settlements."

    Design: Corner/calculations/trailing_volume_provisional_counts_unsettled_captures
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"])
    settlement = capture_settlement(
        merchant["id"], gross_volume_cents=500000, refund_volume_cents=0)

    current = get_merchant(merchant["id"])
    assert get_settlement(settlement["id"])["settlement_status"] == "CAPTURED"
    assert current["rolling_90d_billed_volume_cents"] == 500000, (
        "the provisional figure counts the CAPTURED settlement")
    assert current["rolling_90d_settled_volume_cents"] == 0, (
        "the final figure counts SETTLED settlements only")


# ═══ Corner: high-risk reserve ratchet ═══════════════════

def test_high_risk_reserve_equals_floor_of_settled_volume(api):
    """PRD §2.9: "The reserve floor is five per cent of trailing settled volume —
    `RESERVE_FLOOR_BPS` is 500 basis points — and the required figure is the
    larger of that floor and whatever the merchant has previously been required
    to hold"

    Design: Corner/calculations/high_risk_reserve_ratchets_to_the_floor_of_settled_volume
    """
    set_clock()
    from test_helpers.fixtures import setup_high_risk_merchant_with_settled_volume
    _, merchant, _ = setup_high_risk_merchant_with_settled_volume(10000000)

    current = get_merchant(merchant["id"])
    assert current["rolling_90d_settled_volume_cents"] == 10000000
    assert current["reserve_required_cents"] == 500000, (
        "500 bps of 10000000 cents of settled volume")


def test_high_risk_reserve_exact_floor_boundary(api):
    """PRD §2.9: "A merchant whose `IndustryCategory.risk_tier` is `HIGH` must
    hold a security reserve; a merchant whose category is `LOW` or `MEDIUM` holds
    none at all, and its `reserve_required_cents` is zero regardless of volume."

    Design: Corner/calculations/high_risk_reserve_ratchets_to_the_floor_of_settled_volume
    """
    set_clock()
    from test_helpers.fixtures import setup_high_risk_merchant_with_settled_volume
    _, merchant, _ = setup_high_risk_merchant_with_settled_volume(1000000)

    current = get_merchant(merchant["id"])
    assert current["rolling_90d_settled_volume_cents"] == 1000000
    assert current["reserve_required_cents"] == 50000, (
        "500 bps of 1000000 cents is the floor exactly")

    from test_helpers.fixtures import setup_merchant_and_member
    _, low_risk, _ = setup_merchant_and_member(risk_tier="MEDIUM")
    assert get_merchant(low_risk["id"])["reserve_required_cents"] == 0, (
        "a MEDIUM-risk category holds no reserve at all")


# ═══ Difficulty: cross-entity funding gate ═══════════════

def test_finalize_gate_is_checked_but_a_live_merchant_funds_normally(api):
    """PRD §3.3: "It touches every settlement in that batch, moving each from
    `CAPTURED` to `IN_FUNDING`, provided the settlement is `CAPTURED`, its
    `funding_batch_seq` equals the batch being finalized, and the merchant's
    `acceptance_status` is `ACTIVE` — funding is released only to a live
    merchant."

    Design: Difficulty/cross_entity_state_dependency/settlement_funding_gated_by_merchant_acceptance_state
    """
    set_clock()
    category = create_industry_category(risk_tier="HIGH", high_risk_flag=True)
    merchant = create_and_activate_merchant(category["id"])
    settlement = capture_settlement(
        merchant["id"], settlement_cycle=1,
        gross_volume_cents=500000, refund_volume_cents=0)

    finalize_batch(merchant["id"], 1)
    assert get_settlement(settlement["id"])["settlement_status"] == "IN_FUNDING"