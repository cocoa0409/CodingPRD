"""Entity creation, defaults, computed-field copies, not-found, and listing behavior."""

import pytest

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    ApiClient,
    assert_claim,
    assert_member,
    assert_plan,
    create_licensed_plan,
    create_member,
    create_plan,
    create_rate_schedule,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    set_clock,
    setup_two_plan_world,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    make_home_plan_operator_headers,
    make_host_plan_operator_headers,
)

NONEXISTENT_PLAN_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestPlanCreationDefaults:
    def test_plan_create_returns_pending_license_and_version_one(self, api: ApiClient):
        """PRD §3.1: "A newly registered plan's `brand_license_status` begins at `PENDING`, and both of its balances, `claims_paid_balance_cents` and `fees_receivable_balance_cents`, begin at zero."

        Design: Corner/entities/plan_create_returns_defaults_pending_and_version_one
        """
        set_clock(api)
        res = api.create_plan(
            f.plan_payload(plan_code="HCA", legal_name="Home Plan CA", service_area_states=["CA"]),
            ASSOCIATION_ADMIN_HEADERS,
        )
        plan = validate_success(res, 201)
        assert_plan(plan)
        assert plan["brand_license_status"] == "PENDING"
        assert plan["version"] == 1
        assert plan["claims_paid_balance_cents"] == 0
        assert plan["fees_receivable_balance_cents"] == 0
        assert is_valid_uuid(plan["id"])
        assert is_iso8601_timestamp(plan["created_at"])
        assert is_iso8601_timestamp(plan["updated_at"])

    def test_plan_create_license_status_not_client_supplied(self, api: ApiClient):
        """PRD §3.1: "A newly registered plan's `brand_license_status` begins at `PENDING`, and both of its balances, `claims_paid_balance_cents` and `fees_receivable_balance_cents`, begin at zero."

        A client-supplied brand_license_status must not override the PENDING default.

        Design: Corner/entities/plan_create_returns_defaults_pending_and_version_one
        """
        set_clock(api)
        payload = f.plan_payload(plan_code="HCA")
        payload["brand_license_status"] = "LICENSED"
        payload["claims_paid_balance_cents"] = 999
        plan = validate_success(api.create_plan(payload, ASSOCIATION_ADMIN_HEADERS), 201)
        assert plan["brand_license_status"] == "PENDING"
        assert plan["claims_paid_balance_cents"] == 0
        assert plan["fees_receivable_balance_cents"] == 0


class TestMemberCreationDefaults:
    def test_member_create_defaults_active_and_links_home_plan(self, api: ApiClient):
        """PRD §3.2: "A member's `eligibility_status` begins at `ACTIVE`""
        PRD §3.2: "optionally a `national_account_id` when the member is covered under a national account — this last field is `null` for members not under such an arrangement"

        Design: Corner/entities/member_create_defaults_active_and_links_home_plan
        """
        set_clock(api)
        home = create_plan(api, plan_code="HCA", service_area_states=["CA"])
        res = api.create_member(
            f.member_payload(home["id"], member_number="M1", full_name="Pat One", national_account_id=None),
            make_home_plan_operator_headers(home["id"]),
        )
        member = validate_success(res, 201)
        assert_member(member)
        assert member["eligibility_status"] == "ACTIVE"
        assert member["home_plan_id"] == home["id"]
        assert member["national_account_id"] is None

    def test_member_create_with_national_account_persists_link(self, api: ApiClient):
        """PRD §3.2: "A member is registered under a home plan by a `HomePlanOperator` (or by the association on the plan's behalf), supplying `home_plan_id`, the `member_number` printed on the ID card, the member's `full_name`, and optionally a `national_account_id` when the member is covered under a national account"

        Design: Corner/entities/member_create_defaults_active_and_links_home_plan
        """
        set_clock(api)
        home = create_licensed_plan(api, plan_code="HCA", service_area_states=["CA"])
        account = get_success_data(
            api.create_national_account(
                f.national_account_payload(home["id"], account_name="Acme Corp", employer_group_id="ACME-1"),
                ASSOCIATION_ADMIN_HEADERS,
            )
        )
        from test_helpers.test_users import make_home_plan_operator_headers

        member = validate_success(
            api.create_member(
                f.member_payload(home["id"], member_number="M1", national_account_id=account["id"]),
                make_home_plan_operator_headers(home["id"]),
            ),
            201,
        )
        assert member["eligibility_status"] == "ACTIVE"
        assert member["national_account_id"] == account["id"]


