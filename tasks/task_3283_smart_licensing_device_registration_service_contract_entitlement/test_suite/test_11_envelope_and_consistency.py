"""Response envelope, pagination, FK listings, clock default, consistency."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_ts_equal,
    make_account,
    make_account_with_va,
    make_coverage,
    make_device,
    make_pool,
    make_registered_device,
    make_service_contract,
    make_va,
    setup_pool_with_assignment,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestResponseEnvelope:
    def test_list_envelope_shape_and_defaults(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." PRD §2.2:
        "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints." PRD §2.3:
        "`limit` defaults to 10 when omitted".

        Design: Corner/endpoints/response_envelope_shape
        """
        make_account()
        make_account()

        resp = api.list_smart_accounts(ADMIN)
        body = resp.json()
        assert resp.status_code == 200
        assert body["meta"]["api_request_id"], "api_request_id must be non-empty"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"], "api_request_timestamp must be present"
        assert body["response_type"] == "array"
        assert body["meta"]["total_count"] == 2
        assert body["meta"]["limit"] == 10
        assert body["meta"]["offset"] == 0
        assert body["meta"]["has_more"] is False


class TestPagination:
    def test_limit_offset_returns_second_row(self, api):
        """PRD §2.3: "List endpoints accept optional `limit` and `offset`
        query parameters." PRD §2.3: "Results are always sorted by
        `created_at` in ascending order."

        Design: Corner/endpoints/pagination_limit_offset
        """
        first = make_account()
        second = make_account()

        rows, meta = validate_paginated(api.list_smart_accounts(
            ADMIN, params={"limit": 1, "offset": 1}))
        assert len(rows) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert rows[0]["id"] == second["id"], (
            "offset=1 on a created_at-ascending list must return the second-created account")


class TestForeignKeyListing:
    def test_devices_of_va_returns_only_own_devices(self, api):
        """PRD §4: "GET /api/virtual-accounts/{id}/devices — List devices of a
        virtual account". PRD §3.4: "a registration request supplies the
        `virtual_account_id` of the segment, a globally unique
        `serial_number`, and the `product_family` code used for lifecycle
        milestone lookups."

        Design: Corner/endpoints/fk_reverse_reachability_devices_of_va
        """
        account = make_account()
        va1 = make_va(account["id"])
        va2 = make_va(account["id"])
        make_device(va1["id"], serial_number="SN-OWN")
        make_device(va2["id"], serial_number="SN-OTHER")

        rows, meta = validate_paginated(api.list_devices_of_va(va1["id"], ADMIN))
        assert len(rows) == 1
        assert rows[0]["serial_number"] == "SN-OWN", (
            "a device of another virtual account must not leak into this list")


class TestLogicalClockDefault:
    def test_default_clock_stamps_server_timestamps(self, api):
        """PRD §2.4: "At server startup, before any administrative action, the
        logical clock reads exactly `2026-09-01T00:00:00Z`." PRD §3.4:
        "Successful activation stamps `registered_at` and `last_sync_at` with
        the logical clock". PRD §3.6: "attachment stamps `covered_from` from
        the logical clock".

        Design: Corner/cross_cutting_layers/clock_default_is_2026_09_01
        """
        account, va = make_account_with_va()
        device = make_device(va["id"])
        activated = validate_success(api.activate_device(device["id"], ADMIN))
        contract = make_service_contract(account["id"])
        coverage = validate_success(api.create_contract_coverage(
            {"service_contract_id": contract["id"], "device_id": device["id"]}, ADMIN),
            expected_status=201)

        assert_ts_equal(activated["registered_at"], "2026-09-01T00:00:00Z")
        assert_ts_equal(coverage["covered_from"], "2026-09-01T00:00:00Z")


class TestImmediateConsistency:
    def test_deregister_releases_assignments_visible_in_next_read(self, api):
        """PRD §3.4: "The transition releases every `ACTIVE` license
        assignment the device holds — each assignment moves to `RELEASED`, and
        each release recomputes the referenced pool's consumption, compliance
        state, and account posture — then increments the device's `version`."

        Design: Corner/consistency_model/immediate_visibility_of_cascade_in_next_read
        """
        account, va, pool, device, asg = setup_pool_with_assignment(
            purchased=10, assign_qty=4)
        before = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert before["consumed_quantity"] == 4

        validate_success(api.deregister_device(device["id"], ADMIN))

        after = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert after["consumed_quantity"] == 0, (
            f"pool consumption must reflect the release immediately, got {after['consumed_quantity']}")
