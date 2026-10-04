"""Authentication gate: missing identity headers (PRD §2.1, §2.7)."""
from test_helpers import (
    validate_error, ApiErrorId, NON_EXISTENT_UUID, set_clock, api_client,
)


class TestAuthentication:
    def test_missing_x_user_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting an
        `X-User-Role` value outside these five, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)." PRD §2.7: the authentication gate is
        first — "Every request passes through nine ordered validation gates,
        and a request that would fail several gates is always rejected with the
        error from the earliest failing gate".

        Design: Corner/validations/missing_x_user_role_header_returns_unauthenticated
        """
        set_clock()
        # No X-User-Role / X-User-ID headers at all; the path id would
        # otherwise be a 404, proving gate 1 precedes gate 4.
        resp = api._request("GET", f"/plants/{NON_EXISTENT_UUID}", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
        resp2 = api._request("GET", f"/plants/{NON_EXISTENT_UUID}",
                             headers={"X-User-ID": "someone"})
        validate_error(resp2, ApiErrorId.ERR_UNAUTHENTICATED, 401)
