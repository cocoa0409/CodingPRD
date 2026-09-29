"""Inclusive boundaries and cross-entity reads in underwriting and actuarial work.

Covers the death/disability/retirement tail's twin five-year gates and the
reserve adequacy floor (PRD 3.5, 3.1), then the two places where an operation's
outcome is decided by a second entity's state: coverage trigger resolution
against a term's status (PRD 3.6) and term issuance against the insured's
credentialing axis (PRD 3.5).
"""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions, factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.fixtures import (
    advance_clock,
    build_claim,
    build_credentialed_insured,
    build_insured,
    build_policy,
    build_rate_filing,
    build_specialty_class,
    build_term,
    credential_insured,
    decide_coverage,
    issue_term,
    post_reserve,
    submit_rate_filing,
)

TERM_EFFECTIVE = "2026-08-01"
TERM_EXPIRATION = "2027-08-01"
EXPIRY_INSTANT = "2027-08-01T00:00:00Z"

ORTHOPEDIC_CLASS = {
    "specialty_code": "ORTHOPEDIC_SURGERY",
    "base_class_code": "CLASS_5",
    "base_rate_per_million": 24800.00,
    "hazard_index": 6.0,
    "benchmark_severity": 480000.00,
}


def _expired_orthopedic_term(api, headers, years_in_practice,
                             prior_acts_step_credit):
    """One expired claims-made term on an Arizona orthopaedic insured."""
    advance_clock(api, CLOCK_EPOCH)
    specialty = build_specialty_class(api, **ORTHOPEDIC_CLASS)
    insured = build_credentialed_insured(
        api, specialty["id"], credentialing_expires_on="2033-01-01",
        legal_name="Desert Orthopedics PLLC", venue_code="MARICOPA_AZ",
        high_severity_procedure_pct=30, years_in_practice=years_in_practice,
    )
    policy = build_policy(api, insured["id"],
                          prior_acts_step_credit=prior_acts_step_credit)
    term = build_term(api, policy["id"], effective_date=TERM_EFFECTIVE,
                      expiration_date=TERM_EXPIRATION)
    issue_term(api, term["id"])
    advance_clock(api, EXPIRY_INSTANT)
    return policy, validate_success(api.get_policy_term(term["id"], headers))


def _quote_ddr_tail(api, policy_id, term_id, headers):
    return api.create_tail_endorsement(
        policy_id,
        factories.tail_endorsement_payload(
            term_id, tail_type="DEATH_DISABILITY_RETIREMENT",
            trigger_reason="RETIREMENT", effective_date=TERM_EXPIRATION,
        ),
        headers,
    )


