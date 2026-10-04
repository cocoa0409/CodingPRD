"""Performance reviews, corrective action, and member revocation cascades."""
import pytest
from test_helpers import (
    TEST_USERS, ApiErrorId, validate_success, validate_error, get_success_data,
    create_member, set_clock,
    setup_chartered_member_with_counselor, create_grant_cycle,
    create_grant_application, submit_application, advance_cycle_to_awarded,
    award_application, setup_cycle_with_award, setup_member_in_probation,
)

DIRECTOR = TEST_USERS["network_director_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]
REGISTRAR = TEST_USERS["training_registrar_headers"]


class TestPerformanceReviewFork:
    def test_performance_review_branching_fork(self, api):
        """PRD §3.8: "A score of at least 70 resolves the review as
        `SATISFACTORY`, a terminal state with no further side effects. A score
        below 70 resolves to `CORRECTIVE_ACTION`, which sets
        `corrective_plan_due` to the current logical clock plus 60 days, sets
        the member's `failed_review_flag` to true, and recomputes posture."
        PRD §3.7: "Otherwise, if there is at least one open finding, or the
        `failed_review_flag` is set, or the member's lapsed certifications
        exceed 2, the posture is `WATCH`."

        Design: Difficulty/non_linear_state_machine/performance_review_branching_fork
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Fork Housing", "ein": "666666662",
                              "state_code": "FL", "service_regions": ["12002"]},
            program_area="FINANCIAL_CAPABILITY", course_code="FC-101")
        r_pass = validate_success(api.create_performance_review(
            {"member_id": member["id"], "review_period": "FY2027-H1"}, DIRECTOR), expected_status=201)
        r_fail = validate_success(api.create_performance_review(
            {"member_id": member["id"], "review_period": "FY2027-H2"}, DIRECTOR), expected_status=201)
        api.score_performance_review(r_pass["id"], {"review_score": 90}, DIRECTOR)
        api.score_performance_review(r_fail["id"], {"review_score": 40}, DIRECTOR)

        resp = api.resolve_performance_review(r_pass["id"], {"verdict": "SATISFACTORY"}, DIRECTOR)
        r_pass = validate_success(resp)
        assert r_pass["review_status"] == "SATISFACTORY"

        resp = api.resolve_performance_review(r_fail["id"], {"verdict": "CORRECTIVE_ACTION"}, DIRECTOR)
        r_fail = validate_success(resp)
        assert r_fail["review_status"] == "CORRECTIVE_ACTION"
        assert r_fail["corrective_plan_due"] is not None

        member_after = validate_success(api.get_member(member["id"], DIRECTOR))
        assert member_after["failed_review_flag"] is True
        assert member_after["compliance_posture"] == "WATCH"

    def test_satisfactory_branch_leaves_member_untouched(self, api):
        """PRD §3.8: "A score of at least 70 resolves the review as
        `SATISFACTORY`, a terminal state with no further side effects."

        Design: Difficulty/non_linear_state_machine/performance_review_branching_fork
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Fork Two Housing", "ein": "666666664",
                              "state_code": "FL", "service_regions": ["12004"]},
            program_area="FINANCIAL_CAPABILITY", course_code="FC-102")
        review = validate_success(api.create_performance_review(
            {"member_id": member["id"], "review_period": "FY2028-H1"}, DIRECTOR), expected_status=201)
        api.score_performance_review(review["id"], {"review_score": 85}, DIRECTOR)
        resp = api.resolve_performance_review(review["id"], {"verdict": "SATISFACTORY"}, DIRECTOR)
        review = validate_success(resp)
        assert review["review_status"] == "SATISFACTORY"
        member_after = validate_success(api.get_member(member["id"], DIRECTOR))
        assert member_after["failed_review_flag"] is False
        assert member_after["compliance_posture"] == "CLEAR"


