"""State-precondition refusals down the claim, enrollment, tail, peer review and
defence-panel lifecycles (PRD 2.8 item 13, 3.3, 3.5, 3.6 and 3.7)."""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    assign_counsel,
    build_claim,
    build_counsel_firm,
    build_credentialed_insured,
    build_expired_term,
    build_in_force_term,
    build_insured,
    build_investigated_claim,
    build_peer_review_case,
    build_policy,
    build_specialty_class,
    build_tail,
    complete_enrolment,
    decline_assignment,
    enrol_insured,
    issue_tail,
)

TERM_EFFECTIVE = "2026-08-01"
TERM_EXPIRATION = "2027-08-01"
INCIDENT_DATE = "2026-08-05"
REPORT_DATE = "2026-09-01"


def _book_with_live_term(api):
    """A rating class, a credentialed insured and one live claims-made term."""
    specialty = build_specialty_class(api)
    insured = build_credentialed_insured(api, specialty["id"])
    policy = build_policy(api, insured["id"])
    term = build_in_force_term(api, policy["id"], TERM_EFFECTIVE, TERM_EXPIRATION)
    return {"specialty_class": specialty, "insured": insured, "policy": policy,
            "term": term}


def _covered_claim(api, insured_id):
    return build_investigated_claim(
        api, insured_id, "COVERED",
        incident_date=INCIDENT_DATE, report_date=REPORT_DATE,
    )


class TestCoverageAxisIsDecidedOnlyOnce:
    """The coverage axis admits exactly one adjuster call, and the handling axis
    guard answers ahead of it."""

    def test_claim_denied_by_the_intake_resolver_cannot_have_coverage_decided(
        self, api, claims_adjuster_headers
    ):
        """A claim the intake resolver denied for want of responding cover cannot be re-decided.

        PRD: "The claim's handling status must be `INTAKE` — any other handling status is refused with `ERR_CLAIM_STATE_INVALID` — and its current coverage position must be `UNDER_REVIEW` or `RESERVED_RIGHTS`; a claim already `COVERED` or `DENIED` cannot have coverage re-decided and the attempt is refused with `ERR_COVERAGE_ALREADY_DECIDED`."

        Design: Corner/errors/coverage_decision_on_a_claim_denied_at_intake_is_rejected_for_coverage_already_decided
        """
        specialty = build_specialty_class(api)
        insured = build_insured(api, specialty["id"])
        claim = build_claim(
            api, insured["id"],
            incident_date=INCIDENT_DATE, report_date=REPORT_DATE,
        )
        assert claim["coverage_status"] == "DENIED"
        assert claim["denial_reason"] == "NO_RESPONDING_COVERAGE"
        assert claim["claim_status"] == "INTAKE"
        assert claim["policy_term_id"] is None
        assert claim["tail_endorsement_id"] is None

        refused = api.record_coverage_decision(
            claim["id"],
            factories.coverage_decision_payload("COVERED"),
            claims_adjuster_headers,
        )
        validate_error(refused, ApiErrorId.ERR_COVERAGE_ALREADY_DECIDED.value, 409)

        standing = validate_success(api.get_claim(claim["id"], claims_adjuster_headers))
        assert standing["coverage_status"] == "DENIED"
        assert standing["denial_reason"] == "NO_RESPONDING_COVERAGE"
        assert standing["claim_status"] == "INTAKE"

    def test_second_coverage_decision_answers_the_handling_axis_guard(
        self, api, claims_adjuster_headers
    ):
        """A second coverage call after the axis advanced answers the handling-state guard first.

        PRD: "The claim's handling status must be `INTAKE` — any other handling status is refused with `ERR_CLAIM_STATE_INVALID` — and its current coverage position must be `UNDER_REVIEW` or `RESERVED_RIGHTS`; a claim already `COVERED` or `DENIED` cannot have coverage re-decided and the attempt is refused with `ERR_COVERAGE_ALREADY_DECIDED`."

        Design: Corner/errors/second_coverage_decision_after_the_handling_axis_advanced_is_rejected_for_claim_state
        """
        book = _book_with_live_term(api)
        claim = _covered_claim(api, book["insured"]["id"])
        assert claim["claim_status"] == "INVESTIGATION"
        assert claim["coverage_status"] == "COVERED"

        refused = api.record_coverage_decision(
            claim["id"],
            factories.coverage_decision_payload("DENIED"),
            claims_adjuster_headers,
        )
        validate_error(refused, ApiErrorId.ERR_CLAIM_STATE_INVALID.value, 409)

        standing = validate_success(api.get_claim(claim["id"], claims_adjuster_headers))
        assert standing["coverage_status"] == "COVERED"
        assert standing["denial_reason"] is None
        assert standing["claim_status"] == "INVESTIGATION"


