"""Attribution reporting: STRICT vs EXTENDED variants; campaign window bounds."""
from test_helpers import (
    OPS,
    create_campaign_payload,
    make_advertiser_headers,
    record_call,
    set_clock,
    setup_active_campaign,
    setup_ad_account,
    validate_success,
)


def _report(api, account_id, owner_id, campaign_id, variant,
            period_start="2026-09-01", period_end="2026-09-30"):
    return validate_success(
        api.create_attribution_report(
            account_id,
            {
                "campaign_id": campaign_id,
                "period_start": period_start,
                "period_end": period_end,
                "variant": variant,
            },
            make_advertiser_headers(owner_id),
        ),
        expected_status=201,
    )


class TestStrictVsExtendedWindow:
    def test_strict_counts_only_in_period_qualified_calls(self, api):
        """PRD §3.6: "under `STRICT` the window is `[period_start,
        period_end]`".

        Design: Difficulty/dual_variant_calc/attribution_strict_vs_extended_window
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="CALL_TRACKING", bid_cents=500, budget_cents=100000,
            starts_on="2026-08-01", ends_on="2026-09-30",
        )
        # Qualified call 10 days before the report period.
        record_call(account["id"], campaign["id"], "2026-08-20T10:00:00Z", 60,
                    caller_number="+15550001010")
        # Qualified call inside the report period.
        record_call(account["id"], campaign["id"], "2026-09-10T10:00:00Z", 45,
                    caller_number="+15550001011")
        strict = _report(api, account["id"], owner["id"], campaign["id"], "STRICT")
        assert strict["qualified_calls"] == 1
        assert strict["spend_cents"] == 500

    def test_extended_counts_lookback_band_and_strict_is_subset(self, api):
        """PRD §3.6: "under `EXTENDED` the window is `[period_start − 30 days,
        period_end]`, so the extended count is always a superset of strict, and
        the two diverge exactly when qualified calls happened in the 30-day
        lookback band before `period_start`."

        Design: Difficulty/dual_variant_calc/attribution_strict_vs_extended_window
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="CALL_TRACKING", bid_cents=500, budget_cents=100000,
            starts_on="2026-08-01", ends_on="2026-09-30",
        )
        record_call(account["id"], campaign["id"], "2026-08-20T10:00:00Z", 60,
                    caller_number="+15550001020")
        record_call(account["id"], campaign["id"], "2026-09-10T10:00:00Z", 45,
                    caller_number="+15550001021")
        strict = _report(api, account["id"], owner["id"], campaign["id"], "STRICT")
        extended = _report(api, account["id"], owner["id"], campaign["id"], "EXTENDED")
        assert extended["qualified_calls"] == 2
        assert extended["spend_cents"] == 1000
        assert extended["qualified_calls"] >= strict["qualified_calls"]
        # Report generation never charges the account.
        account_after = validate_success(
            api.get_ad_account(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert account_after["spent_today_cents"] == 1000


class TestCampaignWindowInclusiveBounds:
    def test_activation_exactly_on_starts_on_succeeds(self, api):
        """PRD §3.5: "the current logical date falls within the campaign's
        `[starts_on, ends_on]` window — activating outside the window is
        rejected with `ERR_CAMPAIGN_OUT_OF_WINDOW` (HTTP 409)."
        PRD §3.6: "The calendar date of `called_at` must fall within the
        campaign's `[starts_on, ends_on]` window (inclusive on both ends)".

        Design: Difficulty/resource_temporal_overlap/campaign_window_inclusive_bounds
        """
        set_clock("2026-09-01T00:00:00Z")
        # Window starts nine days in the future; activation must wait for it.
        page, owner, account = _setup_account(api)
        campaign = _create_call_campaign(api, account["id"], owner["id"],
                                         starts_on="2026-09-10",
                                         ends_on="2026-09-20")
        set_clock("2026-09-10T00:00:00Z")
        activated = validate_success(
            api.activate_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
        )
        assert activated["status"] == "ACTIVE"

    def test_call_on_ends_on_qualifies_and_completion_is_strictly_past(self, api):
        """PRD §3.6: "The calendar date of `called_at` must fall within the
        campaign's `[starts_on, ends_on]` window (inclusive on both ends)".
        PRD §3.5: "When the logical date advances past a campaign's `ends_on`,
        the system moves the campaign from `ACTIVE` or `PAUSED` to terminal
        `COMPLETED`."

        Design: Difficulty/resource_temporal_overlap/campaign_window_inclusive_bounds
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account = _setup_account(api)
        campaign = _create_call_campaign(api, account["id"], owner["id"],
                                         starts_on="2026-09-10",
                                         ends_on="2026-09-20")
        set_clock("2026-09-10T00:00:00Z")
        validate_success(
            api.activate_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
        )
        event = validate_success(
            record_call(account["id"], campaign["id"], "2026-09-20T23:59:00Z", 31),
            expected_status=201,
        )
        assert event["qualified"] is True
        set_clock("2026-09-21T00:00:00Z")
        final = validate_success(
            api.get_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
        )
        assert final["status"] == "COMPLETED"


def _setup_account(api):
    return setup_ad_account(budget_cents=100000)


def _create_call_campaign(api, account_id, owner_id, starts_on, ends_on):
    return validate_success(
        api.create_campaign(
            account_id,
            create_campaign_payload(
                kind="CALL_TRACKING",
                bid_cents=100,
                starts_on=starts_on,
                ends_on=ends_on,
                call_tracking_enabled=True,
            ),
            make_advertiser_headers(owner_id),
        ),
        expected_status=201,
    )