class TestFreeDeathDisabilityRetirementTailBounds:
    """The twin five-year gates on the free tail, tested on and off each bound."""

    def test_five_practice_years_against_step_year_five_quotes_a_free_tail(
        self, api, underwriting_officer_headers
    ):
        """Both gates sit exactly on 5, so the free form is quoted at factor 0.00.

        PRD: "The free death, disability and retirement form is gated rather than open: it requires the insured's `years_in_practice` to be at least 5 **and** the triggering term's `claims_made_step_year` to be at least 5, both bounds inclusive, and a request failing either is refused with `ERR_DDR_NOT_ELIGIBLE`."

        Design: Difficulty/boundary_precision_check/ddr_free_tail_allowed_at_exactly_five_years_and_step_year_five_bounds
        """
        policy, term = _expired_orthopedic_term(
            api, underwriting_officer_headers, years_in_practice=5,
            prior_acts_step_credit=4,
        )
        assert term["claims_made_step_year"] == 5
        assert float(term["step_factor"]) == 1.00
        assert term["status"] == "EXPIRED"

        tail = validate_success(
            _quote_ddr_tail(api, policy["id"], term["id"],
                            underwriting_officer_headers),
            201,
        )

        assert tail["tail_type"] == "DEATH_DISABILITY_RETIREMENT"
        assertions.assert_money(tail["mature_premium_basis"], 24800.00,
                                "mature_premium_basis")
        assert float(tail["tail_factor"]) == 0.00
        assertions.assert_money(tail["tail_premium"], 0.00, "tail_premium")
        assert tail["status"] == "QUOTED"

    def test_the_free_tail_window_runs_to_the_unlimited_end_date(
        self, api, underwriting_officer_headers
    ):
        """The free form carries the effectively unlimited reporting window.

        PRD: "`reporting_window_end` closes the window: for `ERP_5YR` it is five years after the `effective_date` less one day, so that the closed window spans exactly five years; for `ERP_UNLIMITED` and `DEATH_DISABILITY_RETIREMENT` it is `9999-12-31`, an effectively unlimited window."

        Design: Difficulty/boundary_precision_check/ddr_free_tail_allowed_at_exactly_five_years_and_step_year_five_bounds
        """
        policy, term = _expired_orthopedic_term(
            api, underwriting_officer_headers, years_in_practice=5,
            prior_acts_step_credit=4,
        )

        tail = validate_success(
            _quote_ddr_tail(api, policy["id"], term["id"],
                            underwriting_officer_headers),
            201,
        )

        assert tail["effective_date"] == TERM_EXPIRATION
        assert tail["reporting_window_end"] == "9999-12-31"

    def test_four_practice_years_is_refused_even_at_step_year_five(
        self, api, underwriting_officer_headers
    ):
        """One year short of the practice-years bound loses the free tail.

        PRD: "The free death, disability and retirement form is gated rather than open: it requires the insured's `years_in_practice` to be at least 5 **and** the triggering term's `claims_made_step_year` to be at least 5, both bounds inclusive, and a request failing either is refused with `ERR_DDR_NOT_ELIGIBLE`."

        Design: Difficulty/boundary_precision_check/ddr_free_tail_allowed_at_exactly_five_years_and_step_year_five_bounds
        """
        policy, term = _expired_orthopedic_term(
            api, underwriting_officer_headers, years_in_practice=4,
            prior_acts_step_credit=4,
        )
        assert term["claims_made_step_year"] == 5

        response = _quote_ddr_tail(api, policy["id"], term["id"],
                                   underwriting_officer_headers)

        validate_error(response, ApiErrorId.ERR_DDR_NOT_ELIGIBLE.value, 422)

    def test_step_year_four_is_refused_even_at_five_practice_years(
        self, api, underwriting_officer_headers
    ):
        """A step-four term cannot trigger the free tail however long the practice.

        PRD: "First the step position: on a claims-made policy, `claims_made_step_year` is the lesser of 5 and the sum of the term's `term_index` and the policy's `prior_acts_step_credit`, and `step_factor` is the factor published for that step year — 0.35 for step 1, 0.60 for step 2, 0.80 for step 3, 0.92 for step 4 and 1.00 for step 5."

        Design: Difficulty/boundary_precision_check/ddr_free_tail_allowed_at_exactly_five_years_and_step_year_five_bounds
        """
        policy, term = _expired_orthopedic_term(
            api, underwriting_officer_headers, years_in_practice=5,
            prior_acts_step_credit=3,
        )
        assert term["claims_made_step_year"] == 4

        response = _quote_ddr_tail(api, policy["id"], term["id"],
                                   underwriting_officer_headers)

        validate_error(response, ApiErrorId.ERR_DDR_NOT_ELIGIBLE.value, 422)


def _filing_on_a_carried_reserve(api, expense_amount):
    """One covered claim carrying 600000.00 of indemnity plus the given expense."""
    advance_clock(api, CLOCK_EPOCH)
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"])
    term = build_term(api, policy["id"], effective_date=TERM_EFFECTIVE,
                      expiration_date=TERM_EXPIRATION)
    issue_term(api, term["id"])
    claim = build_claim(api, insured["id"], incident_date="2026-08-05",
                        report_date="2026-09-01", demand_amount=1000000.00)
    decide_coverage(api, claim["id"], "COVERED")
    post_reserve(api, claim["id"], method="CASE_BASIS",
                 effective_at="2026-09-02T00:00:00Z",
                 indemnity_amount=600000.00, expense_amount=expense_amount)
    filing = build_rate_filing(
        api, specialty["id"], indication_method="LOSS_RATIO_METHOD",
        proposed_rate_change_pct=5.00, experience_period_start=TERM_EFFECTIVE,
        experience_period_end=TERM_EXPIRATION, effective_date=TERM_EXPIRATION,
    )
    return specialty, claim, submit_rate_filing(api, filing["id"])


