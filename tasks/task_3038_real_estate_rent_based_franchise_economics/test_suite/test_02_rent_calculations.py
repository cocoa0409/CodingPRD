"""Rent computation: escalation composite, greater-of rule, input-set filtering."""
import test_helpers as th


def test_greater_of_rule_percentage_binds_in_high_sales_year(api, finance_headers):
    """PRD §3.5: "The billed `selected_rent_cents` follows the greater-of rule:
    when `effective_base_rent_cents` is greater than or equal to
    `percentage_rent_cents`, the escalated base binds and the percentage
    component is reported but not billed; when `percentage_rent_cents` exceeds
    `effective_base_rent_cents`, the percentage-of-sales figure binds and the
    escalated base is reported but not billed."
    PRD §3.5: "The `annual_sales_cents` is the sum of `gross_sales_cents` over
    the store's SalesReports whose status is `LOCKED` and whose `period_month`
    falls inside the billing period; `DRAFT` and `SUBMITTED` reports are
    excluded."

    Design: Difficulty/dual_variant_calc/rent_selected_base_binds_vs_percentage_binds_across_years
    """
    th.set_clock("2027-04-01T00:00:00Z")
    ctx = th.setup_open_store()
    # Annual sales of 400,000,000 spread over 12 months; with pct_rent_rate 8%
    # the percentage arm (32,000,000) exceeds the escalated base (2,448,000).
    # 11 x 33,333,333 + 33,333,337 = 400,000,000.
    months_a = [("2027-04", 33_333_337)] + [(f"2027-{m:02d}", 33_333_333) for m in range(5, 13)] + [
        (f"2028-{m:02d}", 33_333_333) for m in range(1, 4)
    ]
    for period_month, gross in months_a:
        th.create_locked_sales_month(ctx["store"], ctx["operator"], period_month, gross)

    charge = th.post_rent_charge(
        ctx["store"]["id"], ctx["sublease"]["id"],
        billing_period="2027", period_start="2027-04-01", period_end="2028-03-31",
    )
    th.assert_rent_charge(charge)
    # One anniversary (2027-04-01) falls inside the billing span.
    assert charge["escalation_count"] == 1
    # round_half_up(2,400,000 * 1.02^1) = 2,448,000
    assert charge["effective_base_rent_cents"] == 2_448_000
    assert charge["annual_sales_cents"] == 400_000_000
    assert charge["percentage_rent_cents"] == 32_000_000
    # percentage arm (32,000,000) exceeds the escalated base (2,448,000)
    assert charge["selected_rent_cents"] == 32_000_000


def test_greater_of_rule_base_binds_in_low_sales_year(api, finance_headers):
    """PRD §3.5: "The billed `selected_rent_cents` follows the greater-of rule:
    when `effective_base_rent_cents` is greater than or equal to
    `percentage_rent_cents`, the escalated base binds and the percentage
    component is reported but not billed; when `percentage_rent_cents` exceeds
    `effective_base_rent_cents`, the percentage-of-sales figure binds and the
    escalated base is reported but not billed."
    PRD §3.5: "The `effective_base_rent_cents` is then the round-half-up of
    `base_rent_cents` multiplied by the compound factor: one plus the
    `escalation_rate`, raised to the power of `escalation_count`."

    Design: Difficulty/dual_variant_calc/rent_selected_base_binds_vs_percentage_binds_across_years
    """
    th.set_clock("2027-04-01T00:00:00Z")
    ctx = th.setup_open_store()
    months_b = [("2028-04", 2_500_000)] + [(f"2028-{m:02d}", 2_500_000) for m in range(5, 13)] + [
        (f"2029-{m:02d}", 2_500_000) for m in range(1, 4)
    ]
    for period_month, gross in months_b:
        th.create_locked_sales_month(ctx["store"], ctx["operator"], period_month, gross)

    charge = th.post_rent_charge(
        ctx["store"]["id"], ctx["sublease"]["id"],
        billing_period="2028", period_start="2028-04-01", period_end="2029-03-31",
    )
    th.assert_rent_charge(charge)
    # Scanning the years of 2028..2029 for the Apr-1 anniversary: 2028-04-01
    # falls inside the inclusive span; 2029-04-01 is past period_end.
    assert charge["escalation_count"] == 1
    # round_half_up(2,400,000 * 1.02^1) = 2,448,000
    assert charge["effective_base_rent_cents"] == 2_448_000
    assert charge["annual_sales_cents"] == 30_000_000
    assert charge["percentage_rent_cents"] == 2_400_000
    # escalated base (2,448,000) is greater-or-equal to percentage (2,400,000)
    assert charge["selected_rent_cents"] == 2_448_000


