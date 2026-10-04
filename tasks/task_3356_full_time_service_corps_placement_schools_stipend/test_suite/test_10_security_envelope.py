"""Cross-cutting contract probes: authentication, role segregation, and the
error envelope on a missing resource."""

from test_helpers import (
    NON_EXISTENT_ID,
    ApiErrorId,
    fixtures,
    get_success_data,
    validate_error,
)
from test_helpers.test_users import (
    PROGRAM_MANAGER_HEADERS,
    STIPEND_ADMIN_1_HEADERS,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity
        in which they act. A request missing either header, or presenting a
        malformed one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        fixtures.set_clock(api)
        # No X-User-ID / X-User-Role at all: authentication fails before any
        # role or resource check.
        resp = api.get_site(NON_EXISTENT_ID, headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestRoleSegregation:
    def test_stipend_admin_cannot_verify_hours(self, api):
        """PRD §2.1: "A `StipendAdministrator` administers living stipends and
        education awards; deliberate segregation of duties keeps this role
        away from hour verification and keeps a `ProgramManager` away from
        stipend approval."

        Design: Corner/rbac/stipend_admin_cannot_verify_hours
        """
        fixtures.set_clock(api)
        site = fixtures.create_active_site(api)
        member = fixtures.create_active_member(api, site["id"])
        entry = fixtures.log_pending_entry(api, member["id"], "2026-09-01", 4.0)

        blocked = api.review_hour_entry(entry["id"], {"decision": "VERIFY"}, STIPEND_ADMIN_1_HEADERS)
        validate_error(blocked, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

        entries = get_success_data(
            api.list_member_hour_entries(member["id"], STIPEND_ADMIN_1_HEADERS)
        )
        assert entries[0]["status"] == "PENDING"


class TestErrorEnvelope:
    def test_member_get_not_found_returns_404(self, api):
        """PRD §2.8: "for any endpoint whose URL nests one resource under
        another, identifiers are validated left-to-right, and the request is
        rejected with `ERR_NOT_FOUND` for the first identifier that does not
        exist, before any later identifier or business rule is examined."

        Design: Corner/entities/member_get_not_found_returns_404
        """
        fixtures.set_clock(api)
        resp = api.get_member(NON_EXISTENT_ID, headers=PROGRAM_MANAGER_HEADERS)
        assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
