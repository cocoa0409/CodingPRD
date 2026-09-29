"""The two non-linear state machines: the cyclic review loop and the
agreement's two independent status dimensions.
"""

from test_helpers import (
    ApiErrorId,
    accept_review,
    api_client,
    assert_instant_equals,
    execute_agreement,
    fund_escrow,
    issue_deficiency,
    read_agreement,
    read_application,
    resubmit_application,
    settle_escrow,
    set_clock,
    setup_scenario,
    validate_error,
    decide_application,
    file_application,
    post_notice,
)

DEPOSIT_CENTS = 2405001


def _application_under_review():
    """A CLASS_47 filing accepted into review by analyst-1, clock untouched."""
    return setup_scenario(
        stage="application_under_review",
        county_overrides={"quota_licenses_total": 100, "protest_window_days": 15},
        represents_buyer=True,
        deposit_by_buyer=True,
        application_fee=173250,
    )


def test_review_cycle_runs_twice_raising_the_fee_on_every_lap():
    """SUBMITTED to UNDER_REVIEW to DEFICIENT to SUBMITTED, twice.

    PRD: "From `UNDER_REVIEW`, the analyst may kick the application back by
    issuing a deficiency notice carrying `deficiency_codes`, advancing
    `UNDER_REVIEW → DEFICIENT`, incrementing `deficiency_round_count` by one and
    storing the supplied codes in `last_deficiency_codes`."

    PRD: "From `DEFICIENT`, the `Broker` refiles, advancing `DEFICIENT →
    SUBMITTED` with a fresh `fee_paid_cents` and optionally a fresh
    `applicant_statement_ref`."

    PRD: "The full cycle is therefore `SUBMITTED → UNDER_REVIEW → DEFICIENT →
    SUBMITTED`, traversable at most twice."

    The subtotal grows 165000, 195000, 225000 across the laps, and only the last
    of those reaches the 200000 tier edge and its 800 basis points: the fees are
    173250, 204750 and 243000, summing to 621000 tendered in all.

    Design: Difficulty/non_linear_state_machine/transfer_application_deficiency_revision_cycle
    """
    scenario = _application_under_review()
    application_id = scenario["application_id"]
    assert scenario["application"]["status"] == "UNDER_REVIEW"

    first_deficient = issue_deficiency(application_id, ["MISSING_FINANCIALS"])
    assert first_deficient["status"] == "DEFICIENT"
    assert first_deficient["deficiency_round_count"] == 1
    assert first_deficient["last_deficiency_codes"] == ["MISSING_FINANCIALS"]

    first_refiling = resubmit_application(application_id, 204750, scenario["brokerage_id"])
    assert first_refiling["status"] == "SUBMITTED"
    assert first_refiling["deficiency_round_count"] == 1
    assert first_refiling["filing_fee_cents"] == 204750

    accept_review(application_id)
    second_deficient = issue_deficiency(application_id, ["MISSING_LEASE"])
    assert second_deficient["status"] == "DEFICIENT"
    assert second_deficient["deficiency_round_count"] == 2
    assert second_deficient["last_deficiency_codes"] == ["MISSING_LEASE"]

    second_refiling = resubmit_application(application_id, 243000, scenario["brokerage_id"])
    assert second_refiling["status"] == "SUBMITTED"
    assert second_refiling["deficiency_round_count"] == 2
    assert second_refiling["filing_fee_cents"] == 243000
    assert second_refiling["fee_paid_total_cents"] == 621000
    assert second_refiling["last_deficiency_codes"] == ["MISSING_LEASE"]


