"""Validation-order conflicts between distinct failure categories (queue A,
rule `priority_pair_validation_conflict`).

The PRD fixes the sequence in which a failing request is adjudicated, so a
request that trips two categories must be reported under the earlier one and
never under the later one.
"""
from test_helpers import (
    ApiErrorId,
    GOVERNANCE,
    UNDERWRITING,
    api_client,
    get_success_data,
    make_station_eligible,
    set_clock,
    validate_error,
)

STATION_FIXTURE = dict(
    call_sign="WAMU", licensee_name="District Licensee", state_code="DC",
    dma_market_rank=9, dma_households=2300000, coverage_population=100000,
    full_time_staff_count=8, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH",
)

ACK_STATION = dict(
    call_sign="WBEZ", licensee_name="Lakefront Licensee", state_code="IL",
    dma_market_rank=3, dma_households=3200000, coverage_population=110000,
    full_time_staff_count=8, newsroom_staff_count=4,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_MIDWEST",
)


def setup_draft_proposal():
    """One DuesStructureProposal in DRAFT, never opened."""
    set_clock("2026-09-01T00:00:00Z")
    proposal = get_success_data(api_client.create_proposal(
        {"fiscal_year": 2027, "proposed_base_fee_cents": 1350000,
         "proposed_revenue_rate_bps": 275, "quorum_required_votes": 1,
         "effective_from": "2026-08-01T00:00:00Z"}, GOVERNANCE), 201)
    return get_success_data(api_client.get_proposal(proposal["id"], GOVERNANCE))


def test_enact_of_an_unopened_proposal_fails_the_state_check():
    """PRD §2.9: "A resource not in the required from-state, or failing a declared
    precondition on its transition, fails with `ERR_INVALID_STATE` (409)".
    PRD §3.9: "A governance officer enacts a `PASSED` proposal once the current
    instant has reached its `effective_from`".

    The proposal is still DRAFT, so the from-state precondition is what fails.

    Design: Difficulty/priority_pair_validation_conflict/priority_state_over_fiscal_mode
    """
    proposal = setup_draft_proposal()
    resp = api_client.enact_proposal(
        proposal["id"], {"expected_proposal_version": proposal["version"]}, GOVERNANCE)

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_enact_reports_the_state_failure_rather_than_the_fiscal_one():
    """PRD §2.9: categories are "ordered by increasing specificity, so an
    unauthenticated caller never learns whether a station exists".
    PRD §3.9: "An enactment that would over-allocate the fiscal-year pool, as
    described below, fails with `ERR_POOL_OVER_ALLOCATED`".

    Both categories are named for this endpoint, and the contract resolves the
    pair in favour of the earlier state category, so the pool error must not be
    the one returned while the proposal is still DRAFT.

    Design: Difficulty/priority_pair_validation_conflict/priority_state_over_fiscal_mode
    """
    proposal = setup_draft_proposal()
    resp = api_client.enact_proposal(
        proposal["id"], {"expected_proposal_version": proposal["version"]}, GOVERNANCE)
    error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert error["error_id"] != ApiErrorId.ERR_POOL_OVER_ALLOCATED, (
        "the state category outranks the fiscal category for the same request"
    )


def setup_submittable_underwriting(ack_script_text):
    """An UnderwritingAgreement in SUBMITTED carrying the supplied script."""
    set_clock("2026-09-01T00:00:00Z")
    station = make_station_eligible(**ACK_STATION)
    agreement = get_success_data(api_client.create_underwriting(
        {
            "sponsor_name": "Prairie Motors",
            "station_id": station["id"],
            "program_code": "NP-1005",
            "ack_script_text": ack_script_text,
            "consideration_cents": 250000,
            "compliance_segment_count": 1,
        },
        UNDERWRITING), 201)
    return {"station": station, "agreement": agreement}


def test_violating_script_blocks_submission_with_the_language_error():
    """PRD §3.8: "the caller sees `ERR_ACK_LANGUAGE_VIOLATION` (HTTP 422) from the
    approval path when the script does not pass".
    PRD §3.8: "A script matching none of the five passes."

    The script trips both the superlative check and the call-to-action check, so
    the language rule is the category that governs submission.

    Design: Difficulty/priority_pair_validation_conflict/priority_safety_over_compliance
    """
    ctx = setup_submittable_underwriting("The best cars in Chicago, call now")
    resp = api_client.submit_underwriting_review(ctx["agreement"]["id"], UNDERWRITING)

    validate_error(resp, ApiErrorId.ERR_ACK_LANGUAGE_VIOLATION)


def test_over_length_script_alone_also_blocks_submission():
    """PRD §3.8: "a 31-word script containing no forbidden phrase surfaces the
    length violation alone. A 30-word script with no forbidden phrase passes."

    The script carries no forbidden phrase, no comparative token, no price
    invitation and no call to action, so only the length check can trip it.

    Design: Difficulty/priority_pair_validation_conflict/priority_safety_over_compliance
    """
    words = " ".join(["signal"] * 31)
    ctx = setup_submittable_underwriting(words)
    resp = api_client.submit_underwriting_review(ctx["agreement"]["id"], UNDERWRITING)

    validate_error(resp, ApiErrorId.ERR_ACK_LANGUAGE_VIOLATION)