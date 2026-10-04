"""RBAC, segregation of duties, and optimistic concurrency control."""
import pytest
from test_helpers import (
    TEST_USERS, ApiErrorId, validate_success, validate_error, get_success_data,
    create_member, create_member_under_assessment, create_counselor,
    create_course, set_clock, setup_chartered_member_with_counselor,
    create_grant_cycle, create_grant_application, submit_application,
    advance_cycle_to_awarded, award_application, setup_cycle_with_award,
    submit_expenditure_report, flag_report_and_get_audit,
    make_member_admin_headers, make_assessor_headers,
    make_network_director_headers, make_grant_officer_headers,
)

DIRECTOR = TEST_USERS["network_director_headers"]
ASSESSOR = TEST_USERS["assessor_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting an
        `X-User-Role` that is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.list_members(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRbacDenials:
    def test_assessor_cannot_adjudicate(self, api):
        """PRD §2.1: "A request whose role is declared but not permitted for
        the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: adjudication is authorized for "NetworkDirector" only.

        Design: Corner/rbac/assessor_cannot_adjudicate
        """
        member, assessment = create_member_under_assessment(
            member_overrides={"legal_name": "RBAC Org", "ein": "700000001",
                              "state_code": "CA", "service_regions": ["06052"]},
            assessor_headers=make_assessor_headers("u-assessor-rb"),
            director_user_id="u-director-rb",
            governance_score=90, finance_score=90, program_capacity_score=90)
        assert assessment["assessment_status"] == "SCORED"

        resp = api.adjudicate_assessment(
            assessment["id"], {"site_visit_adjustment": 0}, ASSESSOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
        after = validate_success(api.get_assessment(assessment["id"], ASSESSOR))
        assert after["assessment_status"] == "SCORED"

    def test_grant_officer_cannot_audit(self, api):
        """PRD §2.1: "the `Auditor` conducts expenditure audits and is
        deliberately segregated from the `GrantOfficer` who flags reports."
        PRD §2.1: "A request whose role is declared but not permitted for the
        targeted endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/grant_officer_cannot_audit
        """
        member, cycle, award = self._setup_flagged_award(api, ein="700000002",
                                                         region="06053", fy=2045,
                                                         course_code="HO-611")
        resp = api.list_compliance_audits(AUDITOR, params={"award_id": award["id"]})
        audits = get_success_data(resp)
        audit = audits[0]

        resp = api.issue_audit_findings(audit["id"], {"disallowance_cents": 0}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
        after = validate_success(api.get_compliance_audit(audit["id"], AUDITOR))
        assert after["audit_status"] == "OPEN"

    def _setup_flagged_award(self, api, ein, region, fy, course_code):
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "RBAC2 Org", "ein": ein,
                              "state_code": "CA", "service_regions": [region]},
            course_code=course_code)
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=fy, formula_pool_cents=100000,
            requested_formula_cents=40000, activate=False)
        report = submit_expenditure_report(
            award, member, period_start="2026-10-01T00:00:00Z",
            period_end="2026-10-31T00:00:00Z", reported_spent_cents=100)
        flag_report_and_get_audit(report)
        return member, cycle, award


class TestSegregationOfDuties:
    def test_segregation_of_duties_same_user_score_blocked(self, api):
        """PRD §2.1: "the operator who countersigns an assessment's scores must differ from the one who submitted them"
        PRD §2.1: "A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.1: "the director who countersigns must not be the assessor who
        submitted; if they are the same operator the countersign is rejected
        with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_same_user_score_blocked
        """
        member = create_member(legal_name="SoD Org", ein="700000003",
                               state_code="CA", service_regions=["06054"])
        assessor = make_assessor_headers("u-shared-1")
        resp = api.begin_assessment(member["id"], assessor)
        assessment = validate_success(resp, expected_status=201)
        resp = api.submit_assessment(
            assessment["id"],
            {"governance_score": 90, "finance_score": 90, "program_capacity_score": 90},
            assessor)
        assessment = validate_success(resp)
        assert assessment["assessment_status"] == "SUBMITTED"

        # Same X-User-ID, now acting as NetworkDirector, attempts countersign.
        resp = api.score_assessment(
            assessment["id"], make_network_director_headers("u-shared-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        after = validate_success(api.get_assessment(assessment["id"], DIRECTOR))
        assert after["assessment_status"] == "SUBMITTED"


class TestOptimisticConcurrency:
    def test_stale_cycle_version_conflict(self, api):
        """PRD §2.8: "If the cycle's current `version` has advanced since the
        client read it — for example because the formula phase was locked or
        another application was created against the cycle — the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "successfully creating an application itself increments the
        cycle's `version` by one, so two applications drafted against the same
        observed version cannot both succeed without the second re-reading the
        cycle."

        Design: Corner/cross_cutting_layers/stale_cycle_version_conflict
        """
        m1, _c1, _cert1 = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "OCC One", "ein": "800000001",
                              "state_code": "CA", "service_regions": ["06055"]},
            course_code="HO-711")
        m2, _c2, _cert2 = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "OCC Two", "ein": "800000002",
                              "state_code": "CA", "service_regions": ["06056"]},
            course_code="HO-712")
        cycle = create_grant_cycle(fiscal_year=2046, formula_pool_cents=100000,
                                   competitive_pool_cents=0)
        observed_version = cycle["version"]

        resp = api.create_grant_application(
            {"cycle_id": cycle["id"], "member_id": m1["id"], "program_area": "HOMEOWNERSHIP",
             "requested_formula_cents": 1000, "requested_competitive_cents": 0,
             "pledged_match_cents": 500, "expected_cycle_version": observed_version},
            make_member_admin_headers(m1["id"]))
        validate_success(resp, expected_status=201)

        resp = api.create_grant_application(
            {"cycle_id": cycle["id"], "member_id": m2["id"], "program_area": "HOMEOWNERSHIP",
             "requested_formula_cents": 1000, "requested_competitive_cents": 0,
             "pledged_match_cents": 500, "expected_cycle_version": observed_version},
            make_member_admin_headers(m2["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_stale_award_version_on_activate(self, api):
        """PRD §2.8: "Activating a grant award requires the non-optional field
        `expected_award_version`, carrying the client-observed `version` of the
        award. If the award's current `version` has advanced — because a match
        verification or a clawback adjusting entry mutated it in the meantime —
        the activation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/stale_award_version_on_activate
        """
        member, _c, _cert = setup_chartered_member_with_counselor(
            member_overrides={"legal_name": "OCC Award Org", "ein": "800000003",
                              "state_code": "CA", "service_regions": ["06057"]},
            course_code="HO-713")
        cycle, _app, award = setup_cycle_with_award(
            member, fiscal_year=2047, formula_pool_cents=100000,
            requested_formula_cents=40000, activate=False)
        stale_version = award["version"]

        resp = api.verify_match(award["id"], {"additional_match_cents": 4000}, OFFICER)
        award = validate_success(resp)
        assert award["version"] == stale_version + 1

        resp = api.activate_award(award["id"], {"expected_award_version": stale_version}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        resp = api.activate_award(award["id"], {"expected_award_version": award["version"]}, OFFICER)
        award = validate_success(resp)
        assert award["award_status"] == "ACTIVE"


class TestFkFilteredLists:
    def test_fk_reverse_reachability_lists(self, api):
        """PRD §4: "List applications, filterable by `cycle_id`, `member_id`, `application_status`"
        PRD §4: "List disbursements, filterable by `award_id`, `disbursement_status`"
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        member = create_member(legal_name="FK Org", ein="500000002",
                               state_code="CA", service_regions=["06049"])
        cycle = create_grant_cycle(fiscal_year=2043, formula_pool_cents=100000,
                                   competitive_pool_cents=0)
        app = create_grant_application(
            cycle, member, program_area="RENTAL", requested_formula_cents=1000,
            requested_competitive_cents=0, pledged_match_cents=500)

        from test_helpers import validate_paginated
        data, meta = validate_paginated(
            api.list_grant_applications(OFFICER, params={"cycle_id": cycle["id"]}))
        assert len(data) == 1
        assert data[0]["id"] == app["id"]

        data2, meta2 = validate_paginated(
            api.list_disbursements(OFFICER, params={"award_id": app["id"]}))
        assert isinstance(data2, list)
