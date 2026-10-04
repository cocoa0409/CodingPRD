"""Access control: auth headers, role denial, ownership scoping, version
increments, and filtered pagination."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_product,
    create_appointed_agent,
    create_consumer,
    create_direct_quote,
    create_product_payload,
    get_success_data,
    make_consumer_headers,
    set_clock,
    submit_direct_quote,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["carrier_admin_headers"]
RM = TEST_USERS["rating_manager_headers"]
UR = TEST_USERS["underwriting_reviewer_headers"]


class TestAuthHeaders:
    def test_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "A request missing either header, carrying an empty value, or
        naming a role the platform does not recognize is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        set_clock("2026-01-01T00:00:00Z")
        resp = api.list_agents({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestRoleDenial:
    def test_wrong_role_and_unknown_id_returns_forbidden_before_not_found(self, api):
        """PRD §2.8: "When a request would fail several checks, the checks are
        evaluated in a fixed priority order and the error of the **lowest**
        priority number is returned."
        PRD §2.8: "2. Role authorization for the endpoint
        (`ERR_FORBIDDEN_FOR_ROLE`)."

        Design: Corner/validations/wrong_role_and_unknown_id_returns_forbidden_before_not_found
        """
        set_clock("2026-01-01T00:00:00Z")
        consumer = create_consumer()
        resp = api.activate_product(
            "00000000-0000-4000-8000-000000000000",
            make_consumer_headers(consumer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)

    def test_consumer_cannot_create_products_returns_forbidden(self, api):
        """PRD §2.1: "A request whose role is recognized but not listed among the
        roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/consumer_cannot_create_products_returns_forbidden
        """
        set_clock("2026-01-01T00:00:00Z")
        consumer = create_consumer()
        resp = api.create_product(
            {
                "product_code": "P-HACK",
                "line_of_business": "AUTO",
                "state_code": "TX",
                "channel_availability": "DIRECT",
                "coverage_rates": {"X": {"Y": 1}},
                "min_premium_cents": 0,
            },
            make_consumer_headers(consumer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
        rows, meta = validate_paginated(api.list_products(ADMIN))
        assert len(rows) == 0

    def test_rating_manager_cannot_terminate_agent(self, api):
        """PRD §2.1: "A request whose role is recognized but not listed among the
        roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/rating_manager_cannot_terminate_agent
        """
        set_clock("2026-01-01T00:00:00Z")
        agent = create_appointed_agent()
        resp = api.terminate_agent(agent["id"], RM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
        after = get_success_data(api.get_agent(agent["id"], UR))
        assert after["status"] == "APPOINTED"


class TestOwnership:
    def test_agent_cannot_read_other_agents_statement(self, api):
        """PRD §2.1: "Ownership enforcement: on any non-read endpoint acting on an
        owned resource, and on reads of owned records, an entity-backed caller
        whose `X-User-ID` does not match the owning foreign key on the target
        resource is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/agent_cannot_read_other_agents_statement
        """
        from test_helpers import make_agent_headers

        set_clock("2026-03-01T00:00:00Z")
        agent_a = create_appointed_agent()
        agent_b = create_appointed_agent()
        stmt = get_success_data(api.create_commission_statement(
            agent_a["id"],
            {"period_start": "2026-02-01T00:00:00Z",
             "period_end": "2026-03-01T00:00:00Z"},
            ADMIN,
        ))

        resp = api.get_commission_statement(stmt["id"], make_agent_headers(agent_b["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH, 403)

        own = validate_success(
            api.get_commission_statement(stmt["id"], make_agent_headers(agent_a["id"]))
        )
        assert own["id"] == stmt["id"]


class TestVersionIncrementDiscipline:
    def test_version_increments_on_every_agent_mutation(self, api):
        """PRD §2.4: "`version` — an integer starting at 1 at creation and
        incremented by exactly 1 on every state transition or mutation of the
        resource."

        Design: Corner/cross_cutting_layers/version_increments_on_every_agent_mutation
        """
        from test_helpers import create_agent, create_appointment

        set_clock("2026-01-01T00:00:00Z")
        agent = create_agent()
        create_version = agent["version"]
        create_appointment(agent["id"])

        appointed = validate_success(api.appoint_agent(agent["id"], UR))
        assert appointed["version"] == create_version + 1

        suspended = validate_success(api.suspend_agent(agent["id"], UR))
        assert suspended["version"] == create_version + 2

        # An intermediate GET must not change the version
        fetched = get_success_data(api.get_agent(agent["id"], ADMIN))
        assert fetched["version"] == create_version + 2

        reinstated = validate_success(api.reinstate_agent(agent["id"], UR))
        assert reinstated["version"] == create_version + 3


class TestFilteredPagination:
    def test_pagination_filter_sort_interaction_on_quotes(self, api):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to
        10, with a minimum of 1 and a maximum of 100. `offset` skips that many
        items before returning the page; it defaults to 0."
        PRD §4: "List quotes (filters: consumer_id, product_id, agent_id,
        rate_feed_publication_id, channel, status)"

        Design: Corner/cross_cutting_layers/pagination_filter_sort_interaction_on_quotes
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product()
        consumer = create_consumer()
        consumer_headers = make_consumer_headers(consumer["id"])
        quotes = [
            create_direct_quote(consumer, product["id"]) for _ in range(5)
        ]
        submit_direct_quote(consumer, quotes[0]["id"])
        submit_direct_quote(consumer, quotes[1]["id"])

        page1, meta1 = validate_paginated(
            api.list_quotes(
                ADMIN,
                params={"channel": "DIRECT", "status": "DRAFT", "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_quotes(
                ADMIN,
                params={"channel": "DIRECT", "status": "DRAFT", "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False

        _, meta_q = validate_paginated(
            api.list_quotes(ADMIN, params={"status": "QUOTED"})
        )
        assert meta_q["total_count"] == 2
