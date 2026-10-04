"""Platform-wide surface: response envelopes, pagination, version/updated_at
semantics, read-after-write visibility, 404s, the monotonic clock, and the
RBAC tiers (PRD sections 2.1, 2.2, 2.3, 2.4, 2.5, 2.9).
"""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    TEST_USERS,
    clock_payload,
    create_account,
    create_account_payload,
    create_kit,
    create_lots,
    create_operational_instrument,
    create_program,
    create_reagent_kit_payload,
    create_reagent_order_payload,
    instrument_event_payload,
    is_iso8601_timestamp,
    make_lab_operator_headers,
    order_line,
    validate_error,
    validate_paginated,
    validate_success,
    advance_clock,
)
from test_helpers import api_client

AM = TEST_USERS["account_manager_headers"]
FA = TEST_USERS["finance_admin_headers"]
PA = TEST_USERS["platform_admin_headers"]
SP = TEST_USERS["supply_planner_headers"]
FSE = TEST_USERS["field_service_engineer_headers"]


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


class TestEnvelopes:
    def test_success_envelope_shape(self, api):
        """A plain account read carries the full success envelope: meta with
        request id and timestamp, response_type object, and the resource in
        data.

        PRD §2.2: "All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:"
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either \"object\" for a single resource or \"array\" for a list of resources."

        Design: Corner/endpoints/success_envelope_shape
        """
        account = create_account()
        resp = api_client.get_account(account["id"], AM)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == account["id"]

    def test_error_envelope_shape(self, api):
        """A 404 carries response_type error with data.error_id and a
        non-empty data.message, and meta holds only the two request fields.

        PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format:"
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
        PRD §2.9: "Fifth, every identifier appearing in the request path must resolve to an existing resource, validated left to right; the first unresolved identifier rejects the request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api_client.get_instrument(NON_EXISTENT_UUID, FA)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip()
        assert set(body["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }


class TestPagination:
    def test_lot_list_pagination_defaults(self, api):
        """Eleven lots under one kit: the default page returns 10 rows with
        total_count 11 and has_more true; limit=5&offset=10 returns the
        tail page of 1 with has_more false.

        PRD §2.3: "`limit` specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/lot_list_pagination_defaults
        """
        kit = create_kit()
        create_lots(kit["id"], 11)
        rows, meta = validate_paginated(
            api_client.list_reagent_lots(SP, params={"kit_id": kit["id"]})
        )
        assert len(rows) == 10
        assert meta["total_count"] == 11
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        tail, tail_meta = validate_paginated(
            api_client.list_reagent_lots(
                SP, params={"kit_id": kit["id"], "limit": 5, "offset": 10}
            )
        )
        assert len(tail) == 1
        assert tail_meta["total_count"] == 11
        assert tail_meta["has_more"] is False


class TestVersionAndVisibility:
    def test_patch_bumps_version_and_restamps_updated_at(self, api):
        """A kit created at the default clock shows version 1 and the default
        created_at; after a one-hour clock advance a price PATCH returns
        version 2, the new price, and updated_at stamped from the new clock.

        PRD §2.5: "`version` (integer): begins at 1 at creation and increases by exactly one on every mutation, whether user-triggered or system-driven."
        PRD §2.5: "`updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource."
        PRD §3.1: "A `PlatformAdmin` price update carries a new `price_cents`, returns the updated kit, increments the kit's `version`, and refreshes its `updated_at`."

        Design: Corner/cross_cutting_layers/version_increments_and_updated_at_refreshes_on_patch
        """
        kit = create_kit()
        assert kit["version"] == 1
        assert _parse_iso(kit["created_at"]) == datetime(
            2026, 9, 1, 0, 0, tzinfo=timezone.utc
        )
        advance_clock("2026-09-01T01:00:00Z")
        patched = validate_success(
            api_client.update_reagent_kit(kit["id"], {"price_cents": 9000}, PA)
        )
        assert patched["version"] == 2
        assert patched["price_cents"] == 9000
        assert _parse_iso(patched["updated_at"]) == datetime(
            2026, 9, 1, 1, 0, tzinfo=timezone.utc
        )

    def test_immediate_visibility_after_write(self, api):
        """A follow-up read observes the just-created program in DRAFT with
        version 1 — creation state is immediately visible.

        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.3: "The program starts in `DRAFT` with the creator recorded as `created_by_user_id`; `period_index` starts at 1; `delivered_spend_cents` and `pipeline_spend_cents` start at 0; `shortfall_flag` starts false; `penalty_cents` starts at 0; and `committed_total_cents` is derived as the annual commitment multiplied by the term in months and divided by 12."
        PRD §2.5: "`version` (integer): begins at 1 at creation and increases by exactly one on every mutation, whether user-triggered or system-driven."

        Design: Corner/consistency_model/immediate_visibility_after_write
        """
        account = create_account()
        program = create_program(account_id=account["id"])
        read = validate_success(api_client.get_placement_program(program["id"], FA))
        assert read["id"] == program["id"]
        assert read["program_state"] == "DRAFT"
        assert read["version"] == 1

    def test_instrument_get_not_found_returns_404(self, api):
        """Reading a well-formed but absent instrument id yields
        ERR_NOT_FOUND.

        PRD §2.9: "Fifth, every identifier appearing in the request path must resolve to an existing resource, validated left to right; the first unresolved identifier rejects the request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/instrument_get_not_found_returns_404
        """
        resp = api_client.get_instrument(NON_EXISTENT_UUID, AM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestClockMonotonicity:
    def test_clock_regression_rejected(self, api):
        """Advancing to 2026-09-02 then attempting 2026-09-01T12:00 fails;
        the clock provably stays at 2026-09-02 because re-setting that very
        instant (not strictly greater) is rejected too.

        PRD §2.4: "A `PlatformAdmin`-only, test-driving capability advances the clock: the request carries a `to_iso8601` instant that must be strictly greater than the clock's current value — the clock is monotonic — and an attempt to hold it steady or move it backwards is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422)."

        Design: Corner/validations/clock_regression_rejected
        """
        result = advance_clock("2026-09-02T00:00:00Z")
        assert result["current_utc"].startswith("2026-09-02")
        resp = api_client.set_clock(clock_payload("2026-09-01T12:00:00Z"), PA)
        validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)
        # Had the rejected call moved the clock backwards, re-applying the
        # 2026-09-02 instant would now be strictly greater and succeed.
        resp2 = api_client.set_clock(clock_payload("2026-09-02T00:00:00Z"), PA)
        validate_error(resp2, ApiErrorId.ERR_CLOCK_REGRESSION)


class TestRbacTiers:
    def test_missing_auth_headers_returns_401(self, api):
        """A request without X-User-Role/X-User-ID is rejected before any
        role or existence check.

        PRD §2.1: "A request with a missing or blank header, or whose role value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/account_create_missing_auth_headers_returns_401
        """
        resp = api_client.create_account(create_account_payload(), NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_catalog_create_forbidden_role_returns_403(self, api):
        """AccountManager is not admitted to reagent-kit creation; the
        endpoint is PlatformAdmin-only.

        PRD §2.1: "Each endpoint admits a fixed set of roles (see §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/genomics/reagent-kits` | Create a reagent kit catalog entry; `capacity_gb` computed at creation | PlatformAdmin |"

        Design: Corner/validations/catalog_create_forbidden_role_returns_403
        """
        resp = api_client.create_reagent_kit(create_reagent_kit_payload(), AM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_lab_operator_cross_account_forbidden(self, api):
        """LabOperator identity is account-backed: account A's operator id
        cannot create an order owned by account B.

        PRD §2.1: "When `X-User-Role` is `LabOperator`, `X-User-ID` is the `id` of the acting account: ownership checks on any resource that references an account compare the resource's `account_id` field — or, for run records, the `account_id` of the referenced instrument — to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`."
        PRD §3.5: "A `LabOperator` creates a reagent order in `DRAFT`, supplying the `account_id` — which must equal the caller's own `X-User-ID` under the ownership rule of §2.1 — plus `lines`, where each line carries a `kit_code` and a `quantity` of at least 1."

        Design: Corner/rbac/lab_operator_cross_account_forbidden
        """
        account_a = create_account(name="Lab XA")
        account_b = create_account(name="Lab XB", region="EU")
        kit = create_kit()
        resp = api_client.create_reagent_order(
            create_reagent_order_payload(
                account_b["id"], [order_line(kit["kit_code"], 1)]
            ),
            make_lab_operator_headers(account_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_field_service_engineer_cannot_decommission(self, api):
        """The shared instrument-events endpoint gates per action:
        DECOMMISSION is AccountManager-only, so a FieldServiceEngineer firing
        it is rejected even though the role can use the endpoint.

        PRD §2.1: "Four multi-action endpoints gate per action rather than per endpoint, and the wrong role for the attempted action is rejected with `ERR_FORBIDDEN`: on instrument lifecycle events, decommissioning requires `AccountManager` while shipping, installing, commissioning, and service open/close require `FieldServiceEngineer`; on placement-program review, submitting requires `AccountManager` while approving and rejecting require `FinanceAdmin`; on placement-program amendments, creating requires `AccountManager` while approving and rejecting require `FinanceAdmin`; on reagent-order advancement, submitting, cancelling, and returning require `LabOperator` while shipping and delivering require `SupplyPlanner`."

        Design: Corner/rbac/fse_cannot_decommission
        """
        instrument = create_operational_instrument()
        resp = api_client.post_instrument_event(
            instrument["id"], instrument_event_payload("DECOMMISSION"), FSE
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api_client.get_instrument(instrument["id"], AM))
        assert after["install_state"] == "OPERATIONAL"
