"""Authentication, role authorization, Member ownership, and existence
checks on nested paths."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    validate_error,
    validate_success,
)
from test_helpers import factories, fixtures
from test_helpers.fixtures import (
    APPLICANT,
    BENEFITS,
    OFFICER_A,
    build_case,
    add_evidence,
    add_service_record,
    make_member_headers,
    submit_case,
)


class TestAuthentication:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        value outside the declared set, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)." PRD §2.7: "(1) header
        authentication, producing `ERR_UNAUTHENTICATED`... (3)
        path-parameter existence, producing `ERR_NOT_FOUND`".

        Design: Corner/rbac/missing_role_header_unauthenticated
        """
        resp = api._request(
            "GET", f"/membership/members/{NON_EXISTENT_UUID}", headers={}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleAuthorization:
    def _under_review_case(self, api):
        case = build_case(api, applicant_legal_name="Rbac Ron")
        record = add_service_record(api, case["id"])
        add_evidence(api, case["id"], covers_service_record_id=record["id"])
        submit_case(api, case["id"])
        return case

    def test_member_role_cannot_decide_case(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4:
        `POST /membership/eligibility-cases/{caseId}/decide` is authorized
        for `VerificationOfficer` only.

        Design: Corner/rbac/member_cannot_decide_case_forbidden
        """
        case = self._under_review_case(api)
        resp = api.decide_case(
            case["id"], {"decision": "APPROVE"},
            make_member_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        current = validate_success(api.get_eligibility_case(case["id"], OFFICER_A))
        assert current["status"] == "UNDER_REVIEW"

    def test_verification_officer_cannot_grant_survivor_case(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4:
        `POST /membership/survivor-cases/{caseId}/grant` is authorized for
        `BenefitsOfficer` only.

        Design: Corner/rbac/verification_officer_cannot_grant_survivor_case
        """
        bundle = fixtures.setup_member_spouse_survivor_case(
            api, sponsor_name="Sod Sam", spouse_name="Sod Sara",
        )
        resp = api.grant_survivor_case(
            bundle["survivor_case"]["id"], OFFICER_A
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        current = validate_success(
            api.get_survivor_case(bundle["survivor_case"]["id"], BENEFITS)
        )
        assert current["status"] == "OPEN"


class TestMemberOwnership:
    def test_member_cannot_act_on_another_members_route(self, api):
        """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id`
        of the acting `Member` row itself; ownership checks on any route of
        the form `/membership/members/{memberId}/...` compare the
        `{memberId}` path parameter against `X-User-ID`, and a mismatch is
        rejected with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/member_ownership_cross_member_denied
        """
        _, m1 = fixtures.approve_direct_member(api, name="Own One")
        _, m2 = fixtures.approve_direct_member(api, name="Own Two")
        resp = api.create_address(
            m2, factories.address_payload(line1="1 Spy Ln"),
            make_member_headers(m1),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


class TestExistence:
    def test_unknown_member_id_not_found(self, api):
        """PRD §2.7: "(3) path-parameter existence, producing
        `ERR_NOT_FOUND`".

        Design: Corner/entities/member_get_unknown_id_returns_not_found
        """
        resp = api.get_member(NON_EXISTENT_UUID, fixtures.ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_nested_path_checked_left_to_right(self, api):
        """PRD §2.7: "Existence checks on nested paths are performed strictly
        left to right: for a path such as
        `/membership/members/{memberId}/entitlements/{entitlementId}/close`,
        an unknown `memberId` yields `ERR_NOT_FOUND` before the entitlement
        identifier is ever examined."

        Design: Corner/validations/existence_checked_left_to_right_in_nested_path
        """
        resp = api.close_entitlement(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, BENEFITS
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
