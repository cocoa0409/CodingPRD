"""Security tests: authentication, authorization, and entity-backed identity."""
from test_helpers import (
    ApiErrorId,
    create_active_member,
    create_member_payload,
    get_success_data,
    validate_error,
)
from test_helpers.test_users import (
    TEST_USERS,
    build_user_headers,
    make_member_headers,
)

OP = TEST_USERS["network_operator_headers"]
FA = TEST_USERS["fraud_analyst_headers"]


class TestAuthentication:
    def test_auth_missing_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        string the system does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/auth_missing_headers_rejected
        """
        res = api.list_members({})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_auth_unrecognized_role_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        string the system does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/auth_missing_headers_rejected
        """
        res = api.list_members(build_user_headers("x-1", "SuperUser"))
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_role_forbidden_endpoint_denied(self, api):
        """PRD §2.1: "Once authenticated, a request whose role is not
        permitted for the target endpoint is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §2.1: "`NetworkOperator` — network-level administrator: membership
        lifecycle, BIN assignment, clock control."
        PRD §3.1: "Approval by a `NetworkOperator` moves the member from
        `APPLICATION` to `ACTIVE` and increments its `version`."

        Design: Corner/validations/role_forbidden_endpoint_denied
        """
        member = get_success_data(api.create_member(
            create_member_payload(member_kind="BOTH"), OP))
        res = api.approve_member(member["id"], FA)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        current = get_success_data(api.get_member(member["id"], OP))
        assert current["status"] == "APPLICATION"

    def test_member_role_cannot_operate_settlement(self, api):
        """PRD §2.1: "Once authenticated, a request whose role is not
        permitted for the target endpoint is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §2.1: "`SettlementOperator` — operates clearing/settlement windows
        and funds-transfer lines."

        Design: Corner/rbac/member_role_cannot_operate_settlement
        """
        member = create_active_member(member_kind="BOTH", region="NA")
        res = api.create_settlement_window(
            {"window_date": "2026-09-02", "opens_at": "2026-09-02T00:00:00Z",
             "closes_at": "2026-09-03T00:00:00Z"},
            make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
