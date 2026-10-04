"""Foundations: entity creation defaults, retrieval round-trip, pagination,
envelope shape, required-field and enum validation, and FK resolution."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_consumer,
    assert_product,
    build_user_headers,
    create_active_product,
    create_consumer,
    create_direct_quote,
    create_product_payload,
    get_success_data,
    is_valid_uuid,
    make_consumer_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


class TestProductCreationDefaults:
    def test_product_create_applies_defaults_and_starts_draft(self, api, rating_manager_headers):
        """PRD §3.1: "Pricing differentiation between channels is expressed as fractional
        factors on the product: `direct_discount_pct` (default 0; a value of 0.10 means a
        10% discount) reduces direct premiums, while `agent_load_pct` (default 0; 0.15
        means a 15% load) raises agent-channel premiums."
        PRD §3.1: "A product is born in `DRAFT` and becomes quotable only when a
        `RatingManager` activates it, moving it to `ACTIVE`; activation requires
        `coverage_rates` to be non-empty, failing with `ERR_INVALID_REQUEST`
        otherwise."
        PRD §2.4: "`version` — an integer starting at 1 at creation and incremented
        by exactly 1 on every state transition or mutation of the resource."

        Design: Corner/entities/product_create_applies_defaults_and_starts_draft
        """
        set_clock("2026-01-01T00:00:00Z")
        resp = api.create_product(create_product_payload(), rating_manager_headers)
        product = validate_success(resp, 201)
        assert_product(product)
        assert product["status"] == "DRAFT"
        assert product["version"] == 1
        assert product["direct_channel_max_premium_cents"] is None
        assert product["bundle_eligible"] is False


class TestAgentRetrieval:
    def test_agent_get_returns_stored_fields_unchanged(
        self, api, carrier_admin_headers, underwriting_reviewer_headers
    ):
        """PRD §3.6: "An agent begins life as an `APPLICANT`, created by a
        `CarrierAdmin` with an `agency_name`, a `principal_name`, and a
        `resident_state_code`."

        Design: Corner/entities/agent_get_returns_stored_fields_unchanged
        """
        set_clock("2026-01-01T00:00:00Z")
        resp = api.create_agent(
            {
                "agency_name": "Hill Country Insurance",
                "principal_name": "A. Reyes",
                "resident_state_code": "TX",
            },
            carrier_admin_headers,
        )
        agent = validate_success(resp, 201)
        fetched = validate_success(api.get_agent(agent["id"], underwriting_reviewer_headers))
        assert fetched["agency_name"] == "Hill Country Insurance"
        assert fetched["principal_name"] == "A. Reyes"
        assert fetched["resident_state_code"] == "TX"
        assert fetched["status"] == "APPLICANT"
        assert fetched["terminated_reason"] is None


class TestQuoteListingPagination:
    def test_quotes_list_paginates_total_count_and_has_more(
        self, api, carrier_admin_headers
    ):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10,
        with a minimum of 1 and a maximum of 100. `offset` skips that many items before
        returning the page; it defaults to 0."
        PRD §2.3: "The `meta` object of list responses carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/quotes_list_paginates_total_count_and_has_more
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product()
        consumer = create_consumer(email="corner-list@example.com")
        for _ in range(3):
            create_direct_quote(consumer, product["id"])

        page1, meta1 = validate_paginated(
            api.list_quotes(
                carrier_admin_headers,
                params={"consumer_id": consumer["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_quotes(
                carrier_admin_headers,
                params={"consumer_id": consumer["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        page_all, meta_all = validate_paginated(
            api.list_quotes(carrier_admin_headers, params={"consumer_id": consumer["id"]})
        )
        assert len(page_all) == 3
        assert meta_all["limit"] == 10
        assert meta_all["offset"] == 0


class TestQuoteNotFound:
    def test_quote_get_unknown_id_returns_not_found(self, api, carrier_admin_headers):
        """PRD §2.5: "The first identifier that does not resolve to an existing
        resource yields `ERR_NOT_FOUND` (HTTP 404) immediately, before later
        segments or any body content are examined."

        Design: Corner/entities/quote_get_unknown_id_returns_not_found
        """
        set_clock("2026-01-01T00:00:00Z")
        resp = api.get_quote(UNKNOWN_UUID, carrier_admin_headers)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        assert "error_id" in err and "message" in err


class TestQuoteRequestShape:
    def test_quote_create_missing_required_coverages_returns_invalid_request(
        self, api, carrier_admin_headers
    ):
        """PRD §2.5: "Body shape — required fields present, types valid, enum members
        valid, datetimes parseable — is verified as `ERR_INVALID_REQUEST` (HTTP
        400); fields the server does not recognize are ignored rather than
        rejected."

        Design: Corner/entities/quote_create_missing_required_coverages_returns_invalid_request
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product()
        consumer = create_consumer()
        resp = api.create_quote(
            {
                "consumer_id": consumer["id"],
                "product_id": product["id"],
                "channel": "DIRECT",
            },
            make_consumer_headers(consumer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        rows, meta = validate_paginated(
            api.list_quotes(carrier_admin_headers, params={"consumer_id": consumer["id"]})
        )
        assert len(rows) == 0

    def test_quote_create_unknown_premium_field_input_ignored(self, api):
        """PRD §2.5: "fields the server does not recognize are ignored rather than
        rejected."
        PRD §3.3: "At creation `quoted_premium_cents`, `quoted_at`, and `expires_at`
        are null, `rate_stale` is false, and both `referral_snapshot` and
        `rate_feed_publication_id` are null."

        Design: Corner/entities/quote_create_unknown_premium_field_input_ignored
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product()
        consumer = create_consumer()
        resp = api.create_quote(
            {
                "consumer_id": consumer["id"],
                "product_id": product["id"],
                "channel": "DIRECT",
                "coverages": [{"coverage_code": "LIABILITY", "tier": "BASIC"}],
                "quoted_premium_cents": 999999,
            },
            make_consumer_headers(consumer["id"]),
        )
        quote = validate_success(resp, 201)
        assert quote["status"] == "DRAFT"
        assert quote["quoted_premium_cents"] is None

    def test_quote_create_with_invalid_enum_channel_rejected(self, api):
        """PRD §2.5: "Body shape — required fields present, types valid, enum members
        valid, datetimes parseable — is verified as `ERR_INVALID_REQUEST` (HTTP
        400); fields the server does not recognize are ignored rather than
        rejected."
        PRD §3.3: "A quote is created in `DRAFT` against a `consumer_id` and a
        `product_id`, carrying a `channel` of `DIRECT` or `AGENT` and the selected
        `coverages` as coverage-code-and-tier pairs."

        Design: Corner/entities/quote_create_with_invalid_enum_channel_rejected
        """
        set_clock("2026-01-01T00:00:00Z")
        product = create_active_product()
        consumer = create_consumer()
        resp = api.create_quote(
            {
                "consumer_id": consumer["id"],
                "product_id": product["id"],
                "channel": "BOTH",
                "coverages": [{"coverage_code": "LIABILITY", "tier": "BASIC"}],
            },
            make_consumer_headers(consumer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestConsumerSystemFields:
    def test_consumer_system_fields_generated_by_server(self, api, anonymous_headers):
        """PRD §2.4: "`id` — a server-minted UUID with no type prefix, generated at
        creation."
        PRD §2.4: "`created_at` — an ISO 8601 UTC timestamp with three fractional
        digits recording when the resource was created, taken from the logical clock."
        PRD §2.4: "`version` — an integer starting at 1 at creation and incremented
        by exactly 1 on every state transition or mutation of the resource."

        Design: Corner/entities/consumer_system_fields_generated_by_server
        """
        set_clock("2026-01-01T00:00:00Z")
        resp = api.create_consumer(
            {
                "email": "sys-fields@example.com",
                "full_name": "Sys Fields",
                "date_of_birth": "1990-01-01",
                "home_state_code": "TX",
            },
            anonymous_headers,
        )
        consumer = validate_success(resp, 201)
        assert_consumer(consumer)
        assert is_valid_uuid(consumer["id"])
        assert not consumer["id"].startswith("cons_")
        assert consumer["created_at"] == "2026-01-01T00:00:00.000Z"
        assert consumer["updated_at"] == "2026-01-01T00:00:00.000Z"
        assert consumer["version"] == 1


class TestClaimParentResolution:
    def test_claim_create_on_unknown_policy_returns_not_found(
        self, api, carrier_admin_headers
    ):
        """PRD §2.5: "Endpoints addressed through a nested path — an appointment
        under an agent, a claim under a policy, a feed publication under a rater —
        validate path identifiers sequentially from left to right. The first
        identifier that does not resolve to an existing resource yields
        `ERR_NOT_FOUND` (HTTP 404) immediately, before later segments or any body
        content are examined."

        Design: Corner/entities/claim_create_on_unknown_policy_returns_not_found
        """
        set_clock("2026-01-01T00:00:00Z")
        resp = api.create_claim(
            UNKNOWN_UUID,
            {"claim_type": "COLLISION", "incurred_amount_cents": 1000},
            carrier_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
