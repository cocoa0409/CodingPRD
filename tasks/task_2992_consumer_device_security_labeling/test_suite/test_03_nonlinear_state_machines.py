"""State machines that are not linear chains.

The conformance assessment runs a bounded revision cycle whose exit is decided
by an accumulated counter rather than by the request, and the label grant
advances two independent status dimensions that no single status column could
express.
"""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    CONSUMER_HEADERS,
    DEFAULT_CLOCK,
    PUBLISHER,
    REVIEWER,
    REVIEWER_2_USER_ID,
    REVIEWER_3_USER_ID,
    REVIEWER_USER_ID,
    api_client,
    assert_grant_statuses,
    assert_instant_equals,
    assert_score,
    assert_status,
    canonical_instant,
    factories,
    fixtures,
    make_reviewer_headers,
    plus_days,
    validate_error,
    validate_success,
    validate_unpaginated,
)

REVIEWER_2 = make_reviewer_headers(REVIEWER_2_USER_ID)
REVIEWER_3 = make_reviewer_headers(REVIEWER_3_USER_ID)

DISPLAY_FROM = "2026-08-10T00:00:00Z"
DISPLAY_UNTIL = "2026-09-10T00:00:00Z"
WITHHOLD_CLOCK = "2026-08-05T00:00:00Z"


def _under_review_speaker_claim():
    """A self-attested speaker claim at UNDER_REVIEW under max_deficiency_rounds 2."""
    fixtures.set_clock(DEFAULT_CLOCK)
    return fixtures.submitted_claim(required_route="SELF_ATTESTATION")


def _resubmit(claim, note):
    """Revise a deficient assessment, returning it to UNDER_REVIEW."""
    response = api_client.resubmit_assessment(
        claim.assessment_id,
        factories.resubmit_payload(resubmission_note=note),
        claim.sponsor.headers,
    )
    claim.assessment = validate_success(response, 201)
    return claim.assessment


def _resubmit_response(claim, note):
    """The raw resubmission response, for the state gate that refuses it."""
    return api_client.resubmit_assessment(
        claim.assessment_id,
        factories.resubmit_payload(resubmission_note=note),
        claim.sponsor.headers,
    )


def _two_rounds_spent(claim):
    """Drive the loop through both permitted deficiency rounds."""
    fixtures.decide_claim(claim, "DEFICIENT", REVIEWER)
    _resubmit(claim, "Round 1 remediation: attached signed build manifest.")
    fixtures.decide_claim(claim, "DEFICIENT", REVIEWER_2)
    _resubmit(claim, "Round 2 remediation: cadence documented.")
    return claim.assessment


def _published_grant_with_online_display():
    """A live label with one AUTHORIZED online display, clock then at 2026-08-05."""
    fixtures.set_clock(DEFAULT_CLOCK)
    program = fixtures.create_program("SELF_ATTESTATION")
    sponsor = fixtures.enrol_manufacturer()
    store = fixtures.register_retailer(retailer_name="Cedar Home Retail")
    grant = fixtures.published_grant(
        fixtures.approved_claim(program=program, sponsor=sponsor)
    )
    authorization = fixtures.authorize_display(
        grant,
        store,
        channel="ONLINE",
        display_from=DISPLAY_FROM,
        display_until=DISPLAY_UNTIL,
    )
    fixtures.set_clock(WITHHOLD_CLOCK)
    return grant, store, authorization


def _registry_entry(grant):
    entries = validate_unpaginated(api_client.get_registry_entry(grant.id, ADMIN))
    assert len(entries) == 1, f"expected exactly one registry entry, got {entries}"
    return entries[0]


