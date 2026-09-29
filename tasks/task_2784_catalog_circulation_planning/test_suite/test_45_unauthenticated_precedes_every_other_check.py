"""Authentication is unreachable through any later failure.

Each call below would fail for a second, cheaper reason if the request ever got that
far — a role the endpoint does not authorize, a path identifier that resolves to
nothing, a body the schema refuses — and each one is issued twice, once with `X-User-ID`
omitted outright and once with it present but empty. Both spellings of anonymity produce
the same 401, and the later code never appears, including on the two test-driving
endpoints that no business workflow uses.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    CLOCK_START,
    DIRECTOR,
    NON_EXISTENT_UUID,
    PLANNER,
    create_season_payload,
    create_segment_payload,
    new_season,
    set_clock,
    set_clock_payload,
    validate_error,
    validate_paginated,
)

SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}


def _omitted(headers) -> dict:
    """The same role header, with `X-User-ID` absent entirely."""
    return {key: value for key, value in headers.items() if key != "X-User-ID"}


def _emptied(headers) -> dict:
    """The same role header, with `X-User-ID` present but an empty string."""
    anonymous = dict(headers)
    anonymous["X-User-ID"] = ""
    return anonymous


def _both_spellings_of_anonymous(headers) -> list:
    return [_omitted(headers), _emptied(headers)]


def _one_season() -> dict:
    set_clock(CLOCK_START)
    return new_season(season_code="FW26", fiscal_year=2026)


class TestEvenAPureReadIsGated:
    def test_reading_an_existing_season_anonymously_is_unauthenticated(self, api):
        """PRD §2.1: "Every request to every endpoint — reads included — must carry two
        headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming
        the role that operator is acting in."
        PRD §2.1: "A request whose `X-User-ID` header is absent or empty is rejected with
        `ERR_UNAUTHENTICATED` before anything else about the request is examined."

        Design: Corner/errors/a_missing_or_empty_x_user_id_is_unauthenticated_before_anything_else
        """
        season = _one_season()

        for anonymous in _both_spellings_of_anonymous(ADMIN):
            response = api.get_season(season["id"], anonymous)
            validate_error(response, "ERR_UNAUTHENTICATED", 401)


class TestAnAnonymousWriteLeavesNothingBehind:
    def test_an_otherwise_valid_segment_post_is_refused_and_creates_no_row(self, api):
        """PRD §2.1: "A request whose `X-User-ID` header is absent or empty is rejected
        with `ERR_UNAUTHENTICATED` before anything else about the request is examined."

        Design: Corner/errors/a_missing_or_empty_x_user_id_is_unauthenticated_before_anything_else
        """
        season = _one_season()
        payload = create_segment_payload(
            season["id"], segment_code="S_A", **SCORING
        )

        for anonymous in _both_spellings_of_anonymous(PLANNER):
            response = api.create_segment(payload, anonymous)
            validate_error(response, "ERR_UNAUTHENTICATED", 401)

        _, meta = validate_paginated(
            api.list_segments(PLANNER, params={"season_id": season["id"]})
        )
        assert meta["total_count"] == 0


class TestAuthenticationOutranksTheRoleCheck:
    def test_an_anonymous_wrong_role_write_is_a_401_and_not_a_403(self, api):
        """PRD §2.10: "1. **`X-User-ID` present and non-empty** on every endpoint —
        otherwise `ERR_UNAUTHENTICATED` (401)."
        PRD §2.10: "2. **Role authorized for the endpoint** on every endpoint — otherwise
        `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/errors/a_missing_or_empty_x_user_id_is_unauthenticated_before_anything_else
        """
        _one_season()
        payload = create_season_payload(season_code="SS27", fiscal_year=2027)

        for anonymous in _both_spellings_of_anonymous(ANALYST):
            response = api.create_season(payload, anonymous)
            error = validate_error(response, "ERR_UNAUTHENTICATED", 401)
            assert error["error_id"] != "ERR_FORBIDDEN_ROLE"


class TestAuthenticationOutranksPathResolution:
    def test_an_anonymous_read_of_a_missing_plan_is_a_401_and_not_a_404(self, api):
        """PRD §2.10: "1. **`X-User-ID` present and non-empty** on every endpoint —
        otherwise `ERR_UNAUTHENTICATED` (401)."
        PRD §2.10: "3. **Every path identifier resolves**, on every endpoint that has one
        — otherwise the matching 404 from §2.8."

        Design: Corner/errors/a_missing_or_empty_x_user_id_is_unauthenticated_before_anything_else
        """
        _one_season()

        for anonymous in _both_spellings_of_anonymous(DIRECTOR):
            response = api.get_plan(NON_EXISTENT_UUID, anonymous)
            error = validate_error(response, "ERR_UNAUTHENTICATED", 401)
            assert error["error_id"] != "ERR_PLAN_NOT_FOUND"


class TestAuthenticationOutranksSchemaValidation:
    def test_an_anonymous_malformed_clock_write_is_a_401_and_not_a_422(self, api):
        """PRD §2.10: "1. **`X-User-ID` present and non-empty** on every endpoint —
        otherwise `ERR_UNAUTHENTICATED` (401)."
        PRD §2.10: "5. **Request body satisfies its schema** on every write endpoint:
        required fields present, enum values in range, integers inside their declared
        bounds, no negative money or quantities — otherwise `ERR_INVALID_REQUEST` (422)."

        Design: Corner/errors/a_missing_or_empty_x_user_id_is_unauthenticated_before_anything_else
        """
        _one_season()
        malformed = set_clock_payload("not-a-timestamp")

        for anonymous in _both_spellings_of_anonymous(ADMIN):
            response = api.set_clock(malformed, anonymous)
            error = validate_error(response, "ERR_UNAUTHENTICATED", 401)
            assert error["error_id"] != "ERR_INVALID_REQUEST"
