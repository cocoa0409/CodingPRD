"""Sales reports, billing runs, monthly royalty split, and annual reconciliation."""
import test_helpers as th


def test_sales_report_initial_state_is_draft(api):
    """PRD §3.4: "A new report starts in `DRAFT`."

    Design: Corner/state_machines/sales_report_initial_state_is_draft
    """
    ctx = th.setup_open_store()
    resp = api.create_sales_report(
        th.create_sales_report_payload(ctx["store"]["id"], "2026-09", 1_000_000),
        th.make_operator_headers(ctx["operator"]["id"]),
    )
    report = th.validate_success(resp, expected_status=201)
    th.assert_sales_report(report)
    assert report["status"] == "DRAFT"


def test_billing_run_locks_report_and_emits_assessment(api, finance_headers):
    """PRD §3.4: "The billing run consumes the month's `SUBMITTED` report,
    locking it `SUBMITTED → LOCKED` so it can feed rent calculations, and emits
    a **FundAssessment** recording the month's royalty and advertising split."
    PRD §3.4: "The assessment is created in `OPEN` status and carries the
    `store_id`, the `agreement_id` of the store's active agreement, and the
    `period_month`."

    Design: Corner/endpoints/billing_run_locks_report_and_emits_assessment
    """
    ctx = th.setup_open_store()
    headers = th.make_operator_headers(ctx["operator"]["id"])
    report = th.get_success_data(api.create_sales_report(
        th.create_sales_report_payload(ctx["store"]["id"], "2026-09", 10_000_000), headers
    ))
    th.get_success_data(api.submit_sales_report(report["id"], headers))

    resp = api.post_billing_run({"store_id": ctx["store"]["id"], "period_month": "2026-09"}, finance_headers)
    assessment = th.validate_success(resp, expected_status=201)
    th.assert_fund_assessment(assessment)
    assert assessment["status"] == "OPEN"
    assert assessment["royalty_cents"] == 160_000
    assert assessment["ad_fund_cents"] == 80_000

    locked = th.validate_success(api.get_sales_report(report["id"], finance_headers))
    assert locked["status"] == "LOCKED"


def test_monthly_royalty_ad_split_rounding_order_pinned(api, finance_headers):
    """PRD §3.4: "First, the `occupancy_share_cents` is computed as
    `gross_sales_cents` multiplied by the agreement's
    `occupancy_allocation_pct`, rounded half-up to whole cents — this rounding
    happens first. Second, the `royalty_sales_cents` is the remainder,
    `gross_sales_cents` minus `occupancy_share_cents`, and is never
    independently rounded. Third, `royalty_cents` is the round-half-up of
    `royalty_sales_cents` times `royalty_rate`, and `ad_fund_cents` is the
    round-half-up of `royalty_sales_cents` times `ad_fund_rate` — each rounding
    per line from the un-rounded remainder."

    Design: Difficulty/combinatorial_formula/monthly_royalty_ad_split_rounding_order_pinned
    """
    ctx = th.setup_open_store()
    assessment = th.create_locked_sales_month(ctx["store"], ctx["operator"], "2026-09", 10_000_000)
    th.assert_fund_assessment(assessment)
    assert assessment["occupancy_share_cents"] == 6_000_000
    assert assessment["royalty_sales_cents"] == 4_000_000
    assert assessment["royalty_cents"] == 160_000
    assert assessment["ad_fund_cents"] == 80_000


def test_monthly_royalty_ad_split_odd_gross_rounds_half_up(api, finance_headers):
    """PRD §3.4: "First, the `occupancy_share_cents` is computed as
    `gross_sales_cents` multiplied by the agreement's
    `occupancy_allocation_pct`, rounded half-up to whole cents — this rounding
    happens first. Second, the `royalty_sales_cents` is the remainder,
    `gross_sales_cents` minus `occupancy_share_cents`, and is never
    independently rounded. Third, `royalty_cents` is the round-half-up of
    `royalty_sales_cents` times `royalty_rate`, and `ad_fund_cents` is the
    round-half-up of `royalty_sales_cents` times `ad_fund_rate` — each rounding
    per line from the un-rounded remainder."

    Design: Difficulty/combinatorial_formula/monthly_royalty_ad_split_rounding_order_pinned
    """
    ctx = th.setup_open_store()
    # gross 10,000,001: occupancy = round_half_up(6,000,000.6) = 6,000,001;
    # royalty base = 4,000,000 (exact integer remainder).
    assessment = th.create_locked_sales_month(ctx["store"], ctx["operator"], "2026-09", 10_000_001)
    th.assert_fund_assessment(assessment)
    assert assessment["occupancy_share_cents"] == 6_000_001
    assert assessment["royalty_sales_cents"] == 4_000_000
    assert assessment["royalty_cents"] == 160_000
    assert assessment["ad_fund_cents"] == 80_000


