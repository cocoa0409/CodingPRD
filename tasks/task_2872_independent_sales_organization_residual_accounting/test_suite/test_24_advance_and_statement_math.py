"""Advance recoupment, clawback decay and statement-window arithmetic.

Each scenario builds its own program, agents, merchants, batches and advances
through the public endpoints, then pins the exact cent figures the PRD produces.
"""

from test_helpers import (
    ADMIN,
    ANALYST_ONE,
    CONTROLLER_ONE,
    SYSTEM_USER_ID,
    add_line,
    api_client,
    approve_adjustment,
    assert_advance_principal_conserved,
    assert_statement_money_lines_consistent,
    attrite_merchant,
    fetch_advance,
    fetch_agent,
    fetch_merchant,
    fund_percent_advance,
    get_success_data,
    issue_statement,
    list_rows,
    make_active_merchant,
    make_agent,
    make_batch,
    make_program,
    normalize_batch,
    post_batch,
    propose_adjustment,
    require_statement,
    review_adjustment,
    set_logical_clock,
)

NET_PROGRAM = {
    "name": "Atlantic Net Program",
    "buy_rate_bps": 45,
    "buy_rate_per_item_cents": 6,
    "assessment_bps": 13,
    "normalization_mode": "NET_REVENUE_SPLIT",
    "minimum_billing_mode": "NO_MINIMUM",
}

WINDOW = {"first_recoupment_month": "2026-07", "last_recoupment_month": "2027-06"}


def test_advance_waterfall_consumes_the_aggregate_cap_in_funded_on_order():
    """The eligible set is consumed in ascending `funded_on` order, with ascending `created_at` breaking ties.

    The aggregate cap is that gross multiplied by one half, rounded half up to
    the cent, and floored at zero.

    `months_recouped` is simply the count of distinct accounting months this
    advance has been recouped from, and it serves as the amortization index.

    Design: Corner/calculations/advance_waterfall_consumes_the_aggregate_cap_in_funded_on_order
    """
    program = make_program(**NET_PROGRAM)
    agent = make_agent(
        name="A1 Principal",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )

    # Three identical in-window advances that differ only in funded_on.
    advance_a = fund_percent_advance(
        agent["id"],
        principal_cents=80000,
        recoupment_pct=0.40,
        amortization_months=12,
        funded_on="2026-06-01",
        **WINDOW,
    )
    advance_b = fund_percent_advance(
        agent["id"],
        principal_cents=80000,
        recoupment_pct=0.40,
        amortization_months=12,
        funded_on="2026-06-15",
        **WINDOW,
    )
    advance_c = fund_percent_advance(
        agent["id"],
        principal_cents=80000,
        recoupment_pct=0.40,
        amortization_months=12,
        funded_on="2026-07-01",
        **WINDOW,
    )

    merchant = make_active_merchant(
        agent["id"],
        program["id"],
        monthly_minimum_cents=0,
        per_transaction_fee_cents=10,
        equipment_lease_monthly_cents=1000,
        boarded_on="2026-04-10",
    )
    batch = make_batch(
        program["id"],
        period_month="2026-07",
        coverage_start="2026-07-01",
        coverage_end="2026-08-01",
    )
    add_line(
        batch["id"],
        merchant["id"],
        transaction_count=100,
        sales_volume_cents=1000000,
        interchange_cents=20000,
        assessments_cents=1300,
        gross_income_cents=67400,
    )
    normalize_batch(batch["id"])
    post_batch(batch["id"])

    statement = require_statement(agent["id"], "2026-07")
    assert statement["gross_after_trueup_cents"] == 20000, (
        f"the statement's gross before the issue expected 20000, got "
        f"{statement['gross_after_trueup_cents']}"
    )
    assert fetch_agent(agent["id"])["advance_outstanding_cents"] == 240000, (
        "three 80,000-cent advances stack: expected 240000 outstanding on the agent"
    )

    issued = issue_statement(statement["id"])
    assert issued["advance_recoupment_cents"] == 10000, (
        "the aggregate cap is round_half_up(20000 x 0.50) == 10000, not the 15000 "
        f"three 5,000-cent instalments would want: got {issued['advance_recoupment_cents']}"
    )

    first = fetch_advance(advance_a["id"])
    second = fetch_advance(advance_b["id"])
    third = fetch_advance(advance_c["id"])

    for label, advance in (("oldest", first), ("middle", second)):
        assert advance["cumulative_recouped_cents"] == 5000, (
            f"the {label} advance takes its full instalment: expected 5000, got "
            f"{advance['cumulative_recouped_cents']}"
        )
        assert advance["outstanding_cents"] == 75000, (
            f"the {label} advance's outstanding_cents expected 75000, got "
            f"{advance['outstanding_cents']}"
        )
        assert advance["months_recouped"] == 1, (
            f"the {label} advance was recouped from one month, got "
            f"{advance['months_recouped']}"
        )
        assert advance["state"] == "ACTIVE", (
            f"the {label} advance still has a balance, got state {advance['state']}"
        )

    assert third["cumulative_recouped_cents"] == 0, (
        "the newest advance by funded_on is the one truncated: expected 0, got "
        f"{third['cumulative_recouped_cents']}"
    )
    assert third["outstanding_cents"] == 80000, (
        f"the truncated advance is untouched: expected 80000, got {third['outstanding_cents']}"
    )
    assert third["months_recouped"] == 0, (
        "a zero take is not a month this advance was recouped from: expected 0, got "
        f"{third['months_recouped']}"
    )
    assert third["state"] == "ACTIVE", (
        f"the truncated advance stays ACTIVE, got {third['state']}"
    )

    for advance in (first, second, third):
        assert_advance_principal_conserved(advance)

    assert fetch_agent(agent["id"])["advance_outstanding_cents"] == 230000, (
        "the agent's exposure falls by exactly what was taken: expected 230000"
    )
    assert issued["net_payable_cents"] == 10000, (
        f"20000 gross less the 10000 recouped: expected 10000, got {issued['net_payable_cents']}"
    )
    assert_statement_money_lines_consistent(issued)