class TestRiskProgramCompletionIsRecordedOnce:
    """A completed programme keeps the credit snapshot of its first completion."""

    def test_replayed_completion_leaves_the_first_credit_snapshot_intact(
        self, api, underwriting_officer_headers
    ):
        """A second completion on an already completed enrollment is refused and changes nothing.

        PRD: "Completion is recorded against an enrollment still in `ENROLLED` status — a completion recorded on an enrollment that is `COMPLETED` or `EXPIRED` is refused with `ERR_ENROLLMENT_STATE_INVALID`, and one addressed to an enrollment that does not exist with `ERR_ENROLLMENT_NOT_FOUND`."

        Design: Corner/errors/enrollment_completion_replayed_is_rejected_for_enrollment_state
        """
        specialty = build_specialty_class(api)
        insured = build_insured(api, specialty["id"])
        enrollment = enrol_insured(
            api, insured["id"], program_code="SIM_LAB", enrolled_on="2026-08-02"
        )
        complete_enrolment(
            api, enrollment["id"],
            completed_on="2026-08-10", attestation_reference="SIM-2026-0001",
        )

        refused = api.complete_enrollment(
            enrollment["id"],
            factories.enrollment_completion_payload(
                completed_on="2026-08-20", attestation_reference="SIM-2026-0002"
            ),
            underwriting_officer_headers,
        )
        validate_error(refused, ApiErrorId.ERR_ENROLLMENT_STATE_INVALID.value, 409)

        standing = validate_success(
            api.get_enrollment(enrollment["id"], underwriting_officer_headers)
        )
        assert standing["status"] == "COMPLETED"
        assert standing["completed_on"] == "2026-08-10"
        assert standing["attestation_reference"] == "SIM-2026-0001"
        assertions.assert_ratio(
            standing["credit_pct_snapshot"], 0.05, "credit_pct_snapshot"
        )
        assert standing["expires_on"] == assertions.days_after("2026-08-10", 730)


class TestTailEndorsementIssuedOnce:
    """A second issuance of the same endorsement trips the tail state guard."""

    def test_replayed_tail_issuance_is_refused_for_tail_state(
        self, api, underwriting_officer_headers
    ):
        """Re-issuing an endorsement already ISSUED is refused for tail state, not for a live sibling.

        PRD: "Issuing a tail takes no payload and requires `QUOTED` status; any other status is refused with `ERR_TAIL_STATE_INVALID`, and an unknown endorsement with `ERR_TAIL_ENDORSEMENT_NOT_FOUND`."

        Design: Corner/errors/tail_issuance_replayed_is_rejected_for_tail_state_not_for_already_issued
        """
        specialty = build_specialty_class(api)
        insured = build_credentialed_insured(api, specialty["id"])
        policy = build_policy(api, insured["id"])
        term = build_expired_term(api, policy["id"], TERM_EFFECTIVE, TERM_EXPIRATION)
        assert term["status"] == "EXPIRED"

        tail = build_tail(
            api, policy["id"], term["id"],
            tail_type="ERP_5YR", trigger_reason="PRACTICE_CLOSURE",
            effective_date=TERM_EXPIRATION,
        )
        issue_tail(api, tail["id"])

        refused = api.issue_tail_endorsement(tail["id"], underwriting_officer_headers)
        validate_error(refused, ApiErrorId.ERR_TAIL_STATE_INVALID.value, 409)

        standing = validate_success(
            api.get_tail_endorsement(tail["id"], underwriting_officer_headers)
        )
        assert standing["status"] == "ISSUED"
        assert float(standing["tail_factor"]) == pytest.approx(1.55, abs=0.0001)
        assert standing["reporting_window_end"] == "2032-07-31"


