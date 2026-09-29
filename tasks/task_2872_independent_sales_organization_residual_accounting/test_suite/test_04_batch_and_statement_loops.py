"""Cyclic state machines: the recall/re-normalize loop and the two statement dimensions."""

from test_helpers import (
    ANALYST,
    CONTROLLER,
    add_line,
    add_thin_line,
    api_client,
    fetch_batch,
    fetch_line,
    fetch_statement_by_id,
    hold_payload,
    make_active_merchant,
    make_agent,
    make_batch,
    make_program,
    normalize_batch,
    require_statement,
    setup_canonical_posted_period,
    validate_success,
)


def _batch_with_one_normalized_line() -> dict:
    """A NORMALIZED 2026-07 batch holding only the rich merchant's line."""
    program = make_program()
    agent = make_agent()
    m1 = make_active_merchant(agent["id"], program["id"])
    m2 = make_active_merchant(
        agent["id"],
        program["id"],
        monthly_minimum_cents=2500,
        per_transaction_fee_cents=20,
        equipment_lease_monthly_cents=0,
        boarded_on="2026-01-05",
    )
    batch = make_batch(program["id"], file_checksum="sha256:loop-0001")
    line = add_line(batch["id"], m1["id"])
    batch = normalize_batch(batch["id"])
    return {"program": program, "agent": agent, "m1": m1, "m2": m2, "batch": batch, "l1": line}


def test_recall_zeroes_the_pricing_but_keeps_what_the_file_reported():
    """NORMALIZED -> RECEIVED wipes the derived money and leaves the ingested counts.

    PRD: "Recall resets `processor_cost_cents` and `normalized_net_revenue_cents`
    to 0 and `normalization_mode_applied` to null on every line of the batch"

    Design: Difficulty/non_linear_state_machine/batch_recall_cycle_then_renormalize_with_appended_line
    """
    scenario = _batch_with_one_normalized_line()

    validate_success(api_client.recall_residual_batch(scenario["batch"]["id"], ANALYST))

    batch = fetch_batch(scenario["batch"]["id"])
    assert batch["state"] == "RECEIVED"
    assert batch["recall_count"] == 1
    assert batch["total_normalized_net_revenue_cents"] == 0
    assert batch["line_count"] == 1, "line_count describes the file, not the pricing"
    assert batch["gross_volume_cents"] == 4812355

    line = fetch_line(scenario["l1"]["id"])
    assert line["normalized_net_revenue_cents"] == 0
    assert line["processor_cost_cents"] == 0
    assert line["normalization_mode_applied"] is None


def test_the_loop_accepts_a_new_line_and_re_derives_the_totals_without_a_second_recall():
    """Re-entering NORMALIZED with an appended line totals 41009 and leaves recall_count at 1.

    PRD: "Each recall raises `recall_count` by one, and the loop may be traversed
    as many times as the operator needs."

    Design: Difficulty/non_linear_state_machine/batch_recall_cycle_then_renormalize_with_appended_line
    """
    scenario = _batch_with_one_normalized_line()

    validate_success(api_client.recall_residual_batch(scenario["batch"]["id"], ANALYST))
    second = add_thin_line(scenario["batch"]["id"], scenario["m2"]["id"])
    validate_success(api_client.normalize_residual_batch(scenario["batch"]["id"], ANALYST))

    batch = fetch_batch(scenario["batch"]["id"])
    assert batch["state"] == "NORMALIZED"
    assert batch["recall_count"] == 1, "re-normalizing is not a second recall"
    assert batch["line_count"] == 2
    assert batch["gross_volume_cents"] == 4912355
    assert batch["total_normalized_net_revenue_cents"] == 41009

    assert fetch_line(scenario["l1"]["id"])["normalized_net_revenue_cents"] == 40939
    assert fetch_line(second["id"])["normalized_net_revenue_cents"] == 70


def test_a_held_statement_can_still_be_finalized_because_the_dimensions_are_parallel():
    """Hold at ISSUED, then finalize while HELD: the combined state is (FINALIZED, HELD).

    PRD: "Neither dimension gates the other except where this document says so
    explicitly: a `HELD` statement can still be issued, and a `HELD` statement
    can still be finalized."

    Design: Difficulty/non_linear_state_machine/statement_parallel_dimensions_hold_finalize_then_settle
    """
    scenario = setup_canonical_posted_period()
    statement_id = scenario["statement"]["id"]

    before = fetch_statement_by_id(statement_id)
    assert before["lifecycle_state"] == "DRAFT"
    assert before["settlement_state"] == "UNSETTLED"
    assert before["net_payable_cents"] == 14643

    validate_success(api_client.issue_agent_statement(statement_id, CONTROLLER))
    issued = fetch_statement_by_id(statement_id)
    assert issued["lifecycle_state"] == "ISSUED"
    assert issued["settlement_state"] == "UNSETTLED"
    assert issued["minimum_true_up_cents"] == 0
    assert issued["advance_recoupment_cents"] == 0
    assert issued["net_payable_cents"] == 14643
    assert issued["issued_at"] is not None

    validate_success(
        api_client.hold_agent_statement(
            statement_id, hold_payload("BANK_DETAILS_UNVERIFIED"), CONTROLLER
        )
    )
    held = fetch_statement_by_id(statement_id)
    assert held["lifecycle_state"] == "ISSUED", "holding never touches the lifecycle"
    assert held["settlement_state"] == "HELD"
    assert held["hold_reason"] == "BANK_DETAILS_UNVERIFIED"

    validate_success(api_client.finalize_agent_statement(statement_id, CONTROLLER))
    finalized = fetch_statement_by_id(statement_id)
    assert finalized["lifecycle_state"] == "FINALIZED"
    assert finalized["settlement_state"] == "HELD"


def test_settlement_resumes_from_the_terminal_lifecycle_state_through_release_hold():
    """Release restores UNSETTLED on a FINALIZED row, which then settles; version rises by five.

    PRD: "Releasing a hold moves the statement `HELD` → `UNSETTLED` and clears
    `hold_reason`, and is available only from `HELD`."

    Design: Difficulty/non_linear_state_machine/statement_parallel_dimensions_hold_finalize_then_settle
    """
    scenario = setup_canonical_posted_period()
    statement_id = scenario["statement"]["id"]
    baseline_version = require_statement(scenario["agent"]["id"])["version"]

    validate_success(api_client.issue_agent_statement(statement_id, CONTROLLER))
    validate_success(
        api_client.hold_agent_statement(
            statement_id, hold_payload("BANK_DETAILS_UNVERIFIED"), CONTROLLER
        )
    )
    validate_success(api_client.finalize_agent_statement(statement_id, CONTROLLER))
    validate_success(api_client.release_agent_statement_hold(statement_id, CONTROLLER))

    released = fetch_statement_by_id(statement_id)
    assert released["lifecycle_state"] == "FINALIZED"
    assert released["settlement_state"] == "UNSETTLED"
    assert released["hold_reason"] is None

    validate_success(
        api_client.settle_agent_statement(statement_id, {"paid_on": "2026-08-15"}, CONTROLLER)
    )
    settled = fetch_statement_by_id(statement_id)
    assert settled["lifecycle_state"] == "FINALIZED"
    assert settled["settlement_state"] == "SETTLED"
    assert settled["paid_on"] == "2026-08-15"
    assert settled["version"] == baseline_version + 5, (
        "issue, hold, finalize, release and settle are five distinct writes"
    )