def test_third_deficiency_notice_is_refused_and_the_cycle_stops():
    """The loop is bounded at two rounds; the row stays where it was.

    PRD: "At most two deficiency rounds are permitted: the notice is allowed only
    while `deficiency_round_count` is less than 2, and a third attempt is refused
    with `ERR_DEFICIENCY_LIMIT_EXCEEDED`."

    PRD: "A successful refiling recomputes and rewrites `filing_fee_cents` at the
    current round count, adds the newly tendered `fee_paid_cents` to the running
    `fee_paid_total_cents`, and deliberately **retains** `accepted_by_analyst_id`,
    so the segregation-of-duties comparand survives the revision loop and the
    accepting analyst cannot recover decision authority by sending the
    application through the cycle again."

    The refused notice leaves the application at `UNDER_REVIEW` — the third lap
    never starts — and the analyst who first accepted it is still recorded.

    Design: Difficulty/non_linear_state_machine/transfer_application_deficiency_revision_cycle
    """
    scenario = _application_under_review()
    application_id = scenario["application_id"]
    accepting_analyst = scenario["application"]["accepted_by_analyst_id"]

    issue_deficiency(application_id, ["MISSING_FINANCIALS"])
    resubmit_application(application_id, 204750, scenario["brokerage_id"])
    accept_review(application_id)
    issue_deficiency(application_id, ["MISSING_LEASE"])
    resubmit_application(application_id, 243000, scenario["brokerage_id"])
    third_lap = accept_review(application_id)
    assert third_lap["status"] == "UNDER_REVIEW"

    refused = api_client.issue_deficiency(
        application_id,
        {"deficiency_codes": ["MISSING_FINANCIALS"]},
        scenario["analyst_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_DEFICIENCY_LIMIT_EXCEEDED.value, 409)

    stored = read_application(application_id)
    assert stored["status"] == "UNDER_REVIEW"
    assert stored["deficiency_round_count"] == 2
    assert stored["accepted_by_analyst_id"] == accepting_analyst


def _funded_draft_agreement():
    """A DRAFT agreement with a fully acknowledged dual-agency disclosure."""
    return setup_scenario(
        stage="disclosure_acked",
        county_overrides={"quota_licenses_total": 100, "protest_window_days": 15},
        represents_buyer=True,
    )


def test_funding_moves_the_money_dimension_while_the_contract_stays_a_draft():
    """Money and contract advance on separate axes of the same record.

    PRD: "First, the money dimension and the contract dimension of an agreement
    move independently — a deposit can be held while the agreement is still a
    draft, and an agreement can be closed while the funds are still held — so the
    platform tracks them as two separate status fields on the same record and
    never collapses them."

    PRD: "Funding is a separate act, performed by the `Buyer` or by the
    `EscrowOfficer`, and it advances only the money dimension: `escrow_status`
    moves `AWAITING_DEPOSIT → HELD` while `agreement_status` is still `DRAFT`."

    PRD: "On success, `executed_at` is stamped with the current logical instant
    and `commission_mode` is frozen from the `FULLY_ACKED` disclosure: it becomes
    `DUAL_AGENCY` when that disclosure asserts both `represents_seller` and
    `represents_buyer`, and `SINGLE_AGENCY` in every other case."

    Design: Difficulty/non_linear_state_machine/agreement_parallel_status_dimensions
    """
    scenario = _funded_draft_agreement()
    agreement_id = scenario["agreement_id"]
    assert scenario["agreement"]["required_deposit_cents"] == DEPOSIT_CENTS

    funded = fund_escrow(agreement_id, DEPOSIT_CENTS, buyer_id=scenario["buyer_id"])
    assert funded["escrow_status"] == "HELD"
    assert funded["agreement_status"] == "DRAFT"
    assert funded["escrow_balance_cents"] == DEPOSIT_CENTS
    assert funded["executed_at"] is None
    assert funded["commission_mode"] is None

    executed = execute_agreement(agreement_id, scenario["brokerage_id"])
    assert executed["agreement_status"] == "EXECUTED"
    assert executed["escrow_status"] == "HELD"
    assert executed["escrow_balance_cents"] == DEPOSIT_CENTS
    assert executed["commission_mode"] == "DUAL_AGENCY"
    assert_instant_equals(executed["executed_at"], "2026-08-01T00:00:00Z", "executed_at")
    assert executed["settled_at"] is None


def test_an_approved_transfer_closes_the_contract_with_the_money_still_held():
    """Only the escrow officer moves the money dimension.

    PRD: "Hop 4 fires because hop 3 set the listing to `SOLD`, and moves the
    agreement's contract dimension from `EXECUTED` to `CLOSED` — deliberately
    leaving the money dimension at `HELD`, because only the escrow officer moves
    money."

    PRD: "The agreement's `escrow_balance_cents` is recomputed to 0, `settled_at`
    is stamped with the current logical instant, and the agreement's `version`
    advances by one."

    The contract dimension reaches its terminal `CLOSED` at the decision, and the
    money dimension only reaches `RELEASED` at the later settlement instant.

    Design: Difficulty/non_linear_state_machine/agreement_parallel_status_dimensions
    """
    scenario = _funded_draft_agreement()
    agreement_id = scenario["agreement_id"]

    fund_escrow(agreement_id, DEPOSIT_CENTS, buyer_id=scenario["buyer_id"])
    execute_agreement(agreement_id, scenario["brokerage_id"])
    application = file_application(agreement_id, 173250, scenario["brokerage_id"])
    accept_review(application["id"])
    set_clock("2026-08-10T00:00:00Z")
    post_notice(application["id"])
    set_clock("2026-09-10T00:00:00Z")
    decide_application(application["id"], "APPROVED")

    closed = read_agreement(agreement_id)
    assert closed["agreement_status"] == "CLOSED"
    assert closed["escrow_status"] == "HELD"
    assert closed["escrow_balance_cents"] == DEPOSIT_CENTS
    assert closed["settled_at"] is None

    released = settle_escrow(agreement_id, "RELEASE")
    assert released["escrow_status"] == "RELEASED"
    assert released["agreement_status"] == "CLOSED"
    assert released["escrow_balance_cents"] == 0
    assert_instant_equals(released["settled_at"], "2026-09-10T00:00:00Z", "settled_at")
    assert_instant_equals(
        released["executed_at"], "2026-08-01T00:00:00Z", "executed_at"
    )