class TestClaimCreationComputedFields:
    def test_claim_create_copies_home_plan_from_member(self, api: ApiClient):
        """PRD §3.5: "At submission the system copies the member's home plan and national account affiliation onto the claim as `home_plan_id` and `national_account_id` — the latter remaining `null` when the member has no national account — and these copies never change afterward."
        PRD §3.5: "The claim is created in `RECEIVED` status."

        Design: Corner/entities/claim_create_copies_home_plan_from_member
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        claim = validate_success(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                world["host_headers"],
            ),
            201,
        )
        assert_claim(claim)
        assert claim["status"] == "RECEIVED"
        assert claim["home_plan_id"] == world["home"]["id"]
        assert claim["provisional_allowed_cents"] == 20000

    def test_claim_create_client_supplied_home_plan_is_overridden(self, api: ApiClient):
        """PRD §3.5: "At submission the system copies the member's home plan and national account affiliation onto the claim as `home_plan_id` and `national_account_id` — the latter remaining `null` when the member has no national account — and these copies never change afterward."

        A client-supplied home_plan_id must not win over the member's home plan copy.

        Design: Corner/entities/claim_create_copies_home_plan_from_member
        """
        world = setup_two_plan_world(api, with_rate_schedule=False, with_fee_schedule=False)
        payload = f.claim_payload(world["member"]["id"], world["host"]["id"])
        payload["home_plan_id"] = world["host"]["id"]  # wrong on purpose
        claim = validate_success(api.create_claim(payload, world["host_headers"]), 201)
        assert claim["home_plan_id"] == world["home"]["id"]
        assert claim["national_account_id"] is None


class TestPlanNotFound:
    def test_plan_get_unknown_id_returns_not_found(self, api: ApiClient):
        """PRD §2.9: "every referenced resource must exist, and references are validated in left-to-right order. The first missing reference yields `ERR_NOT_FOUND` (HTTP 404) before any business rule is evaluated."

        Design: Corner/entities/plan_get_unknown_id_returns_not_found
        """
        set_clock(api)
        res = api.get_plan(NONEXISTENT_PLAN_ID, ASSOCIATION_ADMIN_HEADERS)
        validate_error(res, "ERR_NOT_FOUND", 404)

    def test_plan_get_unknown_id_for_other_roles_also_404(self, api: ApiClient):
        """PRD §2.9: "every referenced resource must exist, and references are validated in left-to-right order. The first missing reference yields `ERR_NOT_FOUND` (HTTP 404) before any business rule is evaluated."

        Design: Corner/entities/plan_get_unknown_id_returns_not_found
        """
        set_clock(api)
        res = api.get_plan(NONEXISTENT_PLAN_ID, make_host_plan_operator_headers(NONEXISTENT_PLAN_ID))
        validate_error(res, "ERR_NOT_FOUND", 404)


class TestClaimsListPaginationAndFiltering:
    def test_claims_list_paginates_and_filters_by_status(self, api: ApiClient):
        """PRD §3.6: "Claims are listed with optional `home_plan_id`, `host_plan_id`, `member_id`, `national_account_id`, and `status` filters"
        PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/claims_list_paginates_and_filters_by_status
        """
        world = setup_two_plan_world(api, with_fee_schedule=False)
        host_headers = world["host_headers"]

        member2 = create_member(api, world["home"], member_number="M2", full_name="Pat Two")
        c1 = get_success_data(
            api.create_claim(
                f.claim_payload(world["member"]["id"], world["host"]["id"]),
                host_headers,
            )
        )
        c2 = get_success_data(
            api.create_claim(
                f.claim_payload(member2["id"], world["host"]["id"], service_date="2026-08-11"),
                host_headers,
            )
        )
        get_success_data(api.price_claim(c2["id"], host_headers))

        data, meta = validate_paginated(api.list_claims(host_headers, params={"status": "RECEIVED"}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == c1["id"]

        data, meta = validate_paginated(
            api.list_claims(host_headers, params={"host_plan_id": world["host"]["id"], "limit": 1, "offset": 0})
        )
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
