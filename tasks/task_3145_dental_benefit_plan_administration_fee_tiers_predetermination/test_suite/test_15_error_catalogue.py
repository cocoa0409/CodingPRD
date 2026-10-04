"""Error catalogue: typed 404s per path segment and the 401 floor."""

from test_helpers.api_errors import (
    ERR_CLAIM_NOT_FOUND,
    ERR_DEPENDENT_NOT_FOUND,
    ERR_FEE_SCHEDULE_NOT_FOUND,
    ERR_PREDETERMINATION_NOT_FOUND,
    ERR_PROVIDER_NOT_FOUND,
    ERR_SUBSCRIBER_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import validate_error
from test_helpers.fixtures import set_clock
from test_helpers.test_users import (
    ADMIN,
    EXAMINER,
    NETWORK,
    NO_HEADERS,
    make_reviewer_headers,
)

UNKNOWN_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestTypedPathNotFound:
    def test_claim_get_unknown_id_returns_claim_not_found(self, client):
        """The claim path segment surfaces its own 404 code.

        PRD 2.10: "Next, path-parameter identifiers are resolved left to
        right — each entity type surfaces its own dedicated 404 code:
        `ERR_PLAN_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_DEPENDENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_PREDETERMINATION_NOT_FOUND`, or
        `ERR_FEE_SCHEDULE_NOT_FOUND` — and a request targeting a nested path
        is rejected at the first identifier that does not resolve, before
        deeper segments are examined."

        Design: Corner/errors/claim_get_unknown_id_returns_claim_not_found
        """
        set_clock(client, "2026-01-01T00:00:00Z")

        resp = client.get_claim(UNKNOWN_UUID, headers=EXAMINER)

        validate_error(resp, ERR_CLAIM_NOT_FOUND, expected_status=404)

    def test_provider_get_unknown_id_returns_provider_not_found(self, client):
        """The provider path segment surfaces its own 404 code.

        PRD 2.10: "Next, path-parameter identifiers are resolved left to
        right — each entity type surfaces its own dedicated 404 code:
        `ERR_PLAN_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_DEPENDENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_PREDETERMINATION_NOT_FOUND`, or
        `ERR_FEE_SCHEDULE_NOT_FOUND` — and a request targeting a nested path
        is rejected at the first identifier that does not resolve, before
        deeper segments are examined."

        Design: Corner/errors/provider_get_unknown_id_returns_provider_not_found
        """
        set_clock(client, "2026-01-01T00:00:00Z")

        resp = client.get_provider(UNKNOWN_UUID, headers=NETWORK)

        validate_error(resp, ERR_PROVIDER_NOT_FOUND, expected_status=404)

    def test_subscriber_get_unknown_id_returns_subscriber_not_found(self, client):
        """The subscriber path segment surfaces its own 404 code.

        PRD 2.10: "Next, path-parameter identifiers are resolved left to
        right — each entity type surfaces its own dedicated 404 code:
        `ERR_PLAN_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_DEPENDENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_PREDETERMINATION_NOT_FOUND`, or
        `ERR_FEE_SCHEDULE_NOT_FOUND` — and a request targeting a nested path
        is rejected at the first identifier that does not resolve, before
        deeper segments are examined."

        Design: Corner/errors/subscriber_get_unknown_id_returns_subscriber_not_found
        """
        set_clock(client, "2026-01-01T00:00:00Z")

        resp = client.get_subscriber(UNKNOWN_UUID, headers=ADMIN)

        validate_error(resp, ERR_SUBSCRIBER_NOT_FOUND, expected_status=404)

    def test_dependent_get_unknown_id_returns_dependent_not_found(self, client):
        """The dependent path segment surfaces its own 404 code.

        PRD 2.10: "Next, path-parameter identifiers are resolved left to
        right — each entity type surfaces its own dedicated 404 code:
        `ERR_PLAN_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_DEPENDENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_PREDETERMINATION_NOT_FOUND`, or
        `ERR_FEE_SCHEDULE_NOT_FOUND` — and a request targeting a nested path
        is rejected at the first identifier that does not resolve, before
        deeper segments are examined."

        Design: Corner/errors/dependent_get_unknown_id_returns_dependent_not_found
        """
        set_clock(client, "2026-01-01T00:00:00Z")

        resp = client.get_dependent(UNKNOWN_UUID, headers=ADMIN)

        validate_error(resp, ERR_DEPENDENT_NOT_FOUND, expected_status=404)

    def test_predetermination_get_unknown_id_returns_predetermination_not_found(self, client):
        """The predetermination path segment surfaces its own 404 code.

        PRD 2.10: "Next, path-parameter identifiers are resolved left to
        right — each entity type surfaces its own dedicated 404 code:
        `ERR_PLAN_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_DEPENDENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_PREDETERMINATION_NOT_FOUND`, or
        `ERR_FEE_SCHEDULE_NOT_FOUND` — and a request targeting a nested path
        is rejected at the first identifier that does not resolve, before
        deeper segments are examined."

        Design: Corner/errors/predetermination_get_unknown_id_returns_predetermination_not_found
        """
        set_clock(client, "2026-01-01T00:00:00Z")

        resp = client.get_predetermination(
            UNKNOWN_UUID, headers=make_reviewer_headers("rev-1")
        )

        validate_error(resp, ERR_PREDETERMINATION_NOT_FOUND, expected_status=404)

    def test_fee_schedule_get_unknown_id_returns_fee_schedule_not_found(self, client):
        """The fee-schedule path segment surfaces its own 404 code.

        PRD 2.10: "Next, path-parameter identifiers are resolved left to
        right — each entity type surfaces its own dedicated 404 code:
        `ERR_PLAN_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_DEPENDENT_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_PREDETERMINATION_NOT_FOUND`, or
        `ERR_FEE_SCHEDULE_NOT_FOUND` — and a request targeting a nested path
        is rejected at the first identifier that does not resolve, before
        deeper segments are examined."

        Design: Corner/errors/fee_schedule_get_unknown_id_returns_fee_schedule_not_found
        """
        set_clock(client, "2026-01-01T00:00:00Z")

        resp = client.get_fee_schedule(UNKNOWN_UUID, headers=NETWORK)

        validate_error(resp, ERR_FEE_SCHEDULE_NOT_FOUND, expected_status=404)


class TestAuthenticationFloor:
    def test_plan_list_without_credentials_returns_unauthenticated(self, client):
        """No headers at all fails before any role question is asked.

        PRD 2.1: "Every request must carry two HTTP headers: `X-User-ID`
        identifying the acting user, and `X-User-Role` naming their
        operational capacity. A request missing either header, or presenting
        an `X-User-Role` value outside the declared role set, is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/plan_list_without_credentials_returns_unauthenticated
        """
        set_clock(client, "2026-01-01T00:00:00Z")

        resp = client.list_plans(headers=NO_HEADERS)

        validate_error(resp, ERR_UNAUTHENTICATED, expected_status=401)
