"""Lifecycle state machines: initial states, idempotent replays, invalid
triggers and terminal-state lockdown.

Every test builds its own state through the public endpoints only; the harness
restarts the server and empties the database before each one, and the logical
clock starts at 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    ADMIN,
    ANALYST,
    ANALYST_ONE,
    ANALYST_ONE_ID,
    CONTROLLER,
    ApiErrorId,
    add_line,
    api_client,
    create_adjustment_payload,
    create_advance_payload,
    create_residual_batch_payload,
    create_residual_line_payload,
    depart_agent,
    fetch_agent,
    fetch_batch,
    fetch_line,
    fetch_merchant,
    fetch_statement_by_id,
    file_notice,
    finalize_statement,
    hold_payload,
    issue_statement,
    list_lines,
    list_profitability,
    list_rows,
    make_active_merchant,
    make_agent,
    make_batch,
    make_merchant,
    make_program,
    normalize_batch,
    notice_payload,
    post_batch,
    reassign_agent_payload,
    require_statement,
    reverse_batch,
    set_logical_clock,
    settle_payload,
    settle_statement,
    transfer_portfolio_payload,
    validate_error,
    validate_success,
)

# ---------------------------------------------------------------------------
# The shared July fixture used by most of the tests below: a NET_REVENUE_SPLIT
# program on NO_MINIMUM, one top-level agent at a 0.50 direct split, one active
# merchant carrying a 1,000-cent equipment lease, and one processor file line.
# ---------------------------------------------------------------------------
PERIOD = "2026-07"
COVERAGE_START = "2026-07-01"
COVERAGE_END = "2026-08-01"

PROGRAM_TERMS = {
    "name": "Atlantic Net Program",
    "buy_rate_bps": 45,
    "buy_rate_per_item_cents": 6,
    "assessment_bps": 13,
    "normalization_mode": "NET_REVENUE_SPLIT",
    "minimum_billing_mode": "NO_MINIMUM",
}
AGENT_TERMS = {
    "name": "A1 Principal",
    "split_pct": 0.50,
    "override_pct": 0.60,
    "vesting_start_date": "2024-01-15",
}
MERCHANT_TERMS = {
    "monthly_minimum_cents": 0,
    "per_transaction_fee_cents": 10,
    "equipment_lease_monthly_cents": 1000,
    "boarded_on": "2026-04-10",
}
LINE_FIGURES = {
    "transaction_count": 100,
    "sales_volume_cents": 1000000,
    "interchange_cents": 20000,
    "assessments_cents": 1300,
    "gross_income_cents": 40000,
}

# Pre-computed expected results for the fixture above.
EXPECTED_PROCESSOR_COST_CENTS = 5100
EXPECTED_NET_REVENUE_CENTS = 13600
EXPECTED_AGENT_BASIS_CENTS = 12600
EXPECTED_DIRECT_SPLIT_CENTS = 6300


def _july_scenario(post: bool = True, merchant_terms: dict = None) -> dict:
    """Program + agent + active merchant + one normalized July line."""
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(**AGENT_TERMS)
    terms = dict(MERCHANT_TERMS)
    terms.update(merchant_terms or {})
    merchant = make_active_merchant(agent["id"], program["id"], **terms)
    batch = make_batch(
        program["id"],
        period_month=PERIOD,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
    )
    line = add_line(batch["id"], merchant["id"], **LINE_FIGURES)
    batch = normalize_batch(batch["id"])
    if post:
        batch = post_batch(batch["id"])
    return {
        "program": program,
        "agent": agent,
        "merchant": merchant,
        "batch": batch,
        "line": line,
    }


# ---------------------------------------------------------------- initial states
def test_agent_starts_active_with_no_departure_fields():
    """A new agent is created with `status` set to `ACTIVE`, `departure_effective_date` and `vested_pct_at_departure` both null, `residual_hold` false, `portfolio_attrition_bps` at 0

    Design: Corner/state_machines/initial_state_of_agent_merchant_batch_and_advance
    """
    agent = make_agent(**AGENT_TERMS)

    assert agent["status"] == "ACTIVE", (
        f"a newly created agent starts ACTIVE, got {agent['status']!r}"
    )
    assert agent["departure_effective_date"] is None, (
        f"departure_effective_date starts null, got {agent['departure_effective_date']!r}"
    )
    assert agent["vested_pct_at_departure"] is None, (
        f"vested_pct_at_departure starts null, got {agent['vested_pct_at_departure']!r}"
    )
    assert agent["residual_hold"] is False, (
        f"residual_hold starts false, got {agent['residual_hold']!r}"
    )
    assert agent["portfolio_attrition_bps"] == 0, (
        f"portfolio_attrition_bps starts at 0, got {agent['portfolio_attrition_bps']}"
    )
    assert agent["version"] == 1, f"version starts at 1, got {agent['version']}"


def test_boarded_merchant_starts_pending_with_no_lifecycle_dates():
    """Boarding leaves the merchant with `status` `PENDING`, `attrition_date` and `reactivation_date` both null, and `clawed_back_bonus_cents` at 0, and it raises the owning agent's `portfolio_merchant_count` by one.

    Design: Corner/state_machines/initial_state_of_agent_merchant_batch_and_advance
    """
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(**AGENT_TERMS)

    merchant = make_merchant(agent["id"], program["id"], **MERCHANT_TERMS)

    assert merchant["status"] == "PENDING", (
        f"a boarded merchant starts PENDING, got {merchant['status']!r}"
    )
    assert merchant["attrition_date"] is None, (
        f"attrition_date starts null, got {merchant['attrition_date']!r}"
    )
    assert merchant["reactivation_date"] is None, (
        f"reactivation_date starts null, got {merchant['reactivation_date']!r}"
    )
    assert merchant["clawed_back_bonus_cents"] == 0, (
        f"clawed_back_bonus_cents starts at 0, got {merchant['clawed_back_bonus_cents']}"
    )
    owner = fetch_agent(agent["id"])
    assert owner["portfolio_merchant_count"] == 1, (
        "boarding raises the owning agent's portfolio_merchant_count to 1, got "
        f"{owner['portfolio_merchant_count']}"
    )


def test_ingested_batch_starts_received_with_zeroed_rollups():
    """The batch is created with `state` `RECEIVED`, `line_count` and `recall_count` at 0, `posted_at` null, and `gross_volume_cents`, `total_normalized_net_revenue_cents` and `iso_retained_cents` all at 0.

    Design: Corner/state_machines/initial_state_of_agent_merchant_batch_and_advance
    """
    program = make_program(**PROGRAM_TERMS)

    payload = create_residual_batch_payload(
        program["id"],
        period_month=PERIOD,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
        file_checksum="sha256:init-0001",
    )
    batch = validate_success(api_client.create_residual_batch(payload, ANALYST), 201)

    assert batch["state"] == "RECEIVED", (
        f"an ingested batch starts RECEIVED, got {batch['state']!r}"
    )
    assert batch["line_count"] == 0, f"line_count starts at 0, got {batch['line_count']}"
    assert batch["recall_count"] == 0, (
        f"recall_count starts at 0, got {batch['recall_count']}"
    )
    assert batch["posted_at"] is None, f"posted_at starts null, got {batch['posted_at']!r}"
    for field in (
        "gross_volume_cents",
        "total_normalized_net_revenue_cents",
        "iso_retained_cents",
    ):
        assert batch[field] == 0, f"{field} starts at 0, got {batch[field]}"


def test_funded_advance_starts_active_with_outstanding_equal_to_principal():
    """A funded advance starts with `state` `ACTIVE`, `outstanding_cents` equal to `principal_cents`, `cumulative_recouped_cents` at 0 and `months_recouped` at 0; the receiving agent's `advance_outstanding_cents` rises by the principal and its `version` is bumped.
    `recoupment_pct` is required when `recoupment_mode` is `PERCENT_OF_RESIDUAL` and must be absent or null otherwise

    Design: Corner/state_machines/initial_state_of_agent_merchant_batch_and_advance
    """
    agent = make_agent(**AGENT_TERMS)

    payload = create_advance_payload(
        agent["version"],
        advance_type="CASH_ADVANCE",
        recoupment_mode="STRAIGHT_LINE_AMORTIZATION",
        principal_cents=100000,
        amortization_months=10,
        first_recoupment_month="2026-08",
        last_recoupment_month="2027-05",
        funded_on="2026-08-01",
    )
    advance = validate_success(
        api_client.create_agent_advance(agent["id"], payload, ADMIN), 201
    )

    assert advance["state"] == "ACTIVE", (
        f"a funded advance starts ACTIVE, got {advance['state']!r}"
    )
    assert advance["outstanding_cents"] == 100000, (
        f"outstanding_cents starts equal to principal_cents, got {advance['outstanding_cents']}"
    )
    assert advance["cumulative_recouped_cents"] == 0, (
        f"cumulative_recouped_cents starts at 0, got {advance['cumulative_recouped_cents']}"
    )
    assert advance["months_recouped"] == 0, (
        f"months_recouped starts at 0, got {advance['months_recouped']}"
    )
    assert advance["recoupment_pct"] is None, (
        "a STRAIGHT_LINE_AMORTIZATION advance carries no recoupment_pct, got "
        f"{advance['recoupment_pct']!r}"
    )

    funded_agent = fetch_agent(agent["id"])
    assert funded_agent["advance_outstanding_cents"] == 100000, (
        "the agent's advance_outstanding_cents rises by the principal, got "
        f"{funded_agent['advance_outstanding_cents']}"
    )
    assert funded_agent["version"] == agent["version"] + 1, (
        f"funding bumps the agent version to {agent['version'] + 1}, got "
        f"{funded_agent['version']}"
    )


def test_posting_cascade_creates_one_draft_unsettled_statement():
    """It is never created directly by a client: it comes into existence as a side effect of a posting cascade or of a system-generated adjustment, always in `lifecycle_state` `DRAFT` and `settlement_state` `UNSETTLED`.
    a `DRAFT` statement forces steps 3 and 5 to zero, so it shows allocations and applied adjustments but never a minimum true-up and never an advance recoupment

    Design: Corner/state_machines/statement_and_adjustment_initial_states_after_first_post
    """
    scenario = _july_scenario()

    rows, meta = list_rows(
        api_client.list_agent_statements,
        {"agent_id": scenario["agent"]["id"], "period_month": PERIOD},
    )
    assert meta["total_count"] == 1, (
        f"the cascade upserts exactly one statement, got total_count {meta['total_count']}"
    )
    statement = rows[0]

    assert statement["lifecycle_state"] == "DRAFT", (
        f"the auto-created statement starts DRAFT, got {statement['lifecycle_state']!r}"
    )
    assert statement["settlement_state"] == "UNSETTLED", (
        f"the auto-created statement starts UNSETTLED, got {statement['settlement_state']!r}"
    )
    assert statement["issued_at"] is None, (
        f"issued_at is null before an issue, got {statement['issued_at']!r}"
    )
    assert statement["paid_on"] is None, (
        f"paid_on is null before a settlement, got {statement['paid_on']!r}"
    )
    assert statement["minimum_true_up_cents"] == 0, (
        f"a DRAFT statement forces the true-up to 0, got {statement['minimum_true_up_cents']}"
    )
    assert statement["advance_recoupment_cents"] == 0, (
        "a DRAFT statement forces the recoupment to 0, got "
        f"{statement['advance_recoupment_cents']}"
    )
    assert statement["opening_deficit_cents"] == 0, (
        f"there is no predecessor month, got {statement['opening_deficit_cents']}"
    )
    assert statement["direct_residual_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        f"direct_residual_cents expected {EXPECTED_DIRECT_SPLIT_CENTS}, got "
        f"{statement['direct_residual_cents']}"
    )
    assert statement["override_residual_cents"] == 0, (
        f"a top-level agent has no override tier, got {statement['override_residual_cents']}"
    )
    assert statement["gross_after_trueup_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        f"gross_after_trueup_cents expected {EXPECTED_DIRECT_SPLIT_CENTS}, got "
        f"{statement['gross_after_trueup_cents']}"
    )
    assert statement["net_payable_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        f"net_payable_cents expected {EXPECTED_DIRECT_SPLIT_CENTS}, got "
        f"{statement['net_payable_cents']}"
    )


def test_proposed_adjustment_starts_proposed_and_moves_no_money():
    """A client-proposed adjustment is created in `state` `PROPOSED` with `created_by_user_id` set to the proposing `X-User-ID` and `approved_by_user_id` null.
    No money moves at proposal time — the statement's `adjustment_cents` counts only `APPLIED` rows — but the parent statement's `version` is nonetheless bumped

    Design: Corner/state_machines/statement_and_adjustment_initial_states_after_first_post
    """
    scenario = _july_scenario()
    statement = require_statement(scenario["agent"]["id"], PERIOD)

    payload = create_adjustment_payload(
        statement["version"],
        kind="DISPUTE_CREDIT",
        amount_cents=500,
        reason="Interchange re-rate credit",
    )
    adjustment = validate_success(
        api_client.create_statement_adjustment(statement["id"], payload, ANALYST_ONE), 201
    )

    assert adjustment["state"] == "PROPOSED", (
        f"a client-proposed adjustment starts PROPOSED, got {adjustment['state']!r}"
    )
    assert adjustment["created_by_user_id"] == ANALYST_ONE_ID, (
        f"created_by_user_id expected {ANALYST_ONE_ID!r}, got "
        f"{adjustment['created_by_user_id']!r}"
    )
    assert adjustment["approved_by_user_id"] is None, (
        f"approved_by_user_id starts null, got {adjustment['approved_by_user_id']!r}"
    )
    assert adjustment["version"] == 1, (
        f"the adjustment's version starts at 1, got {adjustment['version']}"
    )

    after = fetch_statement_by_id(statement["id"])
    assert after["adjustment_cents"] == 0, (
        f"a PROPOSED adjustment moves no money, got adjustment_cents {after['adjustment_cents']}"
    )
    assert after["net_payable_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        f"net_payable_cents stays {EXPECTED_DIRECT_SPLIT_CENTS}, got "
        f"{after['net_payable_cents']}"
    )
    assert after["version"] == statement["version"] + 1, (
        "the proposal bumps the parent statement's version to "
        f"{statement['version'] + 1}, got {after['version']}"
    )


# ------------------------------------------------------------------ idempotency
def test_second_activate_is_refused_and_bumps_nothing():
    """Activation moves a merchant from `PENDING` to `ACTIVE` and is what makes it eligible for monthly-minimum reconciliation. It is refused with `ERR_MERCHANT_STATE_INVALID` from any other status
    `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row

    Design: Corner/state_machines/merchant_activate_then_activate_again_is_refused
    """
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(**AGENT_TERMS)
    merchant = make_merchant(agent["id"], program["id"], **MERCHANT_TERMS)

    first = validate_success(api_client.activate_merchant(merchant["id"], ADMIN))
    assert first["status"] == "ACTIVE", (
        f"the first activate moves the merchant to ACTIVE, got {first['status']!r}"
    )
    assert first["version"] == 2, (
        f"the first activate bumps the version to 2, got {first['version']}"
    )

    replay = api_client.activate_merchant(merchant["id"], ADMIN)
    validate_error(replay, ApiErrorId.ERR_MERCHANT_STATE_INVALID.value)

    unchanged = fetch_merchant(merchant["id"])
    assert unchanged["status"] == "ACTIVE", (
        f"the refused replay leaves the status ACTIVE, got {unchanged['status']!r}"
    )
    assert unchanged["version"] == 2, (
        f"the refused replay increments nothing, expected version 2, got {unchanged['version']}"
    )

    owner = fetch_agent(agent["id"])
    assert owner["portfolio_attrition_bps"] == 0, (
        f"one ACTIVE merchant and no attrition is 0 bps, got {owner['portfolio_attrition_bps']}"
    )
    assert owner["residual_hold"] is False, (
        f"0 bps is below the hold threshold, got residual_hold {owner['residual_hold']!r}"
    )


def test_second_normalize_is_refused():
    """moves the batch from `RECEIVED` to `NORMALIZED` and is where the program's economics are applied. It is refused with `ERR_BATCH_STATE_INVALID` from any other state

    Design: Corner/state_machines/batch_normalize_and_recall_are_not_idempotent
    """
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(**AGENT_TERMS)
    merchant = make_active_merchant(agent["id"], program["id"], **MERCHANT_TERMS)
    batch = make_batch(
        program["id"],
        period_month=PERIOD,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
    )
    line = add_line(batch["id"], merchant["id"], **LINE_FIGURES)

    normalized = validate_success(
        api_client.normalize_residual_batch(batch["id"], ANALYST)
    )
    assert normalized["state"] == "NORMALIZED", (
        f"the first normalize moves the batch to NORMALIZED, got {normalized['state']!r}"
    )
    priced = fetch_line(line["id"])
    assert priced["processor_cost_cents"] == EXPECTED_PROCESSOR_COST_CENTS, (
        f"processor_cost_cents expected {EXPECTED_PROCESSOR_COST_CENTS}, got "
        f"{priced['processor_cost_cents']}"
    )
    assert priced["normalized_net_revenue_cents"] == EXPECTED_NET_REVENUE_CENTS, (
        f"normalized_net_revenue_cents expected {EXPECTED_NET_REVENUE_CENTS}, got "
        f"{priced['normalized_net_revenue_cents']}"
    )
    assert priced["normalization_mode_applied"] == "NET_REVENUE_SPLIT", (
        "the program's mode is stamped onto the line, got "
        f"{priced['normalization_mode_applied']!r}"
    )

    replay = api_client.normalize_residual_batch(batch["id"], ANALYST)
    validate_error(replay, ApiErrorId.ERR_BATCH_STATE_INVALID.value)

    after = fetch_batch(batch["id"])
    assert after["state"] == "NORMALIZED", (
        f"the refused replay leaves the batch NORMALIZED, got {after['state']!r}"
    )
    assert after["total_normalized_net_revenue_cents"] == EXPECTED_NET_REVENUE_CENTS, (
        f"the roll-up stays {EXPECTED_NET_REVENUE_CENTS}, got "
        f"{after['total_normalized_net_revenue_cents']}"
    )
    assert after["recall_count"] == 0, (
        f"no recall happened, expected recall_count 0, got {after['recall_count']}"
    )


def test_second_recall_is_refused_and_recall_count_stays_one():
    """is normalization's undo, moving the batch from `NORMALIZED` back to `RECEIVED` so a corrected file can be re-ingested or a missing merchant added. It is available only from `NORMALIZED`.
    Each recall raises `recall_count` by one, and the loop may be traversed as many times as the operator needs.
    while `line_count` and `gross_volume_cents` deliberately keep their ingested values

    Design: Corner/state_machines/batch_normalize_and_recall_are_not_idempotent
    """
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(**AGENT_TERMS)
    merchant = make_active_merchant(agent["id"], program["id"], **MERCHANT_TERMS)
    batch = make_batch(
        program["id"],
        period_month=PERIOD,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
    )
    line = add_line(batch["id"], merchant["id"], **LINE_FIGURES)
    normalize_batch(batch["id"])

    recalled = validate_success(api_client.recall_residual_batch(batch["id"], ANALYST))
    assert recalled["state"] == "RECEIVED", (
        f"the recall returns the batch to RECEIVED, got {recalled['state']!r}"
    )
    assert recalled["recall_count"] == 1, (
        f"the first recall raises recall_count to 1, got {recalled['recall_count']}"
    )
    cleared = fetch_line(line["id"])
    assert cleared["processor_cost_cents"] == 0, (
        f"the recall resets processor_cost_cents to 0, got {cleared['processor_cost_cents']}"
    )
    assert cleared["normalized_net_revenue_cents"] == 0, (
        "the recall resets normalized_net_revenue_cents to 0, got "
        f"{cleared['normalized_net_revenue_cents']}"
    )
    assert cleared["normalization_mode_applied"] is None, (
        "the recall resets normalization_mode_applied to null, got "
        f"{cleared['normalization_mode_applied']!r}"
    )

    replay = api_client.recall_residual_batch(batch["id"], ANALYST)
    validate_error(replay, ApiErrorId.ERR_BATCH_STATE_INVALID.value)

    after = fetch_batch(batch["id"])
    assert after["recall_count"] == 1, (
        f"the refused second recall leaves recall_count at 1, got {after['recall_count']}"
    )
    assert after["line_count"] == 1, (
        f"line_count survives the recall, expected 1, got {after['line_count']}"
    )
    assert after["gross_volume_cents"] == LINE_FIGURES["sales_volume_cents"], (
        f"gross_volume_cents survives the recall, expected "
        f"{LINE_FIGURES['sales_volume_cents']}, got {after['gross_volume_cents']}"
    )
    assert after["total_normalized_net_revenue_cents"] == 0, (
        "the recall zeroes total_normalized_net_revenue_cents, got "
        f"{after['total_normalized_net_revenue_cents']}"
    )


def test_received_batch_refuses_recall_post_and_reverse():
    """is normalization's undo, moving the batch from `NORMALIZED` back to `RECEIVED` so a corrected file can be re-ingested or a missing merchant added. It is available only from `NORMALIZED`.
    It advances the batch from `NORMALIZED` to `POSTED` and is refused with `ERR_BATCH_STATE_INVALID` from any other state
    it moves the batch from `POSTED` to `REVERSED` — a terminal state from which nothing returns. It is refused with `ERR_BATCH_STATE_INVALID` from any other state

    Design: Corner/state_machines/batch_triggers_outside_the_transition_list_are_refused
    """
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(**AGENT_TERMS)
    merchant = make_active_merchant(agent["id"], program["id"], **MERCHANT_TERMS)
    batch = make_batch(
        program["id"],
        period_month=PERIOD,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
    )
    add_line(batch["id"], merchant["id"], **LINE_FIGURES)

    validate_error(
        api_client.recall_residual_batch(batch["id"], ANALYST),
        ApiErrorId.ERR_BATCH_STATE_INVALID.value,
    )
    validate_error(
        api_client.post_residual_batch(batch["id"], CONTROLLER),
        ApiErrorId.ERR_BATCH_STATE_INVALID.value,
    )
    validate_error(
        api_client.reverse_residual_batch(batch["id"], CONTROLLER),
        ApiErrorId.ERR_BATCH_STATE_INVALID.value,
    )

    after = fetch_batch(batch["id"])
    assert after["state"] == "RECEIVED", (
        f"none of the three refused triggers may move the batch, got {after['state']!r}"
    )
    assert after["posted_at"] is None, (
        f"posted_at stays null on an unposted batch, got {after['posted_at']!r}"
    )
    assert after["recall_count"] == 0, (
        f"the refused recall leaves recall_count at 0, got {after['recall_count']}"
    )
    assert after["iso_retained_cents"] == 0, (
        f"nothing was posted, so iso_retained_cents stays 0, got {after['iso_retained_cents']}"
    )
    rows = list_profitability(residual_batch_id=batch["id"])
    assert rows == [], (
        f"a refused post creates no profitability row, got {len(rows)} row(s)"
    )


def test_normalized_batch_refuses_line_append_and_reversal():
    """only while the batch is `RECEIVED`; an append against a batch in any other state is `ERR_BATCH_STATE_INVALID` (HTTP 409)
    it moves the batch from `POSTED` to `REVERSED` — a terminal state from which nothing returns. It is refused with `ERR_BATCH_STATE_INVALID` from any other state

    Design: Corner/state_machines/batch_triggers_outside_the_transition_list_are_refused
    """
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(**AGENT_TERMS)
    first = make_active_merchant(agent["id"], program["id"], **MERCHANT_TERMS)
    second = make_active_merchant(agent["id"], program["id"], **MERCHANT_TERMS)
    batch = make_batch(
        program["id"],
        period_month=PERIOD,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
    )
    add_line(batch["id"], first["id"], **LINE_FIGURES)
    normalize_batch(batch["id"])

    late_append = api_client.create_residual_line(
        batch["id"],
        create_residual_line_payload(second["id"], **LINE_FIGURES),
        ANALYST,
    )
    validate_error(late_append, ApiErrorId.ERR_BATCH_STATE_INVALID.value)

    lines = list_lines(residual_batch_id=batch["id"])
    assert len(lines) == 1, (
        f"the refused append adds no line, expected 1 line, got {len(lines)}"
    )
    after_append = fetch_batch(batch["id"])
    assert after_append["line_count"] == 1, (
        f"line_count stays 1 after the refused append, got {after_append['line_count']}"
    )

    validate_error(
        api_client.reverse_residual_batch(batch["id"], CONTROLLER),
        ApiErrorId.ERR_BATCH_STATE_INVALID.value,
    )
    after_reverse = fetch_batch(batch["id"])
    assert after_reverse["state"] == "NORMALIZED", (
        f"a NORMALIZED batch cannot be reversed, got {after_reverse['state']!r}"
    )
    assert after_reverse["posted_at"] is None, (
        f"posted_at stays null, got {after_reverse['posted_at']!r}"
    )


def test_reversed_batch_refuses_every_further_trigger():
    """it moves the batch from `POSTED` to `REVERSED` — a terminal state from which nothing returns. It is refused with `ERR_BATCH_STATE_INVALID` from any other state
    only while the batch is `RECEIVED`; an append against a batch in any other state is `ERR_BATCH_STATE_INVALID` (HTTP 409)

    Design: Corner/state_machines/reversed_batch_admits_no_further_transition
    """
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(**AGENT_TERMS)
    merchant = make_active_merchant(agent["id"], program["id"], **MERCHANT_TERMS)
    spare = make_active_merchant(agent["id"], program["id"], **MERCHANT_TERMS)
    batch = make_batch(
        program["id"],
        period_month=PERIOD,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
    )
    add_line(batch["id"], merchant["id"], **LINE_FIGURES)
    normalize_batch(batch["id"])
    post_batch(batch["id"])
    reversed_batch = reverse_batch(batch["id"])
    assert reversed_batch["state"] == "REVERSED", (
        f"the reversal must land on REVERSED, got {reversed_batch['state']!r}"
    )

    validate_error(
        api_client.create_residual_line(
            batch["id"],
            create_residual_line_payload(spare["id"], **LINE_FIGURES),
            ANALYST,
        ),
        ApiErrorId.ERR_BATCH_STATE_INVALID.value,
    )
    validate_error(
        api_client.normalize_residual_batch(batch["id"], ANALYST),
        ApiErrorId.ERR_BATCH_STATE_INVALID.value,
    )
    validate_error(
        api_client.recall_residual_batch(batch["id"], ANALYST),
        ApiErrorId.ERR_BATCH_STATE_INVALID.value,
    )
    validate_error(
        api_client.post_residual_batch(batch["id"], CONTROLLER),
        ApiErrorId.ERR_BATCH_STATE_INVALID.value,
    )
    validate_error(
        api_client.reverse_residual_batch(batch["id"], CONTROLLER),
        ApiErrorId.ERR_BATCH_STATE_INVALID.value,
    )

    after = fetch_batch(batch["id"])
    assert after["state"] == "REVERSED", (
        f"REVERSED is terminal, so the state never changes again, got {after['state']!r}"
    )
    assert after["line_count"] == 1, (
        f"the refused append leaves line_count at 1, got {after['line_count']}"
    )
    assert after["posted_at"] is None, (
        f"the reversal returned posted_at to null, got {after['posted_at']!r}"
    )
    assert after["iso_retained_cents"] == 0, (
        f"the reversal returned iso_retained_cents to 0, got {after['iso_retained_cents']}"
    )
    assert after["recall_count"] == 0, (
        f"the refused recall leaves recall_count at 0, got {after['recall_count']}"
    )


def test_reversal_releases_the_checksum_for_re_ingest():
    """Reversal also releases the batch's `file_checksum` for re-ingest.
    `file_checksum` is unique across all batches whose `state` is not `REVERSED`

    Design: Corner/state_machines/reversed_batch_admits_no_further_transition
    """
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(**AGENT_TERMS)
    merchant = make_active_merchant(agent["id"], program["id"], **MERCHANT_TERMS)
    reissued_checksum = "sha256:reissue-0007"
    batch = make_batch(
        program["id"],
        period_month=PERIOD,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
        file_checksum=reissued_checksum,
    )
    add_line(batch["id"], merchant["id"], **LINE_FIGURES)
    normalize_batch(batch["id"])
    post_batch(batch["id"])
    reverse_batch(batch["id"])

    corrected = validate_success(
        api_client.create_residual_batch(
            create_residual_batch_payload(
                program["id"],
                period_month=PERIOD,
                coverage_start=COVERAGE_START,
                coverage_end=COVERAGE_END,
                file_checksum=reissued_checksum,
            ),
            ANALYST,
        ),
        201,
    )
    assert corrected["file_checksum"] == reissued_checksum, (
        "the corrected file is ingested under the released checksum, got "
        f"{corrected['file_checksum']!r}"
    )
    assert corrected["state"] == "RECEIVED", (
        f"the re-ingested batch starts RECEIVED, got {corrected['state']!r}"
    )
    assert corrected["id"] != batch["id"], (
        "the re-ingest creates a new batch rather than resurrecting the reversed one"
    )
    assert fetch_batch(batch["id"])["state"] == "REVERSED", (
        "the reversed batch stays REVERSED after the re-ingest"
    )


# --------------------------------------------------- terminal statement states
def test_finalized_statement_refuses_issue_recall_and_finalize():
    """Only a `ResidualController` may issue, and only from `DRAFT`; an issue attempt from `ISSUED` or `FINALIZED` is `ERR_STATEMENT_STATE_INVALID` (HTTP 409).
    Recall is available only from `lifecycle_state` `ISSUED` (otherwise `ERR_STATEMENT_STATE_INVALID`)
    Finalizing moves the statement from `ISSUED` to `FINALIZED` and is available only from `ISSUED`; anything else is `ERR_STATEMENT_STATE_INVALID`.

    Design: Corner/state_machines/finalized_statement_lifecycle_is_locked_down
    """
    scenario = _july_scenario()
    statement = require_statement(scenario["agent"]["id"], PERIOD)
    issue_statement(statement["id"])
    finalized = finalize_statement(statement["id"])
    assert finalized["lifecycle_state"] == "FINALIZED", (
        f"the statement must reach FINALIZED, got {finalized['lifecycle_state']!r}"
    )

    validate_error(
        api_client.issue_agent_statement(statement["id"], CONTROLLER),
        ApiErrorId.ERR_STATEMENT_STATE_INVALID.value,
    )
    validate_error(
        api_client.recall_agent_statement(statement["id"], CONTROLLER),
        ApiErrorId.ERR_STATEMENT_STATE_INVALID.value,
    )
    validate_error(
        api_client.finalize_agent_statement(statement["id"], CONTROLLER),
        ApiErrorId.ERR_STATEMENT_STATE_INVALID.value,
    )

    after = fetch_statement_by_id(statement["id"])
    assert after["lifecycle_state"] == "FINALIZED", (
        "FINALIZED is the authoring dimension's terminal state, got "
        f"{after['lifecycle_state']!r}"
    )
    assert after["issued_at"] is not None, (
        "the refused recall leaves issued_at stamped, got None"
    )
    assert after["settlement_state"] == "UNSETTLED", (
        f"the settlement dimension was never touched, got {after['settlement_state']!r}"
    )


def test_finalized_statement_refuses_an_adjustment_proposal():
    """a proposal against a `FINALIZED` statement is `ERR_STATEMENT_STATE_INVALID`
    no adjustment may be applied to it afterwards

    Design: Corner/state_machines/finalized_statement_lifecycle_is_locked_down
    """
    scenario = _july_scenario()
    statement = require_statement(scenario["agent"]["id"], PERIOD)
    issue_statement(statement["id"])
    finalized = finalize_statement(statement["id"])

    refused = api_client.create_statement_adjustment(
        statement["id"],
        create_adjustment_payload(
            finalized["version"],
            kind="DISPUTE_CREDIT",
            amount_cents=1500,
            reason="Late processor credit discovered after finalization",
        ),
        ANALYST_ONE,
    )
    validate_error(refused, ApiErrorId.ERR_STATEMENT_STATE_INVALID.value)

    rows, meta = list_rows(
        api_client.list_statement_adjustments, {"statement_id": statement["id"]}
    )
    assert meta["total_count"] == 0, (
        f"the refused proposal creates no adjustment, got {meta['total_count']}"
    )
    assert rows == [], f"the adjustment collection stays empty, got {len(rows)} row(s)"
    after = fetch_statement_by_id(statement["id"])
    assert after["adjustment_cents"] == 0, (
        f"adjustment_cents stays 0, got {after['adjustment_cents']}"
    )
    assert after["version"] == finalized["version"], (
        "a refused proposal bumps nothing, expected version "
        f"{finalized['version']}, got {after['version']}"
    )


def test_finalized_statement_may_still_be_settled():
    """The `lifecycle_state` must be `ISSUED` or `FINALIZED`; settling a `DRAFT` statement is `ERR_STATEMENT_STATE_INVALID`, because a draft has no true-up and no recoupment booked against it.
    On success `paid_on` is recorded and the statement moves `UNSETTLED` → `SETTLED`

    Design: Corner/state_machines/finalized_statement_lifecycle_is_locked_down
    """
    scenario = _july_scenario()
    statement = require_statement(scenario["agent"]["id"], PERIOD)
    issue_statement(statement["id"])
    finalize_statement(statement["id"])

    settled = validate_success(
        api_client.settle_agent_statement(
            statement["id"], settle_payload("2026-08-14"), CONTROLLER
        )
    )
    assert settled["settlement_state"] == "SETTLED", (
        f"a FINALIZED statement still settles, got {settled['settlement_state']!r}"
    )
    assert settled["paid_on"] == "2026-08-14", (
        f"paid_on is recorded as supplied, got {settled['paid_on']!r}"
    )
    assert settled["lifecycle_state"] == "FINALIZED", (
        "settling does not disturb the authoring dimension, got "
        f"{settled['lifecycle_state']!r}"
    )
    assert settled["net_payable_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        f"net_payable_cents expected {EXPECTED_DIRECT_SPLIT_CENTS}, got "
        f"{settled['net_payable_cents']}"
    )


def test_settled_statement_refuses_a_second_settlement_and_a_hold():
    """The `settlement_state` must be `UNSETTLED`; settling from `HELD` or from `SETTLED` is `ERR_SETTLEMENT_STATE_INVALID`.
    A hold attempted from `HELD` or `SETTLED` is `ERR_SETTLEMENT_STATE_INVALID`.

    Design: Corner/state_machines/settled_statement_settlement_dimension_is_locked_down
    """
    scenario = _july_scenario()
    statement = require_statement(scenario["agent"]["id"], PERIOD)
    issue_statement(statement["id"])
    settled = settle_statement(statement["id"], "2026-08-14")
    assert settled["settlement_state"] == "SETTLED", (
        f"the statement must reach SETTLED, got {settled['settlement_state']!r}"
    )

    validate_error(
        api_client.settle_agent_statement(
            statement["id"], settle_payload("2026-08-20"), CONTROLLER
        ),
        ApiErrorId.ERR_SETTLEMENT_STATE_INVALID.value,
    )
    validate_error(
        api_client.hold_agent_statement(
            statement["id"], hold_payload("MANUAL_REVIEW"), CONTROLLER
        ),
        ApiErrorId.ERR_SETTLEMENT_STATE_INVALID.value,
    )

    after = fetch_statement_by_id(statement["id"])
    assert after["settlement_state"] == "SETTLED", (
        f"SETTLED is the settlement dimension's terminal state, got "
        f"{after['settlement_state']!r}"
    )
    assert after["paid_on"] == "2026-08-14", (
        f"the refused second settlement leaves paid_on untouched, got {after['paid_on']!r}"
    )


def test_settled_statement_refuses_a_hold_release():
    """Releasing a hold moves the statement `HELD` → `UNSETTLED` and clears `hold_reason`, and is available only from `HELD`.

    Design: Corner/state_machines/settled_statement_settlement_dimension_is_locked_down
    """
    scenario = _july_scenario()
    statement = require_statement(scenario["agent"]["id"], PERIOD)
    issue_statement(statement["id"])
    settle_statement(statement["id"], "2026-08-14")

    validate_error(
        api_client.release_agent_statement_hold(statement["id"], CONTROLLER),
        ApiErrorId.ERR_SETTLEMENT_STATE_INVALID.value,
    )

    after = fetch_statement_by_id(statement["id"])
    assert after["settlement_state"] == "SETTLED", (
        f"the refused release leaves the statement SETTLED, got "
        f"{after['settlement_state']!r}"
    )
    assert after["paid_on"] == "2026-08-14", (
        f"paid_on survives the refused release, got {after['paid_on']!r}"
    )


def test_settled_statement_cannot_be_recalled_to_draft():
    """recalling a settled statement is `ERR_SETTLEMENT_STATE_INVALID` (HTTP 409), because the money has already left

    Design: Corner/state_machines/settled_statement_settlement_dimension_is_locked_down
    """
    scenario = _july_scenario()
    statement = require_statement(scenario["agent"]["id"], PERIOD)
    issued = issue_statement(statement["id"])
    settle_statement(statement["id"], "2026-08-14")

    validate_error(
        api_client.recall_agent_statement(statement["id"], CONTROLLER),
        ApiErrorId.ERR_SETTLEMENT_STATE_INVALID.value,
    )

    after = fetch_statement_by_id(statement["id"])
    assert after["lifecycle_state"] == "ISSUED", (
        f"the refused recall leaves the statement ISSUED, got {after['lifecycle_state']!r}"
    )
    assert after["issued_at"] == issued["issued_at"], (
        f"issued_at is untouched, expected {issued['issued_at']!r}, got {after['issued_at']!r}"
    )
    assert after["gross_after_trueup_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        "no recompute happened, so gross_after_trueup_cents stays "
        f"{EXPECTED_DIRECT_SPLIT_CENTS}, got {after['gross_after_trueup_cents']}"
    )


# ------------------------------------------------------- the departed terminus
def test_departed_agent_refuses_notice_rescind_and_a_second_departure():
    """Both transitions are refused with `ERR_AGENT_STATE_INVALID` when the agent is not in the required starting status.
    Departure moves the agent `DEPARTURE_NOTICE` → `DEPARTED`, the agent lifecycle's terminal status

    Design: Corner/state_machines/departed_agent_admits_only_portfolio_transfer
    """
    agent = make_agent(**AGENT_TERMS)
    file_notice(agent["id"], "2026-08-01")
    departed = depart_agent(agent["id"])
    assert departed["status"] == "DEPARTED", (
        f"the agent must reach DEPARTED, got {departed['status']!r}"
    )
    assert departed["vested_pct_at_departure"] == 50, (
        "the vesting schedule is frozen at 50 for a 2024-01-15 anchor read on "
        f"2026-08-01, got {departed['vested_pct_at_departure']}"
    )

    validate_error(
        api_client.file_agent_notice(agent["id"], notice_payload("2026-09-01"), ADMIN),
        ApiErrorId.ERR_AGENT_STATE_INVALID.value,
    )
    validate_error(
        api_client.rescind_agent_notice(agent["id"], ADMIN),
        ApiErrorId.ERR_AGENT_STATE_INVALID.value,
    )
    validate_error(
        api_client.depart_agent(agent["id"], ADMIN),
        ApiErrorId.ERR_AGENT_STATE_INVALID.value,
    )

    after = fetch_agent(agent["id"])
    assert after["status"] == "DEPARTED", (
        f"DEPARTED is terminal, so the status never moves again, got {after['status']!r}"
    )
    assert after["departure_effective_date"] == "2026-08-01", (
        "the refused rescind leaves departure_effective_date in place, got "
        f"{after['departure_effective_date']!r}"
    )
    assert after["vested_pct_at_departure"] == 50, (
        f"the frozen vesting percentage is untouched, got {after['vested_pct_at_departure']}"
    )
    assert after["vested_pct"] == 50, (
        "a departed agent's vested_pct returns the frozen value, got "
        f"{after['vested_pct']}"
    )


def test_departed_agent_still_accepts_a_portfolio_transfer():
    """The transfer is only available from `DEPARTED` — from anywhere else it is `ERR_AGENT_STATE_INVALID` — and it does not change the departing agent's status, which stays `DEPARTED`.

    Design: Corner/state_machines/departed_agent_admits_only_portfolio_transfer
    """
    program = make_program(**PROGRAM_TERMS)
    leaver = make_agent(**AGENT_TERMS)
    successor = make_agent(name="A2 Successor", split_pct=0.40, override_pct=0.60,
                           vesting_start_date="2025-03-01")
    merchant = make_active_merchant(leaver["id"], program["id"], **MERCHANT_TERMS)
    file_notice(leaver["id"], "2026-08-01")
    depart_agent(leaver["id"])

    transferred = validate_success(
        api_client.transfer_agent_portfolio(
            leaver["id"], transfer_portfolio_payload(successor["id"]), ADMIN
        )
    )
    assert transferred["status"] == "DEPARTED", (
        f"the transfer leaves the departing agent DEPARTED, got {transferred['status']!r}"
    )
    assert transferred["portfolio_merchant_count"] == 0, (
        "the departing agent's book is emptied, got "
        f"{transferred['portfolio_merchant_count']}"
    )
    moved = fetch_merchant(merchant["id"])
    assert moved["owning_agent_id"] == successor["id"], (
        f"the merchant is re-pointed at the target, got {moved['owning_agent_id']!r}"
    )
    receiver = fetch_agent(successor["id"])
    assert receiver["portfolio_merchant_count"] == 1, (
        f"the receiving agent's book grows to 1, got {receiver['portfolio_merchant_count']}"
    )


def test_departed_owner_blocks_activation_and_inbound_reassignment():
    """refused with `ERR_AGENT_STATE_INVALID` when the owning agent is no longer `ACTIVE`
    The destination agent must exist and must have `status` `ACTIVE`, otherwise `ERR_AGENT_STATE_INVALID`

    Design: Corner/state_machines/departed_agent_admits_only_portfolio_transfer
    """
    program = make_program(**PROGRAM_TERMS)
    leaver = make_agent(**AGENT_TERMS)
    other = make_agent(name="A2 Peer", split_pct=0.40, override_pct=0.60,
                       vesting_start_date="2025-03-01")
    pending = make_merchant(leaver["id"], program["id"], **MERCHANT_TERMS)
    elsewhere = make_active_merchant(other["id"], program["id"], **MERCHANT_TERMS)
    file_notice(leaver["id"], "2026-08-01")
    depart_agent(leaver["id"])

    validate_error(
        api_client.activate_merchant(pending["id"], ADMIN),
        ApiErrorId.ERR_AGENT_STATE_INVALID.value,
    )
    validate_error(
        api_client.reassign_merchant_agent(
            elsewhere["id"],
            reassign_agent_payload(leaver["id"], elsewhere["version"]),
            ADMIN,
        ),
        ApiErrorId.ERR_AGENT_STATE_INVALID.value,
    )

    assert fetch_merchant(pending["id"])["status"] == "PENDING", (
        "the refused activation leaves the merchant PENDING"
    )
    assert fetch_merchant(elsewhere["id"])["owning_agent_id"] == other["id"], (
        "the refused reassignment leaves ownership where it was"
    )
    assert fetch_agent(leaver["id"])["portfolio_merchant_count"] == 1, (
        "the departed agent still owns only its own pending merchant"
    )


def test_a_notice_may_not_be_backdated_but_may_land_on_the_clock_date():
    """That date must be on or after the logical clock's current date — a notice cannot be backdated — and a violation is `ERR_DEPARTURE_DATE_OUT_OF_RANGE` (HTTP 422).

    Design: Corner/state_machines/notice_and_depart_dates_are_bounded_by_the_clock
    """
    agent = make_agent(**AGENT_TERMS)

    backdated = api_client.file_agent_notice(
        agent["id"], notice_payload("2026-07-31"), ADMIN
    )
    validate_error(backdated, ApiErrorId.ERR_DEPARTURE_DATE_OUT_OF_RANGE.value)

    untouched = fetch_agent(agent["id"])
    assert untouched["status"] == "ACTIVE", (
        f"the refused notice leaves the agent ACTIVE, got {untouched['status']!r}"
    )
    assert untouched["departure_effective_date"] is None, (
        "the refused notice writes no departure_effective_date, got "
        f"{untouched['departure_effective_date']!r}"
    )
    assert untouched["version"] == agent["version"], (
        f"a refused notice bumps nothing, expected version {agent['version']}, got "
        f"{untouched['version']}"
    )

    on_the_boundary = validate_success(
        api_client.file_agent_notice(agent["id"], notice_payload("2026-08-01"), ADMIN)
    )
    assert on_the_boundary["status"] == "DEPARTURE_NOTICE", (
        "a notice dated exactly on the clock date is accepted, got "
        f"{on_the_boundary['status']!r}"
    )
    assert on_the_boundary["departure_effective_date"] == "2026-08-01", (
        f"the effective date is recorded as supplied, got "
        f"{on_the_boundary['departure_effective_date']!r}"
    )


def test_departure_waits_for_the_clock_to_reach_the_effective_date():
    """Departure moves the agent `DEPARTURE_NOTICE` → `DEPARTED`, the agent lifecycle's terminal status, and is permitted only once the logical clock's current date has reached `departure_effective_date`; an early attempt is `ERR_DEPARTURE_DATE_OUT_OF_RANGE`.

    Design: Corner/state_machines/notice_and_depart_dates_are_bounded_by_the_clock
    """
    agent = make_agent(**AGENT_TERMS)
    noticed = file_notice(agent["id"], "2026-09-15")
    assert noticed["status"] == "DEPARTURE_NOTICE", (
        f"the notice moves the agent to DEPARTURE_NOTICE, got {noticed['status']!r}"
    )

    early = api_client.depart_agent(agent["id"], ADMIN)
    validate_error(early, ApiErrorId.ERR_DEPARTURE_DATE_OUT_OF_RANGE.value)

    waiting = fetch_agent(agent["id"])
    assert waiting["status"] == "DEPARTURE_NOTICE", (
        f"the early departure changes nothing, got {waiting['status']!r}"
    )
    assert waiting["vested_pct_at_departure"] is None, (
        "no vesting percentage is frozen by a refused departure, got "
        f"{waiting['vested_pct_at_departure']!r}"
    )

    set_logical_clock("2026-09-15T00:00:00Z")
    departed = validate_success(api_client.depart_agent(agent["id"], ADMIN))
    assert departed["status"] == "DEPARTED", (
        f"once the clock reaches the effective date the departure completes, got "
        f"{departed['status']!r}"
    )
    assert departed["vested_pct_at_departure"] == 50, (
        "the schedule freezes at 50 for a 2024-01-15 anchor read on 2026-09-15, got "
        f"{departed['vested_pct_at_departure']}"
    )
