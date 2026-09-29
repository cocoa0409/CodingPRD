"""Cross-entity cascades, the attrition risk hold, the period lock and the
adjustment review cycle.

Every test builds its own state through the public endpoints only; the harness
restarts the server and empties the database before each one, and the logical
clock starts at 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    ADMIN,
    ANALYST_ONE,
    ANALYST_ONE_ID,
    CONTROLLER,
    CONTROLLER_TWO,
    CONTROLLER_TWO_ID,
    HOLD_REASON_PORTFOLIO_ATTRITION,
    SYSTEM_USER_ID,
    ApiErrorId,
    add_line,
    api_client,
    approve_adjustment,
    attrite_merchant,
    create_adjustment_payload,
    create_agent_payload,
    create_merchant_payload,
    create_percent_advance_payload,
    depart_agent,
    fetch_adjustment,
    fetch_agent,
    fetch_batch,
    fetch_merchant,
    fetch_program,
    fetch_statement_by_id,
    file_notice,
    finalize_statement,
    issue_statement,
    list_rows,
    make_active_merchant,
    make_agent,
    make_batch,
    make_merchant,
    make_program,
    normalize_batch,
    notice_payload,
    post_batch,
    reactivate_merchant,
    reassign_agent_payload,
    recall_statement,
    reject_adjustment,
    release_statement,
    request_info_on_adjustment,
    require_statement,
    resubmit_adjustment,
    review_adjustment,
    settle_payload,
    transfer_portfolio,
    validate_error,
    validate_success,
)

# ---------------------------------------------------------------------------
# The July fixture: a NET_REVENUE_SPLIT program on NO_MINIMUM, one top-level
# agent at a 0.50 direct split, one active merchant carrying a 1,000-cent
# equipment lease, and one processor file line worth 40,000 cents of income.
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
SECOND_PROGRAM_TERMS = dict(PROGRAM_TERMS, name="Second Processor Program")
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
BARE_MERCHANT_TERMS = dict(MERCHANT_TERMS, equipment_lease_monthly_cents=0)
LINE_FIGURES = {
    "transaction_count": 100,
    "sales_volume_cents": 1000000,
    "interchange_cents": 20000,
    "assessments_cents": 1300,
    "gross_income_cents": 40000,
}
SECOND_LINE_FIGURES = {
    "transaction_count": 50,
    "sales_volume_cents": 200000,
    "interchange_cents": 4000,
    "assessments_cents": 260,
    "gross_income_cents": 8000,
}

# Pre-computed expected results for the fixtures above.
EXPECTED_DIRECT_SPLIT_CENTS = 6300
SECOND_PROGRAM_DIRECT_SPLIT_CENTS = 1270
COMBINED_DIRECT_SPLIT_CENTS = 7570
UPFRONT_BONUS_CENTS = 27000
EXPECTED_CLAWBACK_CENTS = 16900


def _posted_july_scenario(bonus_cents: int = 0, extra_merchants: int = 0) -> dict:
    """Program, agent, one producing merchant and a POSTED July batch."""
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(**AGENT_TERMS)
    terms = dict(MERCHANT_TERMS)
    if bonus_cents:
        terms["upfront_bonus_cents"] = bonus_cents
    merchant = make_active_merchant(agent["id"], program["id"], **terms)
    extras = [
        make_active_merchant(agent["id"], program["id"], **BARE_MERCHANT_TERMS)
        for _ in range(extra_merchants)
    ]
    batch = make_batch(
        program["id"],
        period_month=PERIOD,
        coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END,
    )
    add_line(batch["id"], merchant["id"], **LINE_FIGURES)
    normalize_batch(batch["id"])
    batch = post_batch(batch["id"])
    return {
        "program": program,
        "agent": agent,
        "merchant": merchant,
        "extras": extras,
        "batch": batch,
        "statement": require_statement(agent["id"], PERIOD),
    }


# ------------------------------------------------ the reversible notice edge
def test_rescinding_a_notice_clears_the_date_and_a_second_notice_may_follow():
    """A notice may be withdrawn, moving the agent `DEPARTURE_NOTICE` → `ACTIVE` and clearing `departure_effective_date`.
    `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row

    Design: Corner/state_machines/rescind_notice_returns_agent_to_active_and_clears_date
    """
    agent = make_agent(name="A1 Wavering", split_pct=0.50, override_pct=0.60,
                       vesting_start_date="2025-03-01")
    assert agent["version"] == 1, f"the agent starts at version 1, got {agent['version']}"

    noticed = validate_success(
        api_client.file_agent_notice(agent["id"], notice_payload("2026-09-01"), ADMIN)
    )
    assert noticed["status"] == "DEPARTURE_NOTICE", (
        f"the notice moves the agent to DEPARTURE_NOTICE, got {noticed['status']!r}"
    )
    assert noticed["departure_effective_date"] == "2026-09-01", (
        f"the supplied date is recorded, got {noticed['departure_effective_date']!r}"
    )
    assert noticed["version"] == 2, (
        f"one mutation, so version reaches 2, got {noticed['version']}"
    )

    rescinded = validate_success(api_client.rescind_agent_notice(agent["id"], ADMIN))
    assert rescinded["status"] == "ACTIVE", (
        f"the withdrawal returns the agent to ACTIVE, got {rescinded['status']!r}"
    )
    assert rescinded["departure_effective_date"] is None, (
        "the withdrawal clears departure_effective_date rather than ignoring it, got "
        f"{rescinded['departure_effective_date']!r}"
    )
    assert rescinded["version"] == 3, (
        f"the second mutation takes version to 3, got {rescinded['version']}"
    )

    renoticed = validate_success(
        api_client.file_agent_notice(agent["id"], notice_payload("2026-10-01"), ADMIN)
    )
    assert renoticed["status"] == "DEPARTURE_NOTICE", (
        f"the edge is re-traversable, got {renoticed['status']!r}"
    )
    assert renoticed["departure_effective_date"] == "2026-10-01", (
        f"the new date replaces the cleared one, got {renoticed['departure_effective_date']!r}"
    )
    assert renoticed["version"] == 4, (
        f"the third mutation takes version to 4, got {renoticed['version']}"
    )
    assert renoticed["vested_pct_at_departure"] is None, (
        "only the departure edge freezes vesting, got "
        f"{renoticed['vested_pct_at_departure']!r}"
    )


def test_agent_under_notice_refuses_every_book_growing_write():
    """A merchant may only be boarded under an agent whose `status` is `ACTIVE`; otherwise `ERR_AGENT_STATE_INVALID`.
    a `parent_agent_id` naming an agent whose `status` is not `ACTIVE` is `ERR_AGENT_STATE_INVALID`
    An `IsoAdmin` funds an advance against one agent, whose `status` must be `ACTIVE` — funding a non-active agent is `ERR_AGENT_STATE_INVALID`.
    The destination agent must exist and must have `status` `ACTIVE`, otherwise `ERR_AGENT_STATE_INVALID`

    Design: Corner/state_machines/non_active_agent_blocks_merchant_advance_and_parent_writes
    """
    program = make_program(**PROGRAM_TERMS)
    under_notice = make_agent(name="A1 Under Notice", split_pct=0.50, override_pct=0.60,
                              vesting_start_date="2024-01-15")
    active = make_agent(name="A2 Active", split_pct=0.50, override_pct=0.60,
                        vesting_start_date="2025-03-01")
    elsewhere = make_merchant(
        active["id"], program["id"], mid="MID-9002", monthly_minimum_cents=0,
        per_transaction_fee_cents=10, equipment_lease_monthly_cents=0,
        boarded_on="2026-05-10",
    )
    noticed = file_notice(under_notice["id"], "2026-09-01")

    validate_error(
        api_client.create_merchant(
            create_merchant_payload(
                under_notice["id"], program["id"], mid="MID-9003",
                monthly_minimum_cents=0, per_transaction_fee_cents=10,
                equipment_lease_monthly_cents=0, boarded_on="2026-06-01",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_AGENT_STATE_INVALID.value,
    )
    validate_error(
        api_client.create_agent(
            create_agent_payload(
                name="A3 Would-be child", split_pct=0.40, override_pct=0.50,
                vesting_start_date="2026-06-01", parent_agent_id=under_notice["id"],
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_AGENT_STATE_INVALID.value,
    )
    validate_error(
        api_client.create_agent_advance(
            under_notice["id"],
            create_percent_advance_payload(
                noticed["version"], advance_type="PORTFOLIO_BUYOUT",
                principal_cents=50000, recoupment_pct=0.25, amortization_months=6,
                first_recoupment_month="2026-09", last_recoupment_month="2027-02",
                funded_on="2026-08-01",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_AGENT_STATE_INVALID.value,
    )
    validate_error(
        api_client.reassign_merchant_agent(
            elsewhere["id"],
            reassign_agent_payload(under_notice["id"], elsewhere["version"]),
            ADMIN,
        ),
        ApiErrorId.ERR_AGENT_STATE_INVALID.value,
    )

    merchants, merchant_meta = list_rows(api_client.list_merchants, {}, ADMIN)
    assert merchant_meta["total_count"] == 1, (
        f"no merchant was boarded, expected 1 row in total, got {merchant_meta['total_count']}"
    )
    _, agent_meta = list_rows(api_client.list_agents, {}, ADMIN)
    assert agent_meta["total_count"] == 2, (
        f"no child agent was created, expected 2 agents, got {agent_meta['total_count']}"
    )
    _, advance_meta = list_rows(
        api_client.list_agent_advances, {"agent_id": under_notice["id"]}, ADMIN
    )
    assert advance_meta["total_count"] == 0, (
        f"no advance was funded, got {advance_meta['total_count']}"
    )
    assert merchants[0]["owning_agent_id"] == active["id"], (
        "the refused reassignment leaves ownership with the active agent, got "
        f"{merchants[0]['owning_agent_id']!r}"
    )
    still_noticed = fetch_agent(under_notice["id"])
    assert still_noticed["status"] == "DEPARTURE_NOTICE", (
        f"the agent is untouched by the four refusals, got {still_noticed['status']!r}"
    )
    assert still_noticed["advance_outstanding_cents"] == 0, (
        f"no principal was booked, got {still_noticed['advance_outstanding_cents']}"
    )


def test_rescinding_the_notice_reopens_the_book_to_boarding():
    """A notice may be withdrawn, moving the agent `DEPARTURE_NOTICE` → `ACTIVE` and clearing `departure_effective_date`.
    Boarding leaves the merchant with `status` `PENDING`, `attrition_date` and `reactivation_date` both null, and `clawed_back_bonus_cents` at 0, and it raises the owning agent's `portfolio_merchant_count` by one.

    Design: Corner/state_machines/non_active_agent_blocks_merchant_advance_and_parent_writes
    """
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(name="A1 Under Notice", split_pct=0.50, override_pct=0.60,
                       vesting_start_date="2024-01-15")
    file_notice(agent["id"], "2026-09-01")
    payload = create_merchant_payload(
        agent["id"], program["id"], mid="MID-9003", monthly_minimum_cents=0,
        per_transaction_fee_cents=10, equipment_lease_monthly_cents=0,
        boarded_on="2026-06-01",
    )
    validate_error(
        api_client.create_merchant(payload, ADMIN),
        ApiErrorId.ERR_AGENT_STATE_INVALID.value,
    )

    validate_success(api_client.rescind_agent_notice(agent["id"], ADMIN))
    boarded = validate_success(api_client.create_merchant(payload, ADMIN), 201)

    assert boarded["owning_agent_id"] == agent["id"], (
        f"the identical create now lands on the agent, got {boarded['owning_agent_id']!r}"
    )
    assert boarded["status"] == "PENDING", (
        f"a newly boarded merchant is PENDING, got {boarded['status']!r}"
    )
    reopened = fetch_agent(agent["id"])
    assert reopened["status"] == "ACTIVE", (
        f"the rescind returned the agent to ACTIVE, got {reopened['status']!r}"
    )
    assert reopened["portfolio_merchant_count"] == 1, (
        f"the boarding raises the count to 1, got {reopened['portfolio_merchant_count']}"
    )


# ------------------------------------------- the conditional transfer cascade
def _departed_agent_with_mixed_book() -> dict:
    """A DEPARTED agent owning one PENDING, one ACTIVE and one ATTRITED merchant."""
    program = make_program(**PROGRAM_TERMS)
    leaver = make_agent(name="A1 Departing", split_pct=0.50, override_pct=0.60,
                        vesting_start_date="2024-01-15")
    receiver = make_agent(name="A2 Receiving", split_pct=0.50, override_pct=0.60,
                          vesting_start_date="2025-03-01")
    pending = make_merchant(leaver["id"], program["id"], mid="MID-9001",
                            **BARE_MERCHANT_TERMS)
    active = make_active_merchant(leaver["id"], program["id"], mid="MID-9002",
                                  **BARE_MERCHANT_TERMS)
    gone = make_active_merchant(leaver["id"], program["id"], mid="MID-9003",
                                **BARE_MERCHANT_TERMS)
    attrite_merchant(gone["id"], "2026-07-20")
    file_notice(leaver["id"], "2026-08-01")
    depart_agent(leaver["id"])
    return {
        "program": program,
        "leaver": leaver,
        "receiver": receiver,
        "pending": pending,
        "active": active,
        "gone": gone,
    }


def test_portfolio_transfer_moves_only_the_non_attrited_merchants():
    """The cascade is conditional: every merchant owned by the departing agent whose `status` is `PENDING` or `ACTIVE` has its `owning_agent_id` re-pointed to the target and its `version` bumped, while merchants whose `status` is `ATTRITED` deliberately keep the departing agent for audit.

    Design: Corner/state_machines/portfolio_transfer_conditional_cascade_skips_attrited_merchants
    """
    book = _departed_agent_with_mixed_book()
    before_pending = fetch_merchant(book["pending"]["id"])
    before_active = fetch_merchant(book["active"]["id"])
    before_gone = fetch_merchant(book["gone"]["id"])

    transfer_portfolio(book["leaver"]["id"], book["receiver"]["id"])

    after_pending = fetch_merchant(book["pending"]["id"])
    after_active = fetch_merchant(book["active"]["id"])
    after_gone = fetch_merchant(book["gone"]["id"])

    assert after_pending["owning_agent_id"] == book["receiver"]["id"], (
        f"the PENDING merchant moves, got {after_pending['owning_agent_id']!r}"
    )
    assert after_pending["status"] == "PENDING", (
        f"the transfer does not change merchant status, got {after_pending['status']!r}"
    )
    assert after_active["owning_agent_id"] == book["receiver"]["id"], (
        f"the ACTIVE merchant moves, got {after_active['owning_agent_id']!r}"
    )
    assert after_active["status"] == "ACTIVE", (
        f"the transfer does not change merchant status, got {after_active['status']!r}"
    )
    assert after_gone["owning_agent_id"] == book["leaver"]["id"], (
        "the ATTRITED merchant deliberately keeps the departing agent, got "
        f"{after_gone['owning_agent_id']!r}"
    )
    assert after_gone["status"] == "ATTRITED", (
        f"the attrited merchant is untouched, got {after_gone['status']!r}"
    )
    assert after_pending["version"] == before_pending["version"] + 1, (
        "the moved merchant's version is bumped by exactly one, expected "
        f"{before_pending['version'] + 1}, got {after_pending['version']}"
    )
    assert after_active["version"] == before_active["version"] + 1, (
        "the moved merchant's version is bumped by exactly one, expected "
        f"{before_active['version'] + 1}, got {after_active['version']}"
    )
    assert after_gone["version"] == before_gone["version"], (
        "the skipped merchant is not mutated, expected version "
        f"{before_gone['version']}, got {after_gone['version']}"
    )


def test_portfolio_transfer_recomputes_the_attrition_ratio_on_both_agents():
    """Afterwards `portfolio_merchant_count`, `portfolio_attrition_bps` and `residual_hold` are recomputed on both agents
    The denominator is the number of merchants owned by that agent whose `status` is either `ACTIVE` or `ATTRITED`; merchants still `PENDING` are excluded from both the numerator and the denominator

    Design: Corner/state_machines/portfolio_transfer_conditional_cascade_skips_attrited_merchants
    """
    book = _departed_agent_with_mixed_book()

    before = fetch_agent(book["leaver"]["id"])
    assert before["portfolio_merchant_count"] == 3, (
        f"the departing agent owns three merchants, got {before['portfolio_merchant_count']}"
    )
    assert before["portfolio_attrition_bps"] == 5000, (
        "one attrited of two non-pending merchants is 5000 bps, got "
        f"{before['portfolio_attrition_bps']}"
    )
    assert before["residual_hold"] is True, (
        f"5000 bps is above the threshold, so the agent is held, got {before['residual_hold']!r}"
    )

    transfer_portfolio(book["leaver"]["id"], book["receiver"]["id"])

    leaver = fetch_agent(book["leaver"]["id"])
    assert leaver["status"] == "DEPARTED", (
        f"the transfer does not change the departing agent's status, got {leaver['status']!r}"
    )
    assert leaver["portfolio_merchant_count"] == 1, (
        f"only the attrited merchant is left behind, got {leaver['portfolio_merchant_count']}"
    )
    assert leaver["portfolio_attrition_bps"] == 10000, (
        "one attrited of one non-pending merchant is 10000 bps, got "
        f"{leaver['portfolio_attrition_bps']}"
    )
    assert leaver["residual_hold"] is True, (
        f"10000 bps keeps the agent held, got {leaver['residual_hold']!r}"
    )

    receiver = fetch_agent(book["receiver"]["id"])
    assert receiver["portfolio_merchant_count"] == 2, (
        f"the receiving agent takes two merchants, got {receiver['portfolio_merchant_count']}"
    )
    assert receiver["portfolio_attrition_bps"] == 0, (
        "the received book holds no attrited merchant, so the rate is 0 bps, got "
        f"{receiver['portfolio_attrition_bps']}"
    )
    assert receiver["residual_hold"] is False, (
        f"0 bps leaves the receiving agent unheld, got {receiver['residual_hold']!r}"
    )


# ------------------------------------------------ clawback and its compensation
def test_attrition_books_a_system_authored_bonus_clawback():
    """Otherwise the clawback is `upfront_bonus_cents` multiplied by the number of days remaining in the window (270 minus the days the merchant was active), divided by 270, rounded half up to the cent.
    the system upserts the owning agent's statement for the calendar month of `attrition_date`, creating it in `DRAFT` and `UNSETTLED` when no statement for that agent and month exists, and creates an adjustment on it of `kind` `BONUS_CLAWBACK` in `state` `APPLIED`, with `created_by_user_id` set to the literal `system`, `source_merchant_id` pointing at this merchant, and `amount_cents` equal to the negative of the clawback.

    Design: Corner/state_machines/merchant_reactivation_compensates_the_bonus_clawback
    """
    scenario = _posted_july_scenario(bonus_cents=UPFRONT_BONUS_CENTS)
    statement = scenario["statement"]

    attrite_merchant(scenario["merchant"]["id"], "2026-07-20")

    rows, meta = list_rows(
        api_client.list_statement_adjustments, {"statement_id": statement["id"]}
    )
    assert meta["total_count"] == 1, (
        f"the attrition books exactly one adjustment, got {meta['total_count']}"
    )
    clawback = rows[0]
    assert clawback["kind"] == "BONUS_CLAWBACK", (
        f"the cascade books a BONUS_CLAWBACK, got {clawback['kind']!r}"
    )
    assert clawback["amount_cents"] == -EXPECTED_CLAWBACK_CENTS, (
        "101 days active leaves 169 of the 270-day window, so the amount is "
        f"{-EXPECTED_CLAWBACK_CENTS}, got {clawback['amount_cents']}"
    )
    assert clawback["state"] == "APPLIED", (
        f"a system-generated row is created APPLIED, got {clawback['state']!r}"
    )
    assert clawback["created_by_user_id"] == SYSTEM_USER_ID, (
        f"the author is the literal system principal, got {clawback['created_by_user_id']!r}"
    )
    assert clawback["source_merchant_id"] == scenario["merchant"]["id"], (
        f"source_merchant_id points at the lost merchant, got {clawback['source_merchant_id']!r}"
    )

    after = fetch_statement_by_id(statement["id"])
    assert after["adjustment_cents"] == -EXPECTED_CLAWBACK_CENTS, (
        f"adjustment_cents expected {-EXPECTED_CLAWBACK_CENTS}, got {after['adjustment_cents']}"
    )
    assert after["gross_after_trueup_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        "an adjustment never touches the residual gross, expected "
        f"{EXPECTED_DIRECT_SPLIT_CENTS}, got {after['gross_after_trueup_cents']}"
    )
    assert after["net_payable_cents"] == 0, (
        f"6300 minus 16900 floors the payout at 0, got {after['net_payable_cents']}"
    )
    assert after["carry_forward_deficit_cents"] == 10600, (
        f"the shortfall carries forward as 10600, got {after['carry_forward_deficit_cents']}"
    )
    assert fetch_merchant(scenario["merchant"]["id"])["clawed_back_bonus_cents"] == (
        EXPECTED_CLAWBACK_CENTS
    ), "the merchant records the clawed-back bonus"
    assert fetch_agent(scenario["agent"]["id"])["lifetime_clawback_cents"] == (
        EXPECTED_CLAWBACK_CENTS
    ), "the agent's lifetime clawback counter rises to the same figure"


def test_reactivation_compensates_the_clawback_with_a_new_applied_row():
    """when the merchant's `clawed_back_bonus_cents` is greater than zero, the system creates an adjustment of `kind` `CLAWBACK_REVERSAL` in `state` `APPLIED` with `created_by_user_id` set to `system`, `source_merchant_id` pointing at this merchant, and `amount_cents` equal to the positive of `clawed_back_bonus_cents`
    the agent's `lifetime_clawback_cents` is refreshed downward, and the merchant's `clawed_back_bonus_cents` returns to 0. `reactivation_date` is written and `attrition_date` is cleared.

    Design: Corner/state_machines/merchant_reactivation_compensates_the_bonus_clawback
    """
    scenario = _posted_july_scenario(bonus_cents=UPFRONT_BONUS_CENTS)
    statement = scenario["statement"]
    merchant_id = scenario["merchant"]["id"]

    attrite_merchant(merchant_id, "2026-07-20")
    reactivated = reactivate_merchant(merchant_id, "2026-07-25")

    rows, meta = list_rows(
        api_client.list_statement_adjustments, {"statement_id": statement["id"]}
    )
    assert meta["total_count"] == 2, (
        "the compensation adds a row rather than deleting one, expected 2, got "
        f"{meta['total_count']}"
    )
    reversals = [row for row in rows if row["kind"] == "CLAWBACK_REVERSAL"]
    assert len(reversals) == 1, (
        f"exactly one CLAWBACK_REVERSAL is booked, got {len(reversals)}"
    )
    reversal = reversals[0]
    assert reversal["amount_cents"] == EXPECTED_CLAWBACK_CENTS, (
        f"the reversal gives back {EXPECTED_CLAWBACK_CENTS}, got {reversal['amount_cents']}"
    )
    assert reversal["state"] == "APPLIED", (
        f"the reversal is created APPLIED, got {reversal['state']!r}"
    )
    assert reversal["created_by_user_id"] == SYSTEM_USER_ID, (
        f"the reversal is system-authored, got {reversal['created_by_user_id']!r}"
    )
    assert reversal["source_merchant_id"] == merchant_id, (
        f"the reversal points at the same merchant, got {reversal['source_merchant_id']!r}"
    )
    assert reversal["statement_id"] == statement["id"], (
        "2026-07 is the calendar month of both dates, so the reversal lands on the "
        f"same statement, got {reversal['statement_id']!r}"
    )

    after = fetch_statement_by_id(statement["id"])
    assert after["adjustment_cents"] == 0, (
        f"the two signed rows cancel out, got {after['adjustment_cents']}"
    )
    assert after["net_payable_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        f"net_payable_cents returns to {EXPECTED_DIRECT_SPLIT_CENTS}, got "
        f"{after['net_payable_cents']}"
    )
    assert after["carry_forward_deficit_cents"] == 0, (
        f"the deficit is gone, got {after['carry_forward_deficit_cents']}"
    )
    assert reactivated["status"] == "ACTIVE", (
        f"the merchant is back to ACTIVE, got {reactivated['status']!r}"
    )
    assert reactivated["attrition_date"] is None, (
        f"attrition_date is cleared, got {reactivated['attrition_date']!r}"
    )
    assert reactivated["reactivation_date"] == "2026-07-25", (
        f"reactivation_date is written, got {reactivated['reactivation_date']!r}"
    )
    assert fetch_merchant(merchant_id)["clawed_back_bonus_cents"] == 0, (
        "the merchant's clawed_back_bonus_cents returns to 0"
    )
    agent = fetch_agent(scenario["agent"]["id"])
    assert agent["lifetime_clawback_cents"] == 0, (
        f"the agent's lifetime clawback is refreshed downward, got "
        f"{agent['lifetime_clawback_cents']}"
    )
    assert agent["trailing_residual_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        "the production KPI reads gross_after_trueup_cents, which never moved, got "
        f"{agent['trailing_residual_cents']}"
    )


# ------------------------------------------------- the attrition risk hold
def test_attrition_at_the_threshold_holds_the_draft_statement_and_blocks_release():
    """When the result reaches 2,500 basis points the agent's `residual_hold` flips to true, and every statement of that agent whose `lifecycle_state` is `DRAFT` or `ISSUED` and whose `settlement_state` is `UNSETTLED` is moved along the settlement dimension from `UNSETTLED` to `HELD`, with `hold_reason` recorded as `PORTFOLIO_ATTRITION_THRESHOLD`.
    It is refused with `ERR_RESIDUAL_HOLD_ACTIVE` (HTTP 409) while the owning agent's `residual_hold` flag is still set

    Design: Corner/state_machines/attrition_cascade_holds_draft_statement_and_blocks_release_until_reactivation
    """
    scenario = _posted_july_scenario(extra_merchants=3)
    statement = scenario["statement"]
    doomed = scenario["extras"][-1]

    before_agent = fetch_agent(scenario["agent"]["id"])
    assert before_agent["portfolio_attrition_bps"] == 0, (
        f"nothing has attrited yet, got {before_agent['portfolio_attrition_bps']}"
    )
    assert before_agent["residual_hold"] is False, (
        f"the agent starts unheld, got {before_agent['residual_hold']!r}"
    )
    assert statement["settlement_state"] == "UNSETTLED", (
        f"the fresh statement is UNSETTLED, got {statement['settlement_state']!r}"
    )

    attrite_merchant(doomed["id"], "2026-07-20")

    agent = fetch_agent(scenario["agent"]["id"])
    assert agent["portfolio_attrition_bps"] == 2500, (
        "exactly one of four qualifying merchants is 2500 bps, got "
        f"{agent['portfolio_attrition_bps']}"
    )
    assert agent["residual_hold"] is True, (
        f"the inclusive threshold holds the agent, got {agent['residual_hold']!r}"
    )
    held = fetch_statement_by_id(statement["id"])
    assert held["settlement_state"] == "HELD", (
        f"the cascade swept the DRAFT statement to HELD, got {held['settlement_state']!r}"
    )
    assert held["hold_reason"] == HOLD_REASON_PORTFOLIO_ATTRITION, (
        f"the reserved reason is recorded, got {held['hold_reason']!r}"
    )
    assert held["lifecycle_state"] == "DRAFT", (
        f"the authoring dimension is untouched, got {held['lifecycle_state']!r}"
    )

    validate_error(
        api_client.release_agent_statement_hold(statement["id"], CONTROLLER),
        ApiErrorId.ERR_RESIDUAL_HOLD_ACTIVE.value,
    )
    assert fetch_statement_by_id(statement["id"])["settlement_state"] == "HELD", (
        "the refused release leaves the statement HELD"
    )


def test_reactivation_clears_the_flag_but_the_hold_must_still_be_released():
    """when it falls back below 2,500 basis points `residual_hold` flips to false — but statements that were already moved to `HELD` stay `HELD` until they are explicitly released
    Releasing a hold moves the statement `HELD` → `UNSETTLED` and clears `hold_reason`, and is available only from `HELD`.

    Design: Corner/state_machines/attrition_cascade_holds_draft_statement_and_blocks_release_until_reactivation
    """
    scenario = _posted_july_scenario(extra_merchants=3)
    statement = scenario["statement"]
    doomed = scenario["extras"][-1]
    attrite_merchant(doomed["id"], "2026-07-20")

    reactivate_merchant(doomed["id"], "2026-07-25")

    agent = fetch_agent(scenario["agent"]["id"])
    assert agent["portfolio_attrition_bps"] == 0, (
        f"the reactivation empties the numerator, got {agent['portfolio_attrition_bps']}"
    )
    assert agent["residual_hold"] is False, (
        f"the risk flag clears, got {agent['residual_hold']!r}"
    )
    still_held = fetch_statement_by_id(statement["id"])
    assert still_held["settlement_state"] == "HELD", (
        "the statement stays HELD until an operator releases it, got "
        f"{still_held['settlement_state']!r}"
    )

    released = release_statement(statement["id"])
    assert released["settlement_state"] == "UNSETTLED", (
        f"the release returns the statement to UNSETTLED, got {released['settlement_state']!r}"
    )
    assert released["hold_reason"] is None, (
        f"the release clears hold_reason, got {released['hold_reason']!r}"
    )
    assert released["net_payable_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        "no money moved through the hold cycle, expected "
        f"{EXPECTED_DIRECT_SPLIT_CENTS}, got {released['net_payable_cents']}"
    )
    _, meta = list_rows(
        api_client.list_statement_adjustments, {"statement_id": statement["id"]}
    )
    assert meta["total_count"] == 0, (
        "no bonus was paid, so neither merchant transition books an adjustment, got "
        f"{meta['total_count']}"
    )


def test_finalized_statement_settle_is_refused_while_the_risk_flag_is_set():
    """every statement of that agent whose `lifecycle_state` is `DRAFT` or `ISSUED` and whose `settlement_state` is `UNSETTLED` is moved along the settlement dimension from `UNSETTLED` to `HELD`
    The owning agent's `residual_hold` must be false, or the settlement is `ERR_RESIDUAL_HOLD_ACTIVE`.

    Design: Corner/state_machines/finalized_statement_settle_refused_while_attrition_hold_active
    """
    scenario = _posted_july_scenario(extra_merchants=3)
    statement = scenario["statement"]
    issue_statement(statement["id"])
    finalize_statement(statement["id"])

    attrite_merchant(scenario["extras"][-1]["id"], "2026-07-20")

    agent = fetch_agent(scenario["agent"]["id"])
    assert agent["residual_hold"] is True, (
        f"one attrition of four qualifying merchants holds the agent, got "
        f"{agent['residual_hold']!r}"
    )
    skipped = fetch_statement_by_id(statement["id"])
    assert skipped["lifecycle_state"] == "FINALIZED", (
        f"the statement is FINALIZED, got {skipped['lifecycle_state']!r}"
    )
    assert skipped["settlement_state"] == "UNSETTLED", (
        "the auto-hold sweep skips a FINALIZED statement, so it stays UNSETTLED, got "
        f"{skipped['settlement_state']!r}"
    )

    validate_error(
        api_client.settle_agent_statement(
            statement["id"], settle_payload("2026-08-01"), CONTROLLER
        ),
        ApiErrorId.ERR_RESIDUAL_HOLD_ACTIVE.value,
    )

    after = fetch_statement_by_id(statement["id"])
    assert after["settlement_state"] == "UNSETTLED", (
        f"the refused settlement changes nothing, got {after['settlement_state']!r}"
    )
    assert after["paid_on"] is None, (
        f"no payment date is recorded, got {after['paid_on']!r}"
    )


def test_reactivation_reopens_the_settlement_of_a_finalized_statement():
    """The owning agent's `residual_hold` must be false, or the settlement is `ERR_RESIDUAL_HOLD_ACTIVE`.
    On success `paid_on` is recorded and the statement moves `UNSETTLED` → `SETTLED`, which is the settlement dimension's terminal state.

    Design: Corner/state_machines/finalized_statement_settle_refused_while_attrition_hold_active
    """
    scenario = _posted_july_scenario(extra_merchants=3)
    statement = scenario["statement"]
    doomed = scenario["extras"][-1]
    issue_statement(statement["id"])
    finalize_statement(statement["id"])
    attrite_merchant(doomed["id"], "2026-07-20")
    validate_error(
        api_client.settle_agent_statement(
            statement["id"], settle_payload("2026-08-01"), CONTROLLER
        ),
        ApiErrorId.ERR_RESIDUAL_HOLD_ACTIVE.value,
    )

    reactivate_merchant(doomed["id"], "2026-07-25")
    agent = fetch_agent(scenario["agent"]["id"])
    assert agent["portfolio_attrition_bps"] == 0, (
        f"the reactivation empties the numerator, got {agent['portfolio_attrition_bps']}"
    )
    assert agent["residual_hold"] is False, (
        f"the risk flag clears, got {agent['residual_hold']!r}"
    )

    settled = validate_success(
        api_client.settle_agent_statement(
            statement["id"], settle_payload("2026-08-01"), CONTROLLER
        )
    )
    assert settled["settlement_state"] == "SETTLED", (
        f"the settlement now goes through, got {settled['settlement_state']!r}"
    )
    assert settled["paid_on"] == "2026-08-01", (
        f"paid_on is recorded as supplied, got {settled['paid_on']!r}"
    )
    assert settled["net_payable_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        f"net_payable_cents expected {EXPECTED_DIRECT_SPLIT_CENTS}, got "
        f"{settled['net_payable_cents']}"
    )
    assert settled["lifecycle_state"] == "FINALIZED", (
        f"the authoring dimension is untouched, got {settled['lifecycle_state']!r}"
    )


# ------------------------------------------------------------- the period lock
def _two_programs_with_july_files() -> dict:
    """P1's July batch POSTED and the statement ISSUED; P2's July batch NORMALIZED."""
    first_program = make_program(**PROGRAM_TERMS)
    second_program = make_program(**SECOND_PROGRAM_TERMS)
    agent = make_agent(**AGENT_TERMS)
    first_merchant = make_active_merchant(agent["id"], first_program["id"],
                                          **MERCHANT_TERMS)
    second_merchant = make_active_merchant(agent["id"], second_program["id"],
                                           **BARE_MERCHANT_TERMS)
    first_batch = make_batch(
        first_program["id"], period_month=PERIOD, coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END, file_checksum="sha256:lock-0001",
    )
    add_line(first_batch["id"], first_merchant["id"], **LINE_FIGURES)
    normalize_batch(first_batch["id"])
    post_batch(first_batch["id"])
    statement = require_statement(agent["id"], PERIOD)
    issue_statement(statement["id"])
    second_batch = make_batch(
        second_program["id"], period_month=PERIOD, coverage_start=COVERAGE_START,
        coverage_end=COVERAGE_END, file_checksum="sha256:lock-0002",
    )
    add_line(second_batch["id"], second_merchant["id"], **SECOND_LINE_FIGURES)
    second_batch = normalize_batch(second_batch["id"])
    return {
        "first_program": first_program,
        "second_program": second_program,
        "agent": agent,
        "first_batch": first_batch,
        "second_batch": second_batch,
        "statement": statement,
    }


def test_an_issued_statement_locks_the_whole_period_against_post_and_reverse():
    """with `ERR_PERIOD_LOCKED` (HTTP 409) when any statement anywhere in the system whose `period_month` equals the batch's `period_month` has a `lifecycle_state` of `ISSUED` or `FINALIZED`
    and with `ERR_PERIOD_LOCKED` when any statement whose `period_month` equals the batch's `period_month` has a `lifecycle_state` of `ISSUED` or `FINALIZED`

    Design: Corner/state_machines/period_lock_blocks_post_and_reverse_once_a_statement_is_issued
    """
    setup = _two_programs_with_july_files()
    assert setup["second_batch"]["coverage_start"] == COVERAGE_START, (
        "the second program's file covers the same window, got "
        f"{setup['second_batch']['coverage_start']!r}"
    )
    assert setup["second_batch"]["state"] == "NORMALIZED", (
        f"the second file is priced and waiting, got {setup['second_batch']['state']!r}"
    )

    validate_error(
        api_client.post_residual_batch(setup["second_batch"]["id"], CONTROLLER),
        ApiErrorId.ERR_PERIOD_LOCKED.value,
    )
    validate_error(
        api_client.reverse_residual_batch(setup["first_batch"]["id"], CONTROLLER),
        ApiErrorId.ERR_PERIOD_LOCKED.value,
    )

    blocked = fetch_batch(setup["second_batch"]["id"])
    assert blocked["state"] == "NORMALIZED", (
        f"the refused post leaves the batch NORMALIZED, got {blocked['state']!r}"
    )
    assert blocked["posted_at"] is None, (
        f"posted_at stays null, got {blocked['posted_at']!r}"
    )
    assert fetch_program(setup["second_program"]["id"])["posted_batch_count"] == 0, (
        "the second program has posted nothing"
    )
    posted = fetch_batch(setup["first_batch"]["id"])
    assert posted["state"] == "POSTED", (
        f"the refused reversal leaves the batch POSTED, got {posted['state']!r}"
    )
    assert fetch_program(setup["first_program"]["id"])["posted_batch_count"] == 1, (
        "the first program still counts its single posted batch"
    )


def test_recalling_the_statement_unlocks_the_second_program_post():
    """An issued statement may be pulled back to `DRAFT` by a `ResidualController`
    `minimum_true_up_cents` and `advance_recoupment_cents` both return to 0, `issued_at` returns to null

    Design: Corner/state_machines/period_lock_blocks_post_and_reverse_once_a_statement_is_issued
    """
    setup = _two_programs_with_july_files()

    recalled = recall_statement(setup["statement"]["id"])
    assert recalled["lifecycle_state"] == "DRAFT", (
        f"the recall returns the statement to DRAFT, got {recalled['lifecycle_state']!r}"
    )
    assert recalled["issued_at"] is None, (
        f"issued_at returns to null, got {recalled['issued_at']!r}"
    )
    assert recalled["net_payable_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        f"the draft evaluation restores {EXPECTED_DIRECT_SPLIT_CENTS}, got "
        f"{recalled['net_payable_cents']}"
    )

    posted = validate_success(
        api_client.post_residual_batch(setup["second_batch"]["id"], CONTROLLER)
    )
    assert posted["state"] == "POSTED", (
        f"the unlocked post now goes through, got {posted['state']!r}"
    )

    after = fetch_statement_by_id(setup["statement"]["id"])
    assert after["direct_residual_cents"] == COMBINED_DIRECT_SPLIT_CENTS, (
        f"both programs now credit the agent, expected {COMBINED_DIRECT_SPLIT_CENTS}, got "
        f"{after['direct_residual_cents']}"
    )
    assert after["gross_after_trueup_cents"] == COMBINED_DIRECT_SPLIT_CENTS, (
        f"gross_after_trueup_cents expected {COMBINED_DIRECT_SPLIT_CENTS}, got "
        f"{after['gross_after_trueup_cents']}"
    )
    assert after["net_payable_cents"] == COMBINED_DIRECT_SPLIT_CENTS, (
        f"net_payable_cents expected {COMBINED_DIRECT_SPLIT_CENTS}, got "
        f"{after['net_payable_cents']}"
    )


def test_recalling_the_statement_unlocks_the_first_program_reversal():
    """first every allocation produced by this batch's post is deleted, then every profitability row produced by this batch is deleted, then each affected statement is recomputed
    and with `ERR_PERIOD_LOCKED` when any statement whose `period_month` equals the batch's `period_month` has a `lifecycle_state` of `ISSUED` or `FINALIZED`

    Design: Corner/state_machines/period_lock_blocks_post_and_reverse_once_a_statement_is_issued
    """
    setup = _two_programs_with_july_files()
    recall_statement(setup["statement"]["id"])
    validate_success(
        api_client.post_residual_batch(setup["second_batch"]["id"], CONTROLLER)
    )

    reversed_batch = validate_success(
        api_client.reverse_residual_batch(setup["first_batch"]["id"], CONTROLLER)
    )
    assert reversed_batch["state"] == "REVERSED", (
        f"the unlocked reversal now goes through, got {reversed_batch['state']!r}"
    )

    after = fetch_statement_by_id(setup["statement"]["id"])
    assert after["direct_residual_cents"] == SECOND_PROGRAM_DIRECT_SPLIT_CENTS, (
        "only the second program's allocation survives, expected "
        f"{SECOND_PROGRAM_DIRECT_SPLIT_CENTS}, got {after['direct_residual_cents']}"
    )
    assert after["net_payable_cents"] == SECOND_PROGRAM_DIRECT_SPLIT_CENTS, (
        f"net_payable_cents expected {SECOND_PROGRAM_DIRECT_SPLIT_CENTS}, got "
        f"{after['net_payable_cents']}"
    )
    _, meta = list_rows(
        api_client.list_residual_allocations, {"statement_id": setup["statement"]["id"]}
    )
    assert meta["total_count"] == 1, (
        f"exactly one allocation is left on the statement, got {meta['total_count']}"
    )


# --------------------------------------------------- the adjustment review cycle
FIRST_QUESTION = "Attach the processor dispute letter"
SECOND_QUESTION = "Letter is unsigned — resend"


def _proposed_dispute_credit(amount_cents: int = 500) -> dict:
    """A posted July statement carrying one PROPOSED credit from analyst-1."""
    scenario = _posted_july_scenario()
    statement = scenario["statement"]
    adjustment = validate_success(
        api_client.create_statement_adjustment(
            statement["id"],
            create_adjustment_payload(
                statement["version"], kind="DISPUTE_CREDIT",
                amount_cents=amount_cents, reason="Interchange re-rate credit",
            ),
            ANALYST_ONE,
        ),
        201,
    )
    scenario["adjustment"] = adjustment
    return scenario


def test_the_information_request_loop_may_be_traversed_twice_before_approval():
    """From `UNDER_REVIEW` the controller may send it back to the proposer for more information, moving `UNDER_REVIEW` → `INFO_REQUESTED` and recording the question as `info_request_note`. Answering that question returns the adjustment `INFO_REQUESTED` → `UNDER_REVIEW`, clears `info_request_note`, and optionally overwrites `reason` when a new one is supplied
    This loop closes on itself and may be traversed as many times as the review demands.
    `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row

    Design: Corner/state_machines/adjustment_review_cycle_repeats_then_applies
    """
    scenario = _proposed_dispute_credit()
    adjustment = scenario["adjustment"]
    assert adjustment["state"] == "PROPOSED", (
        f"a client proposal lands in PROPOSED, got {adjustment['state']!r}"
    )
    assert adjustment["created_by_user_id"] == ANALYST_ONE_ID, (
        f"the proposer is recorded, got {adjustment['created_by_user_id']!r}"
    )
    assert adjustment["approved_by_user_id"] is None, (
        f"approved_by_user_id starts null, got {adjustment['approved_by_user_id']!r}"
    )
    assert adjustment["version"] == 1, (
        f"the row starts at version 1, got {adjustment['version']}"
    )

    under_review = review_adjustment(adjustment["id"], CONTROLLER_TWO)
    assert under_review["state"] == "UNDER_REVIEW", (
        f"the first hop is PROPOSED -> UNDER_REVIEW, got {under_review['state']!r}"
    )
    assert under_review["version"] == 2, (
        f"one hop, so version 2, got {under_review['version']}"
    )

    asked = request_info_on_adjustment(adjustment["id"], FIRST_QUESTION, CONTROLLER_TWO)
    assert asked["state"] == "INFO_REQUESTED", (
        f"the second hop is UNDER_REVIEW -> INFO_REQUESTED, got {asked['state']!r}"
    )
    assert asked["info_request_note"] == FIRST_QUESTION, (
        f"the question is recorded, got {asked['info_request_note']!r}"
    )
    assert asked["version"] == 3, f"two hops, so version 3, got {asked['version']}"

    answered = resubmit_adjustment(
        adjustment["id"], ANALYST_ONE, reason="Dispute letter attached"
    )
    assert answered["state"] == "UNDER_REVIEW", (
        f"the answer returns the row to UNDER_REVIEW, got {answered['state']!r}"
    )
    assert answered["info_request_note"] is None, (
        f"the answer clears info_request_note, got {answered['info_request_note']!r}"
    )
    assert answered["reason"] == "Dispute letter attached", (
        f"the supplied reason overwrites the old one, got {answered['reason']!r}"
    )
    assert answered["version"] == 4, f"three hops, so version 4, got {answered['version']}"

    asked_again = request_info_on_adjustment(
        adjustment["id"], SECOND_QUESTION, CONTROLLER_TWO
    )
    assert asked_again["state"] == "INFO_REQUESTED", (
        f"the loop closes on itself, got {asked_again['state']!r}"
    )
    assert asked_again["info_request_note"] == SECOND_QUESTION, (
        f"the second question replaces the first, got {asked_again['info_request_note']!r}"
    )
    assert asked_again["version"] == 5, (
        f"four hops, so version 5, got {asked_again['version']}"
    )

    answered_again = resubmit_adjustment(
        adjustment["id"], ANALYST_ONE, reason="Signed letter attached"
    )
    assert answered_again["state"] == "UNDER_REVIEW", (
        f"the second answer returns the row to UNDER_REVIEW, got {answered_again['state']!r}"
    )
    assert answered_again["info_request_note"] is None, (
        f"info_request_note is cleared again, got {answered_again['info_request_note']!r}"
    )
    assert answered_again["version"] == 6, (
        f"five hops, so version 6, got {answered_again['version']}"
    )

    applied = approve_adjustment(adjustment["id"], CONTROLLER_TWO)
    assert applied["state"] == "APPLIED", (
        f"the terminal hop is UNDER_REVIEW -> APPLIED, got {applied['state']!r}"
    )
    assert applied["approved_by_user_id"] == CONTROLLER_TWO_ID, (
        f"the approver is recorded, got {applied['approved_by_user_id']!r}"
    )
    assert applied["version"] == 7, f"six hops, so version 7, got {applied['version']}"


def test_only_the_terminal_approval_moves_the_statement_money():
    """No money moves at proposal time — the statement's `adjustment_cents` counts only `APPLIED` rows
    A successful approval writes `approved_by_user_id` from `X-User-ID`, recomputes the parent statement's `adjustment_cents`, `net_payable_cents` and `carry_forward_deficit_cents`

    Design: Corner/state_machines/adjustment_review_cycle_repeats_then_applies
    """
    scenario = _proposed_dispute_credit()
    adjustment = scenario["adjustment"]
    statement_id = scenario["statement"]["id"]

    assert fetch_statement_by_id(statement_id)["adjustment_cents"] == 0, (
        "a PROPOSED row moves no money"
    )
    review_adjustment(adjustment["id"], CONTROLLER_TWO)
    assert fetch_statement_by_id(statement_id)["adjustment_cents"] == 0, (
        "an UNDER_REVIEW row moves no money"
    )
    request_info_on_adjustment(adjustment["id"], FIRST_QUESTION, CONTROLLER_TWO)
    assert fetch_statement_by_id(statement_id)["adjustment_cents"] == 0, (
        "an INFO_REQUESTED row moves no money"
    )
    resubmit_adjustment(adjustment["id"], ANALYST_ONE, reason="Dispute letter attached")
    assert fetch_statement_by_id(statement_id)["adjustment_cents"] == 0, (
        "answering the question moves no money"
    )

    approve_adjustment(adjustment["id"], CONTROLLER_TWO)

    after = fetch_statement_by_id(statement_id)
    assert after["adjustment_cents"] == 500, (
        f"only the approval books the 500-cent credit, got {after['adjustment_cents']}"
    )
    assert after["gross_after_trueup_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        "the adjustment enters below the gross, which stays "
        f"{EXPECTED_DIRECT_SPLIT_CENTS}, got {after['gross_after_trueup_cents']}"
    )
    assert after["net_payable_cents"] == 6800, (
        f"6300 plus 500 pays 6800, got {after['net_payable_cents']}"
    )
    assert after["carry_forward_deficit_cents"] == 0, (
        f"a positive balance carries nothing forward, got "
        f"{after['carry_forward_deficit_cents']}"
    )
    assert fetch_agent(scenario["agent"]["id"])["trailing_residual_cents"] == (
        EXPECTED_DIRECT_SPLIT_CENTS
    ), "the production KPI reads gross_after_trueup_cents, which the adjustment misses"


# ------------------------------------------- rejection is terminal, not deletion
def _two_reviewed_adjustments() -> dict:
    """One -800 debit and one +200 credit, both UNDER_REVIEW on a July statement."""
    scenario = _posted_july_scenario()
    statement_id = scenario["statement"]["id"]
    debit = validate_success(
        api_client.create_statement_adjustment(
            statement_id,
            create_adjustment_payload(
                scenario["statement"]["version"], kind="MANUAL_DEBIT",
                amount_cents=-800, reason="Equipment shortfall recharge",
            ),
            ANALYST_ONE,
        ),
        201,
    )
    # The first proposal bumped the statement's version, so re-read it before the
    # second one.
    reread = fetch_statement_by_id(statement_id)
    credit = validate_success(
        api_client.create_statement_adjustment(
            statement_id,
            create_adjustment_payload(
                reread["version"], kind="DISPUTE_CREDIT", amount_cents=200,
                reason="Assessment overbill credit",
            ),
            ANALYST_ONE,
        ),
        201,
    )
    review_adjustment(debit["id"], CONTROLLER_TWO)
    review_adjustment(credit["id"], CONTROLLER_TWO)
    scenario["debit"] = debit
    scenario["credit"] = credit
    return scenario


def test_a_rejected_adjustment_is_retained_and_leaves_the_money_untouched():
    """Refusal moves the adjustment `UNDER_REVIEW` → `REJECTED`, records the refusing `X-User-ID` as `approved_by_user_id` and an optional `reason` of record, and leaves the statement's money entirely untouched, because rejected rows are excluded from the applied-only filter that feeds `adjustment_cents`.

    Design: Corner/state_machines/rejected_adjustment_leaves_statement_amount_untouched
    """
    scenario = _two_reviewed_adjustments()
    statement_id = scenario["statement"]["id"]

    rejected = reject_adjustment(
        scenario["debit"]["id"], CONTROLLER_TWO,
        reason="Recharge already billed on the July invoice",
    )
    assert rejected["state"] == "REJECTED", (
        f"the refusal lands on REJECTED, got {rejected['state']!r}"
    )
    assert rejected["approved_by_user_id"] == CONTROLLER_TWO_ID, (
        f"the adjudicator is recorded, got {rejected['approved_by_user_id']!r}"
    )
    assert rejected["amount_cents"] == -800, (
        f"the refused amount is retained as written, got {rejected['amount_cents']}"
    )

    after = fetch_statement_by_id(statement_id)
    assert after["adjustment_cents"] == 0, (
        f"a rejected row is excluded from adjustment_cents, got {after['adjustment_cents']}"
    )
    assert after["net_payable_cents"] == EXPECTED_DIRECT_SPLIT_CENTS, (
        f"net_payable_cents stays {EXPECTED_DIRECT_SPLIT_CENTS}, got "
        f"{after['net_payable_cents']}"
    )
    _, meta = list_rows(
        api_client.list_statement_adjustments,
        {"statement_id": statement_id, "state": "REJECTED"},
    )
    assert meta["total_count"] == 1, (
        f"the rejected row is retained for audit, got {meta['total_count']}"
    )


def test_the_applied_only_filter_sums_the_approved_row_alone():
    """No money moves at proposal time — the statement's `adjustment_cents` counts only `APPLIED` rows
    A successful approval writes `approved_by_user_id` from `X-User-ID`, recomputes the parent statement's `adjustment_cents`, `net_payable_cents` and `carry_forward_deficit_cents`

    Design: Corner/state_machines/rejected_adjustment_leaves_statement_amount_untouched
    """
    scenario = _two_reviewed_adjustments()
    statement_id = scenario["statement"]["id"]

    reject_adjustment(
        scenario["debit"]["id"], CONTROLLER_TWO,
        reason="Recharge already billed on the July invoice",
    )
    applied = approve_adjustment(scenario["credit"]["id"], CONTROLLER_TWO)
    assert applied["state"] == "APPLIED", (
        f"the approved credit lands on APPLIED, got {applied['state']!r}"
    )

    after = fetch_statement_by_id(statement_id)
    assert after["adjustment_cents"] == 200, (
        "only the applied credit is summed, so adjustment_cents is 200 rather than "
        f"-600, got {after['adjustment_cents']}"
    )
    assert after["net_payable_cents"] == 6500, (
        f"6300 plus 200 pays 6500, got {after['net_payable_cents']}"
    )
    assert after["carry_forward_deficit_cents"] == 0, (
        f"nothing carries forward, got {after['carry_forward_deficit_cents']}"
    )
    rows, meta = list_rows(
        api_client.list_statement_adjustments, {"statement_id": statement_id}
    )
    assert meta["total_count"] == 2, (
        f"both rows survive the adjudication, got {meta['total_count']}"
    )
    states = sorted(row["state"] for row in rows)
    assert states == ["APPLIED", "REJECTED"], (
        f"one row is applied and the other rejected, got {states}"
    )
    assert fetch_adjustment(scenario["debit"]["id"])["state"] == "REJECTED", (
        "REJECTED is terminal, so the refused row does not change again"
    )
