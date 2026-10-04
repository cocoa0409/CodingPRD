"""Authentication rung: missing or undeclared credentials."""
from test_helpers import (
    api_client, validate_error, ApiErrorId, create_household_payload, set_clock,
    TEST_USERS,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Each request must include `X-User-ID` to identify the
        acting user and `X-User-Role` to specify their operational capacity.
        A request missing either header, or naming a role the system does not
        declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/household_create_missing_auth_returns_unauthenticated
        """
        set_clock()
        payload = create_household_payload(
            state_code="TX", term_years=1, primary_full_name="Val Vann",
            primary_date_of_birth="1970-01-01")
        resp = api.create_household(payload, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401
