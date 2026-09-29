"""One request violating two rules of different categories at once: the fixed
order of refusal decides which code the caller sees.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    fund_escrow,
    read_agreement,
    setup_scenario,
    validate_error,
)

DEPOSIT_CENTS = 2405001


def _unfunded_undisclosed_draft():
    """A DRAFT agreement with neither a deposit nor any agency disclosure."""
    return setup_scenario(
        stage="agreement_draft",
        county_overrides={"quota_licenses_total": 100},
    )


def test_execution_reports_the_state_violation_before_the_disclosure_one():
    """The unfunded escrow is refused ahead of the missing disclosure.

    PRD: "Many endpoints are guarded by several rules at once, and which rule a
    caller sees when more than one is violated is part of the contract, not an
    implementation detail."

    PRD: "**State precondition.** On every state-transition endpoint: the target
    record must sit in a non-terminal state from which the requested transition is
    declared, and the cross-dimension guards on a parallel-state record count here
    too — the money dimension must be `HELD` for execution, the contract dimension
    must be `CLOSED` for a release, and the money dimension must be
    `AWAITING_DEPOSIT` for a termination."

    PRD: "The money dimension must already be `HELD`, so an unfunded agreement
    reports `ERR_ESCROW_NOT_HELD`; this is the cross-dimension guard that forces
    funding to precede execution."

    The same call also violates the agency-disclosure rule, which sits later in
    the order, so that code must not be the one reported.

    Design: Difficulty/priority_pair_validation_conflict/execute_state_beats_disclosure_referential
    """
    scenario = _unfunded_undisclosed_draft()
    agreement_id = scenario["agreement_id"]
    assert scenario["agreement"]["escrow_status"] == "AWAITING_DEPOSIT"

    refused = api_client.execute_agreement(agreement_id, scenario["broker_headers"])
    error = validate_error(refused, ApiErrorId.ERR_ESCROW_NOT_HELD.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_DUAL_AGENCY_DISCLOSURE_REQUIRED.value

    unchanged = read_agreement(agreement_id)
    assert unchanged["agreement_status"] == "DRAFT"
    assert unchanged["escrow_status"] == "AWAITING_DEPOSIT"


def test_the_disclosure_violation_surfaces_only_once_the_deposit_has_landed():
    """Clearing the earlier rule exposes the later one on the identical call.

    PRD: "**Agency disclosure** — `ERR_DUAL_AGENCY_DISCLOSURE_REQUIRED` or
    `ERR_DUAL_AGENCY_PROHIBITED` (422), on agreement execution,
    transfer-application filing and disclosure filing."

    PRD: "A `FULLY_ACKED` disclosure must exist on the agreement, or the attempt
    is refused with `ERR_DUAL_AGENCY_DISCLOSURE_REQUIRED`."

    The deposit lands, so the money dimension is `HELD` and the state rule is
    satisfied; the second refusal is the disclosure rule at HTTP 422, and the
    contract dimension is still a draft.

    Design: Difficulty/priority_pair_validation_conflict/execute_state_beats_disclosure_referential
    """
    scenario = _unfunded_undisclosed_draft()
    agreement_id = scenario["agreement_id"]

    first = api_client.execute_agreement(agreement_id, scenario["broker_headers"])
    validate_error(first, ApiErrorId.ERR_ESCROW_NOT_HELD.value, 409)

    funded = fund_escrow(agreement_id, DEPOSIT_CENTS, buyer_id=scenario["buyer_id"])
    assert funded["escrow_status"] == "HELD"
    assert funded["escrow_balance_cents"] == DEPOSIT_CENTS

    second = api_client.execute_agreement(agreement_id, scenario["broker_headers"])
    validate_error(
        second, ApiErrorId.ERR_DUAL_AGENCY_DISCLOSURE_REQUIRED.value, 422
    )

    stored = read_agreement(agreement_id)
    assert stored["agreement_status"] == "DRAFT"
    assert stored["escrow_status"] == "HELD"
    assert stored["escrow_balance_cents"] == DEPOSIT_CENTS
