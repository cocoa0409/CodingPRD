"""Advocacy campaigns and mobilization: clock-derived campaign status, the
sponsor-kind boundary, and audience data-use restrictions."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_lobby_arm, create_campaign_ok, get_campaign,
    create_household_with_term,
    create_campaign_payload, create_mobilization_payload,
)

ADV = TEST_USERS["advocacy_director_headers"]


class TestMobilizationRequiresActiveCampaign:
    def _setup_upcoming_campaign(self):
        set_clock()
        lobby = create_lobby_arm()
        campaign = create_campaign_ok(
            lobby["id"], title="Protect Retirement Savings", level="FEDERAL",
            issue_area="RETIREMENT", start_date="2026-10-01",
            end_date="2026-12-31")
        create_household_with_term(
            state_code="NM", term_years=1, primary_full_name="Quinn Quill",
            primary_date_of_birth="1964-01-01")
        return lobby, campaign

    def test_mobilization_rejected_while_campaign_upcoming(self, api):
        """PRD §3.9: "A campaign's `computed_status` is derived lazily on
        every read: `UPCOMING` while the clock date is before `start_date`,
        `ACTIVE` from `start_date` through `end_date` with both bounds
        inclusive, and `CLOSED` once the clock date passes `end_date`." PRD
        §3.9: "The campaign must be `ACTIVE` at request time — mobilizing
        under an `UPCOMING` or `CLOSED` campaign is rejected with
        `ERR_CAMPAIGN_NOT_ACTIVE` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/mobilization_requires_active_campaign_window
        """
        _lobby, campaign = self._setup_upcoming_campaign()
        assert campaign["computed_status"] == "UPCOMING"
        payload = create_mobilization_payload(
            channel="EMAIL", audience_spec={"min_age": 50})
        resp = api.create_mobilization(campaign["id"], payload, ADV)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)

    def test_mobilization_accepted_once_window_opens_with_snapshot(self, api):
        """PRD §3.9: "The event's `audience_count` is a snapshot computed at
        creation: it counts the members who are in good standing, who have
        not set `benefit_marketing_opt_out`, whose household's `state_code`
        equals the supplied `state_code` when that key is present, and whose
        `age_years` is at least `min_age` when that key is present — a member
        exactly `min_age` years old is included." PRD §3.9: "`ACTIVE` from
        `start_date` through `end_date` with both bounds inclusive".

        Design: Difficulty/cross_entity_state_dependency/mobilization_requires_active_campaign_window
        """
        _lobby, campaign = self._setup_upcoming_campaign()
        payload = create_mobilization_payload(
            channel="EMAIL", audience_spec={"min_age": 50})
        validate_error(
            api.create_mobilization(campaign["id"], payload, ADV),
            ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)

        set_clock("2026-10-01T00:00:00Z")
        assert get_campaign(campaign["id"])["computed_status"] == "ACTIVE"
        event = validate_success(
            api.create_mobilization(campaign["id"], payload, ADV),
            expected_status=201)
        # The single non-opted-out good-standing member (age 62 at the clock).
        assert event["audience_count"] == 1


class TestCampaignConditionalStateCode:
    def test_state_code_conditional_requirement(self, api):
        """PRD §3.9: "a conditional `state_code`: required when the level is
        `STATE` and required to be absent when the level is `FEDERAL`, with
        either violation rejected as `ERR_INVALID_REQUEST`."

        Design: Corner/entities/campaign_state_code_conditional_requirement
        """
        set_clock()
        lobby = create_lobby_arm()
        state_payload = create_campaign_payload(
            lobby["id"], title="State Utility Rates", level="STATE",
            issue_area="UTILITIES", start_date="2026-10-01",
            end_date="2026-12-31")
        assert "state_code" not in state_payload
        resp = api.create_campaign(state_payload, ADV)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        federal_payload = create_campaign_payload(
            lobby["id"], title="Federal Drug Prices", level="FEDERAL",
            issue_area="HEALTHCARE", start_date="2026-10-01",
            end_date="2026-12-31", state_code="TX")
        resp = api.create_campaign(federal_payload, ADV)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestMobilizationOnClosedCampaign:
    def test_mobilization_on_closed_campaign_rejected(self, api):
        """PRD §3.9: "`CLOSED` once the clock date passes `end_date`." PRD
        §3.9: "The campaign must be `ACTIVE` at request time — mobilizing
        under an `UPCOMING` or `CLOSED` campaign is rejected with
        `ERR_CAMPAIGN_NOT_ACTIVE` (HTTP 409)".

        Design: Corner/state_machines/mobilization_on_closed_campaign_rejected
        """
        set_clock()
        lobby = create_lobby_arm()
        campaign = create_campaign_ok(
            lobby["id"], title="September Push", level="FEDERAL",
            issue_area="RETIREMENT", start_date="2026-09-01",
            end_date="2026-09-30")
        assert campaign["computed_status"] == "ACTIVE"
        set_clock("2026-10-15T00:00:00Z")
        payload = create_mobilization_payload(channel="MAIL", audience_spec={})
        resp = api.create_mobilization(campaign["id"], payload, ADV)
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)
        assert get_campaign(campaign["id"])["computed_status"] == "CLOSED"


class TestAudienceSpecDataUse:
    def test_audience_restricted_key_vs_unknown_key(self, api):
        """PRD §2.11: "The three benefit-marketing keys
        `owns_licensed_product`, `benefit_product_category`, and
        `provider_customer` are forbidden outright and their presence is
        rejected with `ERR_DATA_USE_RESTRICTED` (HTTP 422); any other key is
        simply malformed and rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §2.11: "Mobilization audiences may filter members only by
        geography and age — the `audience_spec` keys `state_code` and
        `min_age` are the complete allow-list."

        Design: Corner/errors/audience_restricted_key_vs_unknown_key
        """
        set_clock()
        lobby = create_lobby_arm()
        campaign = create_campaign_ok(
            lobby["id"], title="Texas Utility Reform", level="STATE",
            state_code="TX", issue_area="UTILITIES", start_date="2026-09-01",
            end_date="2026-12-31")
        create_household_with_term(
            state_code="TX", term_years=1, primary_full_name="Amy Aker",
            primary_date_of_birth="1969-09-09")

        restricted = create_mobilization_payload(
            channel="EMAIL", audience_spec={"owns_licensed_product": True})
        resp = api.create_mobilization(campaign["id"], restricted, ADV)
        validate_error(resp, ApiErrorId.ERR_DATA_USE_RESTRICTED)
        assert resp.status_code == 422

        unknown = create_mobilization_payload(
            channel="EMAIL", audience_spec={"favorite_color": "blue"})
        resp = api.create_mobilization(campaign["id"], unknown, ADV)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

        valid = create_mobilization_payload(
            channel="EMAIL", audience_spec={"state_code": "TX"})
        event = validate_success(
            api.create_mobilization(campaign["id"], valid, ADV),
            expected_status=201)
        assert event["audience_count"] == 1
