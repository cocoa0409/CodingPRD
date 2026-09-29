"""Refusal bands: which of two simultaneously violated rules is allowed to surface."""

from test_helpers import (
    ANALYST,
    CONTROLLER,
    CONTROLLER_ONE,
    CONTROLLER_TWO,
    ApiErrorId,
    add_thin_line,
    api_client,
    create_residual_batch_payload,
    fetch_adjustment,
    fetch_statement_by_id,
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
    settle_payload,
    validate_error,
)

THIN_PRICING = {
    "monthly_minimum_cents": 2500,
    "per_transaction_fee_cents": 20,
    "equipment_lease_monthly_cents": 0,
    "boarded_on": "2026-01-05",
}


def _thirty_two_cent_draft_statement(monthly_minimum_cents: int = 2500) -> dict:
    """A POSTED thin period whose only statement is worth 32 cents and is never issued."""
    program = make_program()
    agent = make_agent()
    pricing = dict(THIN_PRICING)
    pricing["monthly_minimum_cents"] = monthly_minimum_cents
    merchant = make_active_merchant(agent["id"], program["id"], **pricing)
    batch = make_batch(program["id"], file_checksum="sha256:thin-0001")
    add_thin_line(batch["id"], merchant["id"], transaction_count=125)
    normalize_batch(batch["id"])
    post_batch(batch["id"])
    return {
        "program": program,
        "agent": agent,
        "merchant": merchant,
        "statement": require_statement(agent["id"]),
    }


def test_settling_a_draft_statement_reports_the_state_band_not_the_payout_floor():
    """One settle call violates both band 9 and band 13; only band 9 may surface.

    PRD: "the first band that produces a failure determines the response, and no
    later band is consulted"

    Design: Difficulty/priority_pair_validation_conflict/settle_draft_statement_below_floor_reports_state_over_fiscal
    """
    scenario = _thirty_two_cent_draft_statement()
    statement_id = scenario["statement"]["id"]

    response = api_client.settle_agent_statement(
        statement_id, settle_payload("2026-08-15"), CONTROLLER
    )
    body = validate_error(response, ApiErrorId.ERR_STATEMENT_STATE_INVALID.value, 409)
    assert body["error_id"] != ApiErrorId.ERR_BELOW_MIN_PAYOUT.value, (
        "band 9 outranks band 13"
    )


def test_the_payout_floor_really_is_violated_by_that_same_statement():
    """The 32-cent net payable is far below the 2500-cent floor, so both rules did fail.

    PRD: "The `lifecycle_state` must be `ISSUED` or `FINALIZED`; settling a `DRAFT`
    statement is `ERR_STATEMENT_STATE_INVALID`"

    Design: Difficulty/priority_pair_validation_conflict/settle_draft_statement_below_floor_reports_state_over_fiscal
    """
    scenario = _thirty_two_cent_draft_statement()
    statement_id = scenario["statement"]["id"]

    before = fetch_statement_by_id(statement_id)
    assert before["net_payable_cents"] == 32
    assert before["lifecycle_state"] == "DRAFT"

    validate_error(
        api_client.settle_agent_statement(
            statement_id, settle_payload("2026-08-15"), CONTROLLER
        ),
        ApiErrorId.ERR_STATEMENT_STATE_INVALID.value,
        409,
    )

    after = fetch_statement_by_id(statement_id)
    assert after["settlement_state"] == "UNSETTLED"
    assert after["paid_on"] is None


def _program_with_july_batch() -> dict:
    """One NORMALIZED July batch covering [2026-07-01, 2026-08-01) under sha256:aaa1."""
    program = make_program()
    batch = make_batch(program["id"], file_checksum="sha256:aaa1")
    normalize_batch(batch["id"])
    return {"program": program, "batch": batch}


def test_an_ingest_that_both_overlaps_and_repeats_a_checksum_reports_the_overlap():
    """Band 11 outranks band 12 on a single request that violates both.

    PRD: "the first band that produces a failure determines the response, and no
    later band is consulted"

    Design: Difficulty/priority_pair_validation_conflict/batch_ingest_overlap_and_duplicate_checksum_reports_temporal_over_constraint
    """
    scenario = _program_with_july_batch()

    payload = create_residual_batch_payload(
        scenario["program"]["id"],
        period_month="2026-07",
        coverage_start="2026-07-15",
        coverage_end="2026-08-20",
        file_checksum="sha256:aaa1",
    )
    body = validate_error(
        api_client.create_residual_batch(payload, ANALYST),
        ApiErrorId.ERR_COVERAGE_OVERLAP.value,
        409,
    )
    assert body["error_id"] != ApiErrorId.ERR_DUPLICATE_FILE_CHECKSUM.value

    _, meta = list_rows(
        api_client.list_residual_batches,
        {"processor_program_id": scenario["program"]["id"]},
    )
    assert meta["total_count"] == 1, "the refused ingest created nothing"