class TestAssessmentDeficiencyRevisionCycle:
    """UNDER_REVIEW -> DEFICIENT -> UNDER_REVIEW twice, then a different exit."""

    def test_a_deficiency_within_the_budget_returns_the_claim_for_revision(self):
        """Rounds 1 and 2 both land in DEFICIENT and name the finding reviewer.

        PRD: "If the value of `deficiency_round` after that increment is less than or equal to the tier's `max_deficiency_rounds`, the assessment moves `UNDER_REVIEW → DEFICIENT` and the manufacturer may revise it."
        Design: Difficulty/non_linear_state_machine/assessment_deficiency_revision_cycle
        """
        claim = _under_review_speaker_claim()

        first = fixtures.decide_claim(claim, "DEFICIENT", REVIEWER)
        assert_status(first, "status", "DEFICIENT")
        assert first["deficiency_round"] == 1, first["deficiency_round"]
        assert_status(first, "last_deficiency_by_user_id", REVIEWER_USER_ID)

        _resubmit(claim, "Round 1 remediation: attached signed build manifest.")
        second = fixtures.decide_claim(claim, "DEFICIENT", REVIEWER_2)
        assert_status(second, "status", "DEFICIENT")
        assert second["deficiency_round"] == 2, second["deficiency_round"]
        assert_status(second, "last_deficiency_by_user_id", REVIEWER_2_USER_ID)

    def test_a_revision_returns_the_claim_without_spending_the_counter(self):
        """The budget accumulates across the life of the assessment, not per round.

        PRD: "One thing is deliberately *not* reset: `deficiency_round` keeps its accumulated value, so the deficiency budget is spent across the whole life of the assessment rather than per round."
        Design: Difficulty/non_linear_state_machine/assessment_deficiency_revision_cycle
        """
        claim = _under_review_speaker_claim()

        fixtures.decide_claim(claim, "DEFICIENT", REVIEWER)
        revised = _resubmit(claim, "Round 1 remediation: attached signed build manifest.")
        assert_status(revised, "status", "UNDER_REVIEW")
        assert revised["deficiency_round"] == 1, revised["deficiency_round"]

        fixtures.decide_claim(claim, "DEFICIENT", REVIEWER_2)
        after_two = _resubmit(claim, "Round 2 remediation: cadence documented.")
        assert_status(after_two, "status", "UNDER_REVIEW")
        assert after_two["deficiency_round"] == 2, after_two["deficiency_round"]
        assert_score(after_two["decided_overall_score"], 80.80, "decided_overall_score")

    def test_the_third_deficiency_finding_rejects_instead_of_looping(self):
        """The same trigger resolves to REJECTED once the budget is exhausted.

        PRD: "If the incremented value instead exceeds `max_deficiency_rounds`, the assessment moves `UNDER_REVIEW → REJECTED` rather than to `DEFICIENT`, terminating the revision loop automatically — the increment still happens, so the recorded `deficiency_round` reflects the finding that ended the claim, and no further revision is possible."
        Design: Difficulty/non_linear_state_machine/assessment_deficiency_revision_cycle
        """
        claim = _under_review_speaker_claim()
        _two_rounds_spent(claim)

        third = fixtures.decide_claim(claim, "DEFICIENT", REVIEWER_3)

        assert_status(third, "status", "REJECTED")
        assert third["status"] != "DEFICIENT", third["status"]
        assert third["deficiency_round"] == 3, third["deficiency_round"]
        assert_status(third, "last_deficiency_by_user_id", REVIEWER_3_USER_ID)
        assert_score(third["decided_overall_score"], 80.80, "decided_overall_score")

    def test_a_revision_after_the_loop_terminated_is_refused(self):
        """A fourth revision attempt on the rejected claim is a state error.

        PRD: "The target assessment's `status` admits the requested transition — otherwise `ERR_INVALID_ASSESSMENT_STATE`."
        Design: Difficulty/non_linear_state_machine/assessment_deficiency_revision_cycle
        """
        claim = _under_review_speaker_claim()
        _two_rounds_spent(claim)
        fixtures.decide_claim(claim, "DEFICIENT", REVIEWER_3)

        response = _resubmit_response(
            claim, "Attempted fourth revision after the loop terminated."
        )

        validate_error(response, ApiErrorId.ERR_INVALID_ASSESSMENT_STATE.value)
        unchanged = claim.refresh_assessment()
        assert_status(unchanged, "status", "REJECTED")
        assert unchanged["deficiency_round"] == 3, unchanged["deficiency_round"]


