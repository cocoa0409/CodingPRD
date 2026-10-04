"""Royalty assessment calculations: tiers, cap, rebate, dual variants, rounding."""
from test_helpers import (
    validate_success, get_success_data,
    setup_active_agreement, submit_gci_report, assess_period,
    TEST_USERS,
)

OPS = TEST_USERS["franchisor_ops_headers"]


def test_royalty_due_zero_and_provisional_skips_cap_when_cap_binds(api):
    """PRD §3.5: "Step three applies the annual cap: the billed royalty is the
    smaller of the raw royalty and the remaining headroom under
    `annual_royalty_cap_cents` after `cumulative_billed_royalty_cents`, with the
    headroom floored at zero so a fully consumed cap yields zero billed royalty."
    PRD §3.5: "The provisional variant skips both the annual cap and the
    volume-incentive rebate — it is exactly the raw royalty from step two,
    evaluated on the same GCI input."

    Design: Difficulty/dual_variant_calc/royalty_final_vs_provisional_cap_binding
    """
    ctx = setup_active_agreement(
        base_royalty_rate_bps=600,
        annual_royalty_cap_cents=50_000_000,
        volume_incentive_threshold_cents=1_000_000_000,
        volume_incentive_rate_bps=300,
        ad_fund_rate_bps=200,
    )
    ag_id = ctx["agreement"]["id"]
    submit_gci_report(ag_id, "2027-01", 800_000_000)
    first = assess_period(ag_id, "2027-01")
    assert first["royalty_due_cents"] == 48_000_000

    submit_gci_report(ag_id, "2027-02", 400_000_000)
    second = assess_period(ag_id, "2027-02")
    # raw = floor(200M*600/10000) + floor(200M*300/10000) = 18,000,000
    assert second["provisional_royalty_cents"] == 18_000_000
    # billed = min(18,000,000, max(0, 50,000,000 - 48,000,000)) = 2,000,000
    # rebate = floor(200M * 300 * 50 / 100 / 10000) = 3,000,000
    # due = max(0, 2,000,000 - 3,000,000) = 0
    assert second["royalty_due_cents"] == 0

    agreement = get_success_data(api.get_agreement(ag_id, OPS))
    assert agreement["cumulative_billed_royalty_cents"] == 50_000_000
    assert agreement["cumulative_gci_cents"] == 1_200_000_000


def test_provisional_at_least_final_under_pinned_constants(api):
    """PRD §3.5: "Under the pinned constants it is therefore always at least
    `royalty_due_cents`, and it diverges from the final figure precisely when the
    cap or the rebate binds."

    Design: Difficulty/dual_variant_calc/royalty_final_vs_provisional_cap_binding
    """
    ctx = setup_active_agreement(
        base_royalty_rate_bps=600,
        annual_royalty_cap_cents=50_000_000,
        volume_incentive_threshold_cents=1_000_000_000,
        volume_incentive_rate_bps=300,
        ad_fund_rate_bps=200,
    )
    ag_id = ctx["agreement"]["id"]
    submit_gci_report(ag_id, "2027-01", 800_000_000)
    first = assess_period(ag_id, "2027-01")
    assert first["provisional_royalty_cents"] >= first["royalty_due_cents"]

    submit_gci_report(ag_id, "2027-02", 400_000_000)
    second = assess_period(ag_id, "2027-02")
    assert second["provisional_royalty_cents"] >= second["royalty_due_cents"]
    # Divergence appears exactly because the cap/rebate bind on the second month.
    assert second["provisional_royalty_cents"] > second["royalty_due_cents"]


def test_royalty_tier_split_rounds_per_leg_before_summing(api):
    """PRD §2.5: "the system pins a round-per-leg-then-sum discipline: each
    multiplication leg is floored independently before the legs are summed, never
    the reverse."
    PRD §3.5: "the rebate is the above-threshold portion of this month's GCI
    multiplied by the difference between the base and volume rates, then by 50
    percent, divided by 10000, floored to whole cents; otherwise the rebate is
    zero."

    Design: Difficulty/combinatorial_formula/royalty_tier_split_rounding_per_leg
    """
    ctx = setup_active_agreement(
        base_royalty_rate_bps=633,
        annual_royalty_cap_cents=900_000_000_000,
        volume_incentive_threshold_cents=1_000_000,
        volume_incentive_rate_bps=211,
        ad_fund_rate_bps=100,
    )
    ag_id = ctx["agreement"]["id"]
    submit_gci_report(ag_id, "2027-05", 1_999_999)
    period = assess_period(ag_id, "2027-05")
    # low_part = 1,000,000; high_part = 999,999
    # legs: floor(1,000,000*633/10000)=63,300; floor(999,999*211/10000)=21,099
    # raw = 84,399 (provisional); rebate = floor(999,999*(633-211)*50/100/10000)=21,099
    # due = 84,399 - 21,099 = 63,300
    assert period["provisional_royalty_cents"] == 84_399
    assert period["royalty_due_cents"] == 63_300