def test_the_checksum_rule_is_live_when_the_coverage_window_is_disjoint():
    """The control call keeps the losing rule honest: same checksum, no overlap.

    PRD: "`file_checksum` is unique across all batches whose `state` is not
    `REVERSED`; a repeat is `ERR_DUPLICATE_FILE_CHECKSUM`"

    Design: Difficulty/priority_pair_validation_conflict/batch_ingest_overlap_and_duplicate_checksum_reports_temporal_over_constraint
    """
    scenario = _program_with_july_batch()

    payload = create_residual_batch_payload(
        scenario["program"]["id"],
        period_month="2026-09",
        coverage_start="2026-09-01",
        coverage_end="2026-10-01",
        file_checksum="sha256:aaa1",
    )
    validate_error(
        api_client.create_residual_batch(payload, ANALYST),
        ApiErrorId.ERR_DUPLICATE_FILE_CHECKSUM.value,
        409,
    )

    _, meta = list_rows(
        api_client.list_residual_batches,
        {"processor_program_id": scenario["program"]["id"]},
    )
    assert meta["total_count"] == 1


def _two_proposals_from_one_controller() -> dict:
    """Controller one proposes two credits; controller two moves only the second UNDER_REVIEW."""
    scenario = _thirty_two_cent_draft_statement(monthly_minimum_cents=0)
    statement_id = scenario["statement"]["id"]
    still_proposed = propose_adjustment(
        statement_id,
        CONTROLLER_ONE,
        kind="DISPUTE_CREDIT",
        amount_cents=5000,
        reason="Dispute credit left sitting in PROPOSED on purpose",
    )
    under_review = propose_adjustment(
        statement_id,
        CONTROLLER_ONE,
        kind="DISPUTE_CREDIT",
        amount_cents=6000,
        reason="Dispute credit escalated by the second controller",
    )
    review_adjustment(under_review["id"], CONTROLLER_TWO)
    scenario["still_proposed"] = still_proposed
    scenario["under_review"] = under_review
    return scenario


def test_approving_ones_own_still_proposed_adjustment_reports_the_state_band():
    """Band 9 outranks band 10 when the creator approves a PROPOSED adjustment.

    PRD: "Approving an adjustment that is still `PROPOSED` as its own creator reports
    `ERR_ADJUSTMENT_STATE_INVALID` from band 9, not the segregation-of-duties error
    from band 10 — the state check wins."

    Design: Difficulty/priority_pair_validation_conflict/approve_own_unreviewed_adjustment_reports_state_over_segregation
    """
    scenario = _two_proposals_from_one_controller()
    adjustment_id = scenario["still_proposed"]["id"]

    body = validate_error(
        api_client.approve_statement_adjustment(adjustment_id, CONTROLLER_ONE),
        ApiErrorId.ERR_ADJUSTMENT_STATE_INVALID.value,
        409,
    )
    assert body["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value

    assert fetch_adjustment(adjustment_id)["state"] == "PROPOSED"
    statement = fetch_statement_by_id(scenario["statement"]["id"])
    assert statement["adjustment_cents"] == 0, "no PROPOSED amount reaches the statement"
    assert statement["net_payable_cents"] == 32


def test_the_segregation_rule_is_live_once_the_adjustment_is_under_review():
    """The control call: same principal, same statement, but band 9 is now satisfied.

    PRD: "Moving an adjustment `UNDER_REVIEW` → `APPLIED` requires that the approving
    `X-User-ID` differ from that adjustment's `created_by_user_id`"

    Design: Difficulty/priority_pair_validation_conflict/approve_own_unreviewed_adjustment_reports_state_over_segregation
    """
    scenario = _two_proposals_from_one_controller()
    adjustment_id = scenario["under_review"]["id"]

    validate_error(
        api_client.approve_statement_adjustment(adjustment_id, CONTROLLER_ONE),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        409,
    )

    assert fetch_adjustment(adjustment_id)["state"] == "UNDER_REVIEW"
    statement = fetch_statement_by_id(scenario["statement"]["id"])
    assert statement["adjustment_cents"] == 0
    assert statement["net_payable_cents"] == 32
