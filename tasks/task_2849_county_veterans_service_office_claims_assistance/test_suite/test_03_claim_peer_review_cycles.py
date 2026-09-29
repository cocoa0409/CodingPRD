"""
The peer-review rework loop and the segregation-of-duties refusal.

Both families exercise the boundary between `EVIDENCE_DEVELOPMENT` and
`PEER_REVIEW`, where the reviewer identity is decided and re-used.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    add_received_evidence,
    assert_exact_whole,
    assert_pct_2dp,
    conditions,
    create_active_representative,
    create_claim_in_evidence_development,
    create_represented_veteran,
    make_county_officer_headers,
    read_claim,
    return_for_rework_action,
    set_clock,
    submit_for_peer_review,
    submit_for_review_action,
    validate_error,
)

TWO_CONDITIONS = ["tinnitus", "lumbar_strain"]


@pytest.fixture
def twice_reworked_claim(api):
    """
    A two-condition claim carrying three received items that its reviewer has
    returned for rework twice.
    """
    set_clock(api, CLOCK_START_INSTANT)
    preparer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    reviewer = create_active_representative(
        api, accreditation_type="VSO_ORG", accreditation_expires_on="2029-12-31"
    )
    base = create_represented_veteran(api, designee=preparer)
    ctx = create_claim_in_evidence_development(
        api, base, claimed_conditions=conditions(*TWO_CONDITIONS)
    )
    officer = ctx["officer_headers"]
    claim_id = ctx["claim"]["id"]
    for evidence_type in ("SERVICE_TREATMENT_RECORD", "DBQ", "PRIVATE_MEDICAL"):
        add_received_evidence(api, claim_id, officer, evidence_type=evidence_type)

    reviewer_headers = make_county_officer_headers(reviewer["id"])
    for _ in range(2):
        submit_for_peer_review(api, claim_id, reviewer["id"], officer)
        response = api.claim_transition(
            claim_id, return_for_rework_action("Tighten the nexus discussion"), reviewer_headers
        )
        assert response.status_code == 200

    return {
        "claim_id": claim_id,
        "officer_headers": officer,
        "preparer": preparer,
        "reviewer": reviewer,
    }


@pytest.fixture
def self_review_attempt(api):
    """
    A claim whose preparer is also the designated representative, submitted for
    review naming that very representative.
    """
    set_clock(api, CLOCK_START_INSTANT)
    preparer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    base = create_represented_veteran(api, designee=preparer)
    ctx = create_claim_in_evidence_development(
        api, base, claimed_conditions=conditions("tinnitus")
    )
    return {
        "claim_id": ctx["claim"]["id"],
        "officer_headers": ctx["officer_headers"],
        "preparer": preparer,
    }


class TestReworkCycle:
    """Two completed rework passes leave a counted, reviewer-bearing claim."""

    def test_two_passes_park_the_claim_back_in_development(
        self, api, twice_reworked_claim
    ):
        """
        Returning for rework "sets `status` back to `EVIDENCE_DEVELOPMENT`, increments `rework_count` by 1", and
        "The rework loop may run any number of times, and `rework_count` counts the completed passes."

        Design: Difficulty/non_linear_state_machine/claim_rework_cycle_twice_retains_reviewer_and_increments_rework_count
        """
        claim = read_claim(
            api, twice_reworked_claim["claim_id"], twice_reworked_claim["officer_headers"]
        )
        assert claim["status"] == "EVIDENCE_DEVELOPMENT"
        assert_exact_whole(claim["rework_count"], 2, "rework_count")

    def test_the_reviewer_survives_both_passes(self, api, twice_reworked_claim):
        """
        The loop "deliberately **leaves `peer_reviewed_by_representative_id` in place**, so the same reviewer is re-used on the next submission unless a different `reviewer_representative_id` is supplied".

        Design: Difficulty/non_linear_state_machine/claim_rework_cycle_twice_retains_reviewer_and_increments_rework_count
        """
        claim = read_claim(
            api, twice_reworked_claim["claim_id"], twice_reworked_claim["officer_headers"]
        )
        assert claim["peer_reviewed_by_representative_id"] == (
            twice_reworked_claim["reviewer"]["id"]
        )
        assert claim["prepared_by_representative_id"] == (
            twice_reworked_claim["preparer"]["id"]
        )

    def test_the_evidence_score_is_untouched_by_the_loop(self, api, twice_reworked_claim):
        """
        Three punctual items earn fifty of the seventy points this claim needs;
        the loop only moves status, and creation had set
        "`rework_count` and `reopen_count` to 0, and `evidence_completeness_pct` to 0.00".

        Design: Difficulty/non_linear_state_machine/claim_rework_cycle_twice_retains_reviewer_and_increments_rework_count
        """
        claim = read_claim(
            api, twice_reworked_claim["claim_id"], twice_reworked_claim["officer_headers"]
        )
        assert_pct_2dp(claim["evidence_completeness_pct"], 71.43)
        assert_exact_whole(claim["reopen_count"], 0, "reopen_count")


class TestSegregationOfDutiesPrecedence:
    """One representative who is both preparer and designee trips the earlier band."""

    def test_naming_the_preparer_as_reviewer_is_refused(self, api, self_review_attempt):
        """
        The reviewer "must **not** be `prepared_by_representative_id` — a preparer may never peer-review their own claim, and the attempt is refused with `ERR_SEGREGATION_OF_DUTIES` at HTTP 409".

        Design: Difficulty/priority_pair_validation_conflict/submit_for_review_naming_preparer_who_is_also_designee_returns_segregation_of_duties
        """
        response = api.claim_transition(
            self_review_attempt["claim_id"],
            submit_for_review_action(self_review_attempt["preparer"]["id"]),
            self_review_attempt["officer_headers"],
        )
        validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 409)

    def test_the_designated_representative_code_never_wins(self, api, self_review_attempt):
        """
        The same representative is also the designee, whose distinct refusal
        "`ERR_REVIEWER_IS_DESIGNATED_REPRESENTATIVE`" sits in the later
        "**Band 7 — referential agreement between two rows that already exist.**",
        so the segregation band is reported instead.

        Design: Difficulty/priority_pair_validation_conflict/submit_for_review_naming_preparer_who_is_also_designee_returns_segregation_of_duties
        """
        response = api.claim_transition(
            self_review_attempt["claim_id"],
            submit_for_review_action(self_review_attempt["preparer"]["id"]),
            self_review_attempt["officer_headers"],
        )
        error = validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 409)
        assert error["error_id"] != "ERR_REVIEWER_IS_DESIGNATED_REPRESENTATIVE"

    def test_the_refused_claim_keeps_its_status_and_gains_no_reviewer(
        self, api, self_review_attempt
    ):
        """
        Nothing is written on refusal, so the claim is still where
        "**Submitting for peer review** (`SUBMIT_FOR_REVIEW`) is available only from `EVIDENCE_DEVELOPMENT` and is where segregation of duties bites".

        Design: Difficulty/priority_pair_validation_conflict/submit_for_review_naming_preparer_who_is_also_designee_returns_segregation_of_duties
        """
        api.claim_transition(
            self_review_attempt["claim_id"],
            submit_for_review_action(self_review_attempt["preparer"]["id"]),
            self_review_attempt["officer_headers"],
        )
        claim = read_claim(
            api, self_review_attempt["claim_id"], self_review_attempt["officer_headers"]
        )
        assert claim["status"] == "EVIDENCE_DEVELOPMENT"
        assert claim["peer_reviewed_by_representative_id"] is None
