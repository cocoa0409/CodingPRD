"""Line pricing under both band treatments, and the order-level roll-up."""
import pytest

from test_helpers import (
    assert_paginated_list,
    assert_quote,
    assert_quote_line,
    read_pricing_preview,
    read_quote,
    setup_quote_with_lines,
)


def test_line_pricing_stores_both_band_treatments_on_the_same_line(api, base, analyst_headers):
    """PRD §3.2: "Under the **whole-quantity-average** treatment the entire quantity
    receives the discount of the single band that contains it: the line's
    `effective_stack_discount_pct` is the applicable band's `tier_discount_pct` — zero
    when no band applies — plus `bundle_discount_applied_pct` plus
    `requested_discount_pct`, with the sum capped at the pinned revision's
    `max_stack_discount_pct` and rounded half up to six decimal places, and
    `provisional_net_cents` is `extended_list_cents` multiplied by one minus that
    stacked discount, multiplied by the term multiplier, and rounded half up once to a
    whole cent."
    PRD §3.2: "The bands are walked in ascending `min_quantity` order, each band
    contributing its unit count multiplied by `unit_list_price_cents` multiplied by one
    minus that band's own capped stack, the contributions are summed, the sum is
    multiplied by the term multiplier, and the result is rounded half up once to a whole
    cent and stored as `final_net_cents`."

    Design: Difficulty/dual_variant_calc/tiered_line_pricing_whole_quantity_average_vs_marginal_progressive_money
    """
    quote, _ = setup_quote_with_lines(
        api,
        base,
        [("core", 250, 0.05), ("support", 250, 0.00)],
        term_months=36,
        title="Northwind FY26 Expansion",
        payment_terms_days=60,
        billing_frequency="ANNUAL",
    )

    lines, _ = assert_paginated_list(
        api.list_quote_lines(quote["id"], analyst_headers), expected_total=2, expected_page_size=2
    )
    core_line, support_line = lines
    assert_quote_line(core_line)
    assert_quote_line(support_line)

    assert core_line["extended_list_cents"] == 30000000
    assert core_line["extended_cost_cents"] == 7500000
    assert core_line["volume_tier_level_applied"] == 3
    assert core_line["bundle_discount_applied_pct"] == pytest.approx(0.000000, abs=1e-9)
    assert core_line["effective_stack_discount_pct"] == pytest.approx(0.230000, abs=1e-9)
    assert core_line["provisional_net_cents"] == 20790000, (
        "the whole quantity carries the single band discount that contains it"
    )
    assert core_line["final_net_cents"] == 23038560, (
        "each band slice carries its own discount under the marginal treatment"
    )

    assert support_line["volume_tier_level_applied"] == 0, (
        "a product with no quantity bands records zero"
    )
    assert support_line["bundle_discount_applied_pct"] == pytest.approx(0.050000, abs=1e-9)
    assert support_line["provisional_net_cents"] == 6412500
    assert support_line["final_net_cents"] == 6412500, (
        "a product with no quantity bands collapses the two treatments onto the same number"
    )


def test_quote_rollup_records_both_pricing_passes_side_by_side(api, base):
    """PRD §3.3: "Both passes run on every repricing, and their results land in
    different places. The provisional pass writes its order total to
    `provisional_net_total_cents`. The final pass writes its order total to
    `final_net_total_cents`, and it is the final pass alone whose intermediate
    adjustments are recorded on the quote: `volume_rebate_cents` and
    `payment_terms_uplift_cents` always hold the final pass's figures."
    PRD §3.3: "Once again both passes are recorded: `provisional_margin_pct` from the
    provisional order total and `final_margin_pct` from the final one."

    Design: Difficulty/dual_variant_calc/tiered_line_pricing_whole_quantity_average_vs_marginal_progressive_money
    """
    quote, _ = setup_quote_with_lines(
        api,
        base,
        [("core", 250, 0.05), ("support", 250, 0.00)],
        term_months=36,
        title="Northwind FY26 Expansion",
        payment_terms_days=60,
        billing_frequency="ANNUAL",
    )
    quote = read_quote(api, quote["id"])
    assert_quote(quote)

    assert quote["list_total_cents"] == 37500000
    assert quote["cost_total_cents"] == 9000000
    assert quote["provisional_net_total_cents"] == 26506116
    assert quote["final_net_total_cents"] == 28697113
    assert quote["volume_rebate_cents"] == 1178042
    assert quote["payment_terms_uplift_cents"] == 424095
    assert quote["provisional_blended_discount_pct"] == pytest.approx(0.303616, abs=1e-9)
    assert quote["final_blended_discount_pct"] == pytest.approx(0.246053, abs=1e-9)
    assert quote["provisional_margin_pct"] == pytest.approx(0.660456, abs=1e-9)
    assert quote["final_margin_pct"] == pytest.approx(0.686380, abs=1e-9)
    assert quote["required_approval_level"] == 2
    assert quote["status"] == "DRAFT"


