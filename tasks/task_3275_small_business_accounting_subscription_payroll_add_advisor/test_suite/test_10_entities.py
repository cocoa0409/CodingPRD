"""Corner / entities — creation shape, retrieval round-trip, pagination,
not-found, required fields, defaults, computed fields, system fields,
enum domain, and parent-FK scoping.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_user,
    create_company,
    create_company_user,
    create_essentials_plan,
    create_firm,
    create_plus_plan,
    create_primary_admin,
    get_subscription,
    reset_clock,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_company_user_headers,
)


class TestFirmCreateReturnsDeclaredFields:
    def test_firm_create_returns_every_declared_field_and_starts_active(self, client):
        """PRD 3.10: "The platform operator registers an `AccountantFirm`
        with its `firm_name`, its negotiated `wholesale_discount_pct`
        (between 0 and 0.50, two-decimal precision), and its
        `proadvisor_tier` of `SILVER`, `GOLD`, or `PLATINUM`."
        PRD 2.4: "Every persisted resource exposes an `id` — a server-minted
        UUID with no type prefix — and a `created_at` timestamp in ISO 8601
        UTC with three fractional digits. Most resources additionally carry
        `updated_at` (same format, refreshed on every mutation) and
        `version`, an integer starting at 1 that increments on every
        mutation of that resource."

        Design: Corner/entities/firm_create_returns_every_declared_field_and_starts_active
        """
        reset_clock(client)
        response = client.create_firm(
            {"firm_name": "Fiesta CPAs", "wholesale_discount_pct": 0.25,
             "proadvisor_tier": "GOLD"},
            headers=PLATFORM_ADMIN,
        )
        data = validate_success(response, expected_status=201)
        assert data["firm_status"] == "ACTIVE"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])


class TestPlanRoundTrip:
    def test_plan_create_and_get_round_trips_all_fields(self, client):
        """PRD 3.1: "Each plan carries a unique `plan_code` ... together
        with a monthly `list_price_cents`, a `max_seats` allowance, four
        feature flags (`feature_inventory`, `feature_project_profitability`,
        `feature_multi_currency`, and `feature_bank_rules`), and a
        `plan_rank`."
        PRD 2.4: "Two resource kinds deliberately carry only `id` and
        `created_at`: a `SubscriptionPlan` and a `Category` have neither
        `updated_at` nor `version`; responses for these entities must not
        include those fields."

        Design: Corner/entities/plan_create_and_get_round_trips_all_fields
        """
        reset_clock(client)
        create_response = client.create_plan(
            f.create_plan_payload(), headers=PLATFORM_ADMIN
        )
        created = validate_success(create_response, expected_status=201)
        get_response = client.get_plan(created["id"], headers=PLATFORM_ADMIN)
        plan = validate_success(get_response, expected_status=200)
        assert plan["plan_code"] == "PLUS"
        assert plan["list_price_cents"] == 8000
        assert plan["max_seats"] == 5
        assert plan["feature_inventory"] is True
        assert plan["feature_project_profitability"] is True
        assert plan["feature_multi_currency"] is True
        assert plan["feature_bank_rules"] is True
        assert plan["plan_rank"] == 3
        assert "version" not in plan
        assert "updated_at" not in plan


class TestCompanyUsersPagination:
    def test_company_users_list_paginates_and_reports_total_count_and_has_more(self, client):
        """PRD 2.3: "List endpoints accept `limit` and `offset` query
        parameters. `limit` defaults to 10, with a minimum of 1 and a
        maximum of 100; `offset` defaults to 0. Every list response's
        `meta` block carries `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/company_users_list_paginates_and_reports_total_count_and_has_more
        """
        reset_clock(client)
        plan = create_essentials_plan(client, max_seats=5)
        company = create_company(client, plan["id"], legal_name="Pagination Co")
        admin = create_primary_admin(client, company["id"], email="admin@p.example")
        admin_headers = make_company_user_headers(admin["id"])
        create_company_user(
            client, company["id"], actor_headers=admin_headers,
            email="u2@p.example", display_name="U2",
        )
        create_company_user(
            client, company["id"], actor_headers=admin_headers,
            email="u3@p.example", display_name="U3",
        )

        page1 = client.list_company_users(
            company["id"], headers=PLATFORM_ADMIN, params={"limit": 2, "offset": 0}
        )
        rows1, meta1 = validate_paginated(page1)
        assert len(rows1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2 = client.list_company_users(
            company["id"], headers=PLATFORM_ADMIN, params={"limit": 2, "offset": 2}
        )
        rows2, meta2 = validate_paginated(page2)
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestFirmNotFound:
    def test_firm_get_with_unknown_id_returns_not_found(self, client):
        """PRD 2.4: "Nested URLs are validated left to right: each path
        segment's identifier must resolve to an existing resource before
        the next is examined, and the first unresolvable identifier
        determines the `ERR_NOT_FOUND` (HTTP 404) response."

        Design: Corner/entities/firm_get_with_unknown_id_returns_not_found
        """
        reset_clock(client)
        response = client.get_firm(NON_EXISTENT_UUID, headers=PLATFORM_ADMIN)
        validate_error(response, E.ERR_NOT_FOUND)


class TestCompanyCreateRequiredFields:
    def test_company_create_missing_required_field_returns_invalid_request(self, client):
        """PRD 2.4: "Malformed bodies, missing required fields, or type
        violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/company_create_missing_required_field_returns_invalid_request
        """
        reset_clock(client)
        plan = create_essentials_plan(client)
        response = client.create_company(
            # legal_name omitted
            {"admin_email": "x@x.example", "home_country": "US",
             "data_region": "US", "plan_id": plan["id"]},
            headers=PLATFORM_ADMIN,
        )
        validate_error(response, E.ERR_INVALID_REQUEST)


class TestFirmAdminDefault:
    def test_company_user_is_firm_admin_default_false_applies_when_omitted(self, client):
        """PRD 3.10: "Advisors join the firm as `AccountantUser` records
        with a `full_name`, an `email` unique within the firm (duplicates
        rejected with `ERR_DUPLICATE`), and an `is_firm_admin` flag
        (defaulting to false) marking who may manage billing transfers."

        Design: Corner/entities/company_user_is_firm_admin_default_false_applies_when_omitted
        """
        reset_clock(client)
        firm = create_firm(client)
        response = client.create_firm_user(
            firm["id"],
            {"firm_id": firm["id"], "full_name": "No Flag",
             "email": "noflag@f.example"},
            headers=PLATFORM_ADMIN,
        )
        user = validate_success(response, expected_status=201)
        assert user["is_firm_admin"] is False


class TestSubscriptionComputedFieldInputIgnored:
    def test_subscription_monthly_price_is_computed_input_ignored(self, client):
        """PRD 2.8: "Every computed or derived field named in §3
        (`monthly_price_cents`, `pending_upgrade_prompt`, `tax_filing_status`,
        `cleared_cents`, `difference_cents`, `total_cents`, `conflict_count`,
        `limitation_codes`, `proforma_monthly_cents`) is recomputed by the
        server on the triggers stated with it; clients never supply these
        values, and they appear on every read of the owning resource."

        Design: Corner/entities/subscription_monthly_price_is_computed_input_ignored
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        response = client.create_company(
            {"legal_name": "Cheat Co", "admin_email": "cheat@c.example",
             "home_country": "US", "data_region": "US",
             "plan_id": plan["id"], "monthly_price_cents": 1},
            headers=PLATFORM_ADMIN,
        )
        company = validate_success(response, expected_status=201)
        subscription = get_subscription(client, company["id"])
        assert subscription["monthly_price_cents"] == 8000, (
            "client-supplied monthly_price_cents must be ignored; the server "
            "computes the value from the plan list price"
        )


class TestCompanyUserSystemFields:
    def test_company_user_id_created_at_updated_at_are_system_stamped(self, client):
        """PRD 2.4: "Every persisted resource exposes an `id` — a
        server-minted UUID with no type prefix — and a `created_at`
        timestamp in ISO 8601 UTC with three fractional digits. Most
        resources additionally carry `updated_at` (same format, refreshed
        on every mutation) and `version`, an integer starting at 1 that
        increments on every mutation of that resource."

        Design: Corner/entities/company_user_id_created_at_updated_at_are_system_stamped
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        company = create_company(client, plan["id"], legal_name="Sys Co")
        response = client.create_company_user(
            company["id"],
            f.create_company_user_payload(company["id"], email="u@s.example"),
            headers=PLATFORM_ADMIN,
        )
        user = validate_success(response, expected_status=201)
        assert is_valid_uuid(user["id"])
        assert user["version"] == 1
        assert is_iso8601_timestamp(user["created_at"])
        assert is_iso8601_timestamp(user["updated_at"])


class TestEnumDomainRejectsUnknownValue:
    def test_plan_create_with_out_of_enum_feature_value_rejected(self, client):
        """PRD 2.4: "any enum field whose value falls outside its declared
        set is rejected with `ERR_INVALID_ENUM` (HTTP 400)."

        Design: Corner/entities/plan_create_with_out_of_enum_feature_value_rejected
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        response = client.create_company(
            {"legal_name": "Bad Region Co", "admin_email": "br@br.example",
             "home_country": "US", "data_region": "APAC",
             "plan_id": plan["id"]},
            headers=PLATFORM_ADMIN,
        )
        validate_error(response, E.ERR_INVALID_ENUM)


class TestPayrollAddonSubscriptionFK:
    def test_payroll_addon_requires_valid_subscription_fk(self, client):
        """PRD 2.4: "Body-level foreign keys (for example `plan_id`,
        `assign_category_id`, `accountant_user_id`, `initiating_firm_id`)
        are then validated in the order they appear in the endpoint's
        input list, again surfacing `ERR_NOT_FOUND` for the first miss."

        Design: Corner/entities/payroll_addon_requires_valid_subscription_fk
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        company_a = create_company(client, plan["id"], legal_name="A Co")
        company_b = create_company(client, plan["id"], legal_name="B Co")
        admin_a = create_primary_admin(client, company_a["id"], email="adm@a.example")
        accept_user(client, company_a["id"], admin_a["id"])
        sub_a = get_subscription(client, company_a["id"])

        # Use company A's subscription id when calling under company B — the
        # FK is unresolvable inside company B's scope.
        response = client.create_payroll(
            company_b["id"],
            {"subscription_id": sub_a["id"], "service_level": "SELF_SERVICE"},
            headers=make_company_user_headers(admin_a["id"]),
        )
        # PRD 2.9 pins the priority order: identity resolution
        # (ERR_IDENTITY_MISMATCH) is evaluated before body-FK existence
        # (ERR_NOT_FOUND).  Here the acting user belongs to company A while
        # the path targets company B, so BOTH checks fail and the priority
        # order uniquely determines ERR_IDENTITY_MISMATCH.  A PRD-faithful
        # reader could also scope the subscription FK lookup to the path
        # company without running the actor-ownership check on this route,
        # in which case the FK miss surfaces ERR_NOT_FOUND.  Accept either.
        validate_error_is_one_of(
            response, [E.ERR_IDENTITY_MISMATCH, E.ERR_NOT_FOUND]
        )
