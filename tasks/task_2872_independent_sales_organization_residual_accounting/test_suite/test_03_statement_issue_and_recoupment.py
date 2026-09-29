"""Issuing a statement: the pinned step order and the advance recoupment waterfall."""

from test_helpers import (
    CONTROLLER,
    add_line,
    add_thin_line,
    api_client,
    assert_advance_principal_conserved,
    book_canonical_chargebacks,
    fetch_advance,
    fetch_agent,
    fetch_statement_by_id,
    fund_advance,
    fund_percent_advance,
    issue_statement,
    make_active_merchant,
    make_agent,
    make_batch,
    make_program,
    normalize_batch,
    post_batch,
    require_statement,
    setup_two_agent_posted_period,
    validate_success,
)


def _two_merchant_posted_period() -> dict:
    """One agent, a rich merchant and a merchant whose fee income is 20 cents short."""
    program = make_program(minimum_billing_mode="SHORTFALL_BILLED")
    agent = make_agent(split_pct=0.45, override_pct=0.45)
    rich = make_active_merchant(agent["id"], program["id"], upfront_bonus_cents=25000)
    thin = make_active_merchant(
        agent["id"],
        program["id"],
        monthly_minimum_cents=2500,
        per_transaction_fee_cents=20,
        equipment_lease_monthly_cents=0,
        boarded_on="2026-01-05",
    )
    book_canonical_chargebacks(rich["id"])
    batch = make_batch(program["id"], file_checksum="sha256:order-0001")
    add_line(batch["id"], rich["id"])
    add_thin_line(batch["id"], thin["id"], transaction_count=124)
    normalize_batch(batch["id"])
    batch = post_batch(batch["id"])
    return {
        "program": program,
        "agent": agent,
        "rich": rich,
        "thin": thin,
        "batch": batch,
        "statement": require_statement(agent["id"]),
    }


def test_the_true_up_computed_in_step_three_feeds_the_recoupment_in_step_five():
    """The 5-cent true-up raises G to 14682, so 25% of it is 3671 and not 3669.

    Direct residual 14677 = 14643 from the rich merchant plus 34 from the thin
    one; the thin merchant's billable fee income of 20 * 124 = 2480 is 20 cents
    short of its 2500 minimum, so the agent's share is
    round_half_up(20 * 0.45 * 0.5) = 5.

    PRD: "because step 5 reads step 4 and step 4 includes step 3, so the answer
    is only well defined in this sequence"

    Design: Difficulty/combinatorial_formula/statement_issue_order_trueup_feeds_recoupment_tier
    """
    scenario = _two_merchant_posted_period()
    advance = fund_percent_advance(
        scenario["agent"]["id"], principal_cents=60000, recoupment_pct=0.40
    )

    validate_success(
        api_client.issue_agent_statement(scenario["statement"]["id"], CONTROLLER)
    )

    statement = fetch_statement_by_id(scenario["statement"]["id"])
    assert statement["direct_residual_cents"] == 14677
    assert statement["override_residual_cents"] == 0
    assert statement["minimum_true_up_cents"] == 5
    assert statement["gross_after_trueup_cents"] == 14682
    assert statement["advance_recoupment_cents"] == 3671, (
        "25% of 14682, not the 3669 a recoupment computed before the true-up gives"
    )
    assert statement["net_payable_cents"] == 11011
    assert statement["carry_forward_deficit_cents"] == 0

    stored = fetch_advance(advance["id"])
    assert stored["outstanding_cents"] == 56329
    assert stored["cumulative_recouped_cents"] == 3671


def test_the_requested_percentage_is_truncated_to_the_tier_cap_of_the_grossed_up_figure():
    """A gross of 14682 is below 50,000 cents, so the 0.40 request is capped at 0.25.

    PRD: "twenty-five hundredths when that gross is below 50,000 cents"

    Design: Difficulty/combinatorial_formula/statement_issue_order_trueup_feeds_recoupment_tier
    """
    scenario = _two_merchant_posted_period()
    advance = fund_percent_advance(
        scenario["agent"]["id"], principal_cents=60000, recoupment_pct=0.40
    )

    issue_statement(scenario["statement"]["id"])

    statement = fetch_statement_by_id(scenario["statement"]["id"])
    assert statement["gross_after_trueup_cents"] < 50000
    assert statement["advance_recoupment_cents"] == 3671
    assert statement["advance_recoupment_cents"] != round(14682 * 0.40), (
        "the advance's own 0.40 never applies below the 50,000-cent tier boundary"
    )
    assert_advance_principal_conserved(fetch_advance(advance["id"]))


def _two_advance_scenario(x_overrides: dict, y_overrides: dict, percent_x: bool) -> dict:
    """Two identical 14643 statements, one advance per agent, both issued."""
    scenario = setup_two_agent_posted_period()
    funder_x = fund_percent_advance if percent_x else fund_advance
    scenario["advance_x"] = funder_x(scenario["agent_x"]["id"], **x_overrides)
    scenario["advance_y"] = fund_advance(scenario["agent_y"]["id"], **y_overrides)
    scenario["statement_x"] = issue_statement(scenario["statement_x"]["id"])
    scenario["statement_y"] = issue_statement(scenario["statement_y"]["id"])
    return scenario