def test_line_stack_discount_is_capped_at_the_configured_maximum(api, base, analyst_headers):
    """PRD §3.2: "A rep-requested discount above the pinned revision's
    `max_stack_discount_pct` is refused outright with `ERR_DISCOUNT_STACK_EXCEEDED`, and
    the same check applies when a line's discount is edited."
    PRD §3.2: "Each band's units carry that band's own `tier_discount_pct` plus the same
    `bundle_discount_applied_pct` and `requested_discount_pct`, capped at the same
    `max_stack_discount_pct`."

    Design: Difficulty/combinatorial_formula/line_stack_cap_min_binds_only_in_top_volume_band
    """
    quote, _ = setup_quote_with_lines(
        api,
        base,
        [("core", 200, 0.30)],
        term_months=12,
        title="Northwind Deep Discount",
        payment_terms_days=30,
        billing_frequency="ANNUAL",
    )

    lines, _ = assert_paginated_list(
        api.list_quote_lines(quote["id"], analyst_headers), expected_total=1, expected_page_size=1
    )
    core_line = lines[0]
    assert core_line["effective_stack_discount_pct"] == pytest.approx(0.450000, abs=1e-9), (
        "0.18 + 0.30 is clamped to the configured 0.45 ceiling"
    )
    assert core_line["volume_tier_level_applied"] == 3
    assert core_line["extended_list_cents"] == 24000000
    assert core_line["provisional_net_cents"] == 13200000
    assert core_line["final_net_cents"] == 14982000, (
        "only the top band's stack is clamped; the lower bands pass through untouched"
    )


def test_capped_stack_quote_selects_the_third_approval_level(api, base):
    """PRD §3.3: "The approval matrix is read from `final_blended_discount_pct`: the
    **matrix level** is the `tier_level` of the single band of the pinned revision whose
    `min_discount_pct` is at or below that figure and whose `max_discount_pct` is
    strictly above it."
    PRD §3.3: "the provisional pass writes `provisional_blended_discount_pct`, which is
    informational only, and the final pass writes `final_blended_discount_pct`, which is
    the single value the approval matrix and every delegation ceiling compare against."

    Design: Difficulty/combinatorial_formula/line_stack_cap_min_binds_only_in_top_volume_band
    """
    quote, _ = setup_quote_with_lines(
        api,
        base,
        [("core", 200, 0.30)],
        term_months=12,
        title="Northwind Deep Discount",
        payment_terms_days=30,
        billing_frequency="ANNUAL",
    )
    quote = read_quote(api, quote["id"])

    assert quote["volume_rebate_cents"] == 299640
    assert quote["payment_terms_uplift_cents"] == 0, "standard payment terms buy no uplift block"
    assert quote["final_net_total_cents"] == 14682360
    assert quote["provisional_blended_discount_pct"] == pytest.approx(0.461000, abs=1e-9)
    assert quote["final_blended_discount_pct"] == pytest.approx(0.388235, abs=1e-9)
    assert quote["final_margin_pct"] == pytest.approx(0.591346, abs=1e-9)
    assert quote["required_approval_level"] == 3


