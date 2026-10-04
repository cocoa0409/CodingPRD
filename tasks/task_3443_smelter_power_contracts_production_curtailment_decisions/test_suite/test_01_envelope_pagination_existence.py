"""Envelope shape, pagination defaults, existence ordering, and request-shape
basics (PRD §2.2, §2.3, §2.5, §2.6, §2.7, §3.1).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_potline,
    assert_price_observation,
    assert_smelter,
    create_active_contract,
    create_potline_payload,
    create_power_contract_payload,
    create_price_observation_payload,
    create_smelter,
    create_smelter_payload,
    setup_site,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId


class TestEnvelopeShape:
    def test_success_envelope_on_create(self, api, platform_admin_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §4: "return `201 Created`".

        Design: Corner/endpoints/response_envelope_success_shape
        """
        resp = api.create_smelter(create_smelter_payload(), platform_admin_headers)
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert_smelter(body["data"])

    def test_error_envelope_on_not_found(self, api, platform_admin_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/response_envelope_error_shape
        """
        resp = api.get_smelter(NON_EXISTENT_UUID, platform_admin_headers)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestExistenceAndAuth:
    def test_smelter_not_found_returns_404(self, api, platform_admin_headers):
        """PRD §2.6: "each path identifier must resolve to an existing
        resource, and the request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not resolve, before any
        later identifier or any business rule is examined."

        Design: Corner/entities/smelter_not_found_returns_404
        """
        resp = api.get_smelter(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_unauthenticated_beats_not_found(self, api):
        """PRD §2.7: "When several checks could reject the same request, the
        platform evaluates them in one fixed global order, and a
        lower-numbered check masks every higher-numbered one."
        PRD §2.7: "1. Authentication of the two headers — `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/unauthenticated_missing_headers_beats_not_found
        """
        resp = api.get_smelter(NON_EXISTENT_UUID, headers={})
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        assert resp.json()["data"]["error_id"] == "ERR_UNAUTHENTICATED"


class TestRequestShape:
    def test_smelter_create_missing_region_rejected(self, api, platform_admin_headers):
        """PRD §2.7: "16. Request shape and composition (required fields, enum
        values, numeric ranges, component and allocation composition) —
        `ERR_INVALID_REQUEST`."
        PRD §3.1: "A `PlatformAdmin` onboards a **Smelter** by supplying its
        `name`, its `region_code` — one of `NA_NORTHWEST`, `NA_MIDWEST`,
        `EU_NORDIC`, or `AU_EAST` — its `rated_capacity_tpd`".

        Design: Corner/entities/smelter_create_missing_region_returns_invalid_request
        """
        payload = create_smelter_payload()
        del payload["region_code"]
        resp = api.create_smelter(payload, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_price_observation_carries_no_version(self, api, trading_analyst_headers):
        """PRD §2.5: "Two resource families are immutable, append-only records
        and therefore carry only `id` and `created_at`: a `PriceObservation`
        and an `InterruptEvent` have neither `updated_at` nor `version` — both
        fields are absent on those resources."

        Design: Corner/entities/price_observation_has_no_version_field
        """
        resp = api.create_price_observation(
            create_price_observation_payload(), trading_analyst_headers
        )
        data = validate_success(resp, 201)
        assert_price_observation(data)

    def test_potline_system_fields_on_create_ignored(self, api, smelter_manager_headers):
        """PRD §3.1: "A new potline starts in `OPERATING` status with
        `curtailment_depth_pct` at 0; `curtailed_since`, `last_full_shutdown_at`,
        and `active_decision_id` are all null."
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix."

        Design: Corner/entities/potline_system_fields_input_ignored
        """
        env = setup_site(with_potline=False)
        payload = create_potline_payload(
            env["smelter"]["id"],
            id="00000000-1111-2222-3333-444444444444",
            version=99,
            operating_status="SHUTDOWN",
            curtailment_depth_pct=100,
        )
        resp = api.create_potline(payload, smelter_manager_headers)
        data = validate_success(resp, 201)
        assert_potline(data)
        assert data["operating_status"] == "OPERATING"
        assert data["curtailment_depth_pct"] == 0
        assert data["version"] == 1
        assert data["id"] != "00000000-1111-2222-3333-444444444444"


class TestPaginationDefaults:
    def test_potlines_list_pagination_defaults(self, api, smelter_manager_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10 when omitted, accepts a minimum of 1, and is bounded
        above at 100. The `offset` parameter specifies how many items to skip
        and defaults to 0."
        PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/endpoints/potlines_list_pagination_defaults
        """
        env = setup_site(with_potline=False)
        sm = env["smelter"]["id"]
        for i in range(1, 12):
            resp = api.create_potline(
                create_potline_payload(sm, line_code=f"L{i:02d}", capacity_tpd=10,
                                       amperage_ka=100),
                smelter_manager_headers,
            )
            assert resp.status_code == 201, f"Setup failed: {resp.text}"

        first = api.list_potlines(sm, smelter_manager_headers)
        data1, meta1 = validate_paginated(first)
        assert len(data1) == 10
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        second = api.list_potlines(sm, smelter_manager_headers, params={"limit": 10, "offset": 10})
        data2, meta2 = validate_paginated(second)
        assert len(data2) == 1
        assert meta2["total_count"] == 11
        assert meta2["has_more"] is False