def test_royalty_provisional_vs_final_reconciliation_values(api, finance_headers):
    """PRD §3.4: "The assessment also records a forward-looking
    `provisional_royalty_cents`, equal to 12 times that month's `royalty_cents`,
    annualizing the single month and ignoring the rest of the year's actuals;
    `final_royalty_cents` remains null until annual reconciliation."
    PRD §3.4: "Annual royalty reconciliation, invoked by a `FranchiseFinance`
    officer for a store and a `fiscal_year`, replays the year's actual locked
    reports: `final_royalty_cents` is populated on the year's assessments as
    the round-half-up of the year's summed royalty-allocated sales times the
    `royalty_rate`, and the delta against the provisional figures is surfaced."

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_reconciliation
    """
    ctx = th.setup_open_store()
    assessment = th.create_locked_sales_month(ctx["store"], ctx["operator"], "2026-09", 20_000_000)
    th.assert_fund_assessment(assessment)
    assert assessment["occupancy_share_cents"] == 12_000_000
    assert assessment["royalty_sales_cents"] == 8_000_000
    assert assessment["royalty_cents"] == 320_000
    assert assessment["ad_fund_cents"] == 160_000
    assert assessment["provisional_royalty_cents"] == 3_840_000
    assert assessment["final_royalty_cents"] is None

    resp = api.annual_reconciliation(ctx["store"]["id"], {"fiscal_year": "2026"}, finance_headers)
    assert resp.status_code == 200, f"reconciliation failed: {resp.text}"

    reconciled = th.validate_success(api.get_fund_assessment(assessment["id"], finance_headers))
    assert reconciled["final_royalty_cents"] == 320_000
    assert reconciled["provisional_royalty_cents"] != reconciled["final_royalty_cents"]


def test_royalty_provisional_diverges_from_final_on_nonuniform_sales(api, finance_headers):
    """PRD §3.4: "The assessment also records a forward-looking
    `provisional_royalty_cents`, equal to 12 times that month's `royalty_cents`,
    annualizing the single month and ignoring the rest of the year's actuals;
    `final_royalty_cents` remains null until annual reconciliation."
    PRD §3.4: "Because the provisional variant annualizes one month while the
    final variant replays actuals, identical underlying data produces different
    totals whenever monthly sales are not uniform."

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_reconciliation
    """
    ctx = th.setup_open_store()
    # Two non-uniform months in fiscal 2026.
    sep = th.create_locked_sales_month(ctx["store"], ctx["operator"], "2026-09", 20_000_000)
    th.create_locked_sales_month(ctx["store"], ctx["operator"], "2026-10", 5_000_000)

    # September provisional annualizes its own 320,000 royalty to 3,840,000.
    assert sep["provisional_royalty_cents"] == 3_840_000

    resp = api.annual_reconciliation(ctx["store"]["id"], {"fiscal_year": "2026"}, finance_headers)
    assert resp.status_code == 200, f"reconciliation failed: {resp.text}"

    # Final replays actuals: royalty-allocated sales = (40% of 20,000,000)
    # + (40% of 5,000,000) = 8,000,000 + 2,000,000 = 10,000,000;
    # final = round_half_up(10,000,000 * 0.04) = 400,000.
    reconciled = th.validate_success(api.get_fund_assessment(sep["id"], finance_headers))
    assert reconciled["final_royalty_cents"] == 400_000
    assert reconciled["final_royalty_cents"] != reconciled["provisional_royalty_cents"]