def test_rebate_precedes_uplift_and_extra_days_bill_as_whole_blocks(api, base, analyst_headers):
    """PRD §3.3: "Two order-level adjustments then apply, in a fixed order, and the order
    matters because each is rounded separately."
    PRD §3.3: "Those extra days are converted into whole 30-day blocks rounded **up**, so
    a single extra day still buys a full block and 31 extra days buy two."
    PRD §3.3: "The rebate is never computed on an uplifted amount and the uplift is never
    computed on a pre-rebate amount."

    Design: Difficulty/combinatorial_formula/rebate_then_uplift_evaluation_order_with_ceiling_blocks
    """
    quote, _ = setup_quote_with_lines(
        api,
        base,
        [("core", 60, 0.15), ("service", 4, 0.10), ("usage", 20000, 0.00)],
        term_months=24,
        title="Northwind Platform Plus Usage",
        payment_terms_days=45,
        billing_frequency="ANNUAL",
    )

    lines, _ = assert_paginated_list(
        api.list_quote_lines(quote["id"], analyst_headers), expected_total=3, expected_page_size=3
    )
    core_line, svc_line, usg_line = lines
    assert core_line["final_net_cents"] == 5688600
    assert svc_line["final_net_cents"] == 684000
    assert usg_line["final_net_cents"] == 9500000

    quote = read_quote(api, quote["id"])
    assert quote["volume_rebate_cents"] == 317452, (
        "the rebate rate is applied to the pre-uplift net subtotal"
    )
    assert quote["payment_terms_uplift_cents"] == 233327, (
        "fifteen extra days buy one whole block charged on the post-rebate amount"
    )
    assert quote["final_net_total_cents"] == 15788475
    assert quote["final_blended_discount_pct"] == pytest.approx(0.135825, abs=1e-9)
    assert quote["final_margin_pct"] == pytest.approx(0.594641, abs=1e-9)
    assert quote["required_approval_level"] == 1


def test_pricing_preview_reports_the_same_adjustments_and_the_usage_carve_out(api, base):
    """PRD §3.3: "Any reader may also ask for a **pricing preview** on a quote, a purely
    computed read that mutates nothing and returns both passes side by side:
    `list_total_cents`, `cost_total_cents`, `provisional_net_total_cents`,
    `final_net_total_cents`, `provisional_blended_discount_pct`,
    `final_blended_discount_pct`, `provisional_margin_pct`, `final_margin_pct`,
    `volume_rebate_cents`, `payment_terms_uplift_cents`, `required_approval_level`, both
    risk scores in `terms_risk_score_aggregate` and `terms_risk_score_dominant`, the
    `arrangement_type`, the revenue-allocation figures `usage_excluded_cents`,
    `allocable_amount_cents` and `allocation_residual_cents`, the `margin_give_up_cents`
    the deal would cost in allowance, and a `lines` array carrying the per-line figures."
    PRD §3.6: "`usage_excluded_cents` is the sum of `final_net_cents` over the quote's
    lines whose `rev_rec_category` is `USAGE_AS_INCURRED`, and `allocable_amount_cents`
    is the quote's `final_net_total_cents` less that carve-out."

    Design: Difficulty/combinatorial_formula/rebate_then_uplift_evaluation_order_with_ceiling_blocks
    """
    quote, _ = setup_quote_with_lines(
        api,
        base,
        [("core", 60, 0.15), ("service", 4, 0.10), ("usage", 20000, 0.00)],
        term_months=24,
        title="Northwind Platform Plus Usage",
        payment_terms_days=45,
        billing_frequency="ANNUAL",
    )

    preview = read_pricing_preview(api, quote["id"])
    assert preview["list_total_cents"] == 18000000
    assert preview["cost_total_cents"] == 6400000
    assert preview["volume_rebate_cents"] == 317452
    assert preview["payment_terms_uplift_cents"] == 233327
    assert preview["final_net_total_cents"] == 15788475
    assert preview["arrangement_type"] == "USAGE_BASED_HYBRID"
    assert preview["usage_excluded_cents"] == 9500000
    assert preview["allocable_amount_cents"] == 6288475
    assert len(preview["lines"]) == 3