def _fifty_thousand_over_ten_months() -> dict:
    return _two_advance_scenario(
        {
            "principal_cents": 50000,
            "recoupment_pct": 0.40,
            "amortization_months": 10,
            "first_recoupment_month": "2026-07",
            "last_recoupment_month": "2027-04",
        },
        {
            "principal_cents": 50000,
            "amortization_months": 10,
            "first_recoupment_month": "2026-07",
            "last_recoupment_month": "2027-04",
        },
        percent_x=True,
    )


def test_percent_of_residual_floats_with_the_statement_and_hits_the_tier_cap():
    """The same 50000 principal on the same 14643 statement gives up only 3661.

    The requested 0.40 is truncated to the 0.25 tier cap because the gross is
    below 50,000 cents, so round_half_up(14643 * 0.25) = 3661.

    PRD: "The effective percentage is the smaller of the advance's own
    `recoupment_pct` and that tier cap"

    Design: Difficulty/dual_variant_calc/advance_recoupment_variant_divergence_percent_vs_straight_line
    """
    scenario = _fifty_thousand_over_ten_months()

    statement = fetch_statement_by_id(scenario["statement_x"]["id"])
    assert statement["gross_after_trueup_cents"] == 14643
    assert statement["advance_recoupment_cents"] == 3661
    assert statement["net_payable_cents"] == 10982

    advance = fetch_advance(scenario["advance_x"]["id"])
    assert advance["outstanding_cents"] == 46339
    assert advance["months_recouped"] == 1
    assert_advance_principal_conserved(advance)


def test_straight_line_amortization_takes_its_fixed_instalment_and_diverges_by_1339():
    """The straight-line twin ignores the statement and takes 50000 / 10 = 5000.

    PRD: "Under `STRAIGHT_LINE_AMORTIZATION` the instalment is fixed and ignores
    the statement entirely."

    Design: Difficulty/dual_variant_calc/advance_recoupment_variant_divergence_percent_vs_straight_line
    """
    scenario = _fifty_thousand_over_ten_months()

    straight = fetch_statement_by_id(scenario["statement_y"]["id"])
    assert straight["gross_after_trueup_cents"] == 14643
    assert straight["advance_recoupment_cents"] == 5000
    assert straight["net_payable_cents"] == 9643

    advance = fetch_advance(scenario["advance_y"]["id"])
    assert advance["outstanding_cents"] == 45000
    assert advance["months_recouped"] == 1
    assert_advance_principal_conserved(advance)

    percent = fetch_statement_by_id(scenario["statement_x"]["id"])
    assert (
        straight["advance_recoupment_cents"] - percent["advance_recoupment_cents"] == 1339
    ), "the whole divergence is driven by recoupment_mode alone"


def _window_scenario() -> dict:
    """AX's window opens in 2026-08, AY's in 2026-07; everything else is identical."""
    return _two_advance_scenario(
        {"first_recoupment_month": "2026-08", "last_recoupment_month": "2027-01"},
        {"first_recoupment_month": "2026-07", "last_recoupment_month": "2026-12"},
        percent_x=False,
    )


def test_a_statement_outside_the_closed_month_window_recoups_nothing():
    """AX's window opens in 2026-08, so the 2026-07 statement recoups exactly 0.

    Both advances were funded on 2026-07-05; the month strings decide, not
    funded_on.

    PRD: "Eligible advances are those belonging to the statement's agent whose
    `state` is `ACTIVE` and whose closed window contains the statement's
    `period_month`"

    Design: Difficulty/resource_temporal_overlap/advance_recoupment_window_excludes_statement_period
    """
    scenario = _window_scenario()

    statement = fetch_statement_by_id(scenario["statement_x"]["id"])
    assert statement["advance_recoupment_cents"] == 0
    assert statement["net_payable_cents"] == 14643

    advance = fetch_advance(scenario["advance_x"]["id"])
    assert advance["outstanding_cents"] == 30000
    assert advance["cumulative_recouped_cents"] == 0
    assert advance["months_recouped"] == 0
    assert advance["state"] == "ACTIVE"
    assert fetch_agent(scenario["agent_x"]["id"])["advance_outstanding_cents"] == 30000
    assert_advance_principal_conserved(advance)


def test_a_statement_inside_the_closed_month_window_pays_its_instalment():
    """AY's window opens in 2026-07, so the same advance takes 30000 / 6 = 5000.

    PRD: "the wanted amount is `principal_cents` divided by `amortization_months`,
    rounded half up to the cent"

    Design: Difficulty/resource_temporal_overlap/advance_recoupment_window_excludes_statement_period
    """
    scenario = _window_scenario()

    statement = fetch_statement_by_id(scenario["statement_y"]["id"])
    assert statement["advance_recoupment_cents"] == 5000, (
        "well inside the 7322-cent aggregate cap of a 14643 gross"
    )
    assert statement["net_payable_cents"] == 9643

    advance = fetch_advance(scenario["advance_y"]["id"])
    assert advance["outstanding_cents"] == 25000
    assert advance["cumulative_recouped_cents"] == 5000
    assert advance["months_recouped"] == 1
    assert advance["state"] == "ACTIVE"
    assert fetch_agent(scenario["agent_y"]["id"])["advance_outstanding_cents"] == 25000
    assert_advance_principal_conserved(advance)