class TestReserveAdequacyFloor:
    """The inclusive 0.9000 boundary between a deficient and an adequate filing."""

    def test_a_ratio_of_exactly_zero_point_nine_thousand_flags_adequate(
        self, api, claims_adjuster_headers
    ):
        """835200.00 required against 751680.00 carried is adequate, not deficient.

        PRD: "A ratio strictly below 0.9000 flags the filing `DEFICIENT`; a ratio from 0.9000 up to and including 1.1000 flags it `ADEQUATE`; a ratio above 1.1000 flags it `REDUNDANT`."

        Design: Difficulty/boundary_precision_check/adequacy_ratio_of_exactly_zero_point_nine_thousand_is_adequate_and_approvable
        """
        _specialty, claim, filing = _filing_on_a_carried_reserve(api, 151680.00)

        refreshed_claim = validate_success(
            api.get_claim(claim["id"], claims_adjuster_headers)
        )
        assert refreshed_claim["severity_band"] == "BAND_3"
        assert float(refreshed_claim["severity_band_factor"]) == 0.45
        assertions.assert_money(refreshed_claim["indemnity_reserve"], 600000.00,
                                "indemnity_reserve")
        assertions.assert_money(refreshed_claim["expense_reserve"], 151680.00,
                                "expense_reserve")

        assert filing["claim_count_in_scope"] == 1
        assertions.assert_money(filing["required_reserve_total"], 835200.00,
                                "required_reserve_total")
        assertions.assert_money(filing["carried_reserve_total"], 751680.00,
                                "carried_reserve_total")
        assertions.assert_ratio(filing["reserve_adequacy_ratio"], 0.9000,
                                "reserve_adequacy_ratio")
        assert filing["adequacy_flag"] == "ADEQUATE"

    def test_the_filing_on_the_floor_is_approved_and_rewrites_the_manual_rate(
        self, api, chief_actuary_headers, actuarial_analyst_headers
    ):
        """An adequate filing is approvable and lifts the base rate by five percent.

        PRD: "`DRAFT` → `SUBMITTED` → `APPROVED` sets `approved_rate_change_pct` to the filing's `proposed_rate_change_pct`, records `decided_by_user_id` and the note, and then rewrites the class's manual rate: the new `base_rate_per_million` is the old base rate multiplied by one plus the approved change expressed as a fraction of 100, rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/adequacy_ratio_of_exactly_zero_point_nine_thousand_is_adequate_and_approvable
        """
        specialty, _claim, filing = _filing_on_a_carried_reserve(api, 151680.00)

        decided = validate_success(api.decide_rate_filing(
            filing["id"],
            factories.filing_decision_payload(
                "APPROVE", "reserves sit exactly on the adequacy floor"
            ),
            chief_actuary_headers,
        ))

        assert decided["status"] == "APPROVED"
        assert float(decided["approved_rate_change_pct"]) == 5.00

        refreshed_class = validate_success(
            api.get_specialty_class(specialty["id"], actuarial_analyst_headers)
        )
        assert refreshed_class["rate_revision_index"] == 1
        assertions.assert_money(refreshed_class["base_rate_per_million"], 39900.00,
                                "base_rate_per_million")

    def test_a_ratio_just_below_the_floor_is_deficient_and_blocks_approval(
        self, api, chief_actuary_headers
    ):
        """Carrying 751600.00 lands at 0.8999 and the approval is refused.

        PRD: "An approval requires the filing to be `SUBMITTED`, requires the deciding `X-User-ID` to differ from `prepared_by_user_id`, and requires the filing's `adequacy_flag` not to be `DEFICIENT` — a deficiency must be cured and the filing resubmitted, and an attempt to approve a deficient filing is refused with `ERR_RESERVE_DEFICIENCY_BLOCKS_FILING`."

        Design: Difficulty/boundary_precision_check/adequacy_ratio_of_exactly_zero_point_nine_thousand_is_adequate_and_approvable
        """
        _specialty, _claim, filing = _filing_on_a_carried_reserve(api, 151600.00)

        assertions.assert_money(filing["carried_reserve_total"], 751600.00,
                                "carried_reserve_total")
        assertions.assert_ratio(filing["reserve_adequacy_ratio"], 0.8999,
                                "reserve_adequacy_ratio")
        assert filing["adequacy_flag"] == "DEFICIENT"

        response = api.decide_rate_filing(
            filing["id"],
            factories.filing_decision_payload("APPROVE", "cure the deficiency"),
            chief_actuary_headers,
        )

        validate_error(response,
                       ApiErrorId.ERR_RESERVE_DEFICIENCY_BLOCKS_FILING.value, 409)


