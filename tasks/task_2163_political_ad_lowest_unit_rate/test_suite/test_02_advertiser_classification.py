"""The classification review loop and its bounded number of evidence requests."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_advertiser,
    create_station,
    intake_candidate_advertiser,
    open_review,
    set_clock,
    validate_error,
    validate_success,
)

OFFICER_ALPHA = TEST_USERS["officer_alpha_headers"]


def _advertiser_under_review_after(rounds, api):
    """Intake one candidate buyer and drive `rounds` completed REQUEST_INFO legs."""
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WLOOP-TV", licensee_name="Loop Broadcasting Co", market_code="DMA-140"
    )
    advertiser = intake_candidate_advertiser(
        station["id"],
        None,
        legal_name="Rivera For Senate",
        candidate_name="Dana Rivera",
        office_sought="US Senate",
        qualification_evidence_ref=None,
    )
    open_review(advertiser["id"])
    reasons = ["Ballot certification missing", "Certification unsigned", "Office designation ambiguous"]
    for index in range(rounds):
        validate_success(
            api.decide_advertiser(
                advertiser["id"],
                {"decision": "REQUEST_INFO", "reason": reasons[index]},
                OFFICER_ALPHA,
            )
        )
        open_review(advertiser["id"])
    return station, advertiser


def test_request_info_cycles_the_advertiser_between_review_and_info_requested(api):
    """PRD §3.2: "Opening a review moves an advertiser from `SUBMITTED` to
    `UNDER_REVIEW`; the same operation is also the return leg of the loop, moving an
    advertiser from `INFO_REQUESTED` back to `UNDER_REVIEW` after the buyer has filed
    more evidence."
    PRD §3.2: "`REQUEST_INFO` is the loop leg: while `review_round` is strictly below
    the ceiling of three rounds, it increments `review_round` by one and moves the
    advertiser `UNDER_REVIEW → INFO_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/advertiser_classification_loops_then_auto_rejects_on_fourth_request_info
    """
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WLP2-TV", licensee_name="Loop Broadcasting Co", market_code="DMA-140"
    )
    advertiser = intake_candidate_advertiser(
        station["id"],
        None,
        legal_name="Rivera For Senate",
        candidate_name="Dana Rivera",
        office_sought="US Senate",
        qualification_evidence_ref=None,
    )
    assert advertiser["status"] == "SUBMITTED"
    assert advertiser["review_round"] == 0

    opened = open_review(advertiser["id"])
    assert opened["status"] == "UNDER_REVIEW"

    for expected_round in (1, 2, 3):
        requested = validate_success(
            api.decide_advertiser(
                advertiser["id"],
                {"decision": "REQUEST_INFO", "reason": "More evidence needed"},
                OFFICER_ALPHA,
            )
        )
        assert_advertiser(requested)
        assert requested["status"] == "INFO_REQUESTED", (
            f"round {expected_round} must land in INFO_REQUESTED"
        )
        assert requested["review_round"] == expected_round, (
            f"review_round must read {expected_round} after {expected_round} requests"
        )
        assert requested["entitled_to_luc"] is False

        reopened = open_review(advertiser["id"])
        assert reopened["status"] == "UNDER_REVIEW", (
            "the review reopens on the return leg of the loop"
        )
        assert reopened["review_round"] == expected_round, (
            "reopening the review does not consume another round"
        )


def test_fourth_request_info_auto_rejects_the_advertiser(api):
    """PRD §3.2: "But the fourth such request is refused rather than looped: when
    `review_round` has already reached 3, the same `REQUEST_INFO` decision instead
    moves the advertiser `UNDER_REVIEW → CLASSIFICATION_REJECTED`, sets
    `classification_reason` to the literal string `MAX_REVIEW_ROUNDS_EXCEEDED`, records
    `classified_by_user_id` from the acting `X-User-ID`, and leaves `entitled_to_luc`
    false."

    Design: Difficulty/non_linear_state_machine/advertiser_classification_loops_then_auto_rejects_on_fourth_request_info
    """
    _station, advertiser = _advertiser_under_review_after(3, api)

    rejected = validate_success(
        api.decide_advertiser(
            advertiser["id"],
            {"decision": "REQUEST_INFO", "reason": "Still no certification"},
            OFFICER_ALPHA,
        )
    )
    assert_advertiser(rejected)
    assert rejected["status"] == "CLASSIFICATION_REJECTED"
    assert rejected["review_round"] == 3, "the fourth request does not consume a fourth round"
    assert rejected["classification_reason"] == "MAX_REVIEW_ROUNDS_EXCEEDED"
    assert rejected["classified_by_user_id"] == "officer-alpha"
    assert rejected["entitled_to_luc"] is False


def test_classification_decision_before_the_review_is_opened_is_refused(api):
    """PRD §3.2: "An advertiser in any other position rejects the operation with
    `ERR_ADVERTISER_NOT_IN_REVIEW` (HTTP 409). The same error guards the decision
    operation from the other side: a classification decision may only be recorded on an
    advertiser sitting in `UNDER_REVIEW`."
    PRD §3.2: "Intake always sets the advertiser's `status` to `SUBMITTED`, its
    `review_round` to 0, and its `entitled_to_luc` flag to false, whatever the buyer
    asserted about itself."

    Design: Corner/state_machines/advertiser_decision_before_review_rejected_as_not_in_review
    """
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WRVW-TV", licensee_name="Review Gate Media", market_code="DMA-108"
    )
    advertiser = intake_candidate_advertiser(
        station["id"],
        None,
        legal_name="Rivera For Senate",
        candidate_name="Dana Rivera",
        office_sought="US Senate",
        qualification_evidence_ref="FEC-F2-2026-0088",
    )

    validate_error(
        api.decide_advertiser(
            advertiser["id"],
            {"decision": "CLASSIFY_CANDIDATE", "reason": "Ballot access confirmed"},
            OFFICER_ALPHA,
        ),
        ApiErrorId.ERR_ADVERTISER_NOT_IN_REVIEW,
    )

    unchanged = validate_success(api.get_advertiser(advertiser["id"], OFFICER_ALPHA))
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["review_round"] == 0
    assert unchanged["classified_by_user_id"] is None
    assert unchanged["entitled_to_luc"] is False
