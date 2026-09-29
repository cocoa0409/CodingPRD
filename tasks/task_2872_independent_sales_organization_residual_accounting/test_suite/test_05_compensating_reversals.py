"""Compensating actions: batch reversal and statement recall must leave no drift."""

from test_helpers import (
    CONTROLLER,
    api_client,
    assert_advance_principal_conserved,
    fetch_advance,
    fetch_agent,
    fetch_batch,
    fetch_line,
    fetch_program,
    fetch_statement_by_id,
    fund_advance,
    issue_statement,
    list_allocations,
    list_profitability,
    list_rows,
    require_statement,
    setup_canonical_posted_period,
    setup_hierarchy_posted_period,
    validate_success,
)


def test_reversal_deletes_the_distribution_and_returns_every_counter_to_zero():
    """One reverse undoes all four posting links and keeps the three statements as empty DRAFTs.

    PRD: "Statements that only existed because the post had created them are kept
    as empty `DRAFT` statements rather than deleted"

    Design: Difficulty/compensating_invariant/batch_reverse_conserves_residual_distribution
    """
    scenario = setup_hierarchy_posted_period()
    assert len(list_profitability(residual_batch_id=scenario["batch"]["id"])) == 1
    assert len(list_allocations(merchant_id=scenario["merchant"]["id"])) == 3
    assert require_statement(scenario["a3"]["id"])["net_payable_cents"] == 14643
    assert require_statement(scenario["a2"]["id"])["net_payable_cents"] == 1627
    assert require_statement(scenario["a1"]["id"])["net_payable_cents"] == 1627
    assert fetch_program(scenario["program"]["id"])["posted_batch_count"] == 1

    validate_success(api_client.reverse_residual_batch(scenario["batch"]["id"], CONTROLLER))

    assert list_allocations(merchant_id=scenario["merchant"]["id"]) == []
    assert list_profitability(residual_batch_id=scenario["batch"]["id"]) == []

    rows, meta = list_rows(api_client.list_agent_statements, {"period_month": "2026-07"})
    assert meta["total_count"] == 3, "the auto-created statements survive the reversal"
    for statement in rows:
        assert statement["lifecycle_state"] == "DRAFT"
        assert statement["settlement_state"] == "UNSETTLED"
        assert statement["direct_residual_cents"] == 0
        assert statement["override_residual_cents"] == 0
        assert statement["gross_after_trueup_cents"] == 0
        assert statement["net_payable_cents"] == 0
        assert statement["carry_forward_deficit_cents"] == 0

    for key in ("a1", "a2", "a3"):
        assert fetch_agent(scenario[key]["id"])["trailing_residual_cents"] == 0


def test_reversal_clears_the_house_residue_but_never_rewrites_the_ingested_file():
    """The batch lands in REVERSED with its file figures intact and the program count back to 0.

    PRD: "The batch's `iso_retained_cents` returns to 0 and its `posted_at` to
    null, and the governing program's `posted_batch_count` falls by one."

    Design: Difficulty/compensating_invariant/batch_reverse_conserves_residual_distribution
    """
    scenario = setup_hierarchy_posted_period()
    line_id = scenario["line"]["id"]

    validate_success(api_client.reverse_residual_batch(scenario["batch"]["id"], CONTROLLER))

    batch = fetch_batch(scenario["batch"]["id"])
    assert batch["state"] == "REVERSED"
    assert batch["iso_retained_cents"] == 0
    assert batch["posted_at"] is None
    assert batch["line_count"] == 1
    assert batch["gross_volume_cents"] == 4812355
    assert batch["total_normalized_net_revenue_cents"] == 40939
    assert fetch_line(line_id)["normalized_net_revenue_cents"] == 40939
    assert fetch_program(scenario["program"]["id"])["posted_batch_count"] == 0


def _fully_recouped_advance() -> dict:
    """A 5000-cent advance whose single instalment retires it, on an issued statement."""
    scenario = setup_canonical_posted_period()
    scenario["advance"] = fund_advance(
        scenario["agent"]["id"],
        principal_cents=5000,
        amortization_months=1,
        first_recoupment_month="2026-07",
        last_recoupment_month="2026-07",
    )
    assert_advance_principal_conserved(fetch_advance(scenario["advance"]["id"]))
    scenario["statement"] = issue_statement(scenario["statement"]["id"])
    return scenario


def test_the_final_instalment_retires_the_advance_and_auto_transitions_it_to_recouped():
    """5000 over one month takes the whole outstanding balance and flips the state.

    PRD: "An advance whose `outstanding_cents` reaches exactly zero
    auto-transitions from `ACTIVE` to `RECOUPED` without any operator action."

    Design: Difficulty/compensating_invariant/statement_recall_conserves_advance_principal
    """
    scenario = _fully_recouped_advance()

    advance = fetch_advance(scenario["advance"]["id"])
    assert advance["outstanding_cents"] == 0
    assert advance["cumulative_recouped_cents"] == 5000
    assert advance["months_recouped"] == 1
    assert advance["state"] == "RECOUPED"
    assert_advance_principal_conserved(advance)
    assert fetch_agent(scenario["agent"]["id"])["advance_outstanding_cents"] == 0

    statement = fetch_statement_by_id(scenario["statement"]["id"])
    assert statement["advance_recoupment_cents"] == 5000
    assert statement["net_payable_cents"] == 9643


def test_recall_walks_back_through_the_auto_transition_and_conserves_the_principal():
    """The compensation restores 5000 outstanding, flips RECOUPED back to ACTIVE and leaves settlement alone.

    PRD: "an advance that had reached `RECOUPED` auto-transitions back from
    `RECOUPED` to `ACTIVE` as soon as its outstanding balance is positive again"

    Design: Difficulty/compensating_invariant/statement_recall_conserves_advance_principal
    """
    scenario = _fully_recouped_advance()
    statement_id = scenario["statement"]["id"]

    validate_success(api_client.recall_agent_statement(statement_id, CONTROLLER))

    advance = fetch_advance(scenario["advance"]["id"])
    assert advance["outstanding_cents"] == 5000
    assert advance["cumulative_recouped_cents"] == 0
    assert advance["months_recouped"] == 0
    assert advance["state"] == "ACTIVE"
    assert_advance_principal_conserved(advance)
    assert fetch_agent(scenario["agent"]["id"])["advance_outstanding_cents"] == 5000

    statement = fetch_statement_by_id(statement_id)
    assert statement["lifecycle_state"] == "DRAFT"
    assert statement["issued_at"] is None
    assert statement["minimum_true_up_cents"] == 0
    assert statement["advance_recoupment_cents"] == 0
    assert statement["gross_after_trueup_cents"] == 14643
    assert statement["net_payable_cents"] == 14643
    assert statement["settlement_state"] == "UNSETTLED", (
        "the compensation touches only the lifecycle dimension"
    )
