"""Closed and half-open coverage intervals, and the unwinds that must not drift.

Covers the half-open term period against the closed tail reporting window
(PRD 3.5), then the two compensating movements that have to leave no residue:
a declined counsel assignment returning a firm's capacity counter (PRD 3.7)
and a flat cancellation reversing the premium ledger and the cover the term
granted (PRD 3.5, 3.6).
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions, factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import (
    advance_clock,
    assign_counsel,
    build_claim,
    build_counsel_firm,
    build_credentialed_insured,
    build_policy,
    build_specialty_class,
    build_term,
    decide_coverage,
    decline_assignment,
    issue_term,
)

FIRST_EFFECTIVE = "2026-08-01"
FIRST_EXPIRATION = "2027-08-01"
RENEWAL_EXPIRATION = "2028-08-01"
EXPIRY_INSTANT = "2027-08-01T00:00:00Z"


def _live_first_term_book(api, headers):
    """A rated class, a credentialed insured and one IN_FORCE first term."""
    advance_clock(api, CLOCK_EPOCH)
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"], retroactive_date=FIRST_EFFECTIVE)
    term = build_term(api, policy["id"], effective_date=FIRST_EFFECTIVE,
                      expiration_date=FIRST_EXPIRATION)
    issue_term(api, term["id"])
    return insured, validate_success(api.get_policy(policy["id"], headers)), term


def _renew_on_the_expiration_date(api, policy_id, predecessor_term_id):
    """The renewal that starts exactly where the expiring term stops."""
    return build_term(api, policy_id, effective_date=FIRST_EXPIRATION,
                      expiration_date=RENEWAL_EXPIRATION,
                      predecessor_term_id=predecessor_term_id)


class TestAdjacentAndStraddlingTermPeriods:
    """A shared boundary date is adjacency; a genuine intersection is a conflict."""

    def test_a_renewal_starting_on_the_prior_expiration_is_accepted_as_adjacent(
        self, api, underwriting_officer_headers
    ):
        """Because the period stops short of its expiration date, the renewal fits.

        PRD: "Independently, the new term's half-open period must not intersect the period of any existing term on the same policy whose status is not `CANCELLED_FLAT`; sharing a single boundary date is legal adjacency, while a genuine intersection is refused with `ERR_TERM_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/adjacent_term_periods_pass_while_a_straddling_third_term_conflicts
        """
        _insured, policy, first_term = _live_first_term_book(
            api, underwriting_officer_headers
        )

        renewal = _renew_on_the_expiration_date(api, policy["id"], first_term["id"])

        assert renewal["effective_date"] == FIRST_EXPIRATION
        assert renewal["expiration_date"] == RENEWAL_EXPIRATION
        assert renewal["status"] == "DRAFT"
        assertions.assert_policy_term(renewal)

    def test_the_adjacent_renewal_takes_the_next_index_and_the_renewal_variant(
        self, api, underwriting_officer_headers
    ):
        """Naming a predecessor makes the renewal term two on a prospective rating.

        PRD: "`rating_variant` follows from the same fact: a first term with no predecessor is rated `UNDERWRITING_SNAPSHOT`, and a term with a predecessor is rated `RENEWAL_PROSPECTIVE`."

        Design: Difficulty/resource_temporal_overlap/adjacent_term_periods_pass_while_a_straddling_third_term_conflicts
        """
        _insured, policy, first_term = _live_first_term_book(
            api, underwriting_officer_headers
        )

        renewal = _renew_on_the_expiration_date(api, policy["id"], first_term["id"])

        assert renewal["term_index"] == 2
        assert renewal["rating_variant"] == "RENEWAL_PROSPECTIVE"
        assert renewal["predecessor_term_id"] == first_term["id"]

    def test_the_adjacent_renewal_is_rated_at_the_step_two_factor(
        self, api, underwriting_officer_headers
    ):
        """A step-two renewal charges 33060.00 manual against the 0.60 factor.

        PRD: "First the step position: on a claims-made policy, `claims_made_step_year` is the lesser of 5 and the sum of the term's `term_index` and the policy's `prior_acts_step_credit`, and `step_factor` is the factor published for that step year — 0.35 for step 1, 0.60 for step 2, 0.80 for step 3, 0.92 for step 4 and 1.00 for step 5."

        Design: Difficulty/resource_temporal_overlap/adjacent_term_periods_pass_while_a_straddling_third_term_conflicts
        """
        _insured, policy, first_term = _live_first_term_book(
            api, underwriting_officer_headers
        )

        renewal = _renew_on_the_expiration_date(api, policy["id"], first_term["id"])

        assert renewal["claims_made_step_year"] == 2
        assert float(renewal["step_factor"]) == 0.60
        assertions.assert_money(renewal["premium_manual"], 33060.00,
                                "premium_manual")
        assertions.assert_money(renewal["premium_net"], 33060.00, "premium_net")

    def test_the_adjacent_renewal_climbs_into_the_middle_fee_tier(
        self, api, underwriting_officer_headers
    ):
        """At 33060.00 net the flat fee is 500.00 and the assessment 419.50.

        PRD: "`guaranty_fund_assessment` is one and a quarter percent of the sum of `premium_net` and `administrative_fee`, rounded half up to two decimal places."

        Design: Difficulty/resource_temporal_overlap/adjacent_term_periods_pass_while_a_straddling_third_term_conflicts
        """
        _insured, policy, first_term = _live_first_term_book(
            api, underwriting_officer_headers
        )

        renewal = _renew_on_the_expiration_date(api, policy["id"], first_term["id"])

        assertions.assert_money(renewal["administrative_fee"], 500.00,
                                "administrative_fee")
        assertions.assert_money(renewal["guaranty_fund_assessment"], 419.50,
                                "guaranty_fund_assessment")
        assertions.assert_money(renewal["term_total"], 33979.50, "term_total")
        assertions.assert_fee_ladder(renewal)

    def test_a_third_term_starting_inside_the_renewal_period_is_refused(
        self, api, underwriting_officer_headers
    ):
        """A term inception of 2028-02-01 sits inside the renewal's live period.

        PRD: "Independently, the new term's half-open period must not intersect the period of any existing term on the same policy whose status is not `CANCELLED_FLAT`; sharing a single boundary date is legal adjacency, while a genuine intersection is refused with `ERR_TERM_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/adjacent_term_periods_pass_while_a_straddling_third_term_conflicts
        """
        _insured, policy, first_term = _live_first_term_book(
            api, underwriting_officer_headers
        )
        _renew_on_the_expiration_date(api, policy["id"], first_term["id"])

        current_version = validate_success(
            api.get_policy(policy["id"], underwriting_officer_headers)
        )["version"]
        response = api.create_policy_term(
            policy["id"],
            factories.policy_term_payload(
                effective_date="2028-02-01", expiration_date="2029-02-01",
                expected_policy_version=current_version,
            ),
            underwriting_officer_headers,
        )

        validate_error(response, ApiErrorId.ERR_TERM_PERIOD_OVERLAP.value, 409)

    def test_the_refused_third_term_leaves_the_policy_version_where_it_stood(
        self, api, underwriting_officer_headers
    ):
        """No version is consumed by a term that was never created.

        PRD: "Creating the term increments the policy's `version` by 1."

        Design: Difficulty/resource_temporal_overlap/adjacent_term_periods_pass_while_a_straddling_third_term_conflicts
        """
        _insured, policy, first_term = _live_first_term_book(
            api, underwriting_officer_headers
        )
        _renew_on_the_expiration_date(api, policy["id"], first_term["id"])

        version_before = validate_success(
            api.get_policy(policy["id"], underwriting_officer_headers)
        )["version"]
        api.create_policy_term(
            policy["id"],
            factories.policy_term_payload(
                effective_date="2028-02-01", expiration_date="2029-02-01",
                expected_policy_version=version_before,
            ),
            underwriting_officer_headers,
        )

        version_after = validate_success(
            api.get_policy(policy["id"], underwriting_officer_headers)
        )["version"]
        assert version_after == version_before


FIRST_WINDOW_END = "2032-07-31"
SECOND_WINDOW_END = "2037-07-31"


def _quote_five_year_tail(api, policy_id, term_id, effective_date, headers,
                          trigger_reason="PRACTICE_CLOSURE"):
    return api.create_tail_endorsement(
        policy_id,
        factories.tail_endorsement_payload(
            term_id, tail_type="ERP_5YR", trigger_reason=trigger_reason,
            effective_date=effective_date,
        ),
        headers,
    )


def _book_with_one_issued_five_year_tail(api, headers):
    """An expired first term carrying one ISSUED five-year reporting window."""
    _insured, policy, term = _live_first_term_book(api, headers)
    advance_clock(api, EXPIRY_INSTANT)
    quoted = validate_success(
        _quote_five_year_tail(api, policy["id"], term["id"], FIRST_EXPIRATION,
                              headers, trigger_reason="CARRIER_CHANGE"),
        201,
    )
    issued = validate_success(api.issue_tail_endorsement(quoted["id"], headers))
    return policy, validate_success(api.get_policy_term(term["id"], headers)), issued


class TestTailReportingWindowEndpoints:
    """The reporting window is closed, so even one shared date is an intersection."""

    def test_the_first_five_year_window_closes_one_day_short_of_five_years(
        self, api, underwriting_officer_headers
    ):
        """A window opening 2027-08-01 closes 2032-07-31 to span exactly five years.

        PRD: "`reporting_window_end` closes the window: for `ERP_5YR` it is five years after the `effective_date` less one day, so that the closed window spans exactly five years; for `ERP_UNLIMITED` and `DEATH_DISABILITY_RETIREMENT` it is `9999-12-31`, an effectively unlimited window."

        Design: Difficulty/resource_temporal_overlap/tail_reporting_windows_are_closed_intervals_so_touching_endpoints_conflict
        """
        _policy, term, tail = _book_with_one_issued_five_year_tail(
            api, underwriting_officer_headers
        )

        assert term["status"] == "EXPIRED"
        assert tail["effective_date"] == FIRST_EXPIRATION
        assert tail["reporting_window_end"] == FIRST_WINDOW_END
        assert tail["status"] == "ISSUED"
        assertions.assert_tail_endorsement(tail)

    def test_the_tail_premium_reconstructs_the_mature_step_five_basis(
        self, api, underwriting_officer_headers
    ):
        """Dividing the 0.35 step factor out of 19285.00 gives a 55100.00 basis.

        PRD: "`mature_premium_basis` is the triggering term's `premium_manual` divided by that term's `step_factor`, rounded half up to two decimal places — dividing the step factor out reconstructs the mature, step-five premium the term would have carried at full maturity."

        Design: Difficulty/resource_temporal_overlap/tail_reporting_windows_are_closed_intervals_so_touching_endpoints_conflict
        """
        _policy, _term, tail = _book_with_one_issued_five_year_tail(
            api, underwriting_officer_headers
        )

        assertions.assert_money(tail["mature_premium_basis"], 55100.00,
                                "mature_premium_basis")
        assert float(tail["tail_factor"]) == 1.55
        assertions.assert_money(tail["tail_premium"], 85405.00, "tail_premium")

    def test_a_second_window_sharing_the_closing_date_alone_still_conflicts(
        self, api, underwriting_officer_headers
    ):
        """A window opening on 2032-07-31 touches the live window's last day.

        PRD: "Finally, the new tail's closed window must not intersect the closed window of any `ISSUED` tail on the same policy; because both endpoints are inclusive, two windows sharing even a single date do intersect and the quote is refused with `ERR_TAIL_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/tail_reporting_windows_are_closed_intervals_so_touching_endpoints_conflict
        """
        policy, term, tail = _book_with_one_issued_five_year_tail(
            api, underwriting_officer_headers
        )
        assert tail["reporting_window_end"] == FIRST_WINDOW_END

        response = _quote_five_year_tail(
            api, policy["id"], term["id"], FIRST_WINDOW_END,
            underwriting_officer_headers,
        )

        validate_error(response, ApiErrorId.ERR_TAIL_WINDOW_OVERLAP.value, 409)

    def test_a_second_window_opening_the_day_after_the_close_is_quoted(
        self, api, underwriting_officer_headers
    ):
        """Opening 2032-08-01 clears the closed window by exactly one day.

        PRD: "An **extended reporting window** on a tail endorsement is closed at both ends: it runs from its effective date inclusive to its `reporting_window_end` inclusive."

        Design: Difficulty/resource_temporal_overlap/tail_reporting_windows_are_closed_intervals_so_touching_endpoints_conflict
        """
        policy, term, _tail = _book_with_one_issued_five_year_tail(
            api, underwriting_officer_headers
        )

        successor = validate_success(
            _quote_five_year_tail(api, policy["id"], term["id"], "2032-08-01",
                                  underwriting_officer_headers),
            201,
        )

        assert successor["effective_date"] == "2032-08-01"
        assert successor["reporting_window_end"] == SECOND_WINDOW_END
        assertions.assert_money(successor["tail_premium"], 85405.00, "tail_premium")
        assert successor["status"] == "QUOTED"


HALLORAN = {
    "firm_name": "Halloran Defense LLP",
    "admitted_venue_codes": ["COOK_IL"],
    "allegation_specialties": ["OBSTETRIC_INJURY"],
    "blended_hourly_rate": 500.00,
    "quality_score": 95,
    "max_concurrent_assignments": 5,
    "conflict_insured_ids": [],
}


def _covered_claim_with_counsel_assigned(api, headers):
    """One live term, one ACTIVE panel firm and one covered claim it defends."""
    insured, _policy, _term = _live_first_term_book(api, headers)
    firm = build_counsel_firm(api, **HALLORAN)
    claim = build_claim(api, insured["id"], incident_date="2026-08-05",
                        report_date="2026-09-01", demand_amount=800000.00)
    decide_coverage(api, claim["id"], "COVERED")
    assignment = assign_counsel(api, claim["id"])
    return firm, claim, assignment


class TestDeclinedAssignmentCapacityCounter:
    """A decline must return the firm's capacity counter without drift."""

    def test_the_assignment_lifts_the_only_eligible_firms_counter_to_one(
        self, api, claims_adjuster_headers, claims_committee_approver_headers
    ):
        """A single-firm panel yields a pool of one and consumes one slot.

        PRD: "`candidate_pool_size` records how many firms passed that filter."

        Design: Difficulty/compensating_invariant/declined_assignment_restores_firm_capacity_counter_without_drift
        """
        firm, _claim, assignment = _covered_claim_with_counsel_assigned(
            api, claims_adjuster_headers
        )

        assert assignment["assignment_status"] == "ASSIGNED"
        assert assignment["candidate_pool_size"] == 1
        assert assignment["selection_rank_snapshot"] == 1
        assert assignment["counsel_firm_id"] == firm["id"]

        engaged_firm = validate_success(
            api.get_counsel_firm(firm["id"], claims_committee_approver_headers)
        )
        assert engaged_firm["open_assignment_count"] == 1

    def test_declining_returns_the_counter_to_its_pre_assignment_value(
        self, api, claims_adjuster_headers, claims_committee_approver_headers
    ):
        """The counter falls back to 0 while the declined row survives.

        PRD: "`ASSIGNED` → `DECLINED` records the reason and `closed_at`, decrements the firm's `open_assignment_count` by 1 so its capacity counter returns to its pre-assignment value, appends the firm's identifier to the claim's `excluded_counsel_firm_ids` so the selector will not choose it again for this claim, and sets the claim's `counsel_reassignment_required` to true."

        Design: Difficulty/compensating_invariant/declined_assignment_restores_firm_capacity_counter_without_drift
        """
        firm, _claim, assignment = _covered_claim_with_counsel_assigned(
            api, claims_adjuster_headers
        )

        declined = decline_assignment(api, assignment["id"],
                                      decline_reason="CONFLICT_OF_INTEREST")

        assert declined["assignment_status"] == "DECLINED"
        assert declined["decline_reason"] == "CONFLICT_OF_INTEREST"
        assert declined["candidate_pool_size"] == 1

        released_firm = validate_success(
            api.get_counsel_firm(firm["id"], claims_committee_approver_headers)
        )
        assert released_firm["open_assignment_count"] == 0
        assert released_firm["panel_status"] == "ACTIVE"

    def test_the_decline_excludes_the_firm_and_flags_the_claim_for_reassignment(
        self, api, claims_adjuster_headers
    ):
        """The firm stays on the panel but is barred from this one claim.

        PRD: "A firm is eligible when its `panel_status` is `ACTIVE`, when the claim's `venue_code` appears in its `admitted_venue_codes`, when the claim's `allegation_category` appears in its `allegation_specialties`, when the claim's `insured_id` does not appear in its `conflict_insured_ids`, when its `open_assignment_count` is strictly below its `max_concurrent_assignments`, and when its identifier does not appear in the claim's `excluded_counsel_firm_ids`."

        Design: Difficulty/compensating_invariant/declined_assignment_restores_firm_capacity_counter_without_drift
        """
        firm, claim, assignment = _covered_claim_with_counsel_assigned(
            api, claims_adjuster_headers
        )

        decline_assignment(api, assignment["id"],
                           decline_reason="CONFLICT_OF_INTEREST")

        refreshed_claim = validate_success(
            api.get_claim(claim["id"], claims_adjuster_headers)
        )
        assert firm["id"] in refreshed_claim["excluded_counsel_firm_ids"]
        assert refreshed_claim["counsel_reassignment_required"] is True
        assert refreshed_claim["claim_status"] == "INVESTIGATION"

    def test_reselection_finds_an_empty_pool_once_the_one_firm_is_excluded(
        self, api, claims_adjuster_headers
    ):
        """The restored capacity does not make the excluded firm selectable again.

        PRD: "An empty pool is refused with `ERR_NO_ELIGIBLE_COUNSEL`."

        Design: Difficulty/compensating_invariant/declined_assignment_restores_firm_capacity_counter_without_drift
        """
        _firm, claim, assignment = _covered_claim_with_counsel_assigned(
            api, claims_adjuster_headers
        )
        decline_assignment(api, assignment["id"],
                           decline_reason="CONFLICT_OF_INTEREST")

        response = api.create_counsel_assignment(claim["id"],
                                                 claims_adjuster_headers)

        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_COUNSEL.value, 409)


