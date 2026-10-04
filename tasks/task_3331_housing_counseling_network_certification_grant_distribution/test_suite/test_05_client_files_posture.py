"""Client files, file reviews, compliance posture, and congressional rollup."""
import pytest
from test_helpers import (
    TEST_USERS, ApiErrorId, validate_success, validate_error,
    validate_error_is_one_of,
    create_member, create_counselor, create_course, set_clock,
    setup_chartered_member_with_counselor, create_client_file,
    begin_counseling, record_outcome,
    make_member_admin_headers,
)

DIRECTOR = TEST_USERS["network_director_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]


class TestCrossEntityIntegrity:
    def test_cross_entity_counselor_member_mismatch(self, api):
        """PRD §3.7: "The counselor must belong to the file's member, or
        creation is rejected with `ERR_CROSS_ENTITY_MISMATCH`."
        PRD §2.7: "the counselor assigned to a client file must belong to the
        member organization that owns the file"

        Design: Corner/validations/cross_entity_counselor_member_mismatch
        """
        m1 = create_member(legal_name="Xref One", ein="400000003", state_code="CA",
                           service_regions=["06045"])
        m2 = create_member(legal_name="Xref Two", ein="400000004", state_code="CA",
                           service_regions=["06046"])
        c2 = create_counselor(m2["id"], full_name="Cx2", email="cx2@x.com")
        resp = api.create_client_file(
            {"member_id": m1["id"], "counselor_id": c2["id"],
             "program_area": "HOMEOWNERSHIP", "household_size": 2},
            make_member_admin_headers(m1["id"]))
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_MISMATCH)


class TestOutcomeHoursBoundary:
    def test_no_outcome_hours_zero_boundary(self, api):
        """PRD §3.7: "A file recorded with `NO_OUTCOME` must show at least 2.0
        hours of counseling; recording `NO_OUTCOME` with fewer hours is
        rejected with `ERR_OUTCOME_HOURS_INSUFFICIENT`."

        Design: Difficulty/boundary_precision_check/no_outcome_hours_zero_boundary
        """
        member, counselor, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Hours Housing", "ein": "999999901",
                              "state_code": "NV", "service_regions": ["32003"]},
            program_area="FINANCIAL_CAPABILITY", course_code="FC-601")
        fA = create_client_file(member, counselor, program_area="FINANCIAL_CAPABILITY",
                                household_size=3)
        fB = create_client_file(member, counselor, program_area="FINANCIAL_CAPABILITY",
                                household_size=2)
        begin_counseling(fA, member)
        begin_counseling(fB, member)

        respA = api.record_outcome(
            fA["id"], {"outcome_code": "NO_OUTCOME", "counseling_hours": 2.0},
            make_member_admin_headers(member["id"]))
        fileA = validate_success(respA)
        assert fileA["file_status"] == "OUTCOME_RECORDED"

        respB = api.record_outcome(
            fB["id"], {"outcome_code": "NO_OUTCOME", "counseling_hours": 1.9},
            make_member_admin_headers(member["id"]))
        validate_error(respB, ApiErrorId.ERR_OUTCOME_HOURS_INSUFFICIENT)
        fileB = validate_success(api.get_client_file(fB["id"], DIRECTOR))
        assert fileB["file_status"] == "COUNSELING"

    def test_real_outcome_below_hours_threshold_succeeds(self, api):
        """PRD §3.7: "The `outcome_code` is one of `PURCHASED_HOME`,
        `MORTGAGE_READY`, `RENTAL_STABILIZED`, `FORECLOSURE_AVERTED`,
        `BUDGET_PLAN_ADOPTED`, or `NO_OUTCOME`" — the 2.0-hour floor applies
        only to `NO_OUTCOME` ("A file recorded with `NO_OUTCOME` must show at
        least 2.0 hours of counseling").

        Design: Difficulty/boundary_precision_check/no_outcome_hours_zero_boundary
        """
        member, counselor, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Hours Two Housing", "ein": "999999902",
                              "state_code": "NV", "service_regions": ["32004"]},
            program_area="FINANCIAL_CAPABILITY", course_code="FC-602")
        f1 = create_client_file(member, counselor, program_area="FINANCIAL_CAPABILITY",
                                household_size=3)
        begin_counseling(f1, member)
        resp = api.record_outcome(
            f1["id"], {"outcome_code": "BUDGET_PLAN_ADOPTED", "counseling_hours": 0.5},
            make_member_admin_headers(member["id"]))
        file1 = validate_success(resp)
        assert file1["file_status"] == "OUTCOME_RECORDED"


