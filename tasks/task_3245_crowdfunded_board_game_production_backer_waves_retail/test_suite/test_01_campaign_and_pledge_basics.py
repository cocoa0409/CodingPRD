"""Campaign and pledge basics: creation defaults, retrieval, listing, RBAC,
generic request errors, OCC."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_campaign,
    assert_pledge,
    create_campaign,
    create_campaign_payload,
    create_charged_pledge,
    create_pledge,
    get_campaign,
    launch_campaign,
    make_backer_headers,
    set_clock,
    setup_live_campaign,
    validate_error,
    validate_paginated,
    validate_success,
)


def api_headers_owner():
    return TEST_USERS["campaign_owner_headers"]


def api_headers_admin():
    return TEST_USERS["platform_admin_headers"]


class TestCampaignCreation:
    def test_campaign_create_returns_draft_with_zeroed_computed_fields(self, api):
        """PRD §3.1: "A `CampaignOwner` or `PlatformAdmin` creates a campaign
        in `DRAFT` status".
        PRD §2.7: "A campaign is created with `version` 1."
        PRD §2.7: "Every top-level resource — Campaign, Pledge, ... — carries
        four system-managed fields: `id` ... `created_at` ... `updated_at` ...
        and `version`, an integer incremented on every mutation."
        PRD §3.6: "Until every wave is dispatched, `retail_release_at` is
        null."

        Design: Corner/entities/campaign_create_returns_draft_with_zeroed_computed_fields
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_campaign(create_campaign_payload(), api_headers_owner())
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["version"] == 1
        assert data["gross_charged_cents"] == 0
        assert data["net_payable_cents"] == 0
        assert data["total_backers_charged"] == 0
        assert data["retail_release_at"] is None
        assert_campaign(data)

    def test_campaign_get_unknown_id_returns_404(self, api):
        """PRD §2.5 item 3: "Existence of every identifier appearing in the
        URL path, validated left to right (`ERR_NOT_FOUND`)."

        Design: Corner/entities/campaign_get_unknown_id_returns_404
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.get_campaign(NON_EXISTENT_UUID, api_headers_owner())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPledgeBasics:
    def test_pledge_get_returns_stored_fields(self, api):
        """PRD §3.3: "Every pledge is born with `charge_status` `PENDING`,
        `address_status` `UNCONFIRMED`, `fulfillment_status` `QUEUED`,
        `assigned_wave_id` null, and `address_locked_at` null."
        PRD §3.3: "The level line is the level's `price_cents` multiplied by
        one plus the `late_pledge_premium_pct` when `is_late_pledge` is true,
        or by one alone when it is false, rounded half-up."

        Design: Corner/entities/pledge_get_returns_stored_fields
        """
        campaign = setup_live_campaign()
        pledge = create_pledge(
            campaign["id"],
            backer_user_id="b1",
            backer_email="b1@x",
            region_code="EU",
        )
        resp = api.get_pledge(pledge["id"], api_headers_owner())
        data = validate_success(resp)
        assert data["backer_email"] == "b1@x"
        assert data["region_code"] == "EU"
        assert data["charge_status"] == "PENDING"
        assert data["address_status"] == "UNCONFIRMED"
        assert data["fulfillment_status"] == "QUEUED"
        assert data["pledge_total_cents"] == 5000
        assert_pledge(data)

    def test_pledges_list_paginates_total_count_and_has_more(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`,
        the maximum number of items to return, defaulting to 10 with a
        minimum of 1 and a maximum of 100; and `offset`, the number of items
        to skip, defaulting to 0."
        PRD §2.3: "The `meta` object of every list response includes the
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/pledges_list_paginates_total_count_and_has_more
        """
        campaign = setup_live_campaign()
        create_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x", region_code="NA"
        )
        create_pledge(
            campaign["id"], backer_user_id="b2", backer_email="b2@x", region_code="EU"
        )
        create_pledge(
            campaign["id"],
            backer_user_id="b3",
            backer_email="b3@x",
            region_code="APAC",
        )
        resp = api.list_pledges(
            api_headers_owner(),
            params={"campaign_id": campaign["id"], "limit": 2, "offset": 0},
        )
        rows, meta = validate_paginated(resp)
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        resp = api.list_pledges(
            api_headers_owner(),
            params={"campaign_id": campaign["id"], "limit": 2, "offset": 2},
        )
        rows, meta = validate_paginated(resp)
        assert len(rows) == 1
        assert meta["has_more"] is False

        resp = api.list_pledges(
            api_headers_owner(),
            params={"campaign_id": campaign["id"], "region_code": "EU"},
        )
        rows, meta = validate_paginated(resp)
        assert len(rows) == 1
        assert rows[0]["region_code"] == "EU"

    def test_pledge_create_missing_campaign_id_returns_invalid_request(self, api):
        """PRD §2.5: "malformed or missing required fields are rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)".
        PRD §3.3: "creates a pledge against a campaign by supplying the
        `campaign_id`, their own `backer_user_id` and `backer_email` ... and
        the `pledge_level_name`".

        Design: Corner/entities/pledge_create_missing_campaign_id_returns_invalid_request
        """
        campaign = create_campaign()
        payload = {
            "backer_user_id": "b1",
            "backer_email": "b1@x",
            "region_code": "NA",
            "pledge_level_name": "L",
            "expected_campaign_version": campaign["version"],
        }
        resp = api.create_pledge(payload, api_headers_admin())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_pledge_defaults_is_late_pledge_false_and_addons_empty(self, api):
        """PRD §3.3: "The optional `is_late_pledge` flag defaults to false".
        PRD §3.3: "The optional `add_on_lines` array, defaulting to empty,
        lists `{sku, quantity}` pairs referencing catalog entries".

        Design: Corner/entities/pledge_defaults_is_late_pledge_false_and_addons_empty
        """
        campaign = setup_live_campaign()
        pledge = create_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        assert pledge["is_late_pledge"] is False
        assert pledge["add_on_lines"] == []

    def test_pledge_invalid_region_code_returns_invalid_enum(self, api):
        """PRD §2.6: "Backers, freight shipments, waves, distributor
        allocations, and replacement requests all carry a `region_code` drawn
        from exactly four values: `NA`, `EU`, `APAC`, and `ROW`."
        PRD §2.6: "Every enum value must match its declared set exactly;
        deviations produce `ERR_INVALID_ENUM`."

        Design: Corner/entities/pledge_invalid_region_code_returns_invalid_enum
        """
        campaign = setup_live_campaign()
        version = get_campaign(campaign["id"])["version"]
        payload = {
            "campaign_id": campaign["id"],
            "backer_user_id": "b1",
            "backer_email": "b1@x",
            "region_code": "INVALID",
            "pledge_level_name": "L",
            "expected_campaign_version": version,
        }
        resp = api.create_pledge(payload, api_headers_admin())
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


