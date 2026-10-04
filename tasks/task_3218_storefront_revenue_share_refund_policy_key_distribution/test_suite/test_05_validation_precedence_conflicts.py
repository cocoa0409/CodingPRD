"""Depth tests for fixed validation-ordering conflicts (PRD §2.7)."""
from test_helpers import (
    api_client,
    buy_title,
    create_buyer,
    create_refund_request_payload,
    create_regional_price_payload,
    create_released_title,
    get_success_data,
    make_developer_headers,
    make_user_headers,
    read_title,
    request_refund,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
    TEST_USERS,
)

OPS = TEST_USERS["platform_ops_headers"]


class TestRefundStateVsTemporalPriority:
    def test_refunded_purchase_reports_invalid_state_even_past_window(self):
        """PRD §2.7: "When several checks could reject the same request, they
        are evaluated in a fixed order so the surfaced error is deterministic."

        Design: Difficulty/priority_pair_validation_conflict/refund_state_vs_temporal_priority
        """
        developer, title = create_released_title(base_price_usd_cents=800)
        buyer = create_buyer()
        purchase = buy_title(buyer, title)

        # Full auto-refund on day 0 moves the purchase to terminal REFUNDED.
        rr = request_refund(purchase, buyer, reason="refund me")
        assert rr["status"] == "APPROVED"
        purchase_read = validate_success(
            api_client.get_purchase(purchase["id"], make_user_headers(buyer["id"]))
        )
        assert purchase_read["status"] == "REFUNDED"

        # Advance 20 days so the temporal window is also expired.
        set_clock("2026-09-21T00:00:00Z")

        res = api_client.create_refund_request(
            create_refund_request_payload(purchase["id"], reason="again"),
            make_user_headers(buyer["id"]),
        )
        # PRD §3.5: refund-request creation gates a purchase that is not in
        # COMPLETED or PARTIALLY_REFUNDED with ERR_REFUND_AMOUNT (422); no
        # state-machine transition check applies to this endpoint.
        validate_error(res, ApiErrorId.ERR_REFUND_AMOUNT)

        purchase_after = validate_success(
            api_client.get_purchase(purchase["id"], make_user_headers(buyer["id"]))
        )
        assert purchase_after["status"] == "REFUNDED"

    def test_state_error_not_temporal_error_when_purchase_terminal(self):
        """PRD §2.7: "First comes authentication (missing or malformed headers
        yield `ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN`).
        Next, every identifier referenced in the path and body is resolved
        left-to-right in path order, and the first missing resource yields
        `ERR_NOT_FOUND`."

        Design: Difficulty/priority_pair_validation_conflict/refund_state_vs_temporal_priority
        """
        developer, title = create_released_title(base_price_usd_cents=800)
        buyer = create_buyer()
        purchase = buy_title(buyer, title)
        rr = request_refund(purchase, buyer, reason="first")
        assert rr["status"] == "APPROVED"

        set_clock("2026-09-30T00:00:00Z")

        res = api_client.create_refund_request(
            create_refund_request_payload(purchase["id"], reason="late and refunded"),
            make_user_headers(buyer["id"]),
        )
        # PRD §3.5: a purchase outside {COMPLETED, PARTIALLY_REFUNDED} is
        # rejected at creation with ERR_REFUND_AMOUNT (422).
        err = validate_error(res, ApiErrorId.ERR_REFUND_AMOUNT)
        assert err["error_id"] == "ERR_REFUND_AMOUNT"


class TestOverrideUniquenessVsDeviationPriority:
    def _setup_with_override(self):
        developer, title = create_released_title(base_price_usd_cents=6000)
        dev_headers = make_developer_headers(developer["id"])
        version = read_title(title["id"], developer)["version"]
        # EUR recommended = round_half_up(6000 * 0.92 * 0.90) = 4968; 4000 is inside the cap.
        get_success_data(
            api_client.create_regional_price(
                create_regional_price_payload(title["id"], "EUR", 4000, version),
                dev_headers,
            )
        )
        return developer, title, dev_headers

    def test_deviation_fires_before_uniqueness(self):
        """PRD §2.7: "Only after all of those do the business gates fire, in
        their own relative order: developer-account activity
        (`ERR_DEVELOPER_NOT_ACTIVE`), user-account activity
        (`ERR_ACCOUNT_RESTRICTED`), temporal schedule rules
        (`ERR_INVALID_SCHEDULE`), early-access disclosure
        (`ERR_MISSING_DISCLOSURE`), the one-open-review rule
        (`ERR_REVIEW_ALREADY_OPEN`), regional price deviation
        (`ERR_PRICE_DEVIATION`), override uniqueness (`ERR_OVERRIDE_EXISTS`),
        free-key allowance (`ERR_FREE_KEY_ALLOWANCE_EXCEEDED`), gray-market risk
        (`ERR_GRAY_MARKET_RISK`), redemption velocity (`ERR_REDEEM_VELOCITY`),
        refund window expiry (`ERR_REFUND_WINDOW_EXPIRED`), playtime limits
        (`ERR_PLAYTIME_EXCEEDED`), refund-abuse restriction (`ERR_REFUND_ABUSE`),
        refund amount bounds (`ERR_REFUND_AMOUNT`), the one-pending-refund rule
        (`ERR_REFUND_ALREADY_PENDING`), review ownership (`ERR_REVIEW_NOT_OWNED`),
        the recognized-revenue floor (`ERR_NEGATIVE_REVENUE`), workshop item
        purchasability (`ERR_ITEM_NOT_PURCHASABLE`), and finally uniqueness
        conflicts (`ERR_DUPLICATE`)."

        Design: Difficulty/priority_pair_validation_conflict/override_uniqueness_vs_deviation_priority
        """
        developer, title, dev_headers = self._setup_with_override()
        version = read_title(title["id"], developer)["version"]

        # price 100 vs recommendation 4968: deviation ~-98%, far beyond 2500 bps,
        # AND an ACTIVE EUR override already exists.
        res = api_client.create_regional_price(
            create_regional_price_payload(title["id"], "EUR", 100, version),
            dev_headers,
        )
        # Deviation is checked before override uniqueness.
        validate_error(res, ApiErrorId.ERR_PRICE_DEVIATION)

        data, _meta = validate_paginated(
            api_client.list_title_regional_prices(title["id"], dev_headers)
        )
        active = [o for o in data if o["currency"] == "EUR" and o["status"] == "ACTIVE"]
        assert len(active) == 1
        assert active[0]["price_cents"] == 4000

    def test_duplicate_override_within_cap_reports_override_exists(self):
        """PRD §3.3: "Only one override per title and currency may be `ACTIVE`
        at a time; attempting a second yields `ERR_OVERRIDE_EXISTS` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/override_uniqueness_vs_deviation_priority
        """
        developer, title, dev_headers = self._setup_with_override()
        version = read_title(title["id"], developer)["version"]

        # 4500 vs recommendation 4968: deviation ~-9.4%, inside the 2500 bps cap,
        # so the deviation gate passes and the uniqueness gate must fire.
        res = api_client.create_regional_price(
            create_regional_price_payload(title["id"], "EUR", 4500, version),
            dev_headers,
        )
        validate_error(res, ApiErrorId.ERR_OVERRIDE_EXISTS)