class TestCertificationGatesCounseling:
    def test_client_file_gated_by_counselor_certification(self, api):
        """PRD §3.7: "Beginning counseling requires the assigned counselor to
        be `ACTIVE` and to hold a certification in `CERTIFIED` status whose
        program area matches the file's"
        PRD §3.3: "When the requirement is unmet, the certification lapses,
        moving from `CERTIFIED` to `LAPSED`"

        Design: Difficulty/cross_entity_state_dependency/client_file_gated_by_counselor_certification
        """
        member, counselor, certification = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Gate Housing", "ein": "123450001",
                              "state_code": "OR", "service_regions": ["41001"]},
            program_area="RENTAL", course_code="RE-701")
        f1 = create_client_file(member, counselor, program_area="RENTAL", household_size=4)
        f2 = create_client_file(member, counselor, program_area="RENTAL", household_size=1)

        f1 = begin_counseling(f1, member)
        assert f1["file_status"] == "COUNSELING"

        # Lapse the certification: advance past lapse_deadline with 0 CE credits.
        set_clock("2028-10-01T00:00:00Z")
        resp = api.evaluate_continuing_requirement(certification["id"],
                                                   TEST_USERS["training_registrar_headers"])
        lapsed = validate_success(resp)
        assert lapsed["certification_status"] == "LAPSED"

        resp = api.begin_counseling(f2["id"], make_member_admin_headers(member["id"]))
        # PRD §3.7 names ERR_CROSS_ENTITY_MISMATCH only for a program-area
        # mismatch; a lapsed certification (status gate) has no uniquely-named
        # error in PRD, so either the state gate or the cross-entity rule may fire.
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_CROSS_ENTITY_MISMATCH])
        f2_after = validate_success(api.get_client_file(f2["id"], DIRECTOR))
        assert f2_after["file_status"] == "OPEN"

    def test_begin_counseling_requires_active_counselor(self, api):
        """PRD §3.7: "Beginning counseling requires the assigned counselor to
        be `ACTIVE`"
        PRD §3.2: "a `NetworkDirector` may also suspend an `ACTIVE` counselor
        directly, and either path lapses every certification that counselor
        holds in `CERTIFIED` status, moving each to `LAPSED`."

        Design: Difficulty/cross_entity_state_dependency/client_file_gated_by_counselor_certification
        """
        member, counselor, certification = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Gate Two Housing", "ein": "123450008",
                              "state_code": "OR", "service_regions": ["41008"]},
            program_area="RENTAL", course_code="RE-702")
        f1 = create_client_file(member, counselor, program_area="RENTAL", household_size=2)

        resp = api.suspend_counselor(counselor["id"], DIRECTOR)
        validate_success(resp)
        resp = api.begin_counseling(f1["id"], make_member_admin_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        cert_after = validate_success(api.get_certification(
            certification["id"], TEST_USERS["training_registrar_headers"]))
        assert cert_after["certification_status"] == "LAPSED"


class TestFileReviewAndClose:
    def test_err_review_pending_blocks_close(self, api):
        """PRD §3.7: "Closing the file requires every file review against it to
        have reached `PASSED` or `REMEDIATED`; a close attempted while a review
        is still `OPEN` or `FAILED` is rejected with `ERR_REVIEW_PENDING`."
        PRD §3.7: "Passing the review stamps `reviewed_at` and recomputes the
        member's `open_finding_count`."

        Design: Corner/errors/err_review_pending_blocks_close
        """
        member, counselor, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Review Org", "ein": "600000001",
                              "state_code": "CA", "service_regions": ["06050"]},
            program_area="RENTAL", course_code="RE-511")
        f1 = create_client_file(member, counselor, program_area="RENTAL", household_size=3)
        begin_counseling(f1, member)
        record_outcome(f1, member, outcome_code="RENTAL_STABILIZED", counseling_hours=4.0)
        resp = api.create_file_review({"client_file_id": f1["id"]}, REVIEWER)
        review = validate_success(resp, expected_status=201)

        resp = api.close_client_file(f1["id"], make_member_admin_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_REVIEW_PENDING)

        resp = api.pass_file_review(review["id"], REVIEWER)
        review = validate_success(resp)
        assert review["review_status"] == "PASSED"

        resp = api.close_client_file(f1["id"], make_member_admin_headers(member["id"]))
        f1 = validate_success(resp)
        assert f1["file_status"] == "CLOSED"