def _book_with_a_drafted_term_already_dated_over_the_claim(api):
    """A term whose dates cover the incident but whose status is still DRAFT."""
    advance_clock(api, CLOCK_EPOCH)
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"], retroactive_date=TERM_EFFECTIVE)
    term = build_term(api, policy["id"], effective_date=TERM_EFFECTIVE,
                      expiration_date=TERM_EXPIRATION)
    return insured, policy, term


class TestClaimIntakeAgainstTermStatus:
    """Coverage resolution reads the term's status, not merely its dates."""

    def test_a_drafted_term_answers_nothing_even_though_its_dates_cover_the_incident(
        self, api, claims_adjuster_headers
    ):
        """An intake against a DRAFT term is denied for no responding coverage.

        PRD: "The candidate set holds the policy terms belonging to policies of the claim's insured whose status is `IN_FORCE`, `EXPIRED` or `CANCELLED_PRO_RATA`; terms in `DRAFT`, `ISSUED` or `CANCELLED_FLAT` status never respond to anything."

        Design: Difficulty/cross_entity_state_dependency/claim_intake_coverage_outcome_hinges_on_the_terms_status_not_its_dates
        """
        insured, _policy, term = _book_with_a_drafted_term_already_dated_over_the_claim(api)

        drafted_term = validate_success(
            api.get_policy_term(term["id"], claims_adjuster_headers)
        )
        assert drafted_term["status"] == "DRAFT"
        assert drafted_term["effective_date"] == TERM_EFFECTIVE
        assert drafted_term["expiration_date"] == TERM_EXPIRATION

        claim = build_claim(api, insured["id"], incident_date="2026-08-05",
                           report_date="2026-09-01", demand_amount=800000.00)

        assert claim["coverage_status"] == "DENIED"
        assert claim["policy_term_id"] is None
        assert claim["tail_endorsement_id"] is None
        assert claim["claim_status"] == "INTAKE"
        assert claim["severity_band"] == "BAND_3"

    def test_the_denial_on_a_drafted_term_names_no_responding_coverage(
        self, api, claims_adjuster_headers
    ):
        """The denial reason distinguishes an absent term from an excluded incident.

        PRD: "Where no tail responds either, `coverage_status` is `DENIED` with `denial_reason` `NO_RESPONDING_COVERAGE`."

        Design: Difficulty/cross_entity_state_dependency/claim_intake_coverage_outcome_hinges_on_the_terms_status_not_its_dates
        """
        insured, _policy, _term = _book_with_a_drafted_term_already_dated_over_the_claim(api)

        claim = build_claim(api, insured["id"], incident_date="2026-08-05",
                            report_date="2026-09-01", demand_amount=800000.00)

        assert claim["denial_reason"] == "NO_RESPONDING_COVERAGE"
        assertions.assert_claim(claim)

    def test_issuing_the_term_makes_the_identical_intake_resolve_under_review(
        self, api, claims_adjuster_headers, underwriting_officer_headers
    ):
        """The same incident and report dates find cover once the term is in force.

        PRD: "If at least one term responds and the incident is not excluded by the retroactive date, `policy_term_id` names the responding term with the latest `effective_date`, ties broken by the earlier creation timestamp, and `coverage_status` is `UNDER_REVIEW`."

        Design: Difficulty/cross_entity_state_dependency/claim_intake_coverage_outcome_hinges_on_the_terms_status_not_its_dates
        """
        insured, _policy, term = _book_with_a_drafted_term_already_dated_over_the_claim(api)

        denied_claim = build_claim(api, insured["id"], incident_date="2026-08-05",
                                   report_date="2026-09-01", demand_amount=800000.00)
        assert denied_claim["coverage_status"] == "DENIED"

        live_term = issue_term(api, term["id"])
        assert live_term["status"] == "IN_FORCE"

        covered_claim = build_claim(api, insured["id"], incident_date="2026-08-05",
                                    report_date="2026-09-01", demand_amount=800000.00)

        assert covered_claim["coverage_status"] == "UNDER_REVIEW"
        assert covered_claim["denial_reason"] is None
        assert covered_claim["policy_term_id"] == term["id"]
        assert covered_claim["claim_status"] == "INTAKE"

    def test_only_the_covered_intake_counts_against_the_insureds_open_exposure(
        self, api, underwriting_officer_headers
    ):
        """The denied claim is excluded from the insured's open claim count.

        PRD: "`open_claim_count` is the number whose handling status is `INTAKE`, `INVESTIGATION` or `LITIGATION` and whose coverage position is anything other than `DENIED`."

        Design: Difficulty/cross_entity_state_dependency/claim_intake_coverage_outcome_hinges_on_the_terms_status_not_its_dates
        """
        insured, _policy, term = _book_with_a_drafted_term_already_dated_over_the_claim(api)

        build_claim(api, insured["id"], incident_date="2026-08-05",
                    report_date="2026-09-01", demand_amount=800000.00)
        issue_term(api, term["id"])
        build_claim(api, insured["id"], incident_date="2026-08-05",
                    report_date="2026-09-01", demand_amount=800000.00)

        refreshed = validate_success(
            api.get_insured(insured["id"], underwriting_officer_headers)
        )
        assert refreshed["open_claim_count"] == 1