def test_advance_tier_cap_boundaries_at_both_ceilings():
    """A tier cap is selected from the statement's gross after true-up: twenty-five hundredths when that gross is below 50,000 cents, forty hundredths when it is at least 50,000 cents but below 150,000 cents, and fifty hundredths at 150,000 cents or above.

    Design: Corner/calculations/advance_tier_cap_boundaries_at_both_ceilings
    """
    program = make_program(**NET_PROGRAM)

    # gross_income, expected gross after true-up, recoupment, net payable, outstanding
    cases = [
        ("A1 Below Tier1", 105096, 49998, 12500, 37498, 187500),
        ("A2 At Tier1", 105100, 50000, 20000, 30000, 180000),
        ("A3 Below Tier2", 305096, 149998, 59999, 89999, 140001),
        ("A4 At Tier2", 305100, 150000, 75000, 75000, 125000),
    ]

    agents = []
    advances = []
    merchants = []
    for name, _gross_income, _gross, _recoup, _net, _outstanding in cases:
        agent = make_agent(
            name=name,
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )
        agents.append(agent)
        advances.append(
            fund_percent_advance(
                agent["id"],
                principal_cents=200000,
                recoupment_pct=0.50,
                amortization_months=12,
                funded_on="2026-06-01",
                **WINDOW,
            )
        )
        merchants.append(
            make_active_merchant(
                agent["id"],
                program["id"],
                monthly_minimum_cents=0,
                per_transaction_fee_cents=10,
                equipment_lease_monthly_cents=0,
                boarded_on="2026-04-10",
            )
        )

    batch = make_batch(
        program["id"],
        period_month="2026-07",
        coverage_start="2026-07-01",
        coverage_end="2026-08-01",
    )
    for merchant, case in zip(merchants, cases):
        add_line(
            batch["id"],
            merchant["id"],
            transaction_count=100,
            sales_volume_cents=1000000,
            interchange_cents=0,
            assessments_cents=0,
            gross_income_cents=case[1],
        )
    normalize_batch(batch["id"])
    post_batch(batch["id"])

    statements = []
    for agent, case in zip(agents, cases):
        statement = require_statement(agent["id"], "2026-07")
        assert statement["gross_after_trueup_cents"] == case[2], (
            f"{case[0]} must gross exactly {case[2]} before the issue, got "
            f"{statement['gross_after_trueup_cents']}"
        )
        statements.append(statement)

    for statement, advance, case in zip(statements, advances, cases):
        issued = issue_statement(statement["id"])
        assert issued["advance_recoupment_cents"] == case[3], (
            f"{case[0]} grossing {case[2]} must recoup {case[3]}, got "
            f"{issued['advance_recoupment_cents']}"
        )
        assert issued["net_payable_cents"] == case[4], (
            f"{case[0]} net_payable_cents expected {case[4]}, got {issued['net_payable_cents']}"
        )
        refreshed = fetch_advance(advance["id"])
        assert refreshed["outstanding_cents"] == case[5], (
            f"{case[0]} advance outstanding_cents expected {case[5]}, got "
            f"{refreshed['outstanding_cents']}"
        )
        assert refreshed["months_recouped"] == 1, (
            f"{case[0]} advance months_recouped expected 1, got {refreshed['months_recouped']}"
        )
        assert refreshed["state"] == "ACTIVE", (
            f"{case[0]} advance still has a balance, got state {refreshed['state']}"
        )
        assert_advance_principal_conserved(refreshed)


