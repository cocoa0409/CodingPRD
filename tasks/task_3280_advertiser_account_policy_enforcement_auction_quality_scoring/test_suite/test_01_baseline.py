"""Baseline creation/defaults/listing tests translated from the corner design index
(entities section) plus the logical-clock corner instances."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_account_payload,
    create_campaign_payload,
    create_account,
    set_clock,
    create_billing_profile,
    make_advertiser_headers,
    validate_error,
    validate_success,
    get_success_data,
    is_valid_uuid,
)


class TestAccountCreationDefaults:
    def test_account_create_returns_defaults_and_system_fields(self, api):
        """PRD §3.1: "The new account begins in `PENDING_VERIFICATION` with all
        lifetime counters at zero: `lifetime_valid_served_cents`,
        `lifetime_billed_cents`, `lifetime_overdelivery_credit_cents`, and
        `lifetime_invalid_click_credit_cents` each start at 0, and both
        `suspension_reason_code` and `suspended_at` are null."
        PRD §2.4: "Every persisted resource carries an `id`, minted by the server
        as a UUID with no type prefix."

        Design: Corner/entities/account_create_returns_defaults_and_system_fields
        """
        resp = api.create_advertiser_account(
            create_account_payload(business_name="Default Corp"),
            TEST_USERS["anonymous_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING_VERIFICATION"
        assert data["version"] == 1
        assert data["verified_business_name"] is None
        assert data["disclosure_text"] is None
        assert data["suspension_reason_code"] is None
        assert data["suspended_at"] is None
        assert data["lifetime_valid_served_cents"] == 0
        assert data["lifetime_billed_cents"] == 0
        assert data["lifetime_overdelivery_credit_cents"] == 0
        assert data["lifetime_invalid_click_credit_cents"] == 0
        assert data["upheld_appeal_count"] == 0
        assert is_valid_uuid(data["id"])

    def test_clock_default_is_fixed_at_startup(self, api):
        """PRD §2.5: "Before the clock is ever set, it reads exactly
        `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time."

        Design: Corner/cross_cutting_complexity_layers/clock_default_is_fixed_at_startup
        """
        resp = api.create_advertiser_account(
            create_account_payload(business_name="Clock Corp"),
            TEST_USERS["anonymous_headers"],
        )
        data = validate_success(resp, expected_status=201)
        created = data["created_at"]
        # The logical clock reads exactly 2026-09-01T00:00:00Z; the timestamp may
        # carry fractional digits but must be the default logical instant.
        assert created.startswith("2026-09-01T00:00:00"), (
            f"created_at must be the default logical clock instant, got {created}"
        )


class TestCampaignCreationDefaults:
    def test_campaign_create_applies_defaults_and_date_roundtrip(self, api):
        """PRD §3.3: "The `Advertiser` creates campaigns in `DRAFT` by supplying
        the owning `account_id`, a `name`, a `daily_budget_cents` of at least 100
        cents, and an inclusive flight window from `start_date` to `end_date` in
        `YYYY-MM-DD` form."
        PRD §3.5: "By contrast, `monthly_cap_provisional_cents` — the
        forward-looking diagnostic exposed on every campaign read — uses only the
        campaign's current `daily_budget_cents`: the current budget multiplied by
        304 and then integer-divided by 10."

        Design: Corner/entities/campaign_create_applies_defaults_and_date_roundtrip
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("Def Corp")
        headers = make_advertiser_headers(account["id"])
        resp = api.create_campaign(
            create_campaign_payload(
                account["id"], name="CD", daily_budget_cents=1000,
                start_date="2026-09-01", end_date="2026-09-30",
            ),
            headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["pause_origin"] == "NONE"
        assert data["eligible_ad_count"] == 0
        assert data["served_lifetime_cents"] == 0
        assert data["monthly_cap_provisional_cents"] == 30400  # 1000 * 304 // 10
        assert data["last_closed_month_cap_cents"] is None
        assert data["last_closed_month_credit_cents"] is None


class TestNotFound:
    def test_get_campaign_returns_not_found_for_unknown_id(self, api):
        """PRD §2.7: "The first id that fails to resolve yields `ERR_NOT_FOUND`
        (HTTP 404), and resolution stops there."

        Design: Corner/entities/get_campaign_returns_not_found_for_unknown_id
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("NF Corp")
        headers = make_advertiser_headers(account["id"])
        resp = api.get_campaign(NON_EXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPagination:
    def test_campaigns_list_paginates_with_total_count_and_has_more(self, api):
        """PRD §2.3: "List endpoints accept two optional query parameters, `limit`
        and `offset`. `limit` defaults to 10, must be at least 1, and may be at
        most 100; `offset` defaults to 0. List responses order by `created_at`
        ascending. The `meta` object of every list response carries `limit`,
        `offset`, `total_count` (the full count of matching resources, not just
        the page), and `has_more` (true when more resources exist beyond the
        returned page)."

        Design: Corner/entities/campaigns_list_paginates_with_total_count_and_has_more
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("Page Corp")
        headers = make_advertiser_headers(account["id"])
        for name in ("P1", "P2", "P3"):
            api.create_campaign(
                create_campaign_payload(
                    account["id"], name=name, daily_budget_cents=100,
                    start_date="2026-09-01", end_date="2026-09-30",
                ),
                headers,
            )
        # First page: limit=2, offset=0
        resp1 = api.list_campaigns(
            headers, params={"account_id": account["id"], "limit": 2, "offset": 0}
        )
        from test_helpers import validate_paginated
        page1, meta1 = validate_paginated(resp1)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        # Second page: limit=2, offset=2
        resp2 = api.list_campaigns(
            headers, params={"account_id": account["id"], "limit": 2, "offset": 2}
        )
        page2, meta2 = validate_paginated(resp2)
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestKeywordFields:
    def test_keyword_normalized_text_is_computed_input_ignored_for_snapshot(self, api):
        """PRD §3.4: "The server derives `normalized_text` from the raw text by
        lowercasing, trimming, and collapsing internal whitespace to single
        spaces; keywords are listed per ad group with an optional `is_negative`
        filter."

        Design: Corner/entities/keyword_normalized_text_is_computed_input_ignored_for_snapshot
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("Norm Corp")
        headers = make_advertiser_headers(account["id"])
        camp = get_success_data(api.create_campaign(
            create_campaign_payload(account["id"], name="CK", daily_budget_cents=100,
                                    start_date="2026-09-01", end_date="2026-09-30"),
            headers,
        ))
        ag = get_success_data(api.create_ad_group(camp["id"], {"name": "AG"}, headers))
        resp = api.create_keyword(
            ag["id"],
            {"text": "  Shoes   MEN ", "match_type": "EXACT", "max_cpc_cents": 150},
            headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["normalized_text"] == "shoes men"
        assert data["text"] == "  Shoes   MEN "

    def test_keyword_invalid_match_type_enum_returns_validation(self, api):
        """PRD §2.10 item 4: "Request-body shape — required fields present, types
        valid, enum values legal, integer ranges respected (the quality component
        scores between 1 and 10, `max_cpc_cents` strictly positive on a
        non-negative keyword), and a negative keyword forbidden from carrying
        `max_cpc_cents`, all yielding `ERR_VALIDATION` (400)."

        Design: Corner/entities/keyword_invalid_match_type_enum_returns_validation
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("Enum Corp")
        headers = make_advertiser_headers(account["id"])
        camp = get_success_data(api.create_campaign(
            create_campaign_payload(account["id"], name="CK2", daily_budget_cents=100,
                                    start_date="2026-09-01", end_date="2026-09-30"),
            headers,
        ))
        ag = get_success_data(api.create_ad_group(camp["id"], {"name": "AG2"}, headers))
        resp = api.create_keyword(
            ag["id"],
            {"text": "shoes", "match_type": "FUZZY", "max_cpc_cents": 100},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestBillingProfileCardinality:
    def test_billing_profile_one_per_account(self, api):
        """PRD §3.5: "Each account has exactly one billing profile."
        PRD §3.5: "A duplicate profile is `ERR_BILLING_PROFILE_EXISTS` (409).
        Fetching the profile through the account returns an array of zero or one
        profiles — empty before creation, one element after."

        Design: Corner/entities/billing_profile_one_per_account
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("BP Corp")
        headers = make_advertiser_headers(account["id"])
        profile = create_billing_profile(account, payment_method_type="CARD")
        resp = api.create_billing_profile(
            account["id"], {"payment_method_type": "INVOICING"}, headers
        )
        validate_error(resp, ApiErrorId.ERR_BILLING_PROFILE_EXISTS)
        got = get_success_data(api.get_account_billing_profile(account["id"], headers))
        assert isinstance(got, list) and len(got) == 1
        assert got[0]["payment_method_type"] == "CARD"
