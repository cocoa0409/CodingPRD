"""Money formulas whose evaluation order is pinned by the specification.

The asset-management fee is rounded share by share and then absorbs one signed
residual, and the permitted-reserve tier is chosen from the gross investment
amount before any fee is subtracted.  Both formulas produce different money if
the steps are reordered.
"""
from test_helpers import (
    annual_test_payload,
    assert_cents,
    assert_instant,
    assert_pct,
    create_qei_payload,
    deploy_qlici,
    get_success_data,
    read_award,
    read_fund,
    read_qei,
    read_qlici,
    set_clock,
    setup_active_award,
    setup_funded_fund,
    setup_issued_investment,
    validate_success,
)

ISSUANCE_CLOCK = "2026-09-01T00:00:00.000Z"
FIRST_YEAR_END = "2027-09-01T00:00:00.000Z"

# Three placements that exactly consume 95000000 cents of deployable capital.
FEE_WATERFALL_PLACEMENTS = (
    ("2026-09-02T00:00:00.000Z", "A", 31_666_667),
    ("2026-09-03T00:00:00.000Z", "A", 31_666_667),
    ("2026-09-04T00:00:00.000Z", "B", 31_666_666),
)


def _investment_with_three_near_equal_placements(api):
    scenario = setup_issued_investment(
        api, clock=ISSUANCE_CLOCK, certification_suffix="003"
    )
    for placed_at, loan_class, principal_cents in FEE_WATERFALL_PLACEMENTS:
        set_clock(api, placed_at)
        scenario.qlicis.append(
            deploy_qlici(
                api,
                scenario.cde,
                scenario.qei,
                scenario.qalicb,
                loan_class=loan_class,
                principal_cents=principal_cents,
            )
        )
    set_clock(api, FIRST_YEAR_END)
    return scenario


def test_fee_shares_are_rounded_individually_and_the_signed_residual_lands_on_one_row(api):
    """Three shares of 166667 over-allocate by one cent, and the earliest largest row absorbs it.

    PRD: "Rounding a running total instead of each share would produce
    different per-row values, so the order matters: a fee of 500000 over
    principals of 31666667, 31666667 and 31666666 (a basis of 95000000) gives
    three shares of 166667, summing to 500001, so the residual is negative one,
    the earliest-created largest row lands at 166666, and the final vector is
    166666, 166667, 166667."

    Design: Difficulty/combinatorial_formula/fee_allocation_rounds_per_qlici_then_pushes_signed_residual_to_earliest_largest
    """
    scenario = _investment_with_three_near_equal_placements(api)

    get_success_data(
        api.run_annual_test(
            scenario.qei["id"],
            annual_test_payload(1),
            scenario.annual_reviewer_headers,
        )
    )

    allocated = [
        read_qlici(api, placement["id"])["allocated_fee_cents"]
        for placement in scenario.qlicis
    ]
    assert_cents(allocated[0], 166_666, "allocated_fee_cents of the earliest largest placement")
    assert_cents(allocated[1], 166_667, "allocated_fee_cents of the second placement")
    assert_cents(allocated[2], 166_667, "allocated_fee_cents of the third placement")
    assert sum(allocated) == 500_000, (
        "the allocated shares must sum to the whole fee, never to 500001"
    )


def test_a_fully_allocated_fee_accrues_nothing_and_leaves_the_investment_fully_deployed(api):
    """The last placement consumes the final cent of deployable capital.

    PRD: "From `DEPLOYING`, a further placement that still leaves a positive
    remainder keeps it in `DEPLOYING`, and one that brings the remainder to
    exactly zero moves it to `FULLY_DEPLOYED` with `uninvested_cash_cents` set
    to 0."

    Design: Difficulty/combinatorial_formula/fee_allocation_rounds_per_qlici_then_pushes_signed_residual_to_earliest_largest
    """
    scenario = _investment_with_three_near_equal_placements(api)

    test = get_success_data(
        api.run_annual_test(
            scenario.qei["id"],
            annual_test_payload(1),
            scenario.annual_reviewer_headers,
        )
    )

    assert_pct(test["measured_pct_direct"], 100.00, "measured_pct_direct")
    assert test["result"] == "PASS"

    qei = read_qei(api, scenario.qei["id"])
    assert_cents(qei["accrued_unpaid_fee_cents"], 0, "accrued_unpaid_fee_cents")
    assert_cents(qei["uninvested_cash_cents"], 0, "uninvested_cash_cents")
    assert qei["deployment_status"] == "FULLY_DEPLOYED"
    assert_cents(qei["permitted_fees_cents"], 5_000_000, "permitted_fees_cents")


