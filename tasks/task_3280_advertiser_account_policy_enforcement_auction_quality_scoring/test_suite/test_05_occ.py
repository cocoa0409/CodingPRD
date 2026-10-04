"""Optimistic concurrency control corner tests."""
from test_helpers import (
    ApiErrorId,
    create_verified_account,
    create_campaign,
    set_clock,
    make_advertiser_headers,
    validate_error,
    validate_success,
)


class TestOccCampaignUpdate:
    def test_occ_campaign_update_stale_version_returns_412(self, api):
        """PRD §2.8: "Updating a campaign requires `expected_campaign_version`
        carrying the client's last observed `version` of that campaign. Because
        budget and end-date writes are absolute sets that would each legitimately
        succeed under product semantics, a stale view of the campaign must be
        refused rather than applied: if the campaign's current `version` has
        advanced since the client last read it, the update is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_campaign_update_stale_version_returns_412
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("OCC Corp", with_billing_profile=False)
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        camp = create_campaign(account, name="OC", daily_budget_cents=1000)
        cv0 = camp["version"]
        first = api.update_campaign(
            camp["id"], {"daily_budget_cents": 2000, "expected_campaign_version": cv0}, headers
        )
        first_data = validate_success(first)
        assert first_data["version"] == cv0 + 1
        stale = api.update_campaign(
            camp["id"], {"daily_budget_cents": 3000, "expected_campaign_version": cv0}, headers
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        fresh = api.update_campaign(
            camp["id"],
            {"daily_budget_cents": 3000, "expected_campaign_version": first_data["version"]},
            headers,
        )
        fresh_data = validate_success(fresh)
        assert fresh_data["version"] == cv0 + 2
        assert fresh_data["daily_budget_cents"] == 3000
