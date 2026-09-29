"""Non-linear lifecycles across the settlement, claim and peer review workflows.

Covers the cyclic settlement negotiation that loops back through committee
authority after a physician's veto, the claim that walks its handling axis while
its coverage axis holds a reservation of rights, and the peer review case whose
two review tracks must both land before the committee may vote.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import assert_money, assert_ratio
from test_helpers.constants import CLOCK_EPOCH, OPERATOR_IDS
from test_helpers.test_users import TEST_USERS

UW = TEST_USERS["underwriting_officer_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
APPROVER = TEST_USERS["claims_committee_approver_headers"]
CHAIR = TEST_USERS["peer_review_chair_headers"]


# --------------------------------------------------------------------------
# Composite books built from the public endpoints only.
# --------------------------------------------------------------------------
def _obstetrics_live_book(api, **policy_overrides):
    """Obstetrics rate manual, credentialed Cook County physician, claims-made
    policy and one live term running 2026-08-01 to 2027-08-01."""
    fixtures.advance_clock(api, CLOCK_EPOCH)
    specialty = fixtures.build_specialty_class(api)
    insured = fixtures.build_credentialed_insured(api, specialty["id"])
    policy = fixtures.build_policy(api, insured["id"], **policy_overrides)
    term = fixtures.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    term = fixtures.issue_term(api, term["id"])
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": term,
    }


def _round_one_vetoed_under_absolute_consent(api):
    """A litigated claim whose first offer of 400000.00 was authorised at
    450000.00, tendered under an absolute consent clause and vetoed."""
    book = _obstetrics_live_book(api, consent_to_settle_clause="ABSOLUTE")
    claim = fixtures.build_litigated_claim(
        api, book["insured"]["id"], suit_filed_on="2026-09-15",
        incident_date="2026-08-05", report_date="2026-09-01",
        venue_code="COOK_IL", allegation_category="OBSTETRIC_INJURY",
        demand_amount=800000.00,
    )
    negotiation = fixtures.open_negotiation(
        api, claim["id"], proposed_amount=400000.00,
        authority_requested=450000.00, headers=ADJ,
    )
    fixtures.decide_authority(
        api, negotiation["id"], "GRANT", 450000.00, headers=APPROVER,
    )
    fixtures.request_consent(api, negotiation["id"])
    fixtures.respond_to_consent(
        api, negotiation["id"], book["insured"]["id"],
        "VETOED", "reputational exposure",
    )
    book["claim"] = claim
    book["negotiation"] = negotiation
    return book


def _intake_claim_awaiting_a_coverage_position(api):
    """A live obstetrics book carrying one surgical-error claim still in intake
    with its coverage position undecided."""
    book = _obstetrics_live_book(api)
    claim = fixtures.build_claim(
        api, book["insured"]["id"],
        incident_date="2026-08-05", report_date="2026-09-01",
        venue_code="COOK_IL", allegation_category="SURGICAL_ERROR",
        demand_amount=800000.00,
    )
    book["claim"] = claim
    return book


def _referred_case_over_a_draft_quote(api):
    """An uncredentialed prospect carrying one unissued DRAFT term and one
    sentinel-event peer review referral with neither track recorded."""
    fixtures.advance_clock(api, CLOCK_EPOCH)
    specialty = fixtures.build_specialty_class(api)
    insured = fixtures.build_insured(api, specialty["id"])
    policy = fixtures.build_policy(api, insured["id"])
    term = fixtures.build_term(api, policy["id"], "2026-08-01", "2027-08-01")
    case = fixtures.build_peer_review_case(
        api, insured["id"], trigger_source="SENTINEL_EVENT",
        referral_note="retained sponge after delivery",
    )
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": term,
        "case": case,
    }


class TestNegotiationVetoRevisionCycle:
    """A vetoed offer loops back to committee authority as a second round."""

    def test_revision_bumps_the_round_and_wipes_the_veto(self, api):
        """Revising the vetoed offer takes the round index from one to two and
        clears the physician's response and reason.

        PRD: "A revision increments `round_index` by 1, overwrites both amounts
        with the submitted values, resets `authority_granted`,
        `approved_by_user_id`, `physician_response` and `veto_reason` to null, and
        sets `prepared_by_user_id` to the revising `X-User-ID` — which means the
        segregation-of-duties test on the next authority decision is measured
        against the reviser, not the original preparer, and the approver who
        legitimately decided round one may be locked out of round two if it was
        that approver who revised."

        Design: Difficulty/non_linear_state_machine/negotiation_veto_revision_cycle_reopens_authority_and_bumps_round_index
        """
        book = _round_one_vetoed_under_absolute_consent(api)

        revised = fixtures.revise_negotiation(
            api, book["negotiation"]["id"],
            proposed_amount=350000.00, authority_requested=380000.00,
        )
        assert revised["round_index"] == 2
        assert_money(revised["proposed_amount"], 350000.00, "proposed_amount")
        assert_money(revised["authority_requested"], 380000.00, "authority_requested")
        assert revised["authority_granted"] is None
        assert revised["approved_by_user_id"] is None
        assert revised["physician_response"] is None
        assert revised["veto_reason"] is None

    def test_revision_returns_the_offer_to_the_authority_queue(self, api):
        """The revised offer sits in AUTHORITY_REQUESTED again, the state it
        already occupied in round one.

        PRD: "The negotiation is **cyclic**: a `ClaimsAdjuster` revises it from
        either `VETOED` or `AUTHORITY_DENIED` back to `AUTHORITY_REQUESTED`,
        supplying a fresh `proposed_amount` and `authority_requested`."

        Design: Difficulty/non_linear_state_machine/negotiation_veto_revision_cycle_reopens_authority_and_bumps_round_index
        """
        book = _round_one_vetoed_under_absolute_consent(api)

        vetoed = validate_success(
            api.get_settlement_negotiation(book["negotiation"]["id"], ADJ)
        )
        assert vetoed["status"] == "VETOED"
        revised = fixtures.revise_negotiation(
            api, book["negotiation"]["id"],
            proposed_amount=350000.00, authority_requested=380000.00,
        )
        assert revised["status"] == "AUTHORITY_REQUESTED"

    def test_second_authority_grant_records_the_new_amount(self, api):
        """The committee grants 380000.00 on the reopened round and the
        negotiation lands back in AUTHORITY_GRANTED.

        PRD: "`AUTHORITY_REQUESTED` → `AUTHORITY_GRANTED` records
        `authority_granted` and `approved_by_user_id`; `AUTHORITY_REQUESTED` →
        `AUTHORITY_DENIED` records `approved_by_user_id` and leaves
        `authority_granted` null."

        Design: Difficulty/non_linear_state_machine/negotiation_veto_revision_cycle_reopens_authority_and_bumps_round_index
        """
        book = _round_one_vetoed_under_absolute_consent(api)

        fixtures.revise_negotiation(
            api, book["negotiation"]["id"],
            proposed_amount=350000.00, authority_requested=380000.00,
        )
        granted = fixtures.decide_authority(
            api, book["negotiation"]["id"], "GRANT", 380000.00, headers=APPROVER,
        )
        assert granted["status"] == "AUTHORITY_GRANTED"
        assert granted["round_index"] == 2
        assert_money(granted["authority_granted"], 380000.00, "authority_granted")

    def test_frozen_consent_clause_survives_the_whole_loop(self, api):
        """The negotiation still carries the absolute consent right it copied at
        creation after a full veto-and-revision circuit.

        PRD: "Crucially, `consent_clause_applied` is frozen at creation from the
        responding policy's `consent_to_settle_clause`, so the negotiation carries
        its own copy of the physician's consent right for its whole life and is
        unaffected by anything later done to the policy record."

        Design: Difficulty/non_linear_state_machine/negotiation_veto_revision_cycle_reopens_authority_and_bumps_round_index
        """
        book = _round_one_vetoed_under_absolute_consent(api)

        fixtures.revise_negotiation(
            api, book["negotiation"]["id"],
            proposed_amount=350000.00, authority_requested=380000.00,
        )
        fixtures.decide_authority(
            api, book["negotiation"]["id"], "GRANT", 380000.00, headers=APPROVER,
        )
        negotiation = validate_success(
            api.get_settlement_negotiation(book["negotiation"]["id"], ADJ)
        )
        assert negotiation["consent_clause_applied"] == "ABSOLUTE"

    def test_claim_stays_in_litigation_throughout_the_cycle(self, api):
        """The claim is still in LITIGATION, the handling state that entitles the
        adjuster to revise the offer at all.

        PRD: "The claim itself must still be in `INVESTIGATION` or `LITIGATION`."

        Design: Difficulty/non_linear_state_machine/negotiation_veto_revision_cycle_reopens_authority_and_bumps_round_index
        """
        book = _round_one_vetoed_under_absolute_consent(api)

        fixtures.revise_negotiation(
            api, book["negotiation"]["id"],
            proposed_amount=350000.00, authority_requested=380000.00,
        )
        claim = validate_success(api.get_claim(book["claim"]["id"], ADJ))
        assert claim["claim_status"] == "LITIGATION"


class TestClaimAxesAdvanceIndependently:
    """The handling axis walks on while the coverage axis holds its reservation."""

    RESERVATION = "late notice of incident under investigation"

    def test_reserving_rights_still_advances_the_handling_axis(self, api):
        """Taking a reservation of rights moves the file out of intake into
        investigation just as a full grant of cover would.

        PRD: "All three outcomes advance the handling axis `INTAKE` →
        `INVESTIGATION`, including a denial: coverage may be refused while the
        file still has to be worked."

        Design: Difficulty/non_linear_state_machine/claim_handling_axis_advances_while_coverage_axis_holds_reserved_rights
        """
        book = _intake_claim_awaiting_a_coverage_position(api)

        claim = fixtures.decide_coverage(
            api, book["claim"]["id"], "RESERVED_RIGHTS", self.RESERVATION
        )
        assert claim["claim_status"] == "INVESTIGATION"
        assert claim["coverage_status"] == "RESERVED_RIGHTS"

    def test_reservation_narrative_is_recorded_without_a_denial_reason(self, api):
        """The adjuster's narrative is kept on the claim and no denial reason is
        written, the position being a reservation rather than a refusal.

        PRD: "The submitted `coverage_status` is `COVERED`, `RESERVED_RIGHTS` or
        `DENIED`, with an optional `reserved_rights_reason` narrative that is
        recorded when the position taken is `RESERVED_RIGHTS`."

        Design: Difficulty/non_linear_state_machine/claim_handling_axis_advances_while_coverage_axis_holds_reserved_rights
        """
        book = _intake_claim_awaiting_a_coverage_position(api)

        claim = fixtures.decide_coverage(
            api, book["claim"]["id"], "RESERVED_RIGHTS", self.RESERVATION
        )
        assert claim["reserved_rights_reason"] == self.RESERVATION
        assert claim["denial_reason"] is None

    def test_suit_filing_leaves_the_coverage_position_untouched(self, api):
        """The claim litigates under the reservation: the handling axis reaches
        LITIGATION while the coverage axis and its narrative are unchanged.

        PRD: "`INVESTIGATION` → `LITIGATION` records the filing date and leaves
        `coverage_status` exactly as it was — a claim may litigate under a
        reservation of rights, and the two axes never move each other here."

        Design: Difficulty/non_linear_state_machine/claim_handling_axis_advances_while_coverage_axis_holds_reserved_rights
        """
        book = _intake_claim_awaiting_a_coverage_position(api)

        fixtures.decide_coverage(
            api, book["claim"]["id"], "RESERVED_RIGHTS", self.RESERVATION
        )
        claim = validate_success(api.record_litigation(
            book["claim"]["id"], factories.litigation_payload("2026-09-20"), ADJ
        ))
        assert claim["claim_status"] == "LITIGATION"
        assert claim["coverage_status"] == "RESERVED_RIGHTS"
        assert claim["reserved_rights_reason"] == self.RESERVATION
        assert claim["suit_filed_on"] == "2026-09-20"

    def test_responding_term_resolved_at_intake_survives_both_moves(self, api):
        """The single live term stays the responding term through the coverage
        position and the suit filing.

        PRD: "If at least one term responds and the incident is not excluded by
        the retroactive date, `policy_term_id` names the responding term with the
        latest `effective_date`, ties broken by the earlier creation timestamp,
        and `coverage_status` is `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/claim_handling_axis_advances_while_coverage_axis_holds_reserved_rights
        """
        book = _intake_claim_awaiting_a_coverage_position(api)

        assert book["claim"]["policy_term_id"] == book["term"]["id"]
        assert book["claim"]["coverage_status"] == "UNDER_REVIEW"
        fixtures.decide_coverage(
            api, book["claim"]["id"], "RESERVED_RIGHTS", self.RESERVATION
        )
        claim = validate_success(api.record_litigation(
            book["claim"]["id"], factories.litigation_payload("2026-09-20"), ADJ
        ))
        assert claim["policy_term_id"] == book["term"]["id"]

    def test_reserved_rights_claim_still_counts_as_open_exposure(self, api):
        """The litigating claim counts as one open claim on the insured, its
        coverage position being something other than a denial.

        PRD: "`open_claim_count` is the number whose handling status is `INTAKE`,
        `INVESTIGATION` or `LITIGATION` and whose coverage position is anything
        other than `DENIED`."

        Design: Difficulty/non_linear_state_machine/claim_handling_axis_advances_while_coverage_axis_holds_reserved_rights
        """
        book = _intake_claim_awaiting_a_coverage_position(api)

        fixtures.decide_coverage(
            api, book["claim"]["id"], "RESERVED_RIGHTS", self.RESERVATION
        )
        validate_success(api.record_litigation(
            book["claim"]["id"], factories.litigation_payload("2026-09-20"), ADJ
        ))
        insured = validate_success(api.get_insured(book["insured"]["id"], UW))
        assert insured["open_claim_count"] == 1


class TestPeerReviewForkJoin:
    """Both review tracks must land before the committee may vote."""

    def test_vote_from_referred_is_refused_before_either_track_lands(self, api):
        """A committee vote attempted on a freshly referred case is refused,
        because neither branch of the fork has been worked.

        PRD: "The vote must carry a majority — `votes_for` strictly greater than
        `votes_against` — or it is refused with `ERR_VALIDATION`; a vote submitted
        from any status other than `REVIEWS_COMPLETE` is refused with
        `ERR_PEER_REVIEW_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/peer_review_fork_join_requires_both_tracks_before_committee_vote
        """
        book = _referred_case_over_a_draft_quote(api)

        validate_error(
            api.record_committee_vote(
                book["case"]["id"],
                factories.committee_vote_payload("DEVIATION_MINOR", 5, 2),
                CHAIR,
            ),
            "ERR_PEER_REVIEW_STATE_INVALID",
            409,
        )
        case = validate_success(api.get_peer_review_case(book["case"]["id"], CHAIR))
        assert case["status"] == "REFERRED"

    def test_first_track_forks_the_case_into_review(self, api):
        """Recording the chart track alone moves the case into IN_REVIEW with only
        that track's outcome written.

        PRD: "The first track recorded moves the case `REFERRED` → `IN_REVIEW`."

        Design: Difficulty/non_linear_state_machine/peer_review_fork_join_requires_both_tracks_before_committee_vote
        """
        book = _referred_case_over_a_draft_quote(api)

        case = validate_success(api.record_review_track(
            book["case"]["id"],
            factories.review_track_payload("CHART", "CONCERN"),
            CHAIR,
        ))
        assert case["status"] == "IN_REVIEW"
        assert case["chart_review_outcome"] == "CONCERN"
        assert case["external_review_outcome"] is None

    def test_second_track_joins_the_fork(self, api):
        """The external track landing second carries the case to REVIEWS_COMPLETE
        with both outcomes on the record.

        PRD: "The second moves it `IN_REVIEW` → `REVIEWS_COMPLETE`, the join at
        which both tracks have landed."

        Design: Difficulty/non_linear_state_machine/peer_review_fork_join_requires_both_tracks_before_committee_vote
        """
        book = _referred_case_over_a_draft_quote(api)

        validate_success(api.record_review_track(
            book["case"]["id"],
            factories.review_track_payload("CHART", "CONCERN"),
            CHAIR,
        ))
        case = validate_success(api.record_review_track(
            book["case"]["id"],
            factories.review_track_payload("EXTERNAL", "CONCERN"),
            CHAIR,
        ))
        assert case["status"] == "REVIEWS_COMPLETE"
        assert case["chart_review_outcome"] == "CONCERN"
        assert case["external_review_outcome"] == "CONCERN"

    def test_vote_after_the_join_closes_the_case_and_freezes_the_surcharge(self, api):
        """The majority vote for a minor deviation closes the case, records the
        chair and the counts, and freezes the surcharge at ten percent.

        PRD: "`REVIEWS_COMPLETE` → `CLOSED` records the verdict, the two vote
        counts and the chair's `chair_user_id`, freezes `surcharge_pct_assigned`
        at the surcharge published for that verdict, and sets `closed_on` to the
        current logical date."

        Design: Difficulty/non_linear_state_machine/peer_review_fork_join_requires_both_tracks_before_committee_vote
        """
        book = _referred_case_over_a_draft_quote(api)

        validate_success(api.record_review_track(
            book["case"]["id"],
            factories.review_track_payload("CHART", "CONCERN"),
            CHAIR,
        ))
        validate_success(api.record_review_track(
            book["case"]["id"],
            factories.review_track_payload("EXTERNAL", "CONCERN"),
            CHAIR,
        ))
        case = validate_success(api.record_committee_vote(
            book["case"]["id"],
            factories.committee_vote_payload("DEVIATION_MINOR", 5, 2),
            CHAIR,
        ))
        assert case["status"] == "CLOSED"
        assert case["committee_vote_result"] == "DEVIATION_MINOR"
        assert case["votes_for"] == 5
        assert case["votes_against"] == 2
        assert case["chair_user_id"] == OPERATOR_IDS["PeerReviewChair"]
        assert_ratio(
            case["surcharge_pct_assigned"], 0.10, "surcharge_pct_assigned"
        )

    def test_closed_minor_deviation_publishes_a_ten_percent_position(self, api):
        """The insured's surcharge position becomes the ten percent published for
        a minor deviation, its only closed case in the window.

        PRD: "Surcharges do not stack: where several closed cases fall inside the
        window, the position is the greatest of their surcharge percentages, which
        are zero percent for `NO_DEVIATION`, ten percent for `DEVIATION_MINOR` and
        twenty-five percent for `DEVIATION_MAJOR`."

        Design: Difficulty/non_linear_state_machine/peer_review_fork_join_requires_both_tracks_before_committee_vote
        """
        book = _referred_case_over_a_draft_quote(api)

        validate_success(api.record_review_track(
            book["case"]["id"],
            factories.review_track_payload("CHART", "CONCERN"),
            CHAIR,
        ))
        validate_success(api.record_review_track(
            book["case"]["id"],
            factories.review_track_payload("EXTERNAL", "CONCERN"),
            CHAIR,
        ))
        validate_success(api.record_committee_vote(
            book["case"]["id"],
            factories.committee_vote_payload("DEVIATION_MINOR", 5, 2),
            CHAIR,
        ))
        insured = validate_success(api.get_insured(book["insured"]["id"], UW))
        assert_ratio(insured["surcharge_pct"], 0.10, "surcharge_pct")

    def test_closing_cascade_reprices_the_draft_quote(self, api):
        """The close restacks the surcharge onto the unissued DRAFT term, lifting
        its net premium to 21213.50 and the policy's quoted total to 21731.79
        while the prospect is left unsuspended.

        PRD: "It then recomputes the insured's `surcharge_pct`, re-rates every
        `DRAFT` term on the insured's policies, recomputes each affected policy's
        `quoted_premium_total`, and — when the verdict is `DEVIATION_MAJOR` and
        the insured's underwriting status is `ACTIVE` — suspends the insured."

        Design: Difficulty/non_linear_state_machine/peer_review_fork_join_requires_both_tracks_before_committee_vote
        """
        book = _referred_case_over_a_draft_quote(api)

        validate_success(api.record_review_track(
            book["case"]["id"],
            factories.review_track_payload("CHART", "CONCERN"),
            CHAIR,
        ))
        validate_success(api.record_review_track(
            book["case"]["id"],
            factories.review_track_payload("EXTERNAL", "CONCERN"),
            CHAIR,
        ))
        validate_success(api.record_committee_vote(
            book["case"]["id"],
            factories.committee_vote_payload("DEVIATION_MINOR", 5, 2),
            CHAIR,
        ))
        term = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert term["status"] == "DRAFT"
        assert_ratio(
            term["surcharge_pct_applied"], 0.10, "surcharge_pct_applied"
        )
        assert_money(term["premium_manual"], 19285.00, "premium_manual")
        assert_money(term["premium_net"], 21213.50, "premium_net")
        assert_money(
            term["guaranty_fund_assessment"], 268.29, "guaranty_fund_assessment"
        )
        assert_money(term["term_total"], 21731.79, "term_total")
        policy = validate_success(api.get_policy(book["policy"]["id"], UW))
        assert_money(
            policy["quoted_premium_total"], 21731.79, "quoted_premium_total"
        )
        insured = validate_success(api.get_insured(book["insured"]["id"], UW))
        assert insured["status"] == "PROSPECT"