class TestDeclinedAssignmentIsClosedToFurtherWork:
    """A declined assignment neither bills expense nor declines twice."""

    @staticmethod
    def _claim_with_declined_assignment(api):
        book = _book_with_live_term(api)
        firm = build_counsel_firm(
            api,
            firm_name="Halloran Defense LLP",
            admitted_venue_codes=["COOK_IL"],
            allegation_specialties=["OBSTETRIC_INJURY"],
            blended_hourly_rate=500.00,
            quality_score=95,
            max_concurrent_assignments=5,
            conflict_insured_ids=[],
        )
        claim = _covered_claim(api, book["insured"]["id"])
        assignment = assign_counsel(api, claim["id"])
        declined = decline_assignment(api, assignment["id"], "CONFLICT_OF_INTEREST")
        return {"firm": firm, "claim": claim, "assignment": declined}

    def test_expense_payment_against_a_declined_assignment_is_refused(
        self, api, claims_adjuster_headers, claims_committee_approver_headers
    ):
        """Defence expense cannot be billed under an assignment the firm has declined.

        PRD: "The named assignment must exist (`ERR_COUNSEL_ASSIGNMENT_NOT_FOUND`), must belong to the addressed claim rather than another one (`ERR_ASSIGNMENT_CLAIM_MISMATCH`), and must still be in `ASSIGNED` status (`ERR_ASSIGNMENT_STATE_INVALID`)."

        Design: Corner/errors/expense_payment_and_a_second_decline_on_a_declined_assignment_are_rejected
        """
        bundle = self._claim_with_declined_assignment(api)

        refused = api.pay_expense(
            bundle["claim"]["id"],
            factories.expense_payment_payload(
                amount=5000.00,
                invoice_reference="INV-2026-0009",
                counsel_assignment_id=bundle["assignment"]["id"],
            ),
            claims_adjuster_headers,
        )
        validate_error(refused, ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID.value, 409)

        claim = validate_success(
            api.get_claim(bundle["claim"]["id"], claims_adjuster_headers)
        )
        assertions.assert_money(claim["paid_expense"], 0, "paid_expense")
        assignment = validate_success(
            api.get_counsel_assignment(
                bundle["assignment"]["id"], claims_adjuster_headers
            )
        )
        assertions.assert_money(
            assignment["billed_expense_amount"], 0, "billed_expense_amount"
        )
        firm = validate_success(
            api.get_counsel_firm(
                bundle["firm"]["id"], claims_committee_approver_headers
            )
        )
        assertions.assert_money(
            firm["billed_expense_total"], 0, "billed_expense_total"
        )
        assert firm["open_assignment_count"] == 0

    def test_second_decline_on_a_declined_assignment_is_refused(
        self, api, claims_adjuster_headers, claims_committee_approver_headers
    ):
        """A firm cannot decline the same matter twice, and its first reason stands.

        PRD: "The adjuster records a decline against an assignment in `ASSIGNED` status — any other status is refused with `ERR_ASSIGNMENT_STATE_INVALID` — supplying a `decline_reason` of `CONFLICT_OF_INTEREST`, `CAPACITY`, `RATE_DISPUTE` or `EXPERTISE_MISMATCH`."

        Design: Corner/errors/expense_payment_and_a_second_decline_on_a_declined_assignment_are_rejected
        """
        bundle = self._claim_with_declined_assignment(api)

        refused = api.decline_counsel_assignment(
            bundle["assignment"]["id"],
            factories.decline_payload("CAPACITY"),
            claims_adjuster_headers,
        )
        validate_error(refused, ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID.value, 409)

        assignment = validate_success(
            api.get_counsel_assignment(
                bundle["assignment"]["id"], claims_adjuster_headers
            )
        )
        assert assignment["assignment_status"] == "DECLINED"
        assert assignment["decline_reason"] == "CONFLICT_OF_INTEREST"
        claim = validate_success(
            api.get_claim(bundle["claim"]["id"], claims_adjuster_headers)
        )
        assert claim["counsel_reassignment_required"] is True
        firm = validate_success(
            api.get_counsel_firm(
                bundle["firm"]["id"], claims_committee_approver_headers
            )
        )
        assert firm["open_assignment_count"] == 0


class TestPeerReviewTracksAreRecordedOnce:
    """Each of the two review tracks lands at most once on a case."""

    def test_repeating_the_chart_track_is_refused(self, api, peer_review_chair_headers):
        """A chart review already on the case cannot be recorded a second time.

        PRD: "Recording a track that has already been recorded on the case is refused with `ERR_REVIEW_TRACK_ALREADY_RECORDED`, and recording a track on a case that is neither `REFERRED` nor `IN_REVIEW` is refused with `ERR_PEER_REVIEW_STATE_INVALID`."

        Design: Corner/errors/duplicate_review_track_on_a_peer_review_case_is_rejected
        """
        specialty = build_specialty_class(api)
        insured = build_insured(api, specialty["id"])
        case = build_peer_review_case(
            api, insured["id"],
            trigger_source="SENTINEL_EVENT",
            referral_note="unexpected neonatal outcome",
        )
        validate_success(api.record_review_track(
            case["id"],
            factories.review_track_payload("CHART", "CONCERN"),
            peer_review_chair_headers,
        ))

        refused = api.record_review_track(
            case["id"],
            factories.review_track_payload("CHART", "NO_CONCERN"),
            peer_review_chair_headers,
        )
        validate_error(refused, ApiErrorId.ERR_REVIEW_TRACK_ALREADY_RECORDED.value, 409)

        standing = validate_success(
            api.get_peer_review_case(case["id"], peer_review_chair_headers)
        )
        assert standing["status"] == "IN_REVIEW"
        assert standing["chart_review_outcome"] == "CONCERN"
        assert standing["external_review_outcome"] is None


