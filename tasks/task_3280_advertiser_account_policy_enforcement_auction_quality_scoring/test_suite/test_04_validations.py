"""Validation-error corner tests (campaigns, keywords, temporal rules)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_campaign_payload,
    create_campaign,
    create_ad_group,
    create_verified_account,
    create_billing_profile,
    set_clock,
    make_advertiser_headers,
    validate_error,
    validate_success,
    get_success_data,
)


class TestCampaignShapeAndFiscalValidation:
    def test_campaign_create_missing_budget_returns_validation(self, api):
        """PRD §2.10 item 4: "Request-body shape — required fields present, types
        valid, enum values legal, integer ranges respected (the quality component
        scores between 1 and 10, `max_cpc_cents` strictly positive on a
        non-negative keyword), and a negative keyword forbidden from carrying
        `max_cpc_cents`, all yielding `ERR_VALIDATION` (400)."

        Design: Corner/validations/campaign_create_missing_budget_returns_validation
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("NB Corp")
        resp = api.create_campaign(
            {"account_id": account["id"], "name": "NB",
             "start_date": "2026-09-01", "end_date": "2026-09-30"},
            make_advertiser_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_campaign_budget_below_minimum_returns_fiscal_error(self, api):
        """PRD §3.3: "a daily budget below the 100-cent floor is
        `ERR_BUDGET_BELOW_MINIMUM` (422)."
        PRD §3.3: "The `Advertiser` creates campaigns in `DRAFT` by supplying the
        owning `account_id`, a `name`, a `daily_budget_cents` of at least 100
        cents, and an inclusive flight window from `start_date` to `end_date` in
        `YYYY-MM-DD` form."

        Design: Corner/validations/campaign_budget_below_minimum_returns_fiscal_error
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("B Corp")
        headers = make_advertiser_headers(account["id"])
        resp = api.create_campaign(
            create_campaign_payload(account["id"], name="B99", daily_budget_cents=99,
                                    start_date="2026-09-01", end_date="2026-09-30"),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_BUDGET_BELOW_MINIMUM)
        ok = api.create_campaign(
            create_campaign_payload(account["id"], name="B100", daily_budget_cents=100,
                                    start_date="2026-09-01", end_date="2026-09-30"),
            headers,
        )
        validate_success(ok, expected_status=201)

    def test_campaign_end_before_start_returns_date_range_error(self, api):
        """PRD §3.3: "An end date earlier than the start date — whether at
        creation or on a later update — is rejected with
        `ERR_CAMPAIGN_DATE_RANGE_INVALID` (422)."

        Design: Corner/validations/campaign_end_before_start_returns_date_range_error
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("BAD Corp")
        resp = api.create_campaign(
            create_campaign_payload(account["id"], name="BAD", daily_budget_cents=100,
                                    start_date="2026-09-20", end_date="2026-09-10"),
            make_advertiser_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_DATE_RANGE_INVALID)


class TestKeywordValidation:
    def test_negative_keyword_must_not_carry_bid(self, api):
        """PRD §3.4: "A negative keyword must not carry `max_cpc_cents`;
        supplying one is a body-shape failure."

        Design: Corner/validations/negative_keyword_must_not_carry_bid
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("NK Corp")
        headers = make_advertiser_headers(account["id"])
        camp = get_success_data(api.create_campaign(
            create_campaign_payload(account["id"], name="NK", daily_budget_cents=100,
                                    start_date="2026-09-01", end_date="2026-09-30"),
            headers,
        ))
        ag = get_success_data(api.create_ad_group(camp["id"], {"name": "AG"}, headers))
        resp = api.create_keyword(
            ag["id"],
            {"text": "free", "match_type": "BROAD", "is_negative": True, "max_cpc_cents": 100},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        ok = api.create_keyword(
            ag["id"], {"text": "free", "match_type": "BROAD", "is_negative": True}, headers
        )
        validate_success(ok, expected_status=201)

    def test_duplicate_keyword_tuple_rejected(self, api):
        """PRD §2.11: "A keyword whose combination of `normalized_text`,
        `match_type`, and `is_negative` already exists in the same ad group is
        rejected with `ERR_DUPLICATE_KEYWORD` (409)."

        Design: Corner/validations/duplicate_keyword_tuple_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("DK Corp")
        headers = make_advertiser_headers(account["id"])
        camp = get_success_data(api.create_campaign(
            create_campaign_payload(account["id"], name="DK", daily_budget_cents=100,
                                    start_date="2026-09-01", end_date="2026-09-30"),
            headers,
        ))
        ag = get_success_data(api.create_ad_group(camp["id"], {"name": "AG"}, headers))
        api.create_keyword(
            ag["id"], {"text": "shoes", "match_type": "EXACT", "max_cpc_cents": 100}, headers
        )
        resp = api.create_keyword(
            ag["id"], {"text": "SHOES", "match_type": "EXACT", "max_cpc_cents": 200}, headers
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEYWORD)
        ok = api.create_keyword(
            ag["id"], {"text": "shoes", "match_type": "PHRASE", "max_cpc_cents": 200}, headers
        )
        validate_success(ok, expected_status=201)

    def test_negative_keyword_blocking_canonical_query_rejected(self, api):
        """PRD §2.11: "Finally, a negative keyword that would block the canonical
        query of another keyword — whether existing or newly created — in the same
        ad group is rejected with `ERR_NEGATIVE_KEYWORD_CONFLICT` (409)."

        Design: Corner/validations/negative_keyword_blocking_canonical_query_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("NC Corp")
        headers = make_advertiser_headers(account["id"])
        camp = get_success_data(api.create_campaign(
            create_campaign_payload(account["id"], name="NC", daily_budget_cents=100,
                                    start_date="2026-09-01", end_date="2026-09-30"),
            headers,
        ))
        ag = get_success_data(api.create_ad_group(camp["id"], {"name": "AG"}, headers))
        api.create_keyword(
            ag["id"], {"text": "shoes", "match_type": "EXACT", "max_cpc_cents": 100}, headers
        )
        resp = api.create_keyword(
            ag["id"], {"text": "shoes", "match_type": "EXACT", "is_negative": True}, headers
        )
        validate_error(resp, ApiErrorId.ERR_NEGATIVE_KEYWORD_CONFLICT)
        ok = api.create_keyword(
            ag["id"], {"text": "boots", "match_type": "EXACT", "is_negative": True}, headers
        )
        validate_success(ok, expected_status=201)


class TestTemporalValidation:
    def test_close_current_month_returns_not_closable(self, api):
        """PRD §3.5: "The month must be fully past — every day of it strictly
        before the current logical date — and strictly after the profile's
        `last_closed_month`; anything else is `ERR_MONTH_NOT_CLOSABLE` (422)."

        Design: Corner/validations/close_current_month_returns_not_closable
        """
        set_clock("2026-09-15T00:00:00Z")
        account = create_account("Close Corp")
        profile = create_billing_profile(account, payment_method_type="CARD")
        resp = api.close_month(
            profile["id"], {"month": "2026-09"}, TEST_USERS["billing_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_MONTH_NOT_CLOSABLE)

    def test_activate_outside_flight_window_returns_temporal_error(self, api):
        """PRD §3.3: "Two gates guard activation, evaluated in the priority order
        of §2.10: the logical date must fall within the flight window from
        `start_date` through `end_date` inclusive, else
        `ERR_CAMPAIGN_OUTSIDE_FLIGHT_WINDOW` (422); and the owning account must be
        `ACTIVE`."

        Design: Corner/validations/activate_outside_flight_window_returns_temporal_error
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Flight Corp", with_billing_profile=False)
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        camp = create_campaign(account, name="FW", daily_budget_cents=1000,
                               start_date="2026-09-10", end_date="2026-09-20")
        resp = api.activate_campaign(camp["id"], headers)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_OUTSIDE_FLIGHT_WINDOW)
        set_clock("2026-09-10T00:00:00Z")
        ok = api.activate_campaign(camp["id"], headers)
        data = validate_success(ok)
        assert data["status"] == "ACTIVE"
