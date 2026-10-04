"""Storm declaration, unit registration, and envelope/system-field contracts."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_storm_event,
    assert_unit,
    create_storm,
    create_unit_for,
    create_unit_payload,
    set_clock,
    setup_storm_with_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStormDeclaration:
    def test_storm_create_returns_declared_fields_and_watch_defaults(self, api, admin_headers):
        """PRD §3.1: "The new `StormEvent` is born in `WATCH` status; the server
        stamps `watch_started_at` from the logical clock — this timestamp anchors
        the pre-positioning window described in §3.4 — and initializes
        `warning_count` to zero."
        PRD §2.4: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/storm_event_create_returns_declared_fields_and_watch_defaults
        """
        set_clock("2026-09-10T08:00:00Z")
        resp = api.create_storm_event({"name": "Hurricane Delta"}, admin_headers)
        storm = validate_success(resp, 201)
        assert_storm_event(storm)
        assert storm["status"] == "WATCH"
        assert storm["warning_count"] == 0
        assert storm["version"] == 1
        assert storm["watch_started_at"] == "2026-09-10T08:00:00.000Z", (
            f"watch_started_at must equal the logical clock, got {storm['watch_started_at']}"
        )
        assert storm["activated_at"] is None
        assert storm["closed_at"] is None

    def test_storm_create_response_envelope_carries_request_meta(self, api, admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §3.1: "The new `StormEvent` is born in `WATCH` status; the server
        stamps `watch_started_at` from the logical clock — this timestamp anchors
        the pre-positioning window described in §3.4 — and initializes
        `warning_count` to zero."

        Design: Corner/entities/storm_event_create_returns_declared_fields_and_watch_defaults
        """
        set_clock("2026-09-10T08:00:00Z")
        resp = api.create_storm_event({"name": "Hurricane Delta"}, admin_headers)
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["data"]["status"] == "WATCH"
        assert body["data"]["warning_count"] == 0

    def test_client_supplied_id_and_version_are_ignored(self, api, admin_headers):
        """PRD §2.4: "Client-supplied `id` or `version` values on creation
        payloads are ignored: system fields are always server-minted."

        Design: Corner/entities/system_fields_id_and_version_are_server_controlled
        """
        set_clock("2026-09-10T08:00:00Z")
        resp = api.create_storm_event(
            {"name": "Hurricane Delta",
             "id": NON_EXISTENT_UUID,
             "version": 99},
            admin_headers,
        )
        storm = validate_success(resp, 201)
        assert storm["id"] != NON_EXISTENT_UUID, "client-supplied id must be ignored"
        assert storm["version"] == 1, f"client-supplied version must be ignored, got {storm['version']}"


class TestUnitRegistration:
    def test_unit_create_applies_defaults_and_full_menu(self, api):
        """PRD §3.1: "An optional `lodging_fund_cents` seeds the per-unit storm
        lodging and travel fund; omitted, the fund starts at zero. Each
        registered unit carries its parent linkage in `storm_event_id`, begins
        with `menu_tier` at `FULL`, all four resource axes `UP`, and
        `cash_only_flag` false."

        Design: Corner/entities/unit_create_applies_defaults_and_full_menu
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        unit = ctx["unit"]
        assert_unit(unit)
        assert unit["menu_tier"] == "FULL"
        assert unit["cash_only_flag"] is False
        assert unit["lodging_fund_cents"] == 0
        assert unit["resource_status"] == {
            "power": "UP", "water": "UP", "gas": "UP", "payment_network": "UP"
        }
        assert unit["last_shift_change_at"] is None
        assert unit["hours_since_shift_change"] == 0
        assert unit["storm_event_id"] == ctx["storm"]["id"]

    def test_unit_creation_requires_parent_storm(self, api, admin_headers):
        """PRD §2.8: "Paths that address nested resources are validated left to
        right. For a path such as a checklist item under a checklist run under
        a unit, the server first confirms that the unit identifier exists, then
        that the run identifier exists and belongs to that unit, before any
        business rule is evaluated; the first missing or wrongly nested
        identifier yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/unit_creation_requires_parent_storm
        """
        set_clock("2026-09-10T08:00:00Z")
        resp = api.create_unit(
            NON_EXISTENT_UUID, create_unit_payload(), admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestStormListPagination:
    def test_list_endpoints_paginate_with_defaults(self, api, admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of returned items:
        it defaults to 10 when omitted, with a minimum of 1 and a maximum of
        100. The `offset` parameter skips a number of items from the head of
        the result set and defaults to 0."
        PRD §2.3: "All list responses expose the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` inside the `meta` object of
        the envelope."

        Design: Corner/endpoints/list_endpoints_paginate_with_defaults
        """
        set_clock("2026-09-10T08:00:00Z")
        for i in range(1, 13):
            create_storm(clock=None, name=f"S{i:02d}")
        page1, meta1 = validate_paginated(api.list_storm_events(admin_headers))
        assert len(page1) == 10, f"default page must hold 10, got {len(page1)}"
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(
            api.list_storm_events(admin_headers, params={"limit": 10, "offset": 10})
        )
        assert len(page2) == 2, f"second page must hold 2, got {len(page2)}"
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 12