def test_escalated_base_rent_composite_exponent_single_rounding(api, finance_headers):
    """PRD §3.5: "The `escalation_count` counts how many escalation
    anniversaries — dates constructed from each year in the billing span
    combined with the sublease's `escalation_month` and `escalation_day` — fall
    within the inclusive bounds of the billing period, scanning every year from
    the year of `period_start` through the year of `period_end`."
    PRD §3.5: "The composite factor is rounded exactly once; iterative rounding
    year by year is forbidden."

    Design: Difficulty/combinatorial_formula/escalated_base_rent_composite_exponent_and_single_rounding
    """
    ctx = th.setup_open_store()
    # Two-year billing span covering two Apr-1 anniversaries, no sales at all.
    charge = th.post_rent_charge(
        ctx["store"]["id"], ctx["sublease"]["id"],
        billing_period="2027", period_start="2026-04-01", period_end="2028-03-31",
    )
    th.assert_rent_charge(charge)
    assert charge["escalation_count"] == 2
    # round_half_up(2,400,000 * 1.02^2) = round_half_up(2,496,960.0) — composite,
    # not iterative per-year rounding
    assert charge["effective_base_rent_cents"] == 2_496_960
    assert charge["percentage_rent_cents"] == 0
    assert charge["selected_rent_cents"] == 2_496_960


def test_escalation_count_zero_when_anniversary_outside_window(api, finance_headers):
    """PRD §3.5: "The `escalation_count` counts how many escalation
    anniversaries — dates constructed from each year in the billing span
    combined with the sublease's `escalation_month` and `escalation_day` — fall
    within the inclusive bounds of the billing period, scanning every year from
    the year of `period_start` through the year of `period_end`."
    PRD §3.5: "The `effective_base_rent_cents` is then the round-half-up of
    `base_rent_cents` multiplied by the compound factor: one plus the
    `escalation_rate`, raised to the power of `escalation_count`."

    Design: Difficulty/combinatorial_formula/escalated_base_rent_composite_exponent_and_single_rounding
    """
    ctx = th.setup_open_store()
    # May-1..Mar-31 window excludes the Apr-1 anniversary entirely.
    # PRD §3.5 requires billing_period in YYYY format.
    charge = th.post_rent_charge(
        ctx["store"]["id"], ctx["sublease"]["id"],
        billing_period="2026", period_start="2026-05-01", period_end="2027-03-31",
    )
    th.assert_rent_charge(charge)
    assert charge["escalation_count"] == 0
    assert charge["effective_base_rent_cents"] == 2_400_000
    assert charge["selected_rent_cents"] == 2_400_000


def test_rent_input_set_excludes_draft_and_submitted_reports(api, finance_headers):
    """PRD §3.5: "The `annual_sales_cents` is the sum of `gross_sales_cents`
    over the store's SalesReports whose status is `LOCKED` and whose
    `period_month` falls inside the billing period; `DRAFT` and `SUBMITTED`
    reports are excluded."

    Design: Corner/calculations/rent_input_set_excludes_draft_and_submitted_reports
    """
    ctx = th.setup_open_store()
    # A DRAFT report of 999,000,000 in the billing year — never submitted.
    api.create_sales_report(
        th.create_sales_report_payload(ctx["store"]["id"], "2026-09", 999_000_000),
        th.make_operator_headers(ctx["operator"]["id"]),
    )
    charge = th.post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"])
    th.assert_rent_charge(charge)
    assert charge["annual_sales_cents"] == 0
    assert charge["percentage_rent_cents"] == 0
    # base arm binds: round_half_up(2,400,000 * 1.02^1) = 2,448,000
    assert charge["selected_rent_cents"] == 2_448_000