# --- The reserve tier is read from the gross amount -------------------------

LARGE_FUND = {
    "legal_name": "NMTC Fund II LLC",
    "equity_contribution_cents": 325_000_000,
    "leverage_loan_principal_cents": 175_000_000,
    "leverage_loan_rate_bps": 450,
}


def _award_and_fund_for_a_half_billion_investment(api):
    scenario = setup_active_award(
        api, clock=ISSUANCE_CLOCK, certification_suffix="004"
    )
    setup_funded_fund(api, scenario, fund_overrides=dict(LARGE_FUND))
    scenario.award = read_award(api, scenario.award["id"])
    return scenario


def _issue_half_billion(api, scenario):
    return validate_success(
        api.create_qei(
            create_qei_payload(
                scenario.award["id"],
                scenario.fund["id"],
                scenario.award["version"],
                qei_amount_cents=500_000_000,
            ),
            scenario.cde_headers,
        ),
        201,
    )


def test_reserve_tier_is_chosen_from_the_gross_amount_and_not_from_a_net_figure(api):
    """A gross of 500000000 cents sits at 400 basis points, not at 500.

    PRD: "Deriving the tier from a net figure is the classic error and produces
    different money: a gross of 500000000 sits in the 400-basis-point tier and
    yields fees of 20000000 and a net of 480000000, where a net-derived tier
    would fall back to 500 basis points and wrongly yield fees of 25000000 and
    a net of 475000000."

    Design: Difficulty/combinatorial_formula/qei_reserve_tier_selected_from_gross_amount_before_fee_subtraction
    """
    scenario = _award_and_fund_for_a_half_billion_investment(api)

    qei = _issue_half_billion(api, scenario)

    assert qei["reserve_bps"] == 400
    assert_cents(qei["permitted_fees_cents"], 20_000_000, "permitted_fees_cents")
    assert_cents(qei["net_deployable_cents"], 480_000_000, "net_deployable_cents")
    assert_cents(qei["uninvested_cash_cents"], 480_000_000, "uninvested_cash_cents")
    assert qei["permitted_fees_cents"] != 25_000_000, (
        "25000000 is the fee a net-derived tier would wrongly produce"
    )
    assert qei["net_deployable_cents"] != 475_000_000


def test_issuance_draws_authority_and_fund_capital_and_fixes_the_deployment_deadline(api):
    """The gross amount leaves both the award's authority and the fund's capital.

    PRD: "In the same request the award's `remaining_authority_cents` falls by
    the gross amount, its `issued_qei_count` rises by 1 and its `version`
    increments; the fund's `deployed_to_qei_cents` rises by the same amount, its
    `capital_available_cents` falls by it, the fund moves `FUNDED` to
    `QEI_MADE`, and its `version` increments."

    PRD: "`issued_at` is stamped from the logical clock and anchors every
    compliance-year window for the next seven years; `issued_by_user_id`
    records the acting sponsor; `deployment_deadline_at` is the issuance instant
    advanced by 365 days, and it is the last instant at which any
    sub-allocation may be placed from this investment."

    Design: Difficulty/combinatorial_formula/qei_reserve_tier_selected_from_gross_amount_before_fee_subtraction
    """
    scenario = _award_and_fund_for_a_half_billion_investment(api)

    qei = _issue_half_billion(api, scenario)

    assert_instant(qei["issued_at"], ISSUANCE_CLOCK, "issued_at")
    assert_instant(qei["deployment_deadline_at"], FIRST_YEAR_END, "deployment_deadline_at")

    award = read_award(api, scenario.award["id"])
    assert_cents(award["remaining_authority_cents"], 4_500_000_000, "remaining_authority_cents")
    assert award["issued_qei_count"] == 1

    fund = read_fund(api, scenario.fund["id"])
    assert_cents(fund["capital_available_cents"], 0, "capital_available_cents")
    assert_cents(fund["deployed_to_qei_cents"], 500_000_000, "deployed_to_qei_cents")
    assert fund["status"] == "QEI_MADE"