def test_gci_exactly_at_volume_threshold_earns_no_rebate(api):
    """PRD §3.5: "when the running GCI total after this month exceeds the
    threshold, the rebate is the above-threshold portion of this month's GCI
    multiplied by the difference between the base and volume rates, then by 50
    percent, divided by 10000, floored to whole cents; otherwise the rebate is
    zero."

    Design: Difficulty/boundary_precision_check/gci_exactly_at_volume_threshold_gets_no_rebate
    """
    ctx = setup_active_agreement(
        base_royalty_rate_bps=575,
        annual_royalty_cap_cents=900_000_000_000,
        volume_incentive_threshold_cents=500_000_000,
        volume_incentive_rate_bps=400,
        ad_fund_rate_bps=100,
    )
    ag_id = ctx["agreement"]["id"]
    submit_gci_report(ag_id, "2027-01", 500_000_000)
    period = assess_period(ag_id, "2027-01")
    # post_gci == T (not > T): no rebate; raw = floor(500M*575/10000) = 28,750,000
    assert period["royalty_due_cents"] == 28_750_000


def test_per_leg_flooring_diverges_from_sum_then_round(api):
    """PRD §2.5: "the system pins a round-per-leg-then-sum discipline: each
    multiplication leg is floored independently before the legs are summed, never
    the reverse."
    PRD §3.5: "The round-per-leg-then-sum order of §2.5 is pinned here: flooring
    each leg before summing is required, and summing first and flooring once is
    forbidden."

    Design: Difficulty/combinatorial_formula/royalty_tier_split_rounding_per_leg
    """
    ctx = setup_active_agreement(
        base_royalty_rate_bps=333,
        annual_royalty_cap_cents=900_000_000_000,
        volume_incentive_threshold_cents=1_111_111,
        volume_incentive_rate_bps=111,
        ad_fund_rate_bps=100,
    )
    ag_id = ctx["agreement"]["id"]
    submit_gci_report(ag_id, "2027-05", 3_333_333)
    period = assess_period(ag_id, "2027-05")
    # low leg: floor(1,111,111*333/10000) = 36,999
    # high leg: floor(2,222,222*111/10000) = 24,666
    # per-leg raw = 61,665; sum-then-round would give 61,666 — a one-cent divergence.
    assert period["provisional_royalty_cents"] == 61_665
    # rebate: floor(2,222,222*(333-111)*50/100/10000) = floor(2,222,222*111/10000) = 24,666
    assert period["royalty_due_cents"] == 36_999


def test_gci_one_cent_above_threshold_still_earns_no_rebate_after_flooring(api):
    """PRD §3.5: "when the running GCI total after this month exceeds the
    threshold, the rebate is the above-threshold portion of this month's GCI
    multiplied by the difference between the base and volume rates, then by 50
    percent, divided by 10000, floored to whole cents; otherwise the rebate is
    zero."
    PRD §2.5: "Every rate-to-amount multiplication in the royalty and ad-fund
    pipelines is floored to whole cents"

    Design: Difficulty/boundary_precision_check/gci_exactly_at_volume_threshold_gets_no_rebate
    """
    ctx = setup_active_agreement(
        base_royalty_rate_bps=575,
        annual_royalty_cap_cents=900_000_000_000,
        volume_incentive_threshold_cents=500_000_000,
        volume_incentive_rate_bps=400,
        ad_fund_rate_bps=100,
    )
    ag_id = ctx["agreement"]["id"]
    submit_gci_report(ag_id, "2027-01", 500_000_001)
    period = assess_period(ag_id, "2027-01")
    # post_gci = T+1: above-threshold portion is 1 cent; every 1-cent leg floors
    # to 0, so rebate is still 0 and due equals the below-threshold leg.
    assert period["royalty_due_cents"] == 28_750_000
