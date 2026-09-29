"""Requests that violate two rules at once, where the precedence order of 2.11
decides which refusal the caller sees."""
from test_helpers import (
    assert_fund_invariants,
    assert_fund_terms,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_activity_payload
from test_helpers.fixtures import (
    DIRECTOR,
    TRUSTEE_2,
    adopt_position,
    cast_ballots,
    draft_position,
    draft_registration,
    file_registration,
    open_ballot_round,
    read_candidate,
    read_contribution,
    read_fund,
    read_position,
    read_registration,
    setup_disbursed_contribution,
    setup_quorate_committee,
    tally_round,
)

ACTIVITY = {"activity_date": "2026-07-05", "hours": 2.0, "expenditure_cents": 50_000}


def test_board_approve_reports_the_state_gate_rather_than_the_balance_gate():
    """A disbursed row is refused on its status, not on the thin fund balance.

    PRD 3.9: "The contribution must be `PENDING_BOARD`: a row the fund's
    restricted posture pushed to `SUSPENDED` is refused specifically with
    `ERR_CONTRIBUTION_SUSPENDED`, while a row that is `BOARD_APPROVED`,
    `DISBURSED` or `VOIDED` is refused with `ERR_CONTRIBUTION_NOT_PENDING`."
    PRD 2.11: "8. The target resource is in a state from which the requested
    transition is declared — otherwise the matching state error (409)."

    Design: Difficulty/priority_pair_validation_conflict/board_approve_state_gate_beats_fund_balance_gate_rejected
    """
    state = setup_disbursed_contribution(
        amount_cents=250_000, min_reserve_cents=0, receipt_amount_cents=300_000
    )
    fund = read_fund(state["fund"]["id"])
    assert fund["available_balance_cents"] == 50_000
    assert fund["posture"] == "OPEN"

    response = api_client.board_approve_contribution(state["contribution"]["id"], TRUSTEE_2)

    validate_error(response, "ERR_CONTRIBUTION_NOT_PENDING", 409)


def test_the_refused_board_approval_moves_no_accumulator():
    """The rejected retry leaves the disbursed row and every total alone.

    PRD 3.9: "And the amount must fit the fund: `amount_cents` must not exceed
    the fund's current `available_balance_cents`, with equality accepted, and an
    amount larger than the balance is refused with
    `ERR_INSUFFICIENT_FUND_BALANCE`."
    PRD 3.9: "On success the fund's `committed_balance_cents` falls by the amount
    and its `disbursed_total_cents` rises by it, which by design leaves
    `available_balance_cents` unchanged — the money was already reserved at
    approval."

    Design: Difficulty/priority_pair_validation_conflict/board_approve_state_gate_beats_fund_balance_gate_rejected
    """
    state = setup_disbursed_contribution(
        amount_cents=250_000, min_reserve_cents=0, receipt_amount_cents=300_000
    )
    contribution_id = state["contribution"]["id"]
    approver = read_contribution(contribution_id)["board_approved_by_user_id"]

    api_client.board_approve_contribution(contribution_id, TRUSTEE_2)

    unchanged = read_contribution(contribution_id)
    assert unchanged["status"] == "DISBURSED"
    assert unchanged["board_approved_by_user_id"] == approver

    fund = read_fund(state["fund"]["id"])
    assert_fund_terms(
        fund,
        receipts=300_000,
        committed=0,
        disbursed=250_000,
        fees=0,
        available=50_000,
        posture="OPEN",
    )
    assert_fund_invariants(fund)
    assert read_candidate(state["candidate"]["id"])["disbursed_support_cents"] == 250_000


def test_activity_logging_reports_the_registration_gate_before_the_position_gate():
    """The regulatory registration gate outranks the adoption gate.

    PRD 3.5: "The registration must be `ACTIVE`: a `DRAFT` registration means
    unregistered lobbying, an `AMENDMENT_PENDING` one means the filing on record
    is stale, and a `TERMINATED` one means coverage has ended — all three are
    refused with `ERR_REGISTRATION_NOT_ACTIVE`."
    PRD 2.11: "11. The regulatory registration gate on activity logging —
    otherwise `ERR_REGISTRATION_NOT_ACTIVE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/log_activity_registration_gate_beats_position_gate_rejected
    """
    roster = setup_quorate_committee()
    position = draft_position(roster["committee"]["id"])
    registration = draft_registration()
    assert position["status"] == "DRAFT"
    assert registration["status"] == "DRAFT"

    response = api_client.create_lobbying_activity(
        create_activity_payload(registration["id"], position["id"], **ACTIVITY), DIRECTOR
    )

    validate_error(response, "ERR_REGISTRATION_NOT_ACTIVE", 409)
    after = read_registration(registration["id"])
    assert after["status"] == "DRAFT"
    assert after["ytd_reportable_cents"] == 0
    assert after["ytd_reportable_hours"] == 0
    assert read_position(position["id"])["status"] == "DRAFT"


def test_clearing_both_gates_lets_the_identical_activity_log_succeed():
    """Filing the registration and adopting the position unblocks the same call.

    PRD 3.5: "The cited position must be `ADOPTED`, or the log is refused with
    `ERR_POSITION_NOT_ADOPTED`."
    PRD 3.4: "Adoption is what unlocks the outward-facing work: only an `ADOPTED`
    position may be cited by a lobbying activity or advanced by a grassroots
    campaign."

    Design: Difficulty/priority_pair_validation_conflict/log_activity_registration_gate_beats_position_gate_rejected
    """
    roster = setup_quorate_committee()
    position = draft_position(roster["committee"]["id"])
    registration = draft_registration()
    payload = create_activity_payload(registration["id"], position["id"], **ACTIVITY)

    validate_error(
        api_client.create_lobbying_activity(payload, DIRECTOR),
        "ERR_REGISTRATION_NOT_ACTIVE",
        409,
    )

    file_registration(registration["id"])
    open_ballot_round(position["id"])
    cast_ballots(position["id"], roster["members"], ["SUPPORT", "SUPPORT", "OPPOSE"])
    tally_round(position["id"])
    adopted = adopt_position(position["id"])
    assert adopted["status"] == "ADOPTED"

    activity = validate_success(
        api_client.create_lobbying_activity(payload, DIRECTOR), 201
    )
    assert activity["status"] == "LOGGED"
    assert activity["expenditure_cents"] == 50_000
    assert activity["staff_cost_cents"] == 17_000
    registration_after = read_registration(registration["id"])
    assert registration_after["ytd_reportable_cents"] == 50_000
    assert registration_after["ytd_reportable_hours"] == 2.0