class TestLabelGrantParallelStatusDimensions:
    """The publication dimension moves while the grant dimension stands still."""

    def test_withholding_the_entry_leaves_the_grant_active_and_the_display_authorized(self):
        """Publication drops to WITHHELD; grant_status and the retailer are untouched.

        PRD: "Critically, withholding does **not** touch `grant_status`, and it does **not** withdraw any retailer display authorization, because display gating reads `grant_status` alone."
        Design: Difficulty/non_linear_state_machine/label_grant_parallel_status_dimensions
        """
        grant, store, authorization = _published_grant_with_online_display()

        withheld = fixtures.decide_publication(grant, "WITHHELD", PUBLISHER)

        assert_grant_statuses(withheld, "ACTIVE", "WITHHELD")
        assert withheld["suspension_reason"] is None, withheld["suspension_reason"]
        held = validate_success(
            api_client.get_display_authorization(authorization["id"], store.headers)
        )
        assert_status(held, "status", "AUTHORIZED")
        retailer = store.refresh()
        assert retailer["active_display_count"] == 1, retailer["active_display_count"]

    def test_republication_keeps_the_original_published_at_and_validity_window(self):
        """The second PUBLISHED decision at 2026-08-05 re-stamps nothing.

        PRD: "A withheld entry can be published again, driving `WITHHELD → PUBLISHED` and re-resolving the public page; on that second and any later publication `published_at` and `published_by_user_id` keep their original first-publication values rather than being re-stamped, and `valid_from` and `valid_until` are likewise not recomputed."
        Design: Difficulty/non_linear_state_machine/label_grant_parallel_status_dimensions
        """
        grant, _store, _authorization = _published_grant_with_online_display()
        assert_instant_equals(_registry_entry(grant)["published_at"], DEFAULT_CLOCK, "published_at")

        fixtures.decide_publication(grant, "WITHHELD", PUBLISHER)
        republished = fixtures.decide_publication(grant, "PUBLISHED", PUBLISHER)

        assert_grant_statuses(republished, "ACTIVE", "PUBLISHED")
        entry = _registry_entry(grant)
        assert_instant_equals(entry["published_at"], DEFAULT_CLOCK, "published_at")
        assert canonical_instant(entry["published_at"]) != canonical_instant(WITHHOLD_CLOCK), (
            "published_at must not be re-stamped from the moved clock"
        )
        assert_status(entry, "published_by_user_id", REVIEWER_2_USER_ID)
        assert_instant_equals(republished["valid_from"], DEFAULT_CLOCK, "valid_from")
        assert_instant_equals(
            republished["valid_until"], plus_days(DEFAULT_CLOCK, 365), "valid_until"
        )

    def test_the_public_page_stops_resolving_while_withheld_and_returns_after(self):
        """A withheld code is indistinguishable from an unknown one, then resolves again.

        PRD: "From `PUBLISHED` it drives `PUBLISHED → WITHHELD`, and the public registry lookup for that `scannable_code` stops resolving, returning `ERR_REGISTRY_CODE_NOT_FOUND` exactly as if the code had never existed."
        Design: Difficulty/non_linear_state_machine/label_grant_parallel_status_dimensions
        """
        grant, _store, _authorization = _published_grant_with_online_display()
        code = grant.scannable_code

        fixtures.decide_publication(grant, "WITHHELD", PUBLISHER)
        blocked = api_client.scan_registry(code, CONSUMER_HEADERS)

        validate_error(blocked, ApiErrorId.ERR_REGISTRY_CODE_NOT_FOUND.value)

        fixtures.decide_publication(grant, "PUBLISHED", PUBLISHER)
        page = validate_success(api_client.scan_registry(code, CONSUMER_HEADERS))
        assert page["scannable_code"] == code, page["scannable_code"]
        assert_status(page, "grant_status", "ACTIVE")