class TestApplicationSubmitCycleGate:
    def test_application_submit_gated_by_cycle_phase(self, api):
        """PRD §3.4: "Submitting the draft is allowed only while the cycle is
        `OPEN` — a submission against a cycle that has moved on is rejected
        with `ERR_WINDOW_CLOSED`"

        Design: Difficulty/cross_entity_state_dependency/application_submit_gated_by_cycle_phase
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Phase Housing", "ein": "123450002",
                              "state_code": "OR", "service_regions": ["41002"]},
            course_code="HO-701")
        cycle = create_grant_cycle(fiscal_year=2035, formula_pool_cents=100000,
                                   competitive_pool_cents=0)
        app = create_grant_application(
            cycle, member, requested_formula_cents=10000,
            requested_competitive_cents=0, pledged_match_cents=5000)
        resp = api.lock_formula(cycle["id"], OFFICER)
        validate_success(resp)

        from test_helpers import make_member_admin_headers
        resp = api.submit_application(app["id"], make_member_admin_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_WINDOW_CLOSED)
        app_after = validate_success(api.get_grant_application(app["id"], OFFICER))
        assert app_after["application_status"] == "DRAFT"

    def test_submit_before_lock_succeeds_and_moves_under_review_on_lock(self, api):
        """PRD §3.4: "When the `GrantOfficer` locks the formula phase, the
        cycle moves from `OPEN` to `FORMULA_LOCKED`, every submitted
        application in the cycle moves to `UNDER_REVIEW`, and the cycle's
        `version` increments."

        Design: Difficulty/cross_entity_state_dependency/application_submit_gated_by_cycle_phase
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Phase Two Housing", "ein": "123450009",
                              "state_code": "OR", "service_regions": ["41009"]},
            course_code="HO-702")
        cycle = create_grant_cycle(fiscal_year=2060, formula_pool_cents=100000,
                                   competitive_pool_cents=0)
        app = create_grant_application(
            cycle, member, requested_formula_cents=10000,
            requested_competitive_cents=0, pledged_match_cents=5000)
        app = submit_application(app, member)
        assert app["application_status"] == "SUBMITTED"

        resp = api.lock_formula(cycle["id"], OFFICER)
        validate_success(resp)
        app_after = validate_success(api.get_grant_application(app["id"], OFFICER))
        assert app_after["application_status"] == "UNDER_REVIEW"


class TestMemberRevocationCascade:
    def test_member_revocation_three_level_cascade(self, api):
        """PRD §3.1: "Revocation is the member's terminal state and cascades
        forcefully: every grant award of the member in `DISBURSING`, `ACTIVE`,
        or `SUSPENDED` status transitions to `TERMINATED`; every counselor of
        the member in `ACTIVE` status transitions to `SUSPENDED`; and every
        certification in `CERTIFIED` status held by those counselors
        transitions to `REVOKED`."

        Design: Difficulty/transitive_cascade/member_revocation_three_level_cascade
        """
        member, counselor, certification = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Revoke Housing", "ein": "777777772",
                              "state_code": "GA", "service_regions": ["13002"]},
            program_area="FORECLOSURE_PREVENTION", course_code="FP-101")
        # Active award against the member while still CHARTERED (PRD §3.4 gates
        # submission on charter_status == CHARTERED).
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=2031, formula_pool_cents=100000,
            requested_formula_cents=50000, verify_match_cents=12500)
        assert award["award_status"] == "ACTIVE"

        # Drive the member to PROBATION via an overdue corrective plan (PRD §3.8),
        # since only a PROBATION member may be revoked (PRD §3.1).
        review = validate_success(api.create_performance_review(
            {"member_id": member["id"], "review_period": "FY2031-H1"}, DIRECTOR),
            expected_status=201)
        api.score_performance_review(review["id"], {"review_score": 30}, DIRECTOR)
        review = validate_success(api.resolve_performance_review(
            review["id"], {"verdict": "CORRECTIVE_ACTION"}, DIRECTOR))
        set_clock("2027-01-01T00:00:00Z")
        validate_success(api.escalate_performance_review(review["id"], DIRECTOR))

        resp = api.revoke_member(
            member["id"], {"revocation_reason": "Repeated non-compliance"}, DIRECTOR)
        member_after = validate_success(resp)
        assert member_after["charter_status"] == "REVOKED"

        award_after = validate_success(api.get_grant_award(award["id"], OFFICER))
        assert award_after["award_status"] == "TERMINATED"
        counselor_after = validate_success(api.get_counselor(counselor["id"], REGISTRAR))
        assert counselor_after["counselor_status"] == "SUSPENDED"
        cert_after = validate_success(api.get_certification(certification["id"], REGISTRAR))
        assert cert_after["certification_status"] == "REVOKED"

    def test_revocation_records_reason_and_is_terminal(self, api):
        """PRD §3.1: "A `NetworkDirector` may revoke the charter of a
        `PROBATION` member, recording the supplied `revocation_reason`.
        Revocation is the member's terminal state"

        Design: Difficulty/transitive_cascade/member_revocation_three_level_cascade
        """
        member, counselor, certification, review = setup_member_in_probation(
            member_overrides={"legal_name": "Revoke Two Housing", "ein": "777777774",
                              "state_code": "GA", "service_regions": ["13004"]},
            course_code="FP-102", review_period="FY2032-H1",
            escalate_at="2027-01-01T00:00:00Z")
        resp = api.revoke_member(
            member["id"], {"revocation_reason": "Audit failures"}, DIRECTOR)
        member_after = validate_success(resp)
        assert member_after["charter_status"] == "REVOKED"
        assert member_after["revocation_reason"] == "Audit failures"

        # Terminal: a further revoke attempt is an invalid transition.
        resp = api.revoke_member(
            member["id"], {"revocation_reason": "again"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