def test_clawback_decay_boundary_at_exactly_the_window_edge():
    """The boundary excludes clawback exactly at the window edge: a merchant active for precisely 270 days owes nothing, while one active for 269 days owes the bonus divided by 270, rounded half up.

    "When the clawback is greater than zero, the system upserts the owning
    agent's statement for the calendar month of `attrition_date`, creating it in
    `DRAFT` and `UNSETTLED` when no statement for that agent and month exists,
    and creates an adjustment on it of `kind` `BONUS_CLAWBACK` in `state`
    `APPLIED`, with `created_by_user_id` set to the literal `system`,
    `source_merchant_id` pointing at this merchant, and `amount_cents` equal to
    the negative of the clawback."

    Design: Corner/calculations/clawback_decay_boundary_at_exactly_the_window_edge
    """
    program = make_program(**NET_PROGRAM)
    agent = make_agent(
        name="A1 Principal",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    # Both merchants board on the same day with the same bonus.
    boarding = {
        "monthly_minimum_cents": 0,
        "per_transaction_fee_cents": 10,
        "equipment_lease_monthly_cents": 0,
        "boarded_on": "2026-04-10",
        "upfront_bonus_cents": 27000,
    }
    on_the_edge = make_active_merchant(agent["id"], program["id"], **boarding)
    one_day_short = make_active_merchant(agent["id"], program["id"], **boarding)

    # 2026-04-10 + 270 days == 2027-01-05, so both attritions are in the past.
    set_logical_clock("2027-01-05T00:00:00Z")

    attrite_merchant(on_the_edge["id"], "2027-01-05")
    attrite_merchant(one_day_short["id"], "2027-01-04")

    assert fetch_merchant(on_the_edge["id"])["clawed_back_bonus_cents"] == 0, (
        "exactly 270 days active is inside the safe harbour: the merchant at the "
        "window edge owes nothing"
    )
    assert fetch_merchant(one_day_short["id"])["clawed_back_bonus_cents"] == 100, (
        "269 days active owes round_half_up(27000 x 1 / 270) == 100 cents, got "
        f"{fetch_merchant(one_day_short['id'])['clawed_back_bonus_cents']}"
    )

    edge_rows, edge_meta = list_rows(
        api_client.list_statement_adjustments,
        {"source_merchant_id": on_the_edge["id"]},
        ADMIN,
    )
    assert edge_meta["total_count"] == 0, (
        "a zero clawback creates no adjustment row at all, got "
        f"{edge_meta['total_count']}"
    )
    assert edge_rows == [], f"expected no adjustment rows, got {edge_rows}"

    short_rows, short_meta = list_rows(
        api_client.list_statement_adjustments,
        {"source_merchant_id": one_day_short["id"]},
        ADMIN,
    )
    assert short_meta["total_count"] == 1, (
        f"the 100-cent clawback creates exactly one row, got {short_meta['total_count']}"
    )
    clawback = short_rows[0]
    assert clawback["kind"] == "BONUS_CLAWBACK", (
        f"expected kind BONUS_CLAWBACK, got {clawback['kind']}"
    )
    assert clawback["amount_cents"] == -100, (
        f"amount_cents is the negative of the clawback: expected -100, got "
        f"{clawback['amount_cents']}"
    )
    assert clawback["state"] == "APPLIED", (
        f"the cascade writes the adjustment straight to APPLIED, got {clawback['state']}"
    )
    assert clawback["created_by_user_id"] == SYSTEM_USER_ID, (
        f"expected created_by_user_id {SYSTEM_USER_ID!r}, got "
        f"{clawback['created_by_user_id']!r}"
    )

    # The calendar month of attrition_date 2027-01-04 is 2027-01.
    statement = require_statement(agent["id"], "2027-01")
    assert clawback["statement_id"] == statement["id"], (
        "the adjustment must hang off the agent's statement for the calendar month "
        "of attrition_date"
    )
    assert statement["lifecycle_state"] == "DRAFT", (
        f"the upserted statement is created in DRAFT, got {statement['lifecycle_state']}"
    )
    assert statement["adjustment_cents"] == -100, (
        f"adjustment_cents expected -100, got {statement['adjustment_cents']}"
    )
    assert statement["gross_after_trueup_cents"] == 0, (
        "no residuals were posted for 2027-01, so gross_after_trueup_cents is 0, got "
        f"{statement['gross_after_trueup_cents']}"
    )
    assert statement["net_payable_cents"] == 0, (
        f"net_payable_cents is floored at zero, got {statement['net_payable_cents']}"
    )
    assert statement["carry_forward_deficit_cents"] == 100, (
        f"the 100-cent shortfall carries forward, got "
        f"{statement['carry_forward_deficit_cents']}"
    )
    assert_statement_money_lines_consistent(statement)

    owner = fetch_agent(agent["id"])
    assert owner["lifetime_clawback_cents"] == 100, (
        f"only the in-window clawback counts: expected 100, got "
        f"{owner['lifetime_clawback_cents']}"
    )
    assert owner["portfolio_attrition_bps"] == 10000, (
        f"both merchants attrited, so attrition is 10000 bps, got "
        f"{owner['portfolio_attrition_bps']}"
    )
    assert owner["residual_hold"] is True, (
        "an attrition rate at the threshold puts the agent on residual hold"
    )


def test_trailing_residual_window_counts_three_latest_periods_out_of_post_order():
    """An agent's `trailing_residual_cents` is the sum of `gross_after_trueup_cents` over that agent's three most recent statements.

    The window is "ordered by `period_month` descending, and it counts statements
    in **all** three lifecycle states: `DRAFT`, `ISSUED` and `FINALIZED`."

    Design: Corner/calculations/trailing_residual_window_counts_three_latest_periods_out_of_post_order
    """
    program = make_program(**NET_PROGRAM)
    agent = make_agent(
        name="A1 Principal",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    merchant = make_active_merchant(
        agent["id"],
        program["id"],
        monthly_minimum_cents=0,
        per_transaction_fee_cents=10,
        equipment_lease_monthly_cents=0,
        boarded_on="2026-03-01",
    )

    # Four adjacent half-open periods normalizing to 10000 / 20000 / 30000 / 40000.
    periods = [
        ("2026-04", "2026-04-01", "2026-05-01", 15100, 5000),
        ("2026-05", "2026-05-01", "2026-06-01", 25100, 10000),
        ("2026-06", "2026-06-01", "2026-07-01", 35100, 15000),
        ("2026-07", "2026-07-01", "2026-08-01", 45100, 20000),
    ]
    batches = {}
    for period_month, start, end, gross_income, _direct in periods:
        batch = make_batch(
            program["id"],
            period_month=period_month,
            coverage_start=start,
            coverage_end=end,
        )
        add_line(
            batch["id"],
            merchant["id"],
            transaction_count=100,
            sales_volume_cents=1000000,
            interchange_cents=0,
            assessments_cents=0,
            gross_income_cents=gross_income,
        )
        normalize_batch(batch["id"])
        batches[period_month] = batch

    # Post out of chronological order: Jun, Apr, Jul, May.
    post_batch(batches["2026-06"]["id"])
    assert fetch_agent(agent["id"])["trailing_residual_cents"] == 15000, (
        "one statement in the window (2026-06) sums to 15000"
    )

    post_batch(batches["2026-04"]["id"])
    assert fetch_agent(agent["id"])["trailing_residual_cents"] == 20000, (
        "two statements fit the window: 15000 + 5000 == 20000"
    )

    post_batch(batches["2026-07"]["id"])
    assert fetch_agent(agent["id"])["trailing_residual_cents"] == 40000, (
        "the window is exactly full: 20000 + 15000 + 5000 == 40000"
    )

    post_batch(batches["2026-05"]["id"])
    trailing = fetch_agent(agent["id"])["trailing_residual_cents"]
    assert trailing == 45000, (
        "the last post is May, which displaces April by period_month DESC: "
        f"20000 + 15000 + 10000 == 45000, got {trailing}"
    )
    assert trailing != 50000, (
        "the KPI is a top-three window, not the sum of all four periods"
    )

    rows, meta = list_rows(api_client.list_agent_statements, {"agent_id": agent["id"]}, ADMIN)
    assert meta["total_count"] == 4, (
        f"one statement per posted period: expected 4, got {meta['total_count']}"
    )
    expected_gross = {period[0]: period[4] for period in periods}
    for row in rows:
        assert row["lifecycle_state"] == "DRAFT", (
            f"posting only drafts statements, got {row['lifecycle_state']} for "
            f"{row['period_month']}"
        )
        assert row["gross_after_trueup_cents"] == expected_gross[row["period_month"]], (
            f"{row['period_month']} must gross "
            f"{expected_gross[row['period_month']]}, got {row['gross_after_trueup_cents']}"
        )

    summary = get_success_data(api_client.get_agent_portfolio_summary(agent["id"], ADMIN))
    assert summary["trailing_residual_cents"] == 45000, (
        "the portfolio summary reports the same KPI as the agent record, got "
        f"{summary['trailing_residual_cents']}"
    )


def test_opening_deficit_crosses_only_from_an_issued_predecessor():
    """`opening_deficit_cents` is the `carry_forward_deficit_cents` of this same agent's statement for the calendar month immediately preceding this statement's `period_month`, and only when that predecessor's `lifecycle_state` is `ISSUED` or `FINALIZED`.

    "When no such statement exists, or when the predecessor is still `DRAFT`,
    this is 0."

    Design: Corner/calculations/opening_deficit_crosses_only_from_an_issued_predecessor
    """
    program = make_program(**NET_PROGRAM)
    issued_side = make_agent(
        name="A1 Issued Predecessor",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    draft_side = make_agent(
        name="A2 Draft Predecessor",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    merchant_terms = {
        "monthly_minimum_cents": 0,
        "per_transaction_fee_cents": 10,
        "equipment_lease_monthly_cents": 0,
        "boarded_on": "2026-04-10",
    }
    merchant_one = make_active_merchant(
        issued_side["id"], program["id"], **merchant_terms
    )
    merchant_two = make_active_merchant(
        draft_side["id"], program["id"], **merchant_terms
    )

    def post_period(period_month, coverage_start, coverage_end):
        batch = make_batch(
            program["id"],
            period_month=period_month,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
        )
        for merchant in (merchant_one, merchant_two):
            add_line(
                batch["id"],
                merchant["id"],
                transaction_count=100,
                sales_volume_cents=1000000,
                interchange_cents=0,
                assessments_cents=0,
                gross_income_cents=45100,
            )
        normalize_batch(batch["id"])
        post_batch(batch["id"])

    post_period("2026-06", "2026-06-01", "2026-07-01")
    june_issued = require_statement(issued_side["id"], "2026-06")
    june_draft = require_statement(draft_side["id"], "2026-06")

    # Byte-identical June positions: a 25000-cent debit against a 20000 residual.
    debit = {
        "kind": "MANUAL_DEBIT",
        "amount_cents": -25000,
        "reason": "June processor recovery",
    }
    for statement in (june_issued, june_draft):
        adjustment = propose_adjustment(statement["id"], ANALYST_ONE, **debit)
        review_adjustment(adjustment["id"], CONTROLLER_ONE)
        approve_adjustment(adjustment["id"], CONTROLLER_ONE)

    # Only A1's June statement leaves DRAFT.
    issue_statement(june_issued["id"])

    june_issued = require_statement(issued_side["id"], "2026-06")
    june_draft = require_statement(draft_side["id"], "2026-06")
    for label, statement in (("A1", june_issued), ("A2", june_draft)):
        assert statement["direct_residual_cents"] == 20000, (
            f"{label} June direct_residual_cents expected 20000, got "
            f"{statement['direct_residual_cents']}"
        )
        assert statement["adjustment_cents"] == -25000, (
            f"{label} June adjustment_cents expected -25000, got "
            f"{statement['adjustment_cents']}"
        )
        assert statement["net_payable_cents"] == 0, (
            f"{label} June net_payable_cents is floored at zero, got "
            f"{statement['net_payable_cents']}"
        )
        assert statement["carry_forward_deficit_cents"] == 5000, (
            f"{label} June carry_forward_deficit_cents expected 5000, got "
            f"{statement['carry_forward_deficit_cents']}"
        )
        assert_statement_money_lines_consistent(statement)
    assert june_issued["lifecycle_state"] == "ISSUED", (
        f"A1's June statement must be ISSUED, got {june_issued['lifecycle_state']}"
    )
    assert june_draft["lifecycle_state"] == "DRAFT", (
        f"A2's June statement must still be DRAFT, got {june_draft['lifecycle_state']}"
    )

    post_period("2026-07", "2026-07-01", "2026-08-01")
    july_from_issued = require_statement(issued_side["id"], "2026-07")
    july_from_draft = require_statement(draft_side["id"], "2026-07")

    assert july_from_issued["opening_deficit_cents"] == 5000, (
        "the ISSUED predecessor's deficit crosses the period boundary: expected "
        f"5000, got {july_from_issued['opening_deficit_cents']}"
    )
    assert july_from_issued["net_payable_cents"] == 15000, (
        f"20000 less the 5000 opening deficit, got {july_from_issued['net_payable_cents']}"
    )
    assert july_from_draft["opening_deficit_cents"] == 0, (
        "a DRAFT predecessor contributes no opening deficit, got "
        f"{july_from_draft['opening_deficit_cents']}"
    )
    assert july_from_draft["net_payable_cents"] == 20000, (
        f"the full 20000 residual is payable, got {july_from_draft['net_payable_cents']}"
    )

    issue_statement(july_from_issued["id"])
    issue_statement(july_from_draft["id"])

    july_from_issued = require_statement(issued_side["id"], "2026-07")
    july_from_draft = require_statement(draft_side["id"], "2026-07")

    assert july_from_issued["direct_residual_cents"] == 20000, (
        f"expected 20000, got {july_from_issued['direct_residual_cents']}"
    )
    assert july_from_issued["minimum_true_up_cents"] == 0, (
        f"a NO_MINIMUM program never trues up, got {july_from_issued['minimum_true_up_cents']}"
    )
    assert july_from_issued["advance_recoupment_cents"] == 0, (
        f"no advances exist, got {july_from_issued['advance_recoupment_cents']}"
    )
    assert july_from_issued["opening_deficit_cents"] == 5000, (
        f"the issue re-evaluates to the same 5000, got "
        f"{july_from_issued['opening_deficit_cents']}"
    )
    assert july_from_issued["net_payable_cents"] == 15000, (
        f"expected 15000, got {july_from_issued['net_payable_cents']}"
    )
    assert july_from_issued["carry_forward_deficit_cents"] == 0, (
        f"a positive balance carries nothing forward, got "
        f"{july_from_issued['carry_forward_deficit_cents']}"
    )
    assert_statement_money_lines_consistent(july_from_issued)

    assert july_from_draft["opening_deficit_cents"] == 0, (
        f"the DRAFT June deficit of 5000 never crosses, got "
        f"{july_from_draft['opening_deficit_cents']}"
    )
    assert july_from_draft["net_payable_cents"] == 20000, (
        f"expected 20000, got {july_from_draft['net_payable_cents']}"
    )
    assert_statement_money_lines_consistent(july_from_draft)

    assert require_statement(draft_side["id"], "2026-06")["carry_forward_deficit_cents"] == 5000, (
        "A2's June deficit was neither consumed nor cleared"
    )

    for label, agent in (("A1", issued_side), ("A2", draft_side)):
        trailing = fetch_agent(agent["id"])["trailing_residual_cents"]
        assert trailing == 40000, (
            f"{label}'s KPI reads gross_after_trueup_cents and is blind to the "
            f"deficit: expected 40000, got {trailing}"
        )