FUTURE_EFFECTIVE = "2026-09-01"
FUTURE_EXPIRATION = "2027-09-01"


def _uncredentialed_book_with_a_future_term(api):
    """An insured left on its default PENDING axis under a future-dated term."""
    advance_clock(api, CLOCK_EPOCH)
    specialty = build_specialty_class(api)
    insured = build_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"], retroactive_date=FUTURE_EFFECTIVE)
    term = build_term(api, policy["id"], effective_date=FUTURE_EFFECTIVE,
                      expiration_date=FUTURE_EXPIRATION)
    return insured, policy, term


class TestTermIssuanceAgainstCredentialing:
    """Binding a term reads the insured's credentialing status and expiry."""

    def test_a_pending_credentialing_axis_blocks_the_binding(
        self, api, underwriting_officer_headers
    ):
        """An insured still awaiting a verdict cannot have a term bound to it.

        PRD: "Issuance also tests the insured's credentials against the term being bound: the insured's `credentialing_status` must be `CREDENTIALED` or `PROVISIONAL`, and its `credentialing_expires_on` must be on or after the term's `effective_date`."

        Design: Difficulty/cross_entity_state_dependency/term_issuance_hinges_on_the_insureds_credentialing_axis_status_and_expiry
        """
        insured, _policy, term = _uncredentialed_book_with_a_future_term(api)

        assert insured["credentialing_status"] == "PENDING"

        response = api.issue_policy_term(term["id"], underwriting_officer_headers)

        validate_error(response,
                       ApiErrorId.ERR_CREDENTIALING_NOT_VALID_FOR_TERM.value, 409)

        untouched = validate_success(
            api.get_policy_term(term["id"], underwriting_officer_headers)
        )
        assert untouched["status"] == "DRAFT"

    def test_a_verdict_expiring_before_inception_blocks_the_same_binding(
        self, api, underwriting_officer_headers
    ):
        """Credentials lapsing on 2026-08-15 cannot support a term starting 2026-09-01.

        PRD: "A term whose coverage period would begin after the insured's credentials expire cannot be bound, and either failure is refused with `ERR_CREDENTIALING_NOT_VALID_FOR_TERM`."

        Design: Difficulty/cross_entity_state_dependency/term_issuance_hinges_on_the_insureds_credentialing_axis_status_and_expiry
        """
        insured, _policy, term = _uncredentialed_book_with_a_future_term(api)

        credentialed = credential_insured(
            api, insured["id"], "CREDENTIALED", "2026-08-15"
        )
        assert credentialed["credentialing_status"] == "CREDENTIALED"
        assert credentialed["credentialing_expires_on"] == "2026-08-15"

        response = api.issue_policy_term(term["id"], underwriting_officer_headers)

        validate_error(response,
                       ApiErrorId.ERR_CREDENTIALING_NOT_VALID_FOR_TERM.value, 409)

    def test_credentials_running_past_inception_bind_the_future_term_as_issued(
        self, api, underwriting_officer_headers
    ):
        """A verdict expiring 2028-01-01 binds the term, which waits in ISSUED.

        PRD: "When the effective date is still in the future, `DRAFT` → `ISSUED` fires and the term waits for the clock sweep to promote it."

        Design: Difficulty/cross_entity_state_dependency/term_issuance_hinges_on_the_insureds_credentialing_axis_status_and_expiry
        """
        insured, _policy, term = _uncredentialed_book_with_a_future_term(api)

        credential_insured(api, insured["id"], "CREDENTIALED", "2026-08-15")
        api.issue_policy_term(term["id"], underwriting_officer_headers)
        credential_insured(api, insured["id"], "CREDENTIALED", "2028-01-01")

        issued = validate_success(
            api.issue_policy_term(term["id"], underwriting_officer_headers)
        )

        assert issued["status"] == "ISSUED"
        assertions.assert_money(issued["aggregate_limit_remaining"], 3000000.00,
                                "aggregate_limit_remaining")
        assertions.assert_policy_term(issued)

    def test_the_bound_term_carries_the_step_one_premium_and_its_fee_ladder(
        self, api, underwriting_officer_headers
    ):
        """The bound first term charges 19285.00 net with a 250.00 fee and 244.19 assessment.

        PRD: "`administrative_fee` is a flat charge selected from three tiers on `premium_net` alone — 250.00 when `premium_net` is below 25000.00, 500.00 when it is at least 25000.00 but below 100000.00, and 900.00 when it is 100000.00 or more."

        Design: Difficulty/cross_entity_state_dependency/term_issuance_hinges_on_the_insureds_credentialing_axis_status_and_expiry
        """
        insured, _policy, term = _uncredentialed_book_with_a_future_term(api)

        credential_insured(api, insured["id"], "CREDENTIALED", "2028-01-01")
        issued = validate_success(
            api.issue_policy_term(term["id"], underwriting_officer_headers)
        )

        assertions.assert_money(issued["premium_net"], 19285.00, "premium_net")
        assertions.assert_money(issued["administrative_fee"], 250.00,
                                "administrative_fee")
        assertions.assert_money(issued["guaranty_fund_assessment"], 244.19,
                                "guaranty_fund_assessment")
        assertions.assert_money(issued["term_total"], 19779.19, "term_total")
        assertions.assert_fee_ladder(issued)

    def test_binding_the_term_activates_the_policy_and_the_insured(
        self, api, underwriting_officer_headers
    ):
        """A successful binding writes the net premium up to the policy and lifts both records.

        PRD: "Both branches behave identically in every other respect: `issued_at` records the current logical timestamp, `aggregate_limit_remaining` is set to the policy's `limit_aggregate`, the policy's `written_premium_net_total` and `quoted_premium_total` are recomputed, `current_term_id` is re-derived, the policy's `status` becomes `ACTIVE`, and an insured still in `PROSPECT` is advanced to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/term_issuance_hinges_on_the_insureds_credentialing_axis_status_and_expiry
        """
        insured, policy, term = _uncredentialed_book_with_a_future_term(api)

        credential_insured(api, insured["id"], "CREDENTIALED", "2028-01-01")
        validate_success(api.issue_policy_term(term["id"], underwriting_officer_headers))

        refreshed_policy = validate_success(
            api.get_policy(policy["id"], underwriting_officer_headers)
        )
        assert refreshed_policy["status"] == "ACTIVE"
        assertions.assert_money(refreshed_policy["written_premium_net_total"],
                                19285.00, "written_premium_net_total")
        assert refreshed_policy["current_term_id"] == term["id"]

        refreshed_insured = validate_success(
            api.get_insured(insured["id"], underwriting_officer_headers)
        )
        assert refreshed_insured["status"] == "ACTIVE"
        assert refreshed_insured["credentialing_status"] == "CREDENTIALED"
        assert refreshed_insured["credentialing_expires_on"] == "2028-01-01"
