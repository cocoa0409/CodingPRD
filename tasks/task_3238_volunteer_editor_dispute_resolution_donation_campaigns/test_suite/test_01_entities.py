"""Entity CRUD, listing, and retrieval tests (Corner design index, section entities)."""
import pytest

from test_helpers import (
    api_client, TEST_USERS, make_volunteer_editor_headers,
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId,
    create_editor, create_page, create_revision, set_clock,
    create_editor_payload, create_page_payload, create_revision_payload,
    create_campaign_payload, create_banner_payload,
)


class TestEditorCreation:
    def test_editor_create_returns_defaults_and_system_fields(self):
        """PRD §3.1: "Upon registration, the new editor's `account_status` is set
        to `ACTIVE`, `coi_disclosed` defaults to false, and `edit_count` starts
        at zero."
        PRD §2.4: "Every persisted entity carries an `id` that is a server-minted
        UUID with no type prefix. Every entity also carries `created_at` and
        `updated_at`, both ISO 8601 UTC timestamps with three fractional digits."

        Design: Corner/entities/editor_create_returns_defaults_and_system_fields
        """
        set_clock()
        resp = api_client.create_editor(
            create_editor_payload(username="fresh", email="fresh@x.com"),
            TEST_USERS["anonymous_headers"],
        )
        editor = validate_success(resp, expected_status=201)
        assert editor["account_status"] == "ACTIVE"
        assert editor["coi_disclosed"] is False
        assert editor["edit_count"] == 0
        assert editor["id"]
        assert editor["created_at"]
        assert editor["updated_at"]
        assert editor["version"] >= 1


class TestPageRetrieval:
    def test_page_get_round_trips_stored_fields(self):
        """PRD §3.2: "A new page starts with `protection_level` set to `NONE`,
        `dispute_level` set to `NONE`, and `content_score` set to zero."

        Design: Corner/entities/page_get_round_trips_stored_fields
        """
        set_clock()
        editor, editor_headers = create_editor(username="pg", email="pg@x.com")
        resp = api_client.create_page(
            create_page_payload(title="Round Trip", topic_area="HEALTH"), editor_headers,
        )
        page = validate_success(resp, expected_status=201)
        resp = api_client.get_page(page["id"], editor_headers)
        fetched = validate_success(resp)
        assert fetched["title"] == "Round Trip"
        assert fetched["topic_area"] == "HEALTH"
        assert fetched["protection_level"] == "NONE"
        assert fetched["dispute_level"] == "NONE"
        assert fetched["content_score"] == 0


class TestRevisionListing:
    def test_revisions_list_paginates_with_total_count_and_has_more(self):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
        The default `limit` is 10, the minimum is 1, and the maximum is 100. The
        default `offset` is 0. Results are sorted by `created_at` ascending. The
        `meta` object in list responses includes `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/entities/revisions_list_paginates_with_total_count_and_has_more
        """
        set_clock()
        editor, editor_headers = create_editor(username="lst", email="lst@x.com")
        page = create_page(editor_headers, title="List Page")
        for i in range(3):
            create_revision(page["id"], editor_headers, content_text=f"r{i+1}")

        # Page 1: limit=2, offset=0
        resp = api_client.list_revisions(editor_headers, params={"page_id": page["id"], "limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        # Page 2: limit=2, offset=2
        resp = api_client.list_revisions(editor_headers, params={"page_id": page["id"], "limit": 2, "offset": 2})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        # Defaults: limit=10, offset=0
        resp = api_client.list_revisions(editor_headers, params={"page_id": page["id"]})
        data, meta = validate_paginated(resp)
        assert len(data) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0


class TestDisputeNotFound:
    def test_dispute_get_unknown_id_returns_not_found(self):
        """PRD §2.7: "If any referenced ID does not exist, the request is rejected
        with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/dispute_get_unknown_id_returns_not_found
        """
        set_clock()
        resp = api_client.get_dispute(NON_EXISTENT_UUID, TEST_USERS["administrator_headers"])
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error_data["error_id"] == "ERR_NOT_FOUND"
        assert "message" in error_data


class TestCampaignRequiredFields:
    def test_campaign_create_missing_target_amount_returns_invalid_request(self):
        """PRD §3.7: "A `FundraisingManager` creates a donation campaign by
        supplying a `name`, `start_at`, `end_at`, and `target_amount_cents`."
        PRD §5: `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/entities/campaign_create_missing_target_amount_returns_invalid_request
        """
        set_clock()
        payload = {
            "name": "No Target",
            "start_at": "2026-09-01T00:00:00Z",
            "end_at": "2026-10-01T00:00:00Z",
        }
        resp = api_client.create_campaign(payload, TEST_USERS["fundraising_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # No campaign persisted
        resp = api_client.list_campaigns(TEST_USERS["fundraising_manager_headers"])
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 0


class TestBannerDefaults:
    def test_banner_create_omitting_priority_weight_defaults_to_1(self):
        """PRD §3.8: "A `FundraisingManager` creates a banner under a campaign by
        providing `message_variant`, `geo_target` (an ISO country code or
        `GLOBAL`), `frequency_cap` (maximum impressions per user per day), and an
        optional `priority_weight` defaulting to 1. The banner starts `ACTIVE`
        with all counters at zero."

        Design: Corner/entities/banner_create_omitting_priority_weight_defaults_to_1
        """
        set_clock()
        campaign_resp = api_client.create_campaign(
            create_campaign_payload(name="Def Drive", target_amount_cents=1000),
            TEST_USERS["fundraising_manager_headers"],
        )
        campaign = validate_success(campaign_resp, expected_status=201)
        resp = api_client.create_banner(
            campaign["id"],
            {"message_variant": "D", "geo_target": "GLOBAL", "frequency_cap": 3},
            TEST_USERS["fundraising_manager_headers"],
        )
        banner = validate_success(resp, expected_status=201)
        assert banner["priority_weight"] == 1
        assert banner["status"] == "ACTIVE"
        assert banner["impression_count"] == 0
        assert banner["click_count"] == 0
        assert banner["conversion_count"] == 0


class TestPageComputedFields:
    def test_page_content_score_computed_not_client_supplied(self):
        """PRD §3.2: "A new page starts with `protection_level` set to `NONE`,
        `dispute_level` set to `NONE`, and `content_score` set to zero."

        Design: Corner/entities/page_content_score_computed_not_client_supplied
        """
        set_clock()
        editor, editor_headers = create_editor(username="cf", email="cf@x.com")
        resp = api_client.create_page(
            create_page_payload(title="Computed"), editor_headers,
        )
        page = validate_success(resp, expected_status=201)
        assert page["content_score"] == 0


class TestPageEnumConstraint:
    def test_page_create_invalid_topic_area_enum_rejected(self):
        """PRD §3.2: "A `VolunteerEditor` may create a new wiki page by supplying
        a `title` and selecting a `topic_area` from the set `GENERAL`, `POLITICS`,
        `HEALTH`, `BIOGRAPHY`, or `HISTORY`."
        PRD §5: `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/entities/page_create_invalid_topic_area_enum_rejected
        """
        set_clock()
        editor, editor_headers = create_editor(username="en", email="en@x.com")
        resp = api_client.create_page(
            create_page_payload(title="Bad Enum", topic_area="SPORTS"), editor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
