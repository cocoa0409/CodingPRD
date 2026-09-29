"""Rejections raised by the dating and domain-constraint gates: retroactive
dates against the coverage form, report and suit dating, experience windows,
step-chain adjacency, cancellation boundaries, tail applicability, data bank
submission dating and the reserve deficiency that blocks a rate approval.
"""
from datetime import date

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_EPOCH, OPERATOR_IDS
from test_helpers.test_users import TEST_USERS

UW = TEST_USERS["underwriting_officer_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]
APPROVER = TEST_USERS["claims_committee_approver_headers"]
CHAIR = TEST_USERS["peer_review_chair_headers"]
ANALYST = TEST_USERS["actuarial_analyst_headers"]
CHIEF = TEST_USERS["chief_actuary_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

TERM_EFFECTIVE = "2026-08-01"
TERM_EXPIRATION = "2027-08-01"


def _rated_class_and_insured(api, credentialed=True):
    """A published rating class and one COOK_IL insured on it."""
    fixtures.advance_clock(api, CLOCK_EPOCH)
    specialty = fixtures.build_specialty_class(api)
    if credentialed:
        insured = fixtures.build_credentialed_insured(api, specialty["id"])
    else:
        insured = fixtures.build_insured(api, specialty["id"])
    return specialty, insured


def _in_force_book(api, **policy_overrides):
    """Class, credentialed insured, claims-made policy and a term issued at
    inception so it binds live cover."""
    specialty, insured = _rated_class_and_insured(api)
    policy = fixtures.build_policy(api, insured["id"], **policy_overrides)
    draft = fixtures.build_term(api, policy["id"], TERM_EFFECTIVE, TERM_EXPIRATION)
    term = fixtures.issue_term(api, draft["id"])
    return {
        "specialty": specialty,
        "insured": insured,
        "policy": policy,
        "term": term,
    }


def _covered_claim(api, insured_id, **overrides):
    """A claim reported inside the live term and decided COVERED."""
    defaults = {"incident_date": "2026-08-05", "report_date": "2026-09-01"}
    defaults.update(overrides)
    return fixtures.build_investigated_claim(api, insured_id, **defaults)


def _policy_count(api, insured_id):
    _rows, meta = validate_paginated(
        api.list_policies(UW, {"insured_id": insured_id})
    )
    return meta["total_count"]


def _term_count(api, policy_id):
    _rows, meta = validate_paginated(
        api.list_policy_terms(UW, {"policy_id": policy_id})
    )
    return meta["total_count"]


def _claim_count(api, insured_id):
    _rows, meta = validate_paginated(
        api.list_claims(ADJ, {"insured_id": insured_id})
    )
    return meta["total_count"]


def _filing_count(api):
    _rows, meta = validate_paginated(api.list_rate_filings(ANALYST))
    return meta["total_count"]


class TestRetroactiveDateAgainstTheCoverageForm:
    def test_occurrence_policy_carrying_a_retroactive_date_is_refused(self, api):
        """An occurrence form that supplies a retroactive date never quotes.

        PRD: "A claims-made policy must carry a retroactive date and an occurrence policy must omit it or send it null; either violation is refused with `ERR_RETRO_DATE_INVALID`."

        Design: Corner/errors/retroactive_date_mismatches_against_the_coverage_form_are_rejected
        """
        _specialty, insured = _rated_class_and_insured(api, credentialed=False)

        response = api.create_policy(
            factories.policy_payload(
                insured["id"], coverage_form="OCCURRENCE",
                retroactive_date="2026-08-01",
            ),
            UW,
        )
        validate_error(response, ApiErrorId.ERR_RETRO_DATE_INVALID.value, 422)
        assert _policy_count(api, insured["id"]) == 0

    def test_claims_made_policy_omitting_the_retroactive_date_is_refused(self, api):
        """A claims-made form with no retroactive date never quotes.

        PRD: "A claims-made policy must carry a retroactive date and an occurrence policy must omit it or send it null; either violation is refused with `ERR_RETRO_DATE_INVALID`."

        Design: Corner/errors/retroactive_date_mismatches_against_the_coverage_form_are_rejected
        """
        _specialty, insured = _rated_class_and_insured(api, credentialed=False)

        response = api.create_policy(
            factories.policy_payload(
                insured["id"], coverage_form="CLAIMS_MADE", retroactive_date=None
            ),
            UW,
        )
        validate_error(response, ApiErrorId.ERR_RETRO_DATE_INVALID.value, 422)
        assert _policy_count(api, insured["id"]) == 0

    def test_occurrence_policy_omitting_the_retroactive_date_is_quoted(self, api):
        """An occurrence form that omits the retroactive date is accepted.

        PRD: "A claims-made policy must carry a retroactive date and an occurrence policy must omit it or send it null; either violation is refused with `ERR_RETRO_DATE_INVALID`."

        Design: Corner/errors/retroactive_date_mismatches_against_the_coverage_form_are_rejected
        """
        _specialty, insured = _rated_class_and_insured(api, credentialed=False)

        policy = validate_success(api.create_policy(
            factories.policy_payload(
                insured["id"], coverage_form="OCCURRENCE", retroactive_date=None
            ),
            UW,
        ), 201)
        assert policy["coverage_form"] == "OCCURRENCE"
        assert policy["retroactive_date"] is None
        assert _policy_count(api, insured["id"]) == 1


class TestReportDateAgainstTheIncidentDate:
    def test_report_date_one_day_before_the_incident_is_refused(self, api):
        """A claim reported the day before the incident it reports is refused.

        PRD: "Intake against an insured that does not exist yields `ERR_INSURED_NOT_FOUND`, and a claim whose `report_date` falls earlier than its `incident_date` is refused with `ERR_REPORT_DATE_BEFORE_INCIDENT`."

        Design: Corner/errors/claim_reported_before_the_incident_is_rejected
        """
        book = _in_force_book(api)

        response = api.create_claim(
            factories.claim_payload(
                book["insured"]["id"],
                incident_date="2026-09-02",
                report_date="2026-09-01",
            ),
            ADJ,
        )
        validate_error(
            response, ApiErrorId.ERR_REPORT_DATE_BEFORE_INCIDENT.value, 422
        )
        assert _claim_count(api, book["insured"]["id"]) == 0
        insured = validate_success(api.get_insured(book["insured"]["id"], UW))
        assert insured["open_claim_count"] == 0

    def test_report_on_the_incident_date_itself_is_accepted(self, api):
        """A same-day report sits on the inclusive bound and is taken in.

        PRD: "Intake against an insured that does not exist yields `ERR_INSURED_NOT_FOUND`, and a claim whose `report_date` falls earlier than its `incident_date` is refused with `ERR_REPORT_DATE_BEFORE_INCIDENT`."

        Design: Corner/errors/claim_reported_before_the_incident_is_rejected
        """
        book = _in_force_book(api)

        claim = validate_success(api.create_claim(
            factories.claim_payload(
                book["insured"]["id"],
                incident_date="2026-09-01",
                report_date="2026-09-01",
            ),
            ADJ,
        ), 201)
        assert claim["incident_date"] == "2026-09-01"
        assert claim["report_date"] == "2026-09-01"
        assert _claim_count(api, book["insured"]["id"]) == 1


class TestExperienceWindowBounds:
    def test_inverted_experience_window_is_refused(self, api):
        """An experience period whose end precedes its start never drafts.

        PRD: "The experience period must be coherent — the end strictly after the start, and the filing's effective date on or after the experience period end — or the draft is refused with `ERR_EXPERIENCE_PERIOD_INVALID`."

        Design: Corner/errors/rate_filing_experience_window_bounds_are_rejected_in_both_orders
        """
        specialty, _insured = _rated_class_and_insured(api, credentialed=False)

        response = api.create_rate_filing(
            factories.rate_filing_payload(
                specialty["id"],
                proposed_rate_change_pct=6.5,
                experience_period_start="2026-01-01",
                experience_period_end="2025-01-01",
                effective_date="2027-01-01",
            ),
            ANALYST,
        )
        validate_error(
            response, ApiErrorId.ERR_EXPERIENCE_PERIOD_INVALID.value, 422
        )
        assert _filing_count(api) == 0

    def test_filing_effective_before_the_experience_window_end_is_refused(self, api):
        """A filing taking effect before its own experience period closes is refused.

        PRD: "The experience period must be coherent — the end strictly after the start, and the filing's effective date on or after the experience period end — or the draft is refused with `ERR_EXPERIENCE_PERIOD_INVALID`."

        Design: Corner/errors/rate_filing_experience_window_bounds_are_rejected_in_both_orders
        """
        specialty, _insured = _rated_class_and_insured(api, credentialed=False)

        response = api.create_rate_filing(
            factories.rate_filing_payload(
                specialty["id"],
                proposed_rate_change_pct=6.5,
                experience_period_start="2024-01-01",
                experience_period_end="2026-01-01",
                effective_date="2025-12-31",
            ),
            ANALYST,
        )
        validate_error(
            response, ApiErrorId.ERR_EXPERIENCE_PERIOD_INVALID.value, 422
        )
        assert _filing_count(api) == 0

    def test_filing_effective_on_the_experience_window_end_is_accepted(self, api):
        """An effective date equal to the experience period end is on the bound.

        PRD: "The experience period must be coherent — the end strictly after the start, and the filing's effective date on or after the experience period end — or the draft is refused with `ERR_EXPERIENCE_PERIOD_INVALID`."

        Design: Corner/errors/rate_filing_experience_window_bounds_are_rejected_in_both_orders
        """
        specialty, _insured = _rated_class_and_insured(api, credentialed=False)

        filing = validate_success(api.create_rate_filing(
            factories.rate_filing_payload(
                specialty["id"],
                proposed_rate_change_pct=6.5,
                experience_period_start="2024-01-01",
                experience_period_end="2026-01-01",
                effective_date="2026-01-01",
            ),
            ANALYST,
        ), 201)
        assert filing["experience_period_end"] == "2026-01-01"
        assert filing["effective_date"] == "2026-01-01"
        assert _filing_count(api) == 1


class TestRenewalTermAdjacency:
    def _policy_with_one_term(self, api):
        _specialty, insured = _rated_class_and_insured(api)
        policy = fixtures.build_policy(api, insured["id"])
        first = fixtures.build_term(api, policy["id"], TERM_EFFECTIVE, TERM_EXPIRATION)
        current = validate_success(api.get_policy(policy["id"], UW))
        return policy, first, current["version"]

    def test_renewal_leaving_a_gap_after_the_predecessor_is_refused(self, api):
        """A renewal starting a month after its predecessor expires is refused.

        PRD: "When a predecessor is supplied, the new term's effective date must equal the predecessor's expiration date exactly — the step chain admits neither a gap nor a back-dated overlap — and any other value is refused with `ERR_TERM_PERIOD_GAP`."

        Design: Corner/errors/renewal_term_that_does_not_abut_its_predecessor_is_rejected_for_a_gap
        """
        policy, first, policy_version = self._policy_with_one_term(api)

        response = api.create_policy_term(
            policy["id"],
            factories.policy_term_payload(
                effective_date="2027-09-01",
                expiration_date="2028-09-01",
                predecessor_term_id=first["id"],
                expected_policy_version=policy_version,
            ),
            UW,
        )
        validate_error(response, ApiErrorId.ERR_TERM_PERIOD_GAP.value, 422)

        assert _term_count(api, policy["id"]) == 1
        after = validate_success(api.get_policy(policy["id"], UW))
        assert after["version"] == policy_version

    def test_renewal_abutting_the_predecessor_expiration_is_accepted(self, api):
        """A renewal effective exactly on the predecessor's expiration is accepted.

        PRD: "When a predecessor is supplied, the new term's effective date must equal the predecessor's expiration date exactly — the step chain admits neither a gap nor a back-dated overlap — and any other value is refused with `ERR_TERM_PERIOD_GAP`."

        Design: Corner/errors/renewal_term_that_does_not_abut_its_predecessor_is_rejected_for_a_gap
        """
        policy, first, policy_version = self._policy_with_one_term(api)

        renewal = validate_success(api.create_policy_term(
            policy["id"],
            factories.policy_term_payload(
                effective_date=TERM_EXPIRATION,
                expiration_date="2028-08-01",
                predecessor_term_id=first["id"],
                expected_policy_version=policy_version,
            ),
            UW,
        ), 201)
        assert renewal["effective_date"] == first["expiration_date"]
        assert renewal["term_index"] == 2
        assert _term_count(api, policy["id"]) == 2


class TestCancellationDateBoundaries:
    def test_flat_cancellation_off_the_inception_date_is_refused(self, api):
        """A flat cancellation dated a month after inception is refused.

        PRD: "A flat cancellation requires `cancel_effective_date` to equal the term's `effective_date` exactly; a pro-rata cancellation requires it to lie strictly after the effective date and strictly before the expiration date."

        Design: Corner/errors/cancellation_dates_off_the_branch_specific_boundaries_are_rejected
        """
        book = _in_force_book(api)

        response = api.cancel_policy_term(
            book["term"]["id"],
            factories.cancellation_payload("FLAT", "2026-09-01"),
            UW,
        )
        validate_error(response, ApiErrorId.ERR_CANCEL_DATE_INVALID.value, 422)

        after = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert after["status"] == "IN_FORCE"
        assert after["cancel_effective_date"] is None

    def test_pro_rata_cancellation_on_the_expiration_date_is_refused(self, api):
        """A pro-rata cancellation dated on the expiration bound is refused.

        PRD: "Either dating violation is refused with `ERR_CANCEL_DATE_INVALID`."

        Design: Corner/errors/cancellation_dates_off_the_branch_specific_boundaries_are_rejected
        """
        book = _in_force_book(api)

        response = api.cancel_policy_term(
            book["term"]["id"],
            factories.cancellation_payload("PRO_RATA", TERM_EXPIRATION),
            UW,
        )
        validate_error(response, ApiErrorId.ERR_CANCEL_DATE_INVALID.value, 422)

        after = validate_success(api.get_policy_term(book["term"]["id"], UW))
        assert after["status"] == "IN_FORCE"
        assert after["cancel_effective_date"] is None

    def test_interior_pro_rata_cancellation_returns_the_unearned_premium(self, api):
        """An interior pro-rata date cancels and returns 181 of the 365 days.

        PRD: "`IN_FORCE` → `CANCELLED_PRO_RATA` records the cancellation date and returns only the unearned portion of the premium: the term's whole span in calendar days is measured from `effective_date` to `expiration_date`, the unearned span is measured from `cancel_effective_date` to `expiration_date`, and `return_premium` is `premium_net` multiplied by the unearned span divided by the whole span, with that single ratio applied at full precision and the result rounded half up to two decimal places once."

        Design: Corner/errors/cancellation_dates_off_the_branch_specific_boundaries_are_rejected
        """
        book = _in_force_book(api)
        cancel_on = "2027-02-01"
        whole_span = (date.fromisoformat(TERM_EXPIRATION)
                      - date.fromisoformat(TERM_EFFECTIVE)).days
        unearned_span = (date.fromisoformat(TERM_EXPIRATION)
                         - date.fromisoformat(cancel_on)).days
        premium_net = float(book["term"]["premium_net"])

        cancelled = validate_success(api.cancel_policy_term(
            book["term"]["id"],
            factories.cancellation_payload("PRO_RATA", cancel_on),
            UW,
        ))
        assert cancelled["status"] == "CANCELLED_PRO_RATA"
        assert cancelled["cancel_effective_date"] == cancel_on
        assertions.assert_money(
            cancelled["return_premium"],
            round(premium_net * unearned_span / whole_span + 1e-9, 2),
            "return_premium",
        )


class TestTailApplicabilityAgainstTheCoverageForm:
    def test_tail_quoted_over_an_occurrence_policy_is_refused(self, api):
        """An occurrence policy cannot buy an extended reporting period.

        PRD: "Tails exist only on claims-made business — quoting one on an occurrence policy is refused with `ERR_TAIL_NOT_APPLICABLE`, since an occurrence form already answers for incidents reported after expiry."

        Design: Corner/errors/tail_endorsement_quoted_over_an_occurrence_policy_is_rejected
        """
        _specialty, insured = _rated_class_and_insured(api)
        policy = fixtures.build_policy(
            api, insured["id"], coverage_form="OCCURRENCE", retroactive_date=None
        )
        term = fixtures.build_expired_term(
            api, policy["id"], TERM_EFFECTIVE, TERM_EXPIRATION
        )
        assert term["status"] == "EXPIRED"

        response = api.create_tail_endorsement(
            policy["id"],
            factories.tail_endorsement_payload(
                triggering_term_id=term["id"],
                tail_type="ERP_5YR",
                trigger_reason="RETIREMENT",
                effective_date=TERM_EXPIRATION,
            ),
            UW,
        )
        validate_error(response, ApiErrorId.ERR_TAIL_NOT_APPLICABLE.value, 422)

        _rows, meta = validate_paginated(
            api.list_tail_endorsements(UW, {"policy_id": policy["id"]})
        )
        assert meta["total_count"] == 0


class TestGenericValidationOnDuplicatesAndZeroLengthTerms:
    def test_a_second_class_reusing_a_published_specialty_code_is_refused(self, api):
        """A specialty code already on the manual cannot be published twice.

        PRD: "The `specialty_code` must be unique across specialty classes; a duplicate is rejected with `ERR_VALIDATION`."

        Design: Corner/errors/duplicate_specialty_code_and_an_inverted_term_period_both_return_generic_validation
        """
        specialty, _insured = _rated_class_and_insured(api, credentialed=False)

        response = api.create_specialty_class(
            factories.specialty_class_payload(
                specialty_code=specialty["specialty_code"],
                base_class_code="CLASS_7",
                base_rate_per_million=41000.00,
                hazard_index=7.4,
                benchmark_severity=700000.00,
            ),
            CHIEF,
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        _rows, meta = validate_paginated(api.list_specialty_classes(ANALYST))
        assert meta["total_count"] == 1

    def test_a_term_expiring_on_its_effective_date_is_refused(self, api):
        """A zero-length term earns no cover and is refused generically.

        PRD: "The expiration date must be strictly after the effective date, or the request is refused with `ERR_VALIDATION`."

        Design: Corner/errors/duplicate_specialty_code_and_an_inverted_term_period_both_return_generic_validation
        """
        _specialty, insured = _rated_class_and_insured(api)
        policy = fixtures.build_policy(api, insured["id"])

        response = api.create_policy_term(
            policy["id"],
            factories.policy_term_payload(
                effective_date=TERM_EFFECTIVE,
                expiration_date=TERM_EFFECTIVE,
                expected_policy_version=policy["version"],
            ),
            UW,
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        assert _term_count(api, policy["id"]) == 0
        after = validate_success(api.get_policy(policy["id"], UW))
        assert after["version"] == policy["version"]
        assert after["status"] == "QUOTED"


class TestGenericValidationOnVotesAndSuitDating:
    @pytest.mark.parametrize("votes_for,votes_against", [(2, 3), (2, 2)])
    def test_a_committee_vote_without_a_majority_is_refused(
        self, api, votes_for, votes_against
    ):
        """Neither a losing nor a tied vote carries the committee.

        PRD: "The vote must carry a majority — `votes_for` strictly greater than `votes_against` — or it is refused with `ERR_VALIDATION`; a vote submitted from any status other than `REVIEWS_COMPLETE` is refused with `ERR_PEER_REVIEW_STATE_INVALID`."

        Design: Corner/errors/minority_committee_vote_and_a_backdated_suit_filing_both_return_generic_validation
        """
        _specialty, insured = _rated_class_and_insured(api)
        case = fixtures.build_reviews_complete_case(api, insured["id"])
        assert case["status"] == "REVIEWS_COMPLETE"

        response = api.record_committee_vote(
            case["id"],
            factories.committee_vote_payload(
                "DEVIATION_MINOR", votes_for=votes_for, votes_against=votes_against
            ),
            CHAIR,
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        after = validate_success(api.get_peer_review_case(case["id"], CHAIR))
        assert after["status"] == "REVIEWS_COMPLETE"
        assert after["committee_vote_result"] is None

    def test_a_suit_filed_the_day_before_the_report_is_refused(self, api):
        """A suit cannot be on file before the claim was ever reported.

        PRD: "The adjuster supplies `suit_filed_on`, which must be on or after the claim's `report_date` or the request is refused with `ERR_VALIDATION`; the claim must be in `INVESTIGATION`, or `ERR_CLAIM_STATE_INVALID` applies."

        Design: Corner/errors/minority_committee_vote_and_a_backdated_suit_filing_both_return_generic_validation
        """
        book = _in_force_book(api)
        claim = _covered_claim(api, book["insured"]["id"])

        response = api.record_litigation(
            claim["id"], factories.litigation_payload("2026-08-31"), ADJ
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        after = validate_success(api.get_claim(claim["id"], ADJ))
        assert after["claim_status"] == "INVESTIGATION"
        assert after["suit_filed_on"] is None

    def test_a_suit_filed_on_the_report_date_moves_the_claim_to_litigation(self, api):
        """Filing on the report date itself litigates and leaves cover alone.

        PRD: "`INVESTIGATION` → `LITIGATION` records the filing date and leaves `coverage_status` exactly as it was — a claim may litigate under a reservation of rights, and the two axes never move each other here."

        Design: Corner/errors/minority_committee_vote_and_a_backdated_suit_filing_both_return_generic_validation
        """
        book = _in_force_book(api)
        claim = _covered_claim(api, book["insured"]["id"])

        litigated = validate_success(api.record_litigation(
            claim["id"], factories.litigation_payload("2026-09-01"), ADJ
        ))
        assert litigated["claim_status"] == "LITIGATION"
        assert litigated["suit_filed_on"] == "2026-09-01"
        assert litigated["coverage_status"] == claim["coverage_status"]


class TestDataBankSubmissionDating:
    def _pending_obligation(self, api):
        """A paid indemnity settlement, and the reporting obligation it mints."""
        book = _in_force_book(api)
        claim = _covered_claim(api, book["insured"]["id"])
        negotiation = fixtures.build_authorised_negotiation(
            api, claim["id"], proposed_amount=400000.00,
            authority_requested=400000.00,
        )
        fixtures.advance_clock(api, "2026-10-15T00:00:00Z")
        fixtures.pay_settlement(api, negotiation["id"], "2026-10-15")
        rows, meta = validate_paginated(api.list_npdb_reports(
            COMPLIANCE, {"settlement_negotiation_id": negotiation["id"]}
        ))
        assert meta["total_count"] == 1
        return book, rows[0]

    def test_submission_dated_before_the_payment_is_refused(self, api):
        """An obligation cannot be reported as transmitted before the money moved.

        PRD: "The obligation must be in `PENDING`, or the request is refused with `ERR_NPDB_STATE_INVALID`, and `submitted_on` must be on or after the obligation's `payment_date` or it is refused with `ERR_NPDB_SUBMISSION_DATE_INVALID`."

        Design: Corner/errors/npdb_submission_before_the_payment_date_and_on_a_voided_report_are_both_rejected
        """
        _book, report = self._pending_obligation(api)
        assert report["report_status"] == "PENDING"

        response = api.submit_npdb_report(
            report["id"],
            factories.npdb_submission_payload(
                "2026-10-01", "transmitted before the money moved"
            ),
            COMPLIANCE,
        )
        validate_error(
            response, ApiErrorId.ERR_NPDB_SUBMISSION_DATE_INVALID.value, 422
        )

        after = validate_success(api.get_npdb_report(report["id"], COMPLIANCE))
        assert after["report_status"] == "PENDING"
        assert after["submitted_on"] is None

    def test_submission_on_a_voided_obligation_is_refused(self, api):
        """Once voided, even a well-dated submission is out of state.

        PRD: "The obligation must be in `PENDING`, or the request is refused with `ERR_NPDB_STATE_INVALID`, and `submitted_on` must be on or after the obligation's `payment_date` or it is refused with `ERR_NPDB_SUBMISSION_DATE_INVALID`."

        Design: Corner/errors/npdb_submission_before_the_payment_date_and_on_a_voided_report_are_both_rejected
        """
        book, report = self._pending_obligation(api)
        voided = fixtures.void_npdb_report(
            api, report["id"], "payment recharacterised as expense on review"
        )
        assert voided["report_status"] == "VOID"

        response = api.submit_npdb_report(
            report["id"],
            factories.npdb_submission_payload(
                "2026-10-20", "retransmission attempt on a voided obligation"
            ),
            COMPLIANCE,
        )
        validate_error(response, ApiErrorId.ERR_NPDB_STATE_INVALID.value, 409)

        after = validate_success(api.get_npdb_report(report["id"], COMPLIANCE))
        assert after["report_status"] == "VOID"
        assert after["submitted_on"] is None
        insured = validate_success(api.get_insured(book["insured"]["id"], UW))
        assertions.assert_money(
            insured["npdb_reported_payment_total"], 0.00,
            "npdb_reported_payment_total",
        )


class TestReserveDeficiencyGatesTheApprovalBranch:
    def _submitted_filing_over_a_reserveless_claim(self, api):
        """A submitted filing whose only scoped claim carries no reserves at all."""
        book = _in_force_book(api)
        claim = _covered_claim(api, book["insured"]["id"])
        filing = fixtures.build_submitted_filing(
            api, book["specialty"]["id"],
            proposed_rate_change_pct=8.00,
            experience_period_start=TERM_EFFECTIVE,
            experience_period_end=TERM_EXPIRATION,
            effective_date=TERM_EXPIRATION,
        )
        assert filing["status"] == "SUBMITTED"
        return book, claim, filing

    def test_approving_a_deficient_filing_is_refused(self, api):
        """No rate relief while the carried reserves are short of requirement.

        PRD: "An approval requires the filing to be `SUBMITTED`, requires the deciding `X-User-ID` to differ from `prepared_by_user_id`, and requires the filing's `adequacy_flag` not to be `DEFICIENT` — a deficiency must be cured and the filing resubmitted, and an attempt to approve a deficient filing is refused with `ERR_RESERVE_DEFICIENCY_BLOCKS_FILING`."

        Design: Corner/errors/approving_a_filing_whose_reserves_are_deficient_is_rejected_while_rejecting_it_is_allowed
        """
        _book, _claim, filing = self._submitted_filing_over_a_reserveless_claim(api)
        assert filing["adequacy_flag"] == "DEFICIENT"

        response = api.decide_rate_filing(
            filing["id"],
            factories.filing_decision_payload(
                "APPROVE", "approval attempt over a reserve deficiency"
            ),
            CHIEF,
        )
        validate_error(
            response, ApiErrorId.ERR_RESERVE_DEFICIENCY_BLOCKS_FILING.value, 409
        )

        after = validate_success(api.get_rate_filing(filing["id"], ANALYST))
        assert after["status"] == "SUBMITTED"
        assert after["adequacy_flag"] == "DEFICIENT"
        assert after["decided_by_user_id"] is None

    def test_the_required_reserve_is_loaded_demand_severity_and_venue(self, api):
        """The single scoped claim requires 668160.00 against nothing carried.

        PRD: "`required_reserve_total` is built by taking, for each claim in scope, the product of its `demand_amount`, its `severity_band_factor` and the venue severity factor for its own `venue_code`, multiplying that product by 1.28 (one plus the twenty-eight percent expense loading), rounding that per-claim figure half up to two decimal places, and only then summing the rounded per-claim figures."

        Design: Corner/errors/approving_a_filing_whose_reserves_are_deficient_is_rejected_while_rejecting_it_is_allowed
        """
        _book, _claim, filing = self._submitted_filing_over_a_reserveless_claim(api)

        assert filing["claim_count_in_scope"] == 1
        assertions.assert_money(
            filing["required_reserve_total"], 668160.00, "required_reserve_total"
        )
        assertions.assert_money(
            filing["carried_reserve_total"], 0.00, "carried_reserve_total"
        )

    def test_rejecting_a_deficient_filing_is_allowed(self, api):
        """The same deficient filing may be turned down outright.

        PRD: "A rejection requires only `SUBMITTED` status and the same segregation-of-duties separation; it records `decided_by_user_id` and the note and leaves `base_rate_per_million` untouched."

        Design: Corner/errors/approving_a_filing_whose_reserves_are_deficient_is_rejected_while_rejecting_it_is_allowed
        """
        book, _claim, filing = self._submitted_filing_over_a_reserveless_claim(api)

        decided = validate_success(api.decide_rate_filing(
            filing["id"],
            factories.filing_decision_payload(
                "REJECT", "reserves must be strengthened before any rate relief"
            ),
            CHIEF,
        ))
        assert decided["status"] == "REJECTED"
        assert decided["decided_by_user_id"] == OPERATOR_IDS["ChiefActuary"]
        assert decided["decision_note"] == (
            "reserves must be strengthened before any rate relief"
        )

        specialty = validate_success(
            api.get_specialty_class(book["specialty"]["id"], ANALYST)
        )
        assertions.assert_money(
            specialty["base_rate_per_million"], 38000.00, "base_rate_per_million"
        )
