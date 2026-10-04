"""Sponsorships: computed counters, the pause/resume cycle, impression accrual,
under-delivery compensation, and count conservation across cancel."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_campaign,
    create_campaign,
    create_show,
    create_sponsor,
    set_clock,
    setup_active_production_with_approved_asset,
    validate_error,
    validate_success,
)

PD = TEST_USERS["production_director_headers"]
CP = TEST_USERS["content_producer_headers"]
SM = TEST_USERS["sponsorship_manager_headers"]
VS = TEST_USERS["venue_scheduler_headers"]


class TestSponsorCreation:

    def test_active_campaign_count_starts_at_zero(self, api):
        """PRD: "A `SponsorshipManager` registers a `Sponsor` by supplying a
        `name` and a `brand_tier` (one of `STANDARD` or `PREMIUM`). The sponsor
        is created with `active_campaign_count` equal to 0."

        Design: Corner/entities/sponsor_active_campaign_count_is_computed
        """
        data = validate_success(
            api.create_sponsor({"name": "INITECH", "brand_tier": "STANDARD"}, SM),
            expected_status=201,
        )
        assert data["active_campaign_count"] == 0

    def test_client_supplied_active_campaign_count_ignored(self, api):
        """PRD: "A `SponsorshipManager` registers a `Sponsor` by supplying a
        `name` and a `brand_tier` (one of `STANDARD` or `PREMIUM`). The sponsor
        is created with `active_campaign_count` equal to 0."

        Design: Corner/entities/sponsor_active_campaign_count_is_computed
        """
        data = validate_success(
            api.create_sponsor(
                {"name": "INITECH2", "brand_tier": "STANDARD", "active_campaign_count": 7}, SM
            ),
            expected_status=201,
        )
        assert data["active_campaign_count"] == 0, (
            "active_campaign_count is computed and starts at 0 regardless of client input"
        )


class TestCampaignPauseResumeCycle:

    def test_pause_then_resume_cycles_status_and_count(self, api):
        """PRD: "A campaign may be paused (`ACTIVE → PAUSED`), which decrements
        the sponsor's `active_campaign_count` by 1. Resuming a paused campaign
        goes through the same activation endpoint and increments the count
        again."
        PRD: "On successful activation, the sponsor's `active_campaign_count`
        increments by 1 and the sponsor's `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/campaign_pause_resume_cycle
        """
        sponsor = create_sponsor(name="ACME", brand_tier="STANDARD")
        campaign = create_campaign(
            sponsor["id"],
            start_time="2026-08-31T00:00:00Z",
            end_time="2026-09-30T00:00:00Z",
            exterior_slots=2,
            spot_seconds=60,
            contracted_impressions=10000,
        )
        validate_success(
            api.activate_campaign(campaign["id"], {"expected_sponsor_version": sponsor["version"]}, SM)
        )

        validate_success(api.pause_campaign(campaign["id"], SM))
        sponsor_mid = validate_success(api.get_sponsor(sponsor["id"], SM))
        assert sponsor_mid["active_campaign_count"] == 0, "pause must decrement the count"

        resumed = validate_success(
            api.activate_campaign(
                campaign["id"], {"expected_sponsor_version": sponsor_mid["version"]}, SM
            )
        )
        assert resumed["status"] == "ACTIVE"
        sponsor_after = validate_success(api.get_sponsor(sponsor["id"], SM))
        assert sponsor_after["active_campaign_count"] == 1, "resume must increment the count again"

    def test_pause_resume_cycle_is_repeatable(self, api):
        """PRD: "A campaign may be paused (`ACTIVE → PAUSED`), which decrements
        the sponsor's `active_campaign_count` by 1. Resuming a paused campaign
        goes through the same activation endpoint and increments the count
        again."

        Design: Difficulty/non_linear_state_machine/campaign_pause_resume_cycle
        """
        sponsor, campaign = create_active_campaign(brand_tier="STANDARD")
        for _ in range(2):
            validate_success(api.pause_campaign(campaign["id"], SM))
            sponsor = validate_success(api.get_sponsor(sponsor["id"], SM))
            assert sponsor["active_campaign_count"] == 0
            campaign = validate_success(
                api.activate_campaign(campaign["id"], {"expected_sponsor_version": sponsor["version"]}, SM)
            )
            assert campaign["status"] == "ACTIVE"
            sponsor = validate_success(api.get_sponsor(sponsor["id"], SM))
            assert sponsor["active_campaign_count"] == 1


class TestSponsorCountConservation:

    def test_count_conserved_across_activate_pause_cancel(self, api):
        """PRD: "On successful activation, the sponsor's `active_campaign_count`
        increments by 1 and the sponsor's `version` increments by 1."
        PRD: "Cancellation is permitted from `DRAFT`, `ACTIVE`, or `PAUSED`; it
        decrements `active_campaign_count` by 1 only if the campaign was
        `ACTIVE` at the moment of cancellation, and leaves the count unchanged
        otherwise."

        Design: Difficulty/compensating_invariant/sponsor_active_count_conserved_across_pause_cancel
        """
        sponsor = create_sponsor(name="GLOBEX", brand_tier="PREMIUM")
        campaign = create_campaign(
            sponsor["id"],
            start_time="2026-08-31T00:00:00Z",
            end_time="2026-09-30T00:00:00Z",
            exterior_slots=1,
            spot_seconds=30,
            contracted_impressions=5000,
        )
        validate_success(
            api.activate_campaign(campaign["id"], {"expected_sponsor_version": sponsor["version"]}, SM)
        )
        validate_success(api.pause_campaign(campaign["id"], SM))
        cancelled = validate_success(api.cancel_campaign(campaign["id"], SM))
        assert cancelled["status"] == "CANCELLED"
        sponsor_after = validate_success(api.get_sponsor(sponsor["id"], SM))
        assert sponsor_after["active_campaign_count"] == 0, (
            "count must be conserved across activate (+1), pause (-1), cancel-from-PAUSED (0)"
        )

    def test_cancel_from_active_decrements_count(self, api):
        """PRD: "Cancellation is permitted from `DRAFT`, `ACTIVE`, or `PAUSED`;
        it decrements `active_campaign_count` by 1 only if the campaign was
        `ACTIVE` at the moment of cancellation, and leaves the count unchanged
        otherwise."

        Design: Difficulty/compensating_invariant/sponsor_active_count_conserved_across_pause_cancel
        """
        sponsor, campaign = create_active_campaign(brand_tier="STANDARD")
        sponsor = validate_success(api.get_sponsor(sponsor["id"], SM))
        assert sponsor["active_campaign_count"] == 1
        cancelled = validate_success(api.cancel_campaign(campaign["id"], SM))
        assert cancelled["status"] == "CANCELLED"
        sponsor_after = validate_success(api.get_sponsor(sponsor["id"], SM))
        assert sponsor_after["active_campaign_count"] == 0


class TestImpressionAccrual:

    def test_overlapping_campaign_accrues_impressions_on_completion(self, api):
        """PRD: "Impressions accrue at show completion: every campaign that is
        `ACTIVE` and whose flight window overlaps the completing show's window
        has its `delivered_impressions` incremented by the per-show impression
        count. That count is the campaign's `exterior_slots` multiplied by the
        show's `length_minutes`, multiplied by the campaign's `spot_seconds`,
        divided by 60."

        Design: Corner/calculations/impressions_accrued_on_show_completion
        """
        sponsor, campaign = create_active_campaign(
            brand_tier="STANDARD",
            start_time="2026-08-31T00:00:00Z",
            end_time="2026-09-30T00:00:00Z",
            exterior_slots=2,
            spot_seconds=30,
            contracted_impressions=10000,
        )
        prod, asset = setup_active_production_with_approved_asset(base_price_cents=10000)
        show = create_show(prod["id"], show_format="FILM", start_time="2026-09-01T10:00:00Z", length_minutes=120)
        validate_success(api.schedule_rehearsal(show["id"], VS))
        prod_now = validate_success(api.get_production(prod["id"], PD))
        validate_success(
            api.confirm_show(show["id"], {"expected_production_version": prod_now["version"]}, VS)
        )
        # The §3.8 clock sweep completes the CONFIRMED show once the clock
        # passes start_time + length_minutes (12:00); impression accrual fires
        # there.
        set_clock("2026-09-01T13:00:00Z")
        assert validate_success(api.get_show(show["id"], VS))["status"] == "COMPLETED"
        campaign_after = validate_success(api.get_campaign(campaign["id"], SM))
        # 2 slots x 120 minutes x 30 seconds / 60 = 120
        assert campaign_after["delivered_impressions"] == 120

    def test_premium_tier_does_not_change_impression_count(self, api):
        """PRD: "That count is the campaign's `exterior_slots` multiplied by the
        show's `length_minutes`, multiplied by the campaign's `spot_seconds`,
        divided by 60. Both `STANDARD` and `PREMIUM` tiers use a multiplier of
        1.0 for this calculation — premium tier affects cost, not impression
        count."

        Design: Corner/calculations/impressions_accrued_on_show_completion
        """
        sponsor, campaign = create_active_campaign(
            brand_tier="PREMIUM",
            start_time="2026-08-31T00:00:00Z",
            end_time="2026-09-30T00:00:00Z",
            exterior_slots=2,
            spot_seconds=30,
            contracted_impressions=10000,
        )
        prod, asset = setup_active_production_with_approved_asset(base_price_cents=10000)
        show = create_show(prod["id"], show_format="FILM", start_time="2026-09-01T10:00:00Z", length_minutes=120)
        validate_success(api.schedule_rehearsal(show["id"], VS))
        prod_now = validate_success(api.get_production(prod["id"], PD))
        validate_success(
            api.confirm_show(show["id"], {"expected_production_version": prod_now["version"]}, VS)
        )
        # The §3.8 clock sweep completes the CONFIRMED show once the clock
        # passes start_time + length_minutes (12:00); impression accrual fires
        # there.
        set_clock("2026-09-01T13:00:00Z")
        assert validate_success(api.get_show(show["id"], VS))["status"] == "COMPLETED"
        campaign_after = validate_success(api.get_campaign(campaign["id"], SM))
        # PREMIUM uses the same 1.0 multiplier: 2 x 120 x 30 / 60 = 120
        assert campaign_after["delivered_impressions"] == 120


class TestUnderDeliveryMakeGoods:

    def test_under_delivery_yields_double_make_good_credits(self, api):
        """PRD: "At completion the platform finalizes two figures.
        `under_delivery` is the larger of zero and the difference between
        `contracted_impressions` and `delivered_impressions`. `make_good_credits`
        is twice `under_delivery` — the impressions owed to the sponsor as
        compensation."
        PRD: "Completion is system-driven: when the logical clock reaches or
        passes the campaign's `end_time`, the campaign transitions `ACTIVE →
        COMPLETED`."

        Design: Corner/calculations/campaign_under_delivery_make_good_credits
        """
        sponsor = create_sponsor(name="UD", brand_tier="STANDARD")
        campaign = create_campaign(
            sponsor["id"],
            start_time="2026-08-31T00:00:00Z",
            end_time="2026-09-02T00:00:00Z",
            exterior_slots=1,
            spot_seconds=30,
            contracted_impressions=10000,
        )
        validate_success(
            api.activate_campaign(campaign["id"], {"expected_sponsor_version": sponsor["version"]}, SM)
        )
        set_clock("2026-09-02T01:00:00Z")
        campaign_after = validate_success(api.get_campaign(campaign["id"], SM))
        assert campaign_after["status"] == "COMPLETED"
        assert campaign_after["under_delivery"] == 10000
        assert campaign_after["make_good_credits"] == 20000

    def test_full_delivery_yields_zero_make_good_credits(self, api):
        """PRD: "At completion the platform finalizes two figures.
        `under_delivery` is the larger of zero and the difference between
        `contracted_impressions` and `delivered_impressions`. `make_good_credits`
        is twice `under_delivery` — the impressions owed to the sponsor as
        compensation."
        PRD: "Impressions accrue at show completion: every campaign that is
        `ACTIVE` and whose flight window overlaps the completing show's window
        has its `delivered_impressions` incremented by the per-show impression
        count."

        Design: Corner/calculations/campaign_under_delivery_make_good_credits
        """
        sponsor = create_sponsor(name="UD2", brand_tier="STANDARD")
        campaign = create_campaign(
            sponsor["id"],
            start_time="2026-08-31T00:00:00Z",
            end_time="2026-09-05T00:00:00Z",
            exterior_slots=2,
            spot_seconds=30,
            contracted_impressions=120,
        )
        validate_success(
            api.activate_campaign(campaign["id"], {"expected_sponsor_version": sponsor["version"]}, SM)
        )
        prod, asset = setup_active_production_with_approved_asset(base_price_cents=10000)
        show = create_show(prod["id"], show_format="FILM", start_time="2026-09-01T10:00:00Z", length_minutes=120)
        validate_success(api.schedule_rehearsal(show["id"], VS))
        prod_now = validate_success(api.get_production(prod["id"], PD))
        validate_success(
            api.confirm_show(show["id"], {"expected_production_version": prod_now["version"]}, VS)
        )
        # The §3.8 clock sweep completes the CONFIRMED show once the clock
        # passes start_time + length_minutes (12:00); impression accrual fires
        # there.
        set_clock("2026-09-01T13:00:00Z")
        assert validate_success(api.get_show(show["id"], VS))["status"] == "COMPLETED"
        # delivered == contracted == 120; complete the campaign after the show.
        set_clock("2026-09-05T01:00:00Z")
        campaign_after = validate_success(api.get_campaign(campaign["id"], SM))
        assert campaign_after["status"] == "COMPLETED"
        assert campaign_after["delivered_impressions"] == 120
        assert campaign_after["under_delivery"] == 0
        assert campaign_after["make_good_credits"] == 0
