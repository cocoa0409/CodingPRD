"""Ad campaign pause/resume cycle and window enforcement (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    create_campaign_payload,
    make_advertiser_headers,
    set_clock,
    setup_active_campaign,
    setup_ad_account,
    validate_error,
    validate_success,
)


class TestCampaignPauseResumeCycle:
    def test_resume_from_paused_succeeds_mid_window(self, api):
        """PRD §3.5: "The same transition is used to resume a `PAUSED`
        campaign; on resume the account must still be `ACTIVE` and the logical
        date must not be later than `ends_on`."

        Design: Difficulty/non_linear_state_machine/ad_campaign_pause_resume_cycle
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="SPONSORED_PLACEMENT", bid_cents=100,
            starts_on="2026-08-15", ends_on="2026-09-15",
        )
        paused = validate_success(
            api.pause_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
        )
        assert paused["status"] == "PAUSED"
        resumed = validate_success(
            api.activate_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
        )
        assert resumed["status"] == "ACTIVE"

    def test_campaign_completes_when_clock_passes_ends_on(self, api):
        """PRD §3.5: "When the logical date advances past a campaign's
        `ends_on`, the system moves the campaign from `ACTIVE` or `PAUSED` to
        terminal `COMPLETED`."
        PRD §2.4: "an `AdCampaign` whose `ends_on` date is in the past
        transitions to `COMPLETED`".

        Design: Difficulty/non_linear_state_machine/ad_campaign_pause_resume_cycle
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="SPONSORED_PLACEMENT", bid_cents=100,
            starts_on="2026-08-15", ends_on="2026-09-15",
        )
        validate_success(
            api.pause_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
        )
        validate_success(
            api.activate_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
        )
        set_clock("2026-09-16T00:00:00Z")
        final = validate_success(
            api.get_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
        )
        assert final["status"] == "COMPLETED"


class TestCampaignConfigValidation:
    def test_call_tracking_requires_flag_true(self, api):
        """PRD §3.5: "The flag's value must agree with `kind`: `CALL_TRACKING`
        campaigns require `call_tracking_enabled` true; `SPONSORED_PLACEMENT`
        campaigns require it false. A mismatch is rejected with
        `ERR_CAMPAIGN_CONFIG` (HTTP 422)."

        Design: Corner/validations/campaign_config_mismatch_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account = setup_ad_account(budget_cents=5000)
        r = api.create_campaign(
            account["id"],
            create_campaign_payload(kind="CALL_TRACKING", call_tracking_enabled=False),
            make_advertiser_headers(owner["id"]),
        )
        validate_error(r, ApiErrorId.ERR_CAMPAIGN_CONFIG.value)

    def test_sponsored_placement_requires_flag_false(self, api):
        """PRD §3.5: "The flag's value must agree with `kind`: `CALL_TRACKING`
        campaigns require `call_tracking_enabled` true; `SPONSORED_PLACEMENT`
        campaigns require it false. A mismatch is rejected with
        `ERR_CAMPAIGN_CONFIG` (HTTP 422)."

        Design: Corner/validations/campaign_config_mismatch_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner, account = setup_ad_account(budget_cents=5000)
        r = api.create_campaign(
            account["id"],
            create_campaign_payload(kind="SPONSORED_PLACEMENT", call_tracking_enabled=True),
            make_advertiser_headers(owner["id"]),
        )
        validate_error(r, ApiErrorId.ERR_CAMPAIGN_CONFIG.value)


class TestFiscalCheckedAfterTemporal:
    def test_out_of_window_call_surfaces_attribution_window(self, api):
        """PRD §2.7: "Across the entire surface, validation proceeds in this
        strict order: authentication of the headers first, then role
        authorization, then path and body reference existence, then structural
        payload checks (missing fields, wrong types, enum violations,
        minimum-length violations, out-of-range values, and reversed date
        ranges — all surfaced as `ERR_INVALID_REQUEST`), then state-machine
        admissibility of the operation (`ERR_INVALID_STATE`), and only then
        domain-specific business rules."
        PRD §3.6: "a call outside that window is rejected with
        `ERR_ATTRIBUTION_WINDOW` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/fiscal_checked_last_after_temporal_and_referential
        """
        set_clock("2026-09-05T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="CALL_TRACKING", bid_cents=500, budget_cents=100,
            starts_on="2026-09-05", ends_on="2026-09-10",
        )
        r = api.create_call_event(
            account["id"],
            {
                "campaign_id": campaign["id"],
                "caller_number": "+15550009000",
                "called_at": "2026-09-20T10:00:00Z",
                "duration_seconds": 60,
            },
            make_advertiser_headers(owner["id"]),
        )
        validate_error(r, ApiErrorId.ERR_ATTRIBUTION_WINDOW.value)

    def test_in_window_call_then_surfaces_budget_exceeded(self, api):
        """PRD §2.7: "then state-machine admissibility of the operation
        (`ERR_INVALID_STATE`), and only then domain-specific business rules."
        PRD §3.5: "If the sum would exceed the cap, the charge is rejected with
        `ERR_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/fiscal_checked_last_after_temporal_and_referential
        """
        set_clock("2026-09-05T00:00:00Z")
        page, owner, account, campaign = setup_active_campaign(
            kind="CALL_TRACKING", bid_cents=500, budget_cents=100,
            starts_on="2026-09-05", ends_on="2026-09-10",
        )
        r = api.create_call_event(
            account["id"],
            {
                "campaign_id": campaign["id"],
                "caller_number": "+15550009001",
                "called_at": "2026-09-07T10:00:00Z",
                "duration_seconds": 60,
            },
            make_advertiser_headers(owner["id"]),
        )
        validate_error(r, ApiErrorId.ERR_BUDGET_EXCEEDED.value)
        account_after = validate_success(
            api.get_ad_account(account["id"], make_advertiser_headers(owner["id"]))
        )
        assert account_after["spent_today_cents"] == 0