class TestPostureImmediateConsistency:
    def test_immediate_visibility_of_cascade_in_same_read(self, api):
        """PRD §3.7: "Failing the review requires a non-empty list of
        `deficiency_codes`, stamps `reviewed_at`, increments the member's
        `open_finding_count` by one, and recomputes posture"
        PRD §3.7: "Otherwise, if there is at least one open finding, or the
        `failed_review_flag` is set, or the member's lapsed certifications
        exceed 2, the posture is `WATCH`."

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_read
        """
        member, counselor, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Imm Org", "ein": "900000001",
                              "state_code": "CA", "service_regions": ["06060"]},
            program_area="RENTAL", course_code="RE-911")
        f1 = create_client_file(member, counselor, program_area="RENTAL", household_size=2)
        begin_counseling(f1, member)
        record_outcome(f1, member, outcome_code="RENTAL_STABILIZED", counseling_hours=4.0)
        resp = api.create_file_review({"client_file_id": f1["id"]}, REVIEWER)
        review = validate_success(resp, expected_status=201)

        resp = api.fail_file_review(review["id"], {"deficiency_codes": ["MISSING_BUDGET_WORKSHEET"]}, REVIEWER)
        validate_success(resp)
        member_after = validate_success(api.get_member(member["id"], DIRECTOR))
        assert member_after["open_finding_count"] == 1
        assert member_after["compliance_posture"] == "WATCH"


class TestCongressionalRollup:
    def test_households_rollup_congressional_grouping(self, api):
        """PRD §3.8: "the count of the member's client files in
        `OUTCOME_RECORDED` or `CLOSED` status whose outcome code is recorded
        and is not `NO_OUTCOME` and whose `opened_on` falls within the federal
        fiscal-year window"
        PRD §3.8: "The report returns the `fiscal_year`, the
        `total_households` across those members, and the per-area breakdown in
        `by_program_area`."

        Design: Corner/calculations/households_rollup_congressional_grouping
        """
        member, counselor, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "Rollup Org", "ein": "300000001",
                              "state_code": "CA", "service_regions": ["06042"]},
            course_code="HO-211")
        set_clock("2038-11-01T00:00:00Z")  # inside FY2039 window [2038-10-01, 2039-10-01)

        f1 = create_client_file(member, counselor, program_area="HOMEOWNERSHIP", household_size=4)
        f2 = create_client_file(member, counselor, program_area="HOMEOWNERSHIP", household_size=2)
        f3 = create_client_file(member, counselor, program_area="HOMEOWNERSHIP", household_size=1)
        begin_counseling(f1, member)
        begin_counseling(f2, member)
        record_outcome(f1, member, outcome_code="PURCHASED_HOME", counseling_hours=5.0)
        record_outcome(f2, member, outcome_code="NO_OUTCOME", counseling_hours=3.0)
        # f3 stays OPEN.

        resp = api.get_congressional_report(2039, DIRECTOR)
        report = validate_success(resp)
        assert report["fiscal_year"] == 2039
        assert report["total_households"] == 1
        assert report["by_program_area"]["HOMEOWNERSHIP"] == 1