def _in_force_book_with_a_covered_claim(api, headers):
    """A live first term at 19285.00 net answering one covered claim."""
    insured, policy, term = _live_first_term_book(api, headers)
    claim = build_claim(api, insured["id"], incident_date="2026-08-05",
                        report_date="2026-09-01", demand_amount=800000.00)
    decide_coverage(api, claim["id"], "COVERED")
    return policy, term, claim


class TestFlatCancellationUnwind:
    """A flat cancellation must leave no residue of the issuance anywhere."""

    def test_the_cancellation_returns_the_whole_net_premium_and_the_limit(
        self, api, underwriting_officer_headers
    ):
        """Cancelling flat on inception refunds 19285.00 and surrenders the aggregate.

        PRD: "`IN_FORCE` → `CANCELLED_FLAT` records the cancellation date, returns the whole net premium by setting `return_premium` to `premium_net`, and surrenders the limit by setting `aggregate_limit_remaining` to 0.00."

        Design: Difficulty/compensating_invariant/flat_cancellation_unwinds_the_premium_ledger_and_voids_dependent_coverage
        """
        _policy, term, _claim = _in_force_book_with_a_covered_claim(
            api, underwriting_officer_headers
        )

        cancelled = validate_success(api.cancel_policy_term(
            term["id"],
            factories.cancellation_payload("FLAT", FIRST_EFFECTIVE),
            underwriting_officer_headers,
        ))

        assert cancelled["status"] == "CANCELLED_FLAT"
        assert cancelled["cancel_effective_date"] == FIRST_EFFECTIVE
        assertions.assert_money(cancelled["premium_net"], 19285.00, "premium_net")
        assertions.assert_money(cancelled["return_premium"], 19285.00,
                                "return_premium")
        assertions.assert_money(cancelled["aggregate_limit_remaining"], 0.00,
                                "aggregate_limit_remaining")

    def test_the_policy_premium_ledger_falls_back_to_zero(
        self, api, underwriting_officer_headers
    ):
        """Net of the full return the policy has written nothing at all.

        PRD: "`written_premium_net_total` is the sum, over that policy's terms in `ISSUED`, `IN_FORCE`, `EXPIRED`, `CANCELLED_FLAT` or `CANCELLED_PRO_RATA` status, of each term's `premium_net` less its `return_premium`, rounded to two decimal places."

        Design: Difficulty/compensating_invariant/flat_cancellation_unwinds_the_premium_ledger_and_voids_dependent_coverage
        """
        policy, term, _claim = _in_force_book_with_a_covered_claim(
            api, underwriting_officer_headers
        )
        assertions.assert_money(policy["written_premium_net_total"], 19285.00,
                                "written_premium_net_total")

        validate_success(api.cancel_policy_term(
            term["id"],
            factories.cancellation_payload("FLAT", FIRST_EFFECTIVE),
            underwriting_officer_headers,
        ))

        refreshed_policy = validate_success(
            api.get_policy(policy["id"], underwriting_officer_headers)
        )
        assertions.assert_money(refreshed_policy["written_premium_net_total"],
                                0.00, "written_premium_net_total")

    def test_the_cancelled_policy_closes_with_no_current_term(
        self, api, underwriting_officer_headers
    ):
        """With its only term gone the policy itself is cancelled.

        PRD: "The policy's `written_premium_net_total` is recomputed, its `current_term_id` re-derived, and its `status` set to `CANCELLED` once no term on it remains in `DRAFT`, `ISSUED` or `IN_FORCE`."

        Design: Difficulty/compensating_invariant/flat_cancellation_unwinds_the_premium_ledger_and_voids_dependent_coverage
        """
        policy, term, _claim = _in_force_book_with_a_covered_claim(
            api, underwriting_officer_headers
        )

        validate_success(api.cancel_policy_term(
            term["id"],
            factories.cancellation_payload("FLAT", FIRST_EFFECTIVE),
            underwriting_officer_headers,
        ))

        refreshed_policy = validate_success(
            api.get_policy(policy["id"], underwriting_officer_headers)
        )
        assert refreshed_policy["status"] == "CANCELLED"
        assert refreshed_policy["current_term_id"] is None

    def test_the_cancellation_voids_the_cover_the_term_had_granted(
        self, api, underwriting_officer_headers, claims_adjuster_headers
    ):
        """Rescinding from inception denies the claim the term was answering.

        PRD: "It then rescinds what the term supported: every claim whose responding term is this term and whose coverage position is not already `DENIED` has its `coverage_status` set to `DENIED` with `denial_reason` `TERM_VOIDED`; every settlement negotiation on those claims whose status is neither `PAID` nor `ABANDONED` is moved to `ABANDONED`; and every tail endorsement on the same policy that is `ISSUED` is moved `ISSUED` → `VOID` with `void_reason` recorded as `POLICY_RESCINDED_BY_FLAT_CANCELLATION`, because rescinding the relationship from inception leaves no reporting obligation for a tail to extend."

        Design: Difficulty/compensating_invariant/flat_cancellation_unwinds_the_premium_ledger_and_voids_dependent_coverage
        """
        _policy, term, claim = _in_force_book_with_a_covered_claim(
            api, underwriting_officer_headers
        )

        validate_success(api.cancel_policy_term(
            term["id"],
            factories.cancellation_payload("FLAT", FIRST_EFFECTIVE),
            underwriting_officer_headers,
        ))

        refreshed_claim = validate_success(
            api.get_claim(claim["id"], claims_adjuster_headers)
        )
        assert refreshed_claim["coverage_status"] == "DENIED"
        assert refreshed_claim["denial_reason"] == "TERM_VOIDED"
        assert refreshed_claim["claim_status"] == "INVESTIGATION"

    def test_a_pro_rata_cancellation_leaves_the_cover_and_the_limit_standing(
        self, api, underwriting_officer_headers, claims_adjuster_headers
    ):
        """Only the flat branch rescinds; a mid-term cancellation keeps the position.

        PRD: "`aggregate_limit_remaining` is left exactly as it was, claims already reported under the term keep the coverage position they had, no tail endorsement is voided, the policy's `written_premium_net_total` is recomputed, its `current_term_id` re-derived, and its `status` set to `CANCELLED`."

        Design: Difficulty/compensating_invariant/flat_cancellation_unwinds_the_premium_ledger_and_voids_dependent_coverage
        """
        _policy, term, claim = _in_force_book_with_a_covered_claim(
            api, underwriting_officer_headers
        )

        cancelled = validate_success(api.cancel_policy_term(
            term["id"],
            factories.cancellation_payload("PRO_RATA", "2027-02-01"),
            underwriting_officer_headers,
        ))

        assert cancelled["status"] == "CANCELLED_PRO_RATA"
        assertions.assert_money(cancelled["aggregate_limit_remaining"], 3000000.00,
                                "aggregate_limit_remaining")

        refreshed_claim = validate_success(
            api.get_claim(claim["id"], claims_adjuster_headers)
        )
        assert refreshed_claim["coverage_status"] == "COVERED"
        assert refreshed_claim["denial_reason"] is None