class TestAccessControl:
    def test_missing_role_header_returns_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_role_header_returns_400
        """
        set_clock("2026-09-01T00:00:00Z")
        headers = {"X-User-ID": "somebody", "Content-Type": "application/json"}
        resp = api.get_campaign(NON_EXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_backer_cannot_launch_campaign(self, api):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        role list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST /campaigns/{id}/transition — "Campaign transitions:
        launch, unlaunch, cancel, start-production, complete | CampaignOwner".

        Design: Corner/validations/backer_cannot_launch_campaign
        """
        set_clock("2026-09-01T00:00:00Z")
        campaign = create_campaign()
        resp = api.transition_campaign(
            campaign["id"], {"action": "launch"}, make_backer_headers("b1")
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_backer_ownership_check_on_confirm_address(self, api):
        """PRD §3.7: "Confirming an address moves a pledge's `address_status`
        `UNCONFIRMED → CONFIRMED` and requires the acting `X-User-ID` to equal
        the pledge's `backer_user_id` (otherwise `ERR_FORBIDDEN`)."

        Design: Corner/validations/backer_ownership_check_on_confirm_address
        """
        campaign = setup_live_campaign()
        pledge = create_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        resp = api.transition_pledge(
            pledge["id"],
            {"action": "confirm-address"},
            make_backer_headers("b2"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_unknown_transition_action_returns_400(self, api):
        """PRD §2.5: "a transition `action` outside the endpoint's allowed
        action set is rejected with `ERR_UNKNOWN_ACTION` (HTTP 400)."

        Design: Corner/endpoints/unknown_transition_action_returns_400
        """
        set_clock("2026-09-01T00:00:00Z")
        campaign = create_campaign()
        resp = api.transition_campaign(
            campaign["id"], {"action": "explode"}, api_headers_owner()
        )
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_ACTION)


class TestOptimisticConcurrency:
    def test_occ_stale_campaign_version_on_pledge_create(self, api):
        """PRD §2.8: "A pledge-creation request must carry
        `expected_campaign_version`, the campaign `version` the client last
        observed. If another writer has advanced the campaign's version since
        that observation — for example through a stretch-goal unlock that
        re-priced levels or a sibling pledge charge — the create is rejected
        with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_stale_campaign_version_on_pledge_create
        """
        campaign = setup_live_campaign()
        observed = get_campaign(campaign["id"])["version"]
        create_charged_pledge(
            campaign["id"], backer_user_id="b1", backer_email="b1@x"
        )
        payload = {
            "campaign_id": campaign["id"],
            "backer_user_id": "b2",
            "backer_email": "b2@x",
            "region_code": "NA",
            "pledge_level_name": "L",
            "expected_campaign_version": observed,
        }
        resp = api.create_pledge(payload, api_headers_admin())
        validate_error(resp, ApiErrorId.ERR_STALE_CAMPAIGN_VERSION)


# Header shortcuts bound to the shared test users are defined at the top of
# this module (headers themselves are opaque role identities per PRD §2.1).
