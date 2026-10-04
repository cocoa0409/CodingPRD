"""Show confirmation: cross-entity gates and optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    capture_asset,
    create_active_production,
    create_campaign,
    create_render_batch_payload,
    create_show,
    create_sponsor,
    get_success_data,
    set_clock,
    setup_show_in_rehearsal,
    validate_error,
    validate_success,
)

PD = TEST_USERS["production_director_headers"]
CP = TEST_USERS["content_producer_headers"]
VS = TEST_USERS["venue_scheduler_headers"]
SM = TEST_USERS["sponsorship_manager_headers"]


class TestApprovedAssetGate:

    def test_confirm_rejected_until_asset_approved(self, api):
        """PRD: "Second, at least one asset of the production must have reached
        `APPROVED` — a show cannot be confirmed without media ready to play.
        Failing this check is rejected with `ERR_NO_APPROVED_ASSET` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/show_confirm_requires_approved_asset
        """
        prod = create_active_production(title="XP", base_price_cents=10000)
        asset = capture_asset(prod["id"], title="XA", render_hours_base=2)
        batch = get_success_data(api.create_render_batch(create_render_batch_payload([asset["id"]]), CP))
        validate_success(api.dispatch_render_batch(batch["id"], CP))
        set_clock("2026-09-01T03:00:00Z")
        validate_success(api.settle_render_batch(batch["id"], CP))
        # Asset is now in QC — settled, but NOT yet APPROVED.
        show = create_show(prod["id"], show_format="FILM", start_time="2026-09-03T19:00:00Z", length_minutes=90)
        validate_success(api.schedule_rehearsal(show["id"], VS))
        prod_now = validate_success(api.get_production(prod["id"], PD))
        resp = api.confirm_show(show["id"], {"expected_production_version": prod_now["version"]}, VS)
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_ASSET)

    def test_confirm_succeeds_after_asset_approved(self, api):
        """PRD: "Second, at least one asset of the production must have reached
        `APPROVED` — a show cannot be confirmed without media ready to play.
        Failing this check is rejected with `ERR_NO_APPROVED_ASSET` (HTTP 422)."
        PRD: "Confirmation (`REHEARSAL → CONFIRMED`) is the show's commitment
        point and is guarded by three additional conditions, all of which must
        hold simultaneously."

        Design: Difficulty/cross_entity_state_dependency/show_confirm_requires_approved_asset
        """
        prod = create_active_production(title="XP2", base_price_cents=10000)
        asset = capture_asset(prod["id"], title="XA2", render_hours_base=2)
        batch = get_success_data(api.create_render_batch(create_render_batch_payload([asset["id"]]), CP))
        validate_success(api.dispatch_render_batch(batch["id"], CP))
        set_clock("2026-09-01T03:00:00Z")
        validate_success(api.settle_render_batch(batch["id"], CP))
        show = create_show(prod["id"], show_format="FILM", start_time="2026-09-03T19:00:00Z", length_minutes=90)
        validate_success(api.schedule_rehearsal(show["id"], VS))
        prod_now = validate_success(api.get_production(prod["id"], PD))
        resp = api.confirm_show(show["id"], {"expected_production_version": prod_now["version"]}, VS)
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_ASSET)
        validate_success(api.qc_approve_asset(asset["id"], CP))
        confirmed = validate_success(
            api.confirm_show(show["id"], {"expected_production_version": prod_now["version"]}, VS)
        )
        assert confirmed["status"] == "CONFIRMED"


class TestShowConfirmOCC:

    def test_stale_production_version_rejected(self, api):
        """PRD: "The confirm request is also subject to the
        optimistic-concurrency rule described in §2.7 — the request must carry
        `expected_production_version` matching the production's current
        `version`, else the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/endpoints/show_confirm_occ_stale_version_rejected
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        prod_now = validate_success(api.get_production(prod["id"], PD))
        resp = api.confirm_show(
            show["id"], {"expected_production_version": prod_now["version"] - 1}, VS
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_current_production_version_confirms(self, api):
        """PRD: "The confirm request is also subject to the
        optimistic-concurrency rule described in §2.7 — the request must carry
        `expected_production_version` matching the production's current
        `version`, else the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD: "Confirmation (`REHEARSAL → CONFIRMED`) is the show's commitment
        point and is guarded by three additional conditions, all of which must
        hold simultaneously."

        Design: Corner/endpoints/show_confirm_occ_stale_version_rejected
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={"show_format": "FILM", "start_time": "2026-09-03T19:00:00Z", "length_minutes": 90},
        )
        prod_now = validate_success(api.get_production(prod["id"], PD))
        confirmed = validate_success(
            api.confirm_show(show["id"], {"expected_production_version": prod_now["version"]}, VS)
        )
        assert confirmed["status"] == "CONFIRMED"


class TestCampaignActivateOCC:

    def test_stale_sponsor_version_rejected(self, api):
        """PRD: "The activate call is also subject to the optimistic-concurrency
        rule described in §2.7, requiring `expected_sponsor_version` matching
        the sponsor's current `version`; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/campaign_activate_occ_stale_sponsor_version
        """
        sponsor = create_sponsor(name="OCC", brand_tier="STANDARD")
        campaign = create_campaign(
            sponsor["id"],
            start_time="2026-08-31T00:00:00Z",
            end_time="2026-09-30T00:00:00Z",
            exterior_slots=1,
            spot_seconds=30,
            contracted_impressions=5000,
        )
        resp = api.activate_campaign(
            campaign["id"], {"expected_sponsor_version": sponsor["version"] - 1}, SM
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_current_sponsor_version_activates(self, api):
        """PRD: "The activate call is also subject to the optimistic-concurrency
        rule described in §2.7, requiring `expected_sponsor_version` matching
        the sponsor's current `version`; a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD: "On successful activation, the sponsor's `active_campaign_count`
        increments by 1 and the sponsor's `version` increments by 1."

        Design: Corner/cross_cutting_layers/campaign_activate_occ_stale_sponsor_version
        """
        sponsor = create_sponsor(name="OCC2", brand_tier="STANDARD")
        campaign = create_campaign(
            sponsor["id"],
            start_time="2026-08-31T00:00:00Z",
            end_time="2026-09-30T00:00:00Z",
            exterior_slots=1,
            spot_seconds=30,
            contracted_impressions=5000,
        )
        data = validate_success(
            api.activate_campaign(campaign["id"], {"expected_sponsor_version": sponsor["version"]}, SM)
        )
        assert data["status"] == "ACTIVE"