class TestOneLiveCounselAssignmentPerClaim:
    """A claim already holding a live assignment refuses a second selector run."""

    def test_second_assignment_on_the_same_claim_is_refused(
        self, api, claims_adjuster_headers, claims_committee_approver_headers
    ):
        """A claim with counsel already assigned refuses a second assignment though a rival firm qualifies.

        PRD: "And a claim may hold only one live assignment: if it already has an assignment in `ASSIGNED` status, the request is refused with `ERR_COUNSEL_ALREADY_ASSIGNED`."

        Design: Corner/errors/second_counsel_assignment_on_the_same_claim_is_rejected
        """
        book = _book_with_live_term(api)
        firm_alpha = build_counsel_firm(
            api,
            firm_name="Alpha Defense LLP",
            admitted_venue_codes=["COOK_IL"],
            allegation_specialties=["OBSTETRIC_INJURY"],
            blended_hourly_rate=500.00,
            quality_score=95,
            max_concurrent_assignments=5,
            conflict_insured_ids=[],
        )
        firm_beta = build_counsel_firm(
            api,
            firm_name="Beta Defense LLP",
            admitted_venue_codes=["COOK_IL"],
            allegation_specialties=["OBSTETRIC_INJURY"],
            blended_hourly_rate=400.00,
            quality_score=90,
            max_concurrent_assignments=5,
            conflict_insured_ids=[],
        )
        claim = _covered_claim(api, book["insured"]["id"])
        assignment = assign_counsel(api, claim["id"])

        refused = api.create_counsel_assignment(claim["id"], claims_adjuster_headers)
        validate_error(refused, ApiErrorId.ERR_COUNSEL_ALREADY_ASSIGNED.value, 409)

        assignments, meta = validate_paginated(
            api.list_counsel_assignments(
                claims_adjuster_headers, {"claim_id": claim["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert len(assignments) == 1
        assert assignment["counsel_firm_id"] == firm_alpha["id"]
        assert assignment["candidate_pool_size"] == 2
        alpha = validate_success(
            api.get_counsel_firm(firm_alpha["id"], claims_committee_approver_headers)
        )
        beta = validate_success(
            api.get_counsel_firm(firm_beta["id"], claims_committee_approver_headers)
        )
        assert alpha["open_assignment_count"] == 1
        assert beta["open_assignment_count"] == 0


class TestEmptyCounselPool:
    """A panel with nobody admitted in the claim's venue offers no candidate."""

    def test_assignment_with_no_firm_admitted_in_the_venue_is_refused(
        self, api, claims_adjuster_headers, claims_committee_approver_headers
    ):
        """A Cook County claim finds no counsel when the only panel firm sits in Kings County.

        PRD: "An empty pool is refused with `ERR_NO_ELIGIBLE_COUNSEL`."

        Design: Corner/errors/counsel_assignment_with_no_firm_admitted_in_the_venue_is_rejected
        """
        book = _book_with_live_term(api)
        firm = build_counsel_firm(
            api,
            firm_name="Brooklyn Defense LLP",
            admitted_venue_codes=["KINGS_NY"],
            allegation_specialties=["OBSTETRIC_INJURY"],
            blended_hourly_rate=450.00,
            quality_score=92,
            max_concurrent_assignments=5,
            conflict_insured_ids=[],
        )
        claim = _covered_claim(api, book["insured"]["id"])

        refused = api.create_counsel_assignment(claim["id"], claims_adjuster_headers)
        validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_COUNSEL.value, 409)

        assignments, meta = validate_paginated(
            api.list_counsel_assignments(
                claims_adjuster_headers, {"claim_id": claim["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert assignments == []
        standing_firm = validate_success(
            api.get_counsel_firm(firm["id"], claims_committee_approver_headers)
        )
        assert standing_firm["open_assignment_count"] == 0
        standing_claim = validate_success(
            api.get_claim(claim["id"], claims_adjuster_headers)
        )
        assert standing_claim["coverage_status"] == "COVERED"
        assert standing_claim["excluded_counsel_firm_ids"] == []
        assert standing_claim["counsel_reassignment_required"] is False
