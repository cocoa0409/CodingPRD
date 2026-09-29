"""Validation precedence where two checks fail on one request (PRD 2.8).

Each case drives a single write that violates two rules at once and pins which
of the two the response must carry: a replayed settlement disbursement, a
counsel request on a denied claim, and a stale-version term addition whose
period also duplicates an existing term.
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions, factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import (
    advance_clock,
    build_claim,
    build_credentialed_insured,
    build_policy,
    build_specialty_class,
    build_term,
    decide_authority,
    decide_coverage,
    issue_term,
    open_negotiation,
    pay_settlement,
)

TERM_EFFECTIVE = "2026-08-01"
TERM_EXPIRATION = "2027-08-01"
INCIDENT_DATE = "2026-08-05"
REPORT_DATE = "2026-09-01"


def _live_claims_made_book(api, limit_aggregate=3000000.00):
    """A rating class, a credentialed insured and one live claims-made term."""
    advance_clock(api, CLOCK_EPOCH)
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"], limit_aggregate=limit_aggregate)
    term = build_term(api, policy["id"], effective_date=TERM_EFFECTIVE,
                      expiration_date=TERM_EXPIRATION)
    return insured, policy, issue_term(api, term["id"])


def _covered_claim(api, insured_id, demand_amount):
    """Intakes a claim reported inside the live term and covers it."""
    claim = build_claim(api, insured_id, incident_date=INCIDENT_DATE,
                        report_date=REPORT_DATE, demand_amount=demand_amount)
    return decide_coverage(api, claim["id"], "COVERED")


def _litigate(api, claim_id, headers, suit_filed_on="2026-09-15"):
    return validate_success(api.record_litigation(
        claim_id, factories.litigation_payload(suit_filed_on), headers
    ))


def _paid_settlement_book(api, adjuster_headers):
    """A 900000.00 settlement paid off a term whose aggregate is only 1000000.00."""
    insured, policy, term = _live_claims_made_book(api, limit_aggregate=1000000.00)
    claim = _covered_claim(api, insured["id"], 900000.00)
    _litigate(api, claim["id"], adjuster_headers)
    negotiation = open_negotiation(api, claim["id"], 900000.00, 900000.00)
    decide_authority(api, negotiation["id"], "GRANT", 900000.00)
    paid = pay_settlement(api, negotiation["id"], "2026-10-01")
    return {
        "insured": insured,
        "policy": policy,
        "term": term,
        "claim": claim,
        "negotiation": paid,
    }


class TestReplayedSettlementDisbursement:
    """A settlement paid once, then disbursed again on an exhausted aggregate."""

    def test_the_replay_reports_the_negotiation_state_not_the_aggregate_limit(
        self, api, claims_adjuster_headers
    ):
        """A second disbursement of a PAID offer is refused on status alone.

        PRD: "Three statuses are payable — `AUTHORITY_GRANTED`, `CONSENT_GRANTED` and `HAMMER_INVOKED` — and any other status is refused with `ERR_NEGOTIATION_STATE_INVALID`."

        Design: Difficulty/priority_pair_validation_conflict/replayed_payment_on_paid_negotiation_rejected_for_state_not_aggregate_limit
        """
        book = _paid_settlement_book(api, claims_adjuster_headers)

        replay = api.pay_settlement(
            book["negotiation"]["id"],
            factories.settlement_payment_payload("2026-10-02"),
            claims_adjuster_headers,
        )

        validate_error(replay, ApiErrorId.ERR_NEGOTIATION_STATE_INVALID.value, 409)

    def test_the_refused_replay_leaves_the_disbursement_and_the_aggregate_intact(
        self, api, claims_adjuster_headers, underwriting_officer_headers
    ):
        """The paid offer, the claim's indemnity and the surviving aggregate stand.

        PRD: "When several checks could reject the same request, they are evaluated in a fixed order, and the response carries the error of the first check that fails."

        Design: Difficulty/priority_pair_validation_conflict/replayed_payment_on_paid_negotiation_rejected_for_state_not_aggregate_limit
        """
        book = _paid_settlement_book(api, claims_adjuster_headers)

        api.pay_settlement(
            book["negotiation"]["id"],
            factories.settlement_payment_payload("2026-10-02"),
            claims_adjuster_headers,
        )

        negotiation = validate_success(api.get_settlement_negotiation(
            book["negotiation"]["id"], claims_adjuster_headers
        ))
        assert negotiation["status"] == "PAID"
        assertions.assert_money(negotiation["paid_amount"], 900000.00, "paid_amount")
        assert negotiation["payment_date"] == "2026-10-01"

        claim = validate_success(api.get_claim(book["claim"]["id"],
                                              claims_adjuster_headers))
        assertions.assert_money(claim["paid_indemnity"], 900000.00, "paid_indemnity")

        term = validate_success(api.get_policy_term(book["term"]["id"],
                                                    underwriting_officer_headers))
        assertions.assert_money(term["aggregate_limit_remaining"], 100000.00,
                                "aggregate_limit_remaining")

    def test_the_aggregate_error_surfaces_when_the_negotiation_state_is_payable(
        self, api, claims_adjuster_headers
    ):
        """With only 100000.00 of aggregate left, a fresh payable offer of 200000.00 fails on the aggregate.

        PRD: "The amount being disbursed must not exceed the responding term's `aggregate_limit_remaining` (`ERR_AGGREGATE_LIMIT_EXCEEDED`) nor the policy's `limit_per_claim` less the claim's `paid_indemnity` (`ERR_PER_CLAIM_LIMIT_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/replayed_payment_on_paid_negotiation_rejected_for_state_not_aggregate_limit
        """
        book = _paid_settlement_book(api, claims_adjuster_headers)

        second_claim = _covered_claim(api, book["insured"]["id"], 400000.00)
        second_negotiation = open_negotiation(api, second_claim["id"],
                                              200000.00, 200000.00)
        decide_authority(api, second_negotiation["id"], "GRANT", 200000.00)

        response = api.pay_settlement(
            second_negotiation["id"],
            factories.settlement_payment_payload("2026-10-05"),
            claims_adjuster_headers,
        )

        validate_error(response, ApiErrorId.ERR_AGGREGATE_LIMIT_EXCEEDED.value, 409)


class TestCounselRequestOnADeniedClaim:
    """A panel selector run on a denied claim while no firm is on the panel."""

    def test_the_duty_to_defend_bar_reports_before_the_empty_panel(
        self, api, claims_adjuster_headers
    ):
        """A denied claim gets no counsel even though the panel is also empty.

        PRD: "It must also carry a duty to defend: a claim whose `coverage_status` is `DENIED` gets no counsel, and the attempt is refused with `ERR_COVERAGE_DENIED_NO_DEFENSE`, while positions of `UNDER_REVIEW`, `COVERED` and `RESERVED_RIGHTS` all support an assignment."

        Design: Difficulty/priority_pair_validation_conflict/counsel_request_on_denied_claim_rejected_for_coverage_not_empty_panel
        """
        insured, _policy, _term = _live_claims_made_book(api)
        claim = build_claim(api, insured["id"], incident_date=INCIDENT_DATE,
                            report_date=REPORT_DATE, demand_amount=800000.00)
        denied = decide_coverage(api, claim["id"], "DENIED")
        assert denied["coverage_status"] == "DENIED"

        response = api.create_counsel_assignment(claim["id"],
                                                 claims_adjuster_headers)

        validate_error(response, ApiErrorId.ERR_COVERAGE_DENIED_NO_DEFENSE.value, 409)

    def test_the_denied_claim_records_the_adjusters_denial_and_no_exclusion(
        self, api, claims_adjuster_headers
    ):
        """The refused selector run writes nothing to the claim's counsel fields.

        PRD: "A denial recorded here sets `denial_reason` to `ADJUSTER_DENIAL`, distinguishing an adjuster's coverage call from the two denials the trigger resolution can produce and from the `TERM_VOIDED` denial a flat cancellation produces."

        Design: Difficulty/priority_pair_validation_conflict/counsel_request_on_denied_claim_rejected_for_coverage_not_empty_panel
        """
        insured, _policy, _term = _live_claims_made_book(api)
        claim = build_claim(api, insured["id"], incident_date=INCIDENT_DATE,
                            report_date=REPORT_DATE, demand_amount=800000.00)
        decide_coverage(api, claim["id"], "DENIED")

        api.create_counsel_assignment(claim["id"], claims_adjuster_headers)

        refreshed = validate_success(api.get_claim(claim["id"],
                                                   claims_adjuster_headers))
        assert refreshed["coverage_status"] == "DENIED"
        assert refreshed["denial_reason"] == "ADJUSTER_DENIAL"
        assert refreshed["claim_status"] == "INVESTIGATION"
        assert refreshed["excluded_counsel_firm_ids"] == []
        assert refreshed["counsel_reassignment_required"] is False

    def test_the_empty_panel_error_surfaces_once_coverage_supports_a_defence(
        self, api, claims_adjuster_headers
    ):
        """With the same empty panel but a covered claim, the pool error is reported.

        PRD: "An empty pool is refused with `ERR_NO_ELIGIBLE_COUNSEL`."

        Design: Difficulty/priority_pair_validation_conflict/counsel_request_on_denied_claim_rejected_for_coverage_not_empty_panel
        """
        insured, _policy, _term = _live_claims_made_book(api)
        claim = _covered_claim(api, insured["id"], 800000.00)

        response = api.create_counsel_assignment(claim["id"],
                                                 claims_adjuster_headers)

        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_COUNSEL.value, 409)


def _policy_with_one_drafted_term(api, headers):
    """A quoted policy carrying one drafted term, with both policy versions kept."""
    advance_clock(api, CLOCK_EPOCH)
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"])
    version_before_term = policy["version"]
    term = build_term(api, policy["id"], effective_date=TERM_EFFECTIVE,
                      expiration_date=TERM_EXPIRATION,
                      policy_version=version_before_term)
    version_after_term = validate_success(
        api.get_policy(policy["id"], headers)
    )["version"]
    return policy, term, version_before_term, version_after_term


class TestStalePolicyVersionOnAnOverlappingTerm:
    """A term addition that is both stale on the policy and duplicates a period."""

    def test_the_stale_version_reports_412_and_never_reaches_the_overlap_check(
        self, api, underwriting_officer_headers
    ):
        """The pre-term policy version is refused before the identical period is judged.

        PRD: "Adding a term to a policy requires `expected_policy_version` matching the policy's current `version`; a mismatch is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/stale_policy_version_on_overlapping_term_returns_412_not_overlap_conflict
        """
        policy, _term, stale_version, current_version = _policy_with_one_drafted_term(
            api, underwriting_officer_headers
        )
        assert stale_version != current_version

        response = api.create_policy_term(
            policy["id"],
            factories.policy_term_payload(
                effective_date=TERM_EFFECTIVE,
                expiration_date=TERM_EXPIRATION,
                expected_policy_version=stale_version,
            ),
            underwriting_officer_headers,
        )

        validate_error(response, ApiErrorId.ERR_STALE_POLICY_VERSION.value, 412)

    def test_the_overlap_conflict_surfaces_once_the_current_version_is_sent(
        self, api, underwriting_officer_headers
    ):
        """The very same period, sent on the current version, is refused as an overlap.

        PRD: "Independently, the new term's half-open period must not intersect the period of any existing term on the same policy whose status is not `CANCELLED_FLAT`; sharing a single boundary date is legal adjacency, while a genuine intersection is refused with `ERR_TERM_PERIOD_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/stale_policy_version_on_overlapping_term_returns_412_not_overlap_conflict
        """
        policy, _term, _stale_version, current_version = _policy_with_one_drafted_term(
            api, underwriting_officer_headers
        )

        response = api.create_policy_term(
            policy["id"],
            factories.policy_term_payload(
                effective_date=TERM_EFFECTIVE,
                expiration_date=TERM_EXPIRATION,
                expected_policy_version=current_version,
            ),
            underwriting_officer_headers,
        )

        validate_error(response, ApiErrorId.ERR_TERM_PERIOD_OVERLAP.value, 409)

    def test_the_rejected_addition_leaves_the_policy_version_and_first_term_alone(
        self, api, underwriting_officer_headers
    ):
        """No second term is minted, so the policy version stays where the first left it.

        PRD: "Creating the term increments the policy's `version` by 1."

        Design: Difficulty/priority_pair_validation_conflict/stale_policy_version_on_overlapping_term_returns_412_not_overlap_conflict
        """
        policy, term, stale_version, current_version = _policy_with_one_drafted_term(
            api, underwriting_officer_headers
        )

        api.create_policy_term(
            policy["id"],
            factories.policy_term_payload(
                effective_date=TERM_EFFECTIVE,
                expiration_date=TERM_EXPIRATION,
                expected_policy_version=stale_version,
            ),
            underwriting_officer_headers,
        )

        refreshed_policy = validate_success(
            api.get_policy(policy["id"], underwriting_officer_headers)
        )
        assert refreshed_policy["version"] == current_version

        refreshed_term = validate_success(
            api.get_policy_term(term["id"], underwriting_officer_headers)
        )
        assert refreshed_term["term_index"] == 1
        assert refreshed_term["status"] == "DRAFT"
