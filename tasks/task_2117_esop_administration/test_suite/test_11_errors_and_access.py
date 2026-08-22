"""Authentication, the eleven not-found codes and pagination bounds."""
from test_helpers import (
    PAGINATION_DEFAULT_LIMIT,
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    create_participant,
    create_plan,
    set_clock,
    validate_error,
    validate_paginated,
)

SPONSOR = TEST_USERS["sponsor_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
ADMIN = TEST_USERS["admin_headers"]
UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


class TestAuthentication:
    def test_missing_auth_headers_return_unauthenticated(self, api):
        """PRD 2.1: "Every request to the API, without exception, must carry two headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in
        which that user is acting. If either header is absent, or if `X-User-Role` carries a
        string that is not one of the five declared roles, the request is refused with
        `ERR_UNAUTHENTICATED` and HTTP 401."
        PRD 2.12: "Authentication — both headers present and `X-User-Role` naming a declared
        role, else `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        Design: Corner/errors/missing_auth_headers_return_unauthenticated
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)

        resp = api.get_plan(UNKNOWN_UUID, NO_AUTH_HEADERS)
        error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert error["error_id"] != "ERR_PLAN_NOT_FOUND", (
            "authentication is judged before any existence check"
        )

        validate_error(api.get_plan(UNKNOWN_UUID, build_user_headers("who-01", "Auditor")),
                       ApiErrorId.ERR_UNAUTHENTICATED)
        validate_error(api.get_plan(UNKNOWN_UUID, {"X-User-Role": "Trustee"}),
                       ApiErrorId.ERR_UNAUTHENTICATED)


class TestNotFoundCatalogue:
    def test_every_not_found_error_id_is_reachable(self, api):
        """PRD 2.11: "The path variables in use are `plan_id`, `participant_id`,
        `valuation_id`, `loan_id`, `payment_id`, `run_id`, `allocation_id`, `forfeiture_id`,
        `election_id`, `installment_id`, `exercise_id` and `statement_id`. Each has its own
        not-found code, all of them HTTP 404: `ERR_PLAN_NOT_FOUND`,
        `ERR_PARTICIPANT_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`,
        `ERR_LOAN_PAYMENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
        `ERR_FORFEITURE_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`, `ERR_INSTALLMENT_NOT_FOUND`,
        `ERR_EXERCISE_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/every_not_found_error_id_is_reachable
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)

        cases = [
            (api.get_participant(UNKNOWN_UUID, TRUSTEE), ApiErrorId.ERR_PARTICIPANT_NOT_FOUND),
            (api.get_valuation(UNKNOWN_UUID, TRUSTEE), ApiErrorId.ERR_VALUATION_NOT_FOUND),
            (api.get_loan(UNKNOWN_UUID, TRUSTEE), ApiErrorId.ERR_LOAN_NOT_FOUND),
            (api.get_loan_payment(UNKNOWN_UUID, TRUSTEE), ApiErrorId.ERR_LOAN_PAYMENT_NOT_FOUND),
            (api.get_allocation_run(UNKNOWN_UUID, TRUSTEE), ApiErrorId.ERR_RUN_NOT_FOUND),
            (api.get_share_allocation(UNKNOWN_UUID, TRUSTEE), ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
            (api.get_forfeiture_event(UNKNOWN_UUID, TRUSTEE), ApiErrorId.ERR_FORFEITURE_NOT_FOUND),
            (api.get_distribution_election(UNKNOWN_UUID, TRUSTEE),
             ApiErrorId.ERR_ELECTION_NOT_FOUND),
            (api.get_installment_payment(UNKNOWN_UUID, TRUSTEE),
             ApiErrorId.ERR_INSTALLMENT_NOT_FOUND),
            (api.get_put_option_exercise(UNKNOWN_UUID, TRUSTEE), ApiErrorId.ERR_EXERCISE_NOT_FOUND),
            (api.get_participant_statement(UNKNOWN_UUID, TRUSTEE),
             ApiErrorId.ERR_STATEMENT_NOT_FOUND),
        ]
        for resp, expected in cases:
            validate_error(resp, expected)
            assert resp.status_code == 404, f"{expected} must answer HTTP 404"
            assert resp.json()["response_type"] == "error"


class TestPaginationBounds:
    def test_pagination_limit_above_maximum_rejected(self, api):
        """PRD 2.3: "Every collection-returning endpoint is paginated by the same two query
        parameters. `limit` defaults to 10 when omitted, must be at least 1, and may not
        exceed 100. `offset` defaults to 0 and may not be negative. A `limit` outside 1
        through 100, or a negative `offset`, is a malformed request and is refused with
        `ERR_INVALID_REQUEST` and HTTP 400."

        Design: Corner/validations/pagination_limit_above_maximum_rejected
        """
        set_clock("2026-03-02T00:00:00Z", SPONSOR)
        plan = create_plan(plan_name="Page Plan", sponsor_name="Corner Corp",
                           distribution_policy="LUMP_SUM")
        create_participant(plan["id"], employee_number="E-P1", date_of_birth="1985-06-10",
                           hire_date="2021-03-01", eligible_compensation_cents=34_500_000)

        validate_error(
            api.list_participants(ADMIN, params={"plan_id": plan["id"], "limit": 101}),
            ApiErrorId.ERR_INVALID_REQUEST,
        )
        validate_error(
            api.list_participants(ADMIN, params={"plan_id": plan["id"], "offset": -1}),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

        rows, meta = validate_paginated(
            api.list_participants(ADMIN, params={"plan_id": plan["id"], "limit": 100})
        )
        assert len(rows) == 1 and meta["total_count"] == 1
        assert meta["limit"] == 100, "a limit of exactly 100 is inside the declared bound"

        _rows, default_meta = validate_paginated(
            api.list_participants(ADMIN, params={"plan_id": plan["id"]})
        )
        assert default_meta["limit"] == PAGINATION_DEFAULT_LIMIT
        assert default_meta["offset"] == 0
