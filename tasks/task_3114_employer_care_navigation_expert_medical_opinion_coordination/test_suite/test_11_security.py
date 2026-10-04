"""Security and access control: authentication, role gating, member
ownership, and the eligibility freeze."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_employer_payload, create_member_payload, create_claim_payload,
    claim_line,
    set_clock, setup_employer, setup_employer_with_member, setup_provider,
)
from test_helpers.test_users import (
    make_member_headers,
    make_employer_admin_headers,
    make_plan_administrator_headers,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or naming a role outside
        this list, is rejected with `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        set_clock()
        resp = api.create_employer(
            create_employer_payload(name="NoAuth"), headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED,
                       expected_status=401)


class TestRoleGating:
    def test_wrong_role_on_platform_admin_endpoint_returns_unauthorized(
            self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
        PRD §2.6: "Second, authorization: the role must be permitted on the
        endpoint (else `ERR_UNAUTHORIZED_ROLE`)".

        Design: Corner/validations/wrong_role_on_platform_admin_endpoint_returns_unauthorized
        """
        set_clock()
        # Empty body: authorization (priority 2) precedes shape (priority 3).
        resp = api.create_employer(
            {}, make_employer_admin_headers("ea-x"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                       expected_status=403)

    def test_member_cannot_adjudicate_claims(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
        PRD §4: "POST `/care/claims/{id}/adjudicate` ... PlanAdministrator".

        Design: Corner/rbac/member_cannot_adjudicate_claims
        """
        set_clock()
        _, member = setup_employer_with_member()
        provider = setup_provider(name="Rbac Clinic")
        claim = validate_success(api.create_claim(
            create_claim_payload(
                member_id=member["id"], provider_id=provider["id"],
                billed_amount_cents=50000, allowed_amount_cents=40000,
                lines=[claim_line("A", 50000, 1.0, "NONE")]),
            make_plan_administrator_headers("pa-1")), expected_status=201)

        resp = api.adjudicate_claim(
            claim["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                       expected_status=403)
        after = validate_success(api.get_claim(
            claim["id"], make_plan_administrator_headers("pa-1")))
        assert after["status"] == "RECEIVED"

    def test_employer_admin_read_only_cannot_load_members(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
        PRD §4: "POST `/care/employers/{id}/members` ... PlatformAdmin".

        Design: Corner/rbac/employer_admin_read_only_cannot_load_members
        """
        set_clock()
        emp = setup_employer(name="ReadOnlyCo")
        resp = api.create_member(
            emp["id"], create_member_payload(external_member_ref="RO-1"),
            make_employer_admin_headers("ea-1"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE,
                       expected_status=403)

        rows = validate_success(api.list_employer_members(
            emp["id"], make_employer_admin_headers("ea-1")))
        assert len(rows) == 0


class TestMemberOwnership:
    def test_member_acting_on_other_members_resource_returns_member_mismatch(
            self, api, platform_admin_headers):
        """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id`
        of the acting `Member` resource itself: ownership checks on any
        member-scoped resource compare the resource's `member_id` to
        `X-User-ID` ... A member attempting to touch another member's resources
        is rejected with `ERR_MEMBER_MISMATCH` (403)."

        Design: Corner/validations/member_acting_on_other_members_resource_returns_member_mismatch
        """
        set_clock()
        emp = setup_employer(name="MismatchCo")
        ma = validate_success(api.create_member(
            emp["id"], create_member_payload(
                full_name="A One", external_member_ref="MM-1"),
            platform_admin_headers), expected_status=201)
        mb = validate_success(api.create_member(
            emp["id"], create_member_payload(
                full_name="B Two", external_member_ref="MM-2"),
            platform_admin_headers), expected_status=201)

        resp = api.create_consent(
            mb["id"],
            {"scope": "APPOINTMENT_BOOKING",
             "expires_at": "2027-01-01T00:00:00Z"},
            make_member_headers(ma["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_MISMATCH,
                       expected_status=403)


class TestEligibilityFreeze:
    def test_inactive_member_blocked_from_new_consent(self, api,
                                                      platform_admin_headers):
        """PRD §2.10: "A member whose `eligibility_status` is not `ACTIVE` is
        frozen: no new consents, navigation cases, appointments, record
        requests, expert opinion cases, billing cases, or authorizations may be
        created for them. Each such attempt is rejected with
        `ERR_MEMBER_INELIGIBLE` (409)."

        Design: Corner/validations/inactive_member_blocked_from_new_consent
        """
        set_clock()
        _, member = setup_employer_with_member()
        validate_success(api.deactivate_member(
            member["id"], platform_admin_headers))

        resp = api.create_consent(
            member["id"],
            {"scope": "APPOINTMENT_BOOKING",
             "expires_at": "2027-01-01T00:00:00Z"},
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_INELIGIBLE,
                       expected_status=409)
