"""Accounts, plan tiers, pagination, auth and RBAC (PRD §2.1, §2.3, §3.1)."""
from test_helpers import (
    ApiErrorId,
    ENTERPRISE_PLAN,
    assert_billing_account,
    create_account,
    create_billing_account_payload,
    create_plan_tier_config,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BA, FR, IA, PA


class TestBillingAccountCreation:
    def test_create_returns_declared_fields_and_good_standing(self, api):
        """PRD §3.1: "A new account carries `standing` set to `GOOD`."
        PRD §2.4: "`version` (integer): A system-managed integer starting at 1 that
        increments with every modification to the resource."

        Design: Corner/entities/billing_account_create_returns_declared_fields_and_good_standing
        """
        set_clock()
        create_plan_tier_config()
        data = validate_success(
            api.create_billing_account(
                create_billing_account_payload(name="Test Acct"), PA
            ),
            expected_status=201,
        )
        assert_billing_account(data)
        assert data["standing"] == "GOOD"
        assert data["version"] == 1
        assert data["plan_tier"] == "ENTERPRISE"

    def test_create_ignores_client_supplied_system_fields(self, api):
        """PRD §3.1: "A new account carries `standing` set to `GOOD`."
        PRD §2.4: "`id` (string): A unique, server-minted identifier for the
        resource, formatted as a UUID with no type prefix."

        Design: Corner/entities/system_fields_on_create_input_ignored
        """
        set_clock()
        create_plan_tier_config()
        payload = create_billing_account_payload(name="SysFields")
        payload["id"] = "00000000-0000-4000-8000-deadbeefdead"
        payload["version"] = 99
        payload["standing"] = "DELINQUENT"
        data = validate_success(api.create_billing_account(payload, PA), expected_status=201)
        assert data["id"] != "00000000-0000-4000-8000-deadbeefdead"
        assert data["version"] == 1
        assert data["standing"] == "GOOD"

    def test_create_missing_plan_tier_rejected(self, api):
        """PRD §2.5: "Payload schema. Required fields present, types correct, enum
        values valid — otherwise `ERR_INVALID_REQUEST`."
        PRD §3.1: "supplying a display `name`, a `plan_tier` of `FREE`, `PRO`, or
        `ENTERPRISE`, and a `billing_cycle_anchor_day`".

        Design: Corner/entities/billing_account_create_missing_plan_tier_returns_invalid_request
        """
        set_clock()
        resp = api.create_billing_account(
            {"name": "NoPlan", "billing_cycle_anchor_day": 1}, PA
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_plan_tier_out_of_enum_rejected(self, api):
        """PRD §2.5: "Payload schema. Required fields present, types correct, enum
        values valid — otherwise `ERR_INVALID_REQUEST`."
        PRD §3.1: "a `plan_tier` of `FREE`, `PRO`, or `ENTERPRISE`".

        Design: Corner/entities/plan_tier_enum_out_of_set_rejected
        """
        set_clock()
        resp = api.create_billing_account(
            create_billing_account_payload(name="BadTier", plan_tier="GOLD"), PA
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_unknown_account_returns_not_found(self, api):
        """PRD §2.5: "Path existence. When an endpoint path contains multiple
        resource identifiers ... rejects with `ERR_NOT_FOUND` at the first identifier
        that does not resolve."

        Design: Corner/entities/billing_account_get_with_unknown_id_returns_not_found
        """
        set_clock()
        resp = api.get_billing_account("00000000-0000-4000-8000-000000000000", PA)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestPagination:
    def test_list_reports_total_count_and_has_more(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/entities/pagination_reports_total_count_and_has_more
        """
        set_clock()
        create_plan_tier_config()
        for name in ("A1", "A2", "A3"):
            create_account(name=name)
        data, meta = validate_paginated(
            api.list_billing_accounts(PA, params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        data2, meta2 = validate_paginated(
            api.list_billing_accounts(PA, params={"limit": 2, "offset": 2})
        )
        assert len(data2) == 1
        assert meta2["has_more"] is False


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value
        outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_returns_401
        """
        set_clock()
        resp = api.get("/api/billing-accounts", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_unknown_role_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value
        outside this enumeration, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_returns_401
        """
        set_clock()
        resp = api.get(
            "/api/billing-accounts",
            headers={"X-User-ID": "someone", "X-User-Role": "SuperUser"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestRbacDenials:
    def test_team_lead_cannot_close_billing_period(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted to
        invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /billing-accounts/{id}/billing-periods/{id}/close is authorized
        for BillingAdmin only.

        Design: Corner/endpoints/rbac_team_lead_cannot_close_billing_period
        """
        from test_helpers import make_team_lead_headers, setup_account_with_period

        account, period = setup_account_with_period(name="RBAC")
        team = validate_success(
            api.create_team(account["id"], {"name": "T", "cost_center": "C"}, BA),
            expected_status=201,
        )
        resp = api.close_billing_period(
            account["id"], period["id"], make_team_lead_headers(team["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_finance_reader_cannot_create_commitment(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted to
        invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /billing-accounts/{id}/commitments is authorized for
        BillingAdmin only.

        Design: Corner/endpoints/rbac_finance_reader_cannot_create_commitment
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="FR")
        payload = {
            "meter": "INFRA_HOST",
            "committed_quantity": 1,
            "window_start_utc": "2026-09-01T00:00:00Z",
            "window_end_utc": "2026-09-30T23:59:59Z",
            "committed_unit_rate_cents": 100,
            "overage_unit_rate_cents": 500,
            "expected_billing_account_version": account["version"],
        }
        resp = api.create_commitment(account["id"], payload, FR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_ingestion_agent_cannot_create_billing_account(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted to
        invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /billing-accounts is authorized for PlatformAdmin only.

        Design: Corner/rbac/unauthenticated_request_returns_401
        """
        set_clock()
        resp = api.create_billing_account(create_billing_account_payload(), IA)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
